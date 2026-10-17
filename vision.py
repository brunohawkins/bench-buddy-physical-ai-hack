"""Real-time board view and placement checks. Owner: V.

A background thread warps every camera frame to the flat board (see calibrate.py), tracks motion
and keeps an annotated live view. With no calib.json it calibrates itself from the image, and while
the board is still it re-checks the calibration every few seconds, re-snapping if the board moved.

A check compares a stable "before" board with a stable "after" board:
  1. change mask: pixels that differ from every position within +-2 px of "before" (forgives tiny
     misalignment, so hole edges don't light up)
  2. each changed blob is a wire; its inserted end is the point farthest from where it enters the
     image (or, for a jumper lying wholly on the board, both extremes along its length)
  3. each end snaps to the nearest terminal hole -> (row, column); ends on the rails are ignored
  4. the wire's colour is measured along the blob
Two "after" boards taken ~1 s apart must agree, otherwise the result is "unsure".

Dev harness (calibrates itself if there's no calib.json):

    python -u vision.py --row 13 --colour red [--source N]
    keys: b = take "before", c = check, q = quit
"""
import threading
import time
from pathlib import Path

import numpy as np

from calibrate import PITCH
from contracts import CheckResult, Snapshot

FRAMES_DIR = Path("frames")

# Tuning. Expect to adjust these on the real board.
MOTION_PIXEL = 25        # grey-level change that counts a pixel as moving
MOTION_STILL = 0.003     # fraction of moving pixels below which the board counts as still
STILL_FOR = 0.8          # seconds of stillness before a board counts as stable
DIFF_PIXEL = 35.0        # Lab distance for a pixel to count as changed
SHIFT_TOL = 2            # pixels of misalignment the change mask forgives
MIN_WIRE_AREA = 0.5 * PITCH ** 2   # smallest blob (pixels) treated as a wire
TOO_MUCH = 0.12          # more than this fraction of the board changed: a hand or the board moved
END_REGION = 0.7 * PITCH # a wire end is the centroid of blob pixels this close to the extreme point
END_SNAP = 0.75 * PITCH  # max distance from a wire end to a terminal hole
COLOUR_MIN = 0.15        # fraction of wire pixels that must match the wire colour
RECAL_EVERY = 3.0        # seconds between self-calibration checks while the board is still
RECAL_SHIFT = 0.3        # re-snap when the grid has moved by more than this many pitches

# OpenCV HSV: H 0-180, S and V 0-255.
HSV_RANGES = {
    "red": [((0, 90, 60), (10, 255, 255)), ((170, 90, 60), (180, 255, 255))],
    "orange": [((10, 90, 60), (22, 255, 255))],
    "yellow": [((22, 90, 60), (35, 255, 255))],
    "green": [((35, 60, 40), (85, 255, 255))],
    "blue": [((85, 80, 40), (130, 255, 255))],
    "black": [((0, 0, 0), (180, 255, 50))],
}


# --- pure analysis (no camera; unit-tested in tests/test_vision.py) ---------------

def change_mask(before, after) -> np.ndarray:
    """Pixels that changed, forgiving up to SHIFT_TOL px of misalignment and auto-exposure drift."""
    import cv2
    a = cv2.cvtColor(cv2.GaussianBlur(before, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    b = cv2.cvtColor(cv2.GaussianBlur(after, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    b[..., 0] *= np.median(a[..., 0]) / max(np.median(b[..., 0]), 1.0)
    dist = np.full(a.shape[:2], np.inf, np.float32)
    for dy in range(-SHIFT_TOL, SHIFT_TOL + 1):
        for dx in range(-SHIFT_TOL, SHIFT_TOL + 1):
            shifted = np.roll(a, (dy, dx), axis=(0, 1))
            dist = np.minimum(dist, np.linalg.norm(shifted - b, axis=2))
    mask = (dist > DIFF_PIXEL).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    return mask.astype(bool)


def wire_ends(board, mask) -> list[dict]:
    """Inserted ends of each changed blob, snapped to terminal holes where close enough.
    Each end: {"x", "y", "row", "col", "blob"} with row/col None when not near a terminal hole."""
    import cv2
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8))
    h, w = mask.shape
    ends = []
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < MIN_WIRE_AREA:
            continue
        ys, xs = np.nonzero(labels == i)
        pts = np.stack([xs, ys], axis=1).astype(np.float32)
        border = (xs <= 2) | (ys <= 2) | (xs >= w - 3) | (ys >= h - 3)
        if border.any():
            entry = pts[border].mean(axis=0)                       # wire comes in from off the board
            extremes = [pts[np.argmax(np.linalg.norm(pts - entry, axis=1))]]
        else:                                                      # jumper lying wholly on the board
            centred = pts - pts.mean(axis=0)
            axis = np.linalg.svd(centred, full_matrices=False)[2][0]
            proj = centred @ axis
            extremes = [pts[np.argmin(proj)], pts[np.argmax(proj)]]
        for ext in extremes:
            near = pts[np.linalg.norm(pts - ext, axis=1) < END_REGION]
            x, y = near.mean(axis=0)
            d = np.linalg.norm(board.hole_px - (x, y), axis=1)
            k = int(np.argmin(d))
            row, col = board.holes[k] if d[k] < END_SNAP else (None, None)
            ends.append({"x": float(x), "y": float(y), "row": row, "col": col, "blob": i})
    return ends, labels


def colour_fractions(image, mask) -> dict[str, float]:
    """Fraction of masked pixels falling in each named HSV range."""
    import cv2
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    n = max(int(mask.sum()), 1)
    out = {}
    for name, ranges in HSV_RANGES.items():
        hit = np.zeros(mask.shape, bool)
        for lo, hi in ranges:
            hit |= cv2.inRange(hsv, np.array(lo), np.array(hi)) > 0
        out[name] = float((hit & mask).sum()) / n
    return out


def analyse(board, before, after, expect_rows: list[int], wire_colour: str | None) -> tuple[CheckResult, dict]:
    """Compare two warped boards. Returns the result and an overlay (mask + wire ends) for drawing."""
    mask = change_mask(before, after)
    overlay = {"mask": mask, "ends": []}
    if mask.mean() > TOO_MUCH:
        return CheckResult("unsure", "Something big is in the way. Move your hand away, then say done."), overlay
    ends, labels = wire_ends(board, mask)
    overlay["ends"] = ends
    placed = [e for e in ends if e["row"] is not None]
    if not placed:
        return CheckResult("unsure", "I don't see a wire end in the board yet. Check it's pushed in, then say done."), overlay

    rows_found = sorted({e["row"] for e in placed})
    if set(rows_found) != set(expect_rows):
        want = " and ".join(map(str, expect_rows))
        wrong = [e for e in placed if e["row"] not in expect_rows]
        if len(expect_rows) == 1 and len(placed) == 1:
            detail = f"That went into row {placed[0]['row']}, it should be row {want}."
        elif wrong:
            detail = f"I see a wire end in row {' and '.join(str(e['row']) for e in wrong)}, it should be row {want}."
        else:
            detail = f"I only see a wire end in row {' and '.join(map(str, rows_found))}, it should be row {want}."
        return CheckResult("fail", detail, rows_found), overlay

    if wire_colour:
        wire = np.isin(labels, list({e["blob"] for e in placed}))
        fractions = colour_fractions(after, wire)
        if fractions.get(wire_colour, 0.0) < COLOUR_MIN:
            seen = max(fractions, key=fractions.get)
            looks = f"looks {seen}" if fractions[seen] >= COLOUR_MIN else f"doesn't look {wire_colour}"
            return CheckResult("fail", f"Right row, but that wire {looks}. Use a {wire_colour} wire.", rows_found), overlay

    rows = " and ".join(map(str, expect_rows))
    return CheckResult("pass", f"Row {rows}{', ' + wire_colour if wire_colour else ''}. Looks good.", rows_found), overlay


def draw_result(board, warped, overlay: dict | None, expect_rows=()):
    """Grid, expected rows, changed area and wire ends on a warped board (in place)."""
    import cv2
    board.draw_grid(warped, expect_rows)
    if overlay:
        contours, _ = cv2.findContours(overlay["mask"].astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(warped, contours, -1, (0, 220, 255), 1)
        for e in overlay["ends"]:
            if e["row"] is None:
                cv2.circle(warped, (int(e["x"]), int(e["y"])), 5, (200, 200, 200), 1)
                continue
            x, y = board.hole_px[board.holes.index((e["row"], e["col"]))].astype(int)
            good = e["row"] in expect_rows
            colour = (0, 200, 0) if good else (0, 0, 255)
            cv2.circle(warped, (x, y), int(0.45 * PITCH), colour, 2)
            cv2.putText(warped, f"{e['col']}{e['row']}", (x + 10, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 1, cv2.LINE_AA)
    return warped


# --- real-time -----------------------------------------------------------------------

class Vision:
    def __init__(self, camera, board=None, rows: int = 63):
        import calibrate
        self.camera = camera
        if board is None:
            try:
                board = calibrate.load()
            except FileNotFoundError:
                board, info = calibrate.calibrate_from_camera(camera, rows)
                calibrate.save_board(board)
                print(f"auto-calibrated: {info['holes']}/{info['expected']} holes")
        self.board = board
        self._busy = False                        # true during a check: don't re-snap mid-comparison
        self.expect_rows: list[int] = []          # highlighted on the live view during a check
        self.overlay: dict | None = None          # last check's changed area + wire ends, drawn on the live view
        self.status = ""                          # last check's detail line
        self._lock = threading.Lock()
        self._warped = None
        self._raw = None
        self._motion = 1.0
        self._still_since = time.time()
        self._fps = 0.0
        FRAMES_DIR.mkdir(exist_ok=True)
        threading.Thread(target=self._loop, daemon=True).start()
        threading.Thread(target=self._recalibrate_loop, daemon=True).start()

    def _recalibrate_loop(self):
        """Re-snap the grid if the board (or camera) has moved."""
        import cv2
        import calibrate
        while True:
            time.sleep(RECAL_EVERY)
            if self._busy or not self.is_still():
                continue
            frame = self.camera.latest()
            if frame is None:
                continue
            try:
                new, _ = calibrate.auto_calibrate(frame, self.board.rows)
            except calibrate.CalibrationError:
                continue
            old = self.board
            moved = cv2.perspectiveTransform(new.hole_cam.reshape(-1, 1, 2), old.H).reshape(-1, 2)
            shift = float(np.linalg.norm(moved - old.hole_px, axis=1).mean()) / PITCH
            if shift > RECAL_SHIFT:
                self.board = new
                calibrate.save_board(new)
                self.status = f"board moved {shift:.1f} holes: recalibrated"

    def _loop(self):
        import cv2
        last_id, prev, t_prev = -1, None, time.time()
        while True:
            frame_id, frame = self.camera.latest_with_id()
            if frame is None or frame_id == last_id:
                time.sleep(0.005)
                continue
            last_id = frame_id
            warped = self.board.warp(frame)
            grey = cv2.GaussianBlur(cv2.cvtColor(cv2.resize(warped, None, fx=0.5, fy=0.5), cv2.COLOR_BGR2GRAY), (5, 5), 0)
            motion = 1.0 if prev is None else float((cv2.absdiff(grey, prev) > MOTION_PIXEL).mean())
            prev = grey
            now = time.time()
            with self._lock:
                self._raw, self._warped, self._motion = frame, warped, motion
                if motion > MOTION_STILL:
                    self._still_since = now
                self._fps = 0.9 * self._fps + 0.1 / max(now - t_prev, 1e-3)
            t_prev = now

    def is_still(self) -> bool:
        with self._lock:
            return time.time() - self._still_since >= STILL_FOR

    def wait_stable(self, timeout: float = 20.0):
        """Warped board once it has been still for STILL_FOR seconds, or None on timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_still():
                with self._lock:
                    return self._warped.copy()
            time.sleep(0.02)
        return None

    def _save(self, image, tag: str) -> str:
        import cv2
        path = FRAMES_DIR / f"{time.strftime('%H%M%S')}_{tag}.jpg"
        cv2.imwrite(str(path), image)
        return str(path)

    def snapshot(self) -> Snapshot:
        warped = self.wait_stable()
        if warped is None:
            with self._lock:
                warped = self._warped.copy()
        return Snapshot(image=warped, path=self._save(warped, "before"))

    def check_placement(self, before: Snapshot, expect_rows: list[int], wire_colour: str | None) -> CheckResult:
        self._busy = True
        try:
            return self._check(before, expect_rows, wire_colour)
        finally:
            self._busy = False

    def _check(self, before: Snapshot, expect_rows: list[int], wire_colour: str | None) -> CheckResult:
        self.expect_rows = list(expect_rows)
        first = self.wait_stable()
        time.sleep(1.0)
        second = self.wait_stable()
        if first is None or second is None:
            result = CheckResult("unsure", "Move your hand away from the board, then say done.")
            self.status = result.detail
            return result

        r1, _ = analyse(self.board, before.image, first, expect_rows, wire_colour)
        r2, overlay = analyse(self.board, before.image, second, expect_rows, wire_colour)
        if (r1.status, r1.rows_found) != (r2.status, r2.rows_found):
            r2 = CheckResult("unsure", "Hold still a moment, then say done.", r2.rows_found)
        r2.frame = self._save(draw_result(self.board, second.copy(), overlay, expect_rows), r2.status)
        self.overlay, self.status = overlay, r2.detail
        return r2

    def view(self):
        """Live composite: camera frame with the projected grid on top, warped board underneath."""
        import cv2
        with self._lock:
            if self._raw is None:
                return None
            raw, warped, still, fps = self._raw.copy(), self._warped.copy(), \
                time.time() - self._still_since >= STILL_FOR, self._fps
        self.board.draw_on_camera(raw, self.expect_rows)
        draw_result(self.board, warped, self.overlay, self.expect_rows)
        w = 1280
        raw = cv2.resize(raw, (w, int(raw.shape[0] * w / raw.shape[1])))
        warped = cv2.resize(warped, (w, int(warped.shape[0] * w / warped.shape[1])))
        bar = np.full((40, w, 3), 30, np.uint8)
        cv2.putText(bar, f"{'STILL' if still else 'MOVING'}  {fps:4.1f} fps  {self.status}", (10, 27),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 220, 0) if still else (0, 160, 255), 2, cv2.LINE_AA)
        return np.vstack([raw, warped, bar])

    def show_forever(self, stop=lambda: False) -> None:
        """Display loop. On macOS OpenCV windows must run on the main thread, so call this from there."""
        import cv2
        while not stop():
            frame = self.view()
            if frame is not None:
                cv2.imshow("Bench Buddy vision", frame)
            if cv2.waitKey(15) & 0xFF == ord("q"):
                break
        cv2.destroyAllWindows()


class FakeVision:
    """Fails the first check one row off, then passes, to exercise the retry path."""

    def __init__(self):
        self.calls = 0

    def snapshot(self) -> Snapshot:
        return Snapshot(image=None)

    def check_placement(self, before: Snapshot, expect_rows: list[int], wire_colour: str | None) -> CheckResult:
        self.calls += 1
        row = expect_rows[0]
        if self.calls == 1:
            return CheckResult("fail", f"That went into row {row + 1}, it should be row {row}.", [row + 1])
        return CheckResult("pass", f"Row {row}, {wire_colour or 'wire'} in place. Looks good.", [row])


if __name__ == "__main__":
    import argparse
    import cv2
    from camera import Camera, default_source, parse_source

    p = argparse.ArgumentParser(description="Live vision dev harness")
    p.add_argument("--row", type=int, nargs="+", required=True, help="expected row(s)")
    p.add_argument("--colour", default=None, choices=list(HSV_RANGES))
    p.add_argument("--source", default=None, help="camera index or stream URL (default: CAMERA_SOURCE)")
    args = p.parse_args()

    vision = Vision(Camera(parse_source(args.source) if args.source else default_source()))
    vision.expect_rows = args.row
    state = {"before": None, "busy": False}

    def act(fn):
        def run():
            state["busy"] = True
            try:
                fn()
            finally:
                state["busy"] = False
        if not state["busy"]:
            threading.Thread(target=run, daemon=True).start()

    def take_before():
        state["before"] = vision.snapshot()
        vision.overlay, vision.status = None, "before taken; place the wire, then press c"
        print(vision.status, flush=True)

    def check():
        if state["before"] is None:
            vision.status = "press b first"
            return
        r = vision.check_placement(state["before"], args.row, args.colour)
        print(r, flush=True)
        if vision.overlay:
            ends = ", ".join(f"{e['col']}{e['row']}" if e["row"] else "off-grid" for e in vision.overlay["ends"])
            print(f"changed {vision.overlay['mask'].mean():.1%} of board (hand if > {TOO_MUCH:.0%}); wire ends: {ends or 'none'}",
                  flush=True)

    vision.status = "press b to take 'before'"
    while True:
        frame = vision.view()
        if frame is not None:
            cv2.imshow("Bench Buddy vision", frame)
        key = cv2.waitKey(15) & 0xFF
        if key == ord("q"):
            break
        if key == ord("b"):
            act(take_before)
        elif key == ord("c"):
            act(check)
