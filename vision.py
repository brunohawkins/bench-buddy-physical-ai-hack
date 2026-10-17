"""Real-time board view and placement checks. Owner: V.

A background thread warps every camera frame to the flat board (see calibrate.py), tracks motion
and keeps an annotated live view. With no calib.json it calibrates itself from the image, and while
the board is still it re-checks the calibration every few seconds, re-snapping if the board moved. A check compares a stable "before" board with a stable "after"
board hole by hole: holes whose colour changed -> rows, then an HSV colour test on those holes.
Two "after" boards taken ~1 s apart must agree, otherwise the result is "unsure".

Dev harness (calibrates itself if there's no calib.json):

    python vision.py --row 13 --colour red [--source N]
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
HOLE_RADIUS = int(0.35 * PITCH)
CHANGED = 18.0           # hole score (Lab distance above the board's median) that counts as changed
MIN_MARGIN = 1.5         # expected rows must beat the next row by this factor
TOO_MUCH = 0.25          # more than this fraction of holes changed: a hand or the board moved
COLOUR_MIN = 0.15        # fraction of changed-hole pixels that must match the wire colour
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

def hole_scores(board, before, after) -> np.ndarray:
    """Colour change per terminal hole, in Lab units above the board-wide median."""
    import cv2
    a = cv2.cvtColor(cv2.GaussianBlur(before, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    b = cv2.cvtColor(cv2.GaussianBlur(after, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    b[..., 0] *= np.median(a[..., 0]) / max(np.median(b[..., 0]), 1.0)   # cancel auto-exposure drift
    dist = np.linalg.norm(a - b, axis=2)
    r = HOLE_RADIUS
    scores = np.array([dist[y - r:y + r + 1, x - r:x + r + 1].mean() for x, y in board.hole_px.astype(int)])
    return scores - np.median(scores)


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


def analyse(board, before, after, expect_rows: list[int], wire_colour: str | None) -> tuple[CheckResult, np.ndarray]:
    """Compare two warped boards. Returns the result and a per-hole 'changed' mask for drawing."""
    scores = hole_scores(board, before, after)
    changed = scores > CHANGED
    if changed.mean() > TOO_MUCH:
        return CheckResult("unsure", "Something big is in the way. Move your hand away, then say done."), changed
    if not changed.any():
        return CheckResult("unsure", "I don't see a new wire yet. Check it's pushed in, then say done."), changed

    row_score = np.zeros(board.rows + 1)
    for (r, _), s, c in zip(board.holes, scores, changed):
        if c:
            row_score[r] += s
    ranked = [int(r) for r in np.argsort(-row_score) if row_score[r] > 0]
    k = len(expect_rows)
    top = sorted(ranked[:k])
    runner_up = row_score[ranked[k]] if len(ranked) > k else 0.0
    if runner_up and min(row_score[top]) < MIN_MARGIN * runner_up:
        rows = ", ".join(str(r) for r in ranked[:k + 1])
        return CheckResult("unsure", f"I can't tell which row; I see changes in rows {rows}. Show me closer.",
                           ranked), changed

    if top != sorted(expect_rows):
        if k == 1:
            detail = f"That went into row {top[0]}, it should be row {expect_rows[0]}."
        else:
            detail = f"I see rows {' and '.join(map(str, top))}, it should be rows {' and '.join(map(str, expect_rows))}."
        return CheckResult("fail", detail, ranked), changed

    if wire_colour:
        mask = np.zeros(after.shape[:2], bool)
        for (r, _), (x, y), c in zip(board.holes, board.hole_px.astype(int), changed):
            if c and r in expect_rows:
                mask[y - HOLE_RADIUS:y + HOLE_RADIUS + 1, x - HOLE_RADIUS:x + HOLE_RADIUS + 1] = True
        fractions = colour_fractions(after, mask)
        if fractions.get(wire_colour, 0.0) < COLOUR_MIN:
            seen = max(fractions, key=fractions.get)
            return CheckResult("fail", f"Right row, but that wire looks {seen}. Use a {wire_colour} wire.", ranked), changed

    rows = " and ".join(map(str, expect_rows))
    return CheckResult("pass", f"Row {rows}{', ' + wire_colour if wire_colour else ''}. Looks good.", ranked), changed


def draw_result(board, warped, changed: np.ndarray | None, expect_rows=()):
    """Grid, expected rows and changed holes on a warped board (in place)."""
    import cv2
    board.draw_grid(warped, expect_rows)
    if changed is not None:
        for (r, _), (x, y), c in zip(board.holes, board.hole_px.astype(int), changed):
            if c:
                cv2.circle(warped, (x, y), HOLE_RADIUS + 2, (0, 200, 0) if r in expect_rows else (0, 0, 255), 2)
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
        self.changed: np.ndarray | None = None    # last check's changed holes, drawn on the live view
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
        r2, changed = analyse(self.board, before.image, second, expect_rows, wire_colour)
        if (r1.status, r1.rows_found[:len(expect_rows)]) != (r2.status, r2.rows_found[:len(expect_rows)]):
            r2 = CheckResult("unsure", "Hold still a moment, then say done.", r2.rows_found)
        r2.frame = self._save(draw_result(self.board, second.copy(), changed, expect_rows), r2.status)
        self.changed, self.status = changed, r2.detail
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
        draw_result(self.board, warped, self.changed, self.expect_rows)
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
        vision.changed, vision.status = None, "before taken; place the wire, then press c"
        print(vision.status)

    def check():
        if state["before"] is None:
            vision.status = "press b first"
            return
        r = vision.check_placement(state["before"], args.row, args.colour)
        print(r)
        with vision._lock:
            after = vision._warped.copy()
        scores = hole_scores(vision.board, state["before"].image, after)
        top = np.argsort(-scores)[:5]
        print(f"top hole scores (changed > {CHANGED}):",
              ", ".join(f"{vision.board.holes[i][1]}{vision.board.holes[i][0]}={scores[i]:.1f}" for i in top))

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
