"""Real-time board view and placement checks. Owner: V.

A background thread warps every camera frame to the flat board (see calibrate.py), tracks motion
and keeps an annotated live view. With no calib.json it calibrates itself from the image, and while
the board is still it re-checks the calibration every few seconds, re-snapping if the board moved.

A check compares a stable "before" board with a stable "after" board:
  1. change mask: pixels that differ from every position within +-2 px of "before" (forgives tiny
     misalignment, so hole edges don't light up)
  2. plug candidates: a morphological opening erases thin cable, leaving the plug housing (and the odd
     thick or shadowed stretch of cable)
  3. the plug is the black candidate (housings are black, cables are coloured) at the far end of its
     wire from where the cable enters the image (both ends for a jumper lying wholly on the board);
     if every candidate is dark (a black cable) darkness can't tell, so it's just the far end.
     Its centre snaps to the nearest terminal hole.
     Plugs on the rails are ignored. A spot that got darker is "placed", brighter is "removed"
  4. the wire's colour is measured along the changed blob the plug belongs to
Two "after" boards taken ~1 s apart must agree, otherwise the result is "unsure".

Watching is automatic: whenever the board has been still for STILL_FOR seconds it re-calibrates
from that frame (the board shifts when a wire is pushed in) and is compared with the last accepted state, and a wire end appearing or disappearing becomes an event ("placed i14",
"removed i14"). Hands and big changes are never reported. The state machine can block on
wait_for_placement(expect_rows) instead of waiting for the user to say "done".

Live view (calibrates itself if there's no calib.json; nothing to press):

    python -u vision.py [--row 13] [--colour red] [--source N]      # q quits
"""
import os
import threading
import time
from pathlib import Path

import numpy as np

from calibrate import PITCH
from contracts import CheckResult, Snapshot

FRAMES_DIR = Path("frames")
DEBUG = bool(os.environ.get("VISION_DEBUG"))   # save every evaluated before/after pair to frames/debug

# Tuning. Expect to adjust these on the real board.
MOTION_PIXEL = 25        # grey-level change that counts a pixel as moving
MOTION_STILL = 0.003     # fraction of moving pixels below which the board counts as still
STILL_FOR = 0.8          # seconds of stillness before a board counts as stable
DIFF_PIXEL = 35.0        # Lab distance for a pixel to count as changed
SHIFT_TOL = 2            # pixels of misalignment the change mask forgives
PLUG_OPEN = int(0.65 * PITCH) | 1    # opening kernel: wider than a cable, narrower than a plug
PLUG_MIN_AREA = 0.3 * PITCH ** 2     # smallest surviving blob treated as a plug
PLUG_MAX_AREA = 8 * PITCH ** 2       # bigger than this is a hand or a component, not a plug
PLUG_DARK = 80                       # Dupont housings are black: grey level below this is "plug dark"
PLUG_DARK_MIN = 0.25                 # a candidate this dark (fraction of pixels) counts as a black housing
TOO_MUCH = 0.12          # more than this fraction of the board changed: a hand or the board moved
END_SNAP = 0.75 * PITCH  # max distance from a plug centre to a terminal hole
COLOUR_MIN = 0.15        # fraction of wire pixels that must match the wire colour
CONFIRM_AFTER = 0.5      # seconds: a change must read the same twice this far apart to become an event
RELEARN_AFTER = 3        # still periods in a row with a big change before accepting it as the new board
MOVED = 0.35             # switch to a fresh calibration only when the grid has shifted this many pitches

# OpenCV HSV: H 0-180, S and V 0-255.
HSV_RANGES = {
    "red": [((0, 60, 60), (10, 255, 255)), ((165, 60, 60), (180, 255, 255))],    # incl. pale/salmon red
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


def plug_ends(board, mask, before, after) -> tuple[list[dict], np.ndarray]:
    """Jumper plugs in the change mask, snapped to terminal holes.
    Each: {"x", "y", "row", "col", "kind": placed|removed, "blob"}; row/col None if not on a terminal hole.
    Also returns the connected-component labels of the full mask (plug + cable) for the colour test."""
    import cv2
    m = mask.astype(np.uint8)
    # group into wires on a slightly grown mask: plug and cable often show a small gap between them
    _, grown = cv2.connectedComponents(cv2.dilate(m, np.ones((9, 9), np.uint8)))
    wire_labels = np.where(mask, grown, 0)
    opened = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (PLUG_OPEN, PLUG_OPEN)))
    n, labels, stats, cents = cv2.connectedComponentsWithStats(opened)
    grey_b = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY).astype(np.float32)
    grey_a = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY).astype(np.float32)
    h, w = mask.shape

    # plug candidates grouped by the wire (full-mask component) they sit on
    by_wire: dict[int, list[int]] = {}
    for i in range(1, n):
        if PLUG_MIN_AREA <= stats[i, cv2.CC_STAT_AREA] <= PLUG_MAX_AREA:
            ys, xs = np.nonzero(labels == i)
            by_wire.setdefault(int(np.bincount(wire_labels[ys, xs]).argmax()), []).append(i)

    ends = []
    for wire, cands in by_wire.items():
        # prefer black housings over thick or lifted stretches of coloured cable
        darkness = {i: max((grey_a[labels == i] < PLUG_DARK).mean(), (grey_b[labels == i] < PLUG_DARK).mean())
                    for i in cands}
        dark = [i for i in cands if darkness[i] >= PLUG_DARK_MIN]
        if dark and len(dark) < len(cands):
            cands = dark
        ys, xs = np.nonzero(wire_labels == wire)
        pts = np.stack([xs, ys], axis=1).astype(np.float32)
        border = (xs <= 2) | (ys <= 2) | (xs >= w - 3) | (ys >= h - 3)
        if border.any():                                  # cable comes in from off the board
            entry = pts[border].mean(axis=0)
            chosen = [max(cands, key=lambda i: np.linalg.norm(cents[i] - entry))]
        else:                                             # jumper lying wholly on the board: both ends
            mean = pts.mean(axis=0)
            axis = np.linalg.svd(pts - mean, full_matrices=False)[2][0]
            proj = {i: float((cents[i] - mean) @ axis) for i in cands}
            chosen = sorted({min(proj, key=proj.get), max(proj, key=proj.get)})
        for i in chosen:
            blob = labels == i
            x, y = cents[i]
            d = np.linalg.norm(board.hole_px - (x, y), axis=1)
            k = int(np.argmin(d))
            row, col = board.holes[k] if d[k] < END_SNAP else (None, None)
            kind = "removed" if grey_a[blob].mean() > grey_b[blob].mean() else "placed"
            ends.append({"x": float(x), "y": float(y), "row": row, "col": col, "kind": kind, "blob": wire})
    return ends, wire_labels


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
    """Compare two warped boards. Returns the result and an overlay (mask + plugs) for drawing."""
    mask = change_mask(before, after)
    overlay = {"mask": mask, "ends": []}
    if mask.mean() > TOO_MUCH:
        return CheckResult("unsure", "Something big is in the way. Move your hand away, then say done."), overlay
    ends, wire_labels = plug_ends(board, mask, before, after)
    overlay["ends"] = ends
    placed = [e for e in ends if e["row"] is not None and e["kind"] == "placed"]
    if not placed:
        return CheckResult("unsure", "I don't see a wire plugged in yet. Check it's pushed in, then say done."), overlay

    rows_found = sorted({e["row"] for e in placed})
    if set(rows_found) != set(expect_rows):
        want = " and ".join(map(str, expect_rows))
        wrong = [e for e in placed if e["row"] not in expect_rows]
        if len(expect_rows) == 1 and len(placed) == 1:
            detail = f"That went into row {placed[0]['row']}, it should be row {want}."
        elif wrong:
            detail = f"I see a wire in row {' and '.join(str(e['row']) for e in wrong)}, it should be row {want}."
        else:
            detail = f"I only see a wire in row {' and '.join(map(str, rows_found))}, it should be row {want}."
        return CheckResult("fail", detail, rows_found), overlay

    if wire_colour:
        import cv2
        # colour of the cable only: the plug housing is black whatever the wire colour
        wire = np.isin(wire_labels, [e["blob"] for e in placed])
        housing = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN,
                                   cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (PLUG_OPEN, PLUG_OPEN)))
        cable = wire & ~cv2.dilate(housing, np.ones((5, 5), np.uint8)).astype(bool)
        fractions = colour_fractions(after, cable if cable.sum() > 0.5 * PITCH ** 2 else wire)
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
            if e.get("kind") == "removed":
                cv2.circle(warped, (x, y), int(0.45 * PITCH), (160, 160, 160), 1)
                continue
            good = e["row"] in expect_rows
            colour = (0, 200, 0) if good else (0, 0, 255)
            cv2.circle(warped, (x, y), int(0.45 * PITCH), colour, 2)
            cv2.putText(warped, f"{e['col']}{e['row']}", (x + 10, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 1, cv2.LINE_AA)
    return warped


# --- real-time -----------------------------------------------------------------------

class Vision:
    def __init__(self, camera, board=None, rows: int = 63, persist: bool = True):
        import calibrate
        self.camera = camera
        self.persist = persist                    # write calib.json (off in tests)
        if board is None:
            # Always calibrate fresh from the camera; the saved file is only a fallback, so a stale or
            # wrong calib.json can never poison a run.
            try:
                board, info = calibrate.calibrate_from_camera(camera, rows)
                print(f"auto-calibrated: {info['holes']}/{info['expected']} holes, "
                      f"{'upright' if info['upright'] else 'rotated 180'}", flush=True)
            except calibrate.CalibrationError as e:
                board = calibrate.load()
                if board.rows != rows:
                    raise calibrate.CalibrationError(f"{e}; and calib.json is for a {board.rows}-row board") from e
                print(f"auto-calibration failed ({e}); using calib.json", flush=True)
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
        self.baseline = None                      # last accepted still board; events are changes from it
        self.events: list[dict] = []              # {"t", "kind": placed|removed, "holes": ["i14"], "before", "after", ...}
        self.wires: set[str] = set()              # wire ends currently in the board, e.g. {"i14"}
        self._event_cv = threading.Condition()
        FRAMES_DIR.mkdir(exist_ok=True)
        threading.Thread(target=self._loop, daemon=True).start()
        threading.Thread(target=self._watch_loop, daemon=True).start()

    # --- automatic watching ---------------------------------------------------------

    def _stable_board(self):
        """(still-period id, raw frame) if the board is currently still, else (None, None)."""
        with self._lock:
            if self._raw is None or time.time() - self._still_since < STILL_FOR:
                return None, None
            return self._still_since, self._raw.copy()

    def _debug_dump(self, before, after, mask):
        """VISION_DEBUG=1: save each evaluated before/after pair and print every plug candidate."""
        import cv2
        stamp = time.strftime("%H%M%S")
        out = FRAMES_DIR / "debug"
        out.mkdir(exist_ok=True)
        cv2.imwrite(str(out / f"{stamp}_before.png"), before)
        cv2.imwrite(str(out / f"{stamp}_after.png"), after)
        if mask.mean() < 0.005:
            return                                # nothing worth logging
        ends, _ = plug_ends(self.board, mask, before, after)
        print(f"  debug {stamp}: changed {mask.mean():.1%}; plugs " +
              (", ".join(f"{e['kind']} {e['col']}{e['row']}" for e in ends) or "none"), flush=True)

    def _save_board(self):
        import calibrate
        if self.persist:
            calibrate.save_board(self.board)

    def _aligned(self, raw):
        """Warp a raw frame to the board. Re-calibrates from the frame, but only switches grid when the
        board has really moved (each fit wobbles by a pixel or two, more than the change mask forgives).
        Keeps the current grid if calibration fails (e.g. a hand is in the way)."""
        import cv2
        import calibrate
        try:
            new, _ = calibrate.auto_calibrate(raw, self.board.rows, prev=self.board)
        except calibrate.CalibrationError:
            return self.board.warp(raw)
        moved = cv2.perspectiveTransform(new.hole_cam.reshape(-1, 1, 2), self.board.H).reshape(-1, 2)
        shift = float(np.linalg.norm(moved - self.board.hole_px, axis=1).mean()) / PITCH
        if shift > MOVED:
            self.board = new
            self.status = f"board moved {shift:.1f} holes: re-aligned"
            print(f"  {self.status}", flush=True)
        return self.board.warp(raw)

    def _watch_loop(self):
        import calibrate
        seen = None                               # still period already handled
        big = 0                                   # consecutive still periods with a big change
        while True:
            time.sleep(0.1)
            if self._busy:
                continue
            period, raw = self._stable_board()
            if period is None or period == seen:
                continue
            board_img = self._aligned(raw)
            if self.baseline is None:
                self.baseline, seen = board_img, period
                self._save_board()
                self.status = "watching the board"
                continue
            mask = change_mask(self.baseline, board_img)
            if DEBUG:
                self._debug_dump(self.baseline, board_img, mask)
            if mask.mean() > TOO_MUCH:
                big += 1
                seen = period                     # wait for the next movement
                if big >= RELEARN_AFTER:          # it's not going away: accept the board as it is now
                    self.baseline, big = board_img, 0
                    self.status = "re-learned the board"
                else:
                    self.status = "something big is over the board"
                continue
            big = 0
            ends, _ = plug_ends(self.board, mask, self.baseline, board_img)
            ends = [e for e in ends if e["row"] is not None and not self._near_known_wire(e)]
            if not ends:
                self.baseline, seen = board_img, period    # cable moved / lighting drift: absorb it
                continue
            time.sleep(CONFIRM_AFTER)                       # must read the same a moment later
            period2, raw2 = self._stable_board()
            if period2 != period:
                continue                                    # moved again; re-evaluate when still
            board2 = self.board.warp(raw2)
            ends2, _ = plug_ends(self.board, change_mask(self.baseline, board2), self.baseline, board2)
            ends2 = [e for e in ends2 if not self._near_known_wire(e)]
            key = lambda es: sorted((e["kind"], f"{e['col']}{e['row']}") for e in es if e["row"] is not None)
            if key(ends) != key(ends2):
                continue
            placed = sorted({f"{e['col']}{e['row']}" for e in ends if e["kind"] == "placed"})
            removed = sorted({f"{e['col']}{e['row']}" for e in ends if e["kind"] == "removed"})
            kind = "moved" if placed and removed else "placed" if placed else "removed"
            event = {"t": time.strftime("%H:%M:%S"), "kind": kind, "placed": placed, "removed": removed,
                     "holes": placed or removed, "rows": sorted({e["row"] for e in ends if e["kind"] == "placed"}),
                     "before": self.baseline, "after": board2, "overlay": {"mask": mask, "ends": ends}}
            self.wires = (self.wires - set(removed)) | set(placed)
            self.overlay = event["overlay"]
            parts = ([f"placed at {', '.join(placed)}"] if placed else []) + \
                    ([f"removed from {', '.join(removed)}"] if removed else [])
            self.status = "wire " + " and ".join(parts)
            print(f"[{event['t']}] {self.status}", flush=True)
            self.baseline, seen = board2, period
            self._save_board()
            with self._event_cv:
                self.events.append(event)
                self._event_cv.notify_all()

    def _near_known_wire(self, end: dict) -> bool:
        """A 'placement' within a hole of a wire already in the board is that wire's cable swinging."""
        if end["kind"] != "placed" or end["row"] is None:
            return False
        for hole in self.wires:
            x, y = self.board.hole_px[self.board.holes.index((int(hole[1:]), hole[0]))]
            if np.hypot(end["x"] - x, end["y"] - y) < 1.5 * PITCH:
                return True
        return False

    def wait_for_event(self, timeout: float | None = None, kind: str | None = None) -> dict | None:
        """Block until the next event (optionally of one kind); None on timeout."""
        deadline = None if timeout is None else time.time() + timeout
        with self._event_cv:
            start = len(self.events)
            while True:
                for e in self.events[start:]:
                    if kind is None or e["kind"] == kind:
                        return e
                start = len(self.events)
                remaining = None if deadline is None else deadline - time.time()
                if remaining is not None and remaining <= 0:
                    return None
                self._event_cv.wait(remaining)

    def wait_for_placement(self, expect_rows: list[int], wire_colour: str | None = None,
                           timeout: float | None = 120) -> CheckResult | None:
        """Hands-free check: wait for the next wire placement and judge it. None on timeout."""
        self.expect_rows = list(expect_rows)
        deadline = None if timeout is None else time.time() + timeout
        while True:
            event = self.wait_for_event(None if deadline is None else max(0.0, deadline - time.time()))
            if event is None:
                return None
            if event["placed"]:
                break
        result, overlay = analyse(self.board, event["before"], event["after"], expect_rows, wire_colour)
        result.frame = self._save(draw_result(self.board, event["after"].copy(), overlay, expect_rows), result.status)
        self.overlay, self.status = overlay, result.detail
        return result

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
        for hole in self.wires:                           # every wire end currently in the board
            x, y = self.board.hole_px[self.board.holes.index((int(hole[1:]), hole[0]))].astype(int)
            cv2.circle(warped, (x, y), int(0.3 * PITCH), (255, 200, 0), -1)
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

    def wait_for_placement(self, expect_rows: list[int], wire_colour: str | None = None,
                           timeout: float | None = 120) -> CheckResult | None:
        return self.check_placement(Snapshot(image=None), expect_rows, wire_colour)


if __name__ == "__main__":
    import argparse
    import cv2
    from camera import Camera, default_source, parse_source

    p = argparse.ArgumentParser(description="Live vision: watches the board and reports wire placements")
    p.add_argument("--row", type=int, nargs="+", default=None, help="expected row(s): judge each placement")
    p.add_argument("--colour", default=None, choices=list(HSV_RANGES))
    p.add_argument("--source", default=None, help="camera index or stream URL (default: CAMERA_SOURCE)")
    args = p.parse_args()

    vision = Vision(Camera(parse_source(args.source) if args.source else default_source()))

    if args.row:
        def judge():
            while True:
                r = vision.wait_for_placement(args.row, args.colour, timeout=None)
                print(f"  check vs row {args.row}: {r.status.upper()} - {r.detail}", flush=True)
        threading.Thread(target=judge, daemon=True).start()

    vision.show_forever()
