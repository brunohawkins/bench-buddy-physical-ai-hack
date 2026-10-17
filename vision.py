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
import json
import os
import re
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
PLUG_DARK_MIN = 0.12                 # a candidate must be at least this dark (fraction of pixels) to be a plug (glare greys it)
PARALLAX = float(os.environ.get("VISION_PARALLAX", 0.022))  # a plug's top looks this fraction further from the
                                     # frame centre than its hole (housing height / camera height); 0 = off
TOO_MUCH = 0.12          # more than this fraction of the board changed: a hand or the board moved
END_SNAP = 0.75 * PITCH  # max distance from a plug centre to a terminal hole
COLOUR_MIN = 0.15        # fraction of wire pixels that must match the wire colour
HAND_MIN_AREA = 10 * PITCH ** 2  # thick skin-coloured change at least this big is a hand
COMPONENT_MAX_SPAN = 12 * PITCH  # the radar module is ~8 holes across; a longer blob is cable
COMPONENT_MIN_AREA = 2 * PITCH ** 2  # a non-plug change this big (after erasing thin cable) is a component
LED_V = 235              # a lit LED: brightness (HSV V) at least this...
LED_S = 120              # ...with strong colour (the pale rail stripes measure ~70)...
LED_RISE = 40            # ...and at least this much brighter than the same spot with the LED off
LED_MIN_AREA = 6         # pixels of glow
LED_MAX_AREA = 4 * PITCH ** 2      # bigger is a hand or glare, not an LED
LED_ON_FRAMES = 3        # consecutive frames with a glow before reporting "on"
LED_OFF_FRAMES = 6       # consecutive frames without before reporting "off"
LED_WARMUP = 2.0         # seconds of learning the board with the LED off before judging
LED_BODY_MAX = 3 * PITCH  # an LED's coloured body is ~1-2 holes across; a cable is longer
CONFIRM_AFTER = 0.5      # seconds: a change must read the same twice this far apart to become an event
RELEARN_AFTER = 3        # still periods in a row with a big change before accepting it as the new board
MODEL_MIN_CHANGE = 0.004  # a settled change smaller than this (fraction of the board) is absorbed without asking the model
REALIGN_HOLES = 0.8      # re-align only from a fit that found this fraction of the holes (leads cover some)
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
    """Jumper plugs in the change mask, snapped to terminal holes or power rails.
    Each: {"x", "y", "row", "col", "rail", "label", "kind": placed|removed, "blob"}. label is "d12" or
    "top + rail"; row/col are None on a rail, and label is None when the plug is on neither.
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
        # plugs are black housings: thick, lifted or moved stretches of coloured cable never count
        cands = [i for i in cands if max((grey_a[labels == i] < PLUG_DARK).mean(),
                                         (grey_b[labels == i] < PLUG_DARK).mean()) >= PLUG_DARK_MIN]
        if not cands:
            continue
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
            x, y = _parallax(board, *_pin_point(blob, wire_labels == wire, cents[i]))
            d = np.linalg.norm(board.hole_px - (x, y), axis=1)
            k = int(np.argmin(d))
            row, col = board.holes[k] if d[k] < END_SNAP else (None, None)
            rail = board.rail_at(x, y) if row is None else None
            label = f"{col}{row}" if row is not None else f"{rail} rail" if rail else None
            kind = "removed" if grey_a[blob].mean() > grey_b[blob].mean() else "placed"
            ends.append({"x": float(x), "y": float(y), "row": row, "col": col, "rail": rail, "label": label,
                         "kind": kind, "blob": wire})
    return ends, wire_labels


def _pin_point(blob, wire, centre):
    """Where the pin is under a plug. A housing lying tilted puts its centre half a hole short of the pin,
    which is at the front: the edge facing away from where the cable joins. So take that far edge and
    step back half a hole. Falls back to the centre when no cable is visible next to the plug."""
    import cv2
    near_cable = wire & ~cv2.dilate(blob.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    ys, xs = np.nonzero(near_cable)
    close = np.hypot(xs - centre[0], ys - centre[1]) < 2.5 * PITCH
    if close.sum() < 20:
        return float(centre[0]), float(centre[1])
    u = centre - np.array([xs[close].mean(), ys[close].mean()])
    u /= max(np.linalg.norm(u), 1e-6)                      # from the cable towards the plug's front
    by, bx = np.nonzero(blob)
    far = float(((np.stack([bx, by], axis=1) - centre) @ u).max())
    step = float(np.clip(far - 0.5 * PITCH, 0.0, PITCH))
    x, y = centre + u * step
    return float(x), float(y)


def _parallax(board, x: float, y: float) -> tuple[float, float]:
    """Move a plug-top point (warped) back towards the camera's centre, to the hole it stands in."""
    centre = getattr(board, "cam_centre", None)
    if centre is None or not PARALLAX:
        return x, y
    import cv2
    cam = board.to_camera([(x, y)])[0]
    cam = cam + PARALLAX * (np.float32(centre) - cam)
    out = cv2.perspectiveTransform(np.float32(cam).reshape(1, 1, 2), board.H).reshape(2)
    return float(out[0]), float(out[1])


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


RAIL_UI = {"top +": "+L", "top -": "-L", "bottom +": "+R", "bottom -": "-R"}   # ui/js/board.mjs rail names


def parse_hole(h: str) -> tuple[int | None, str | None, str | None]:
    """"d20" -> (20, "d", None); "+top20" -> (20, None, "top +"); anything else -> (None, None, None)."""
    h = str(h).strip().lower().replace(" ", "")
    m = re.fullmatch(r"([a-j])(\d+)", h)
    if m:
        return int(m[2]), m[1], None
    m = re.fullmatch(r"([+-])(top|bottom)(\d+)", h) or re.fullmatch(r"(top|bottom)([+-])(\d+)", h)
    if m:
        sign, side = (m[1], m[2]) if m[1] in "+-" else (m[2], m[1])
        return int(m[3]), None, f"{side} {sign}"
    return None, None, None


def hole_label(h: str) -> str:
    """Human label: "d20" stays, "+top20" -> "top + rail (row 20)"."""
    row, col, rail = parse_hole(h)
    return f"{col}{row}" if col else f"{rail} rail (row {row})" if rail else str(h)


def ui_parts(board: list[dict]) -> list[dict]:
    """The model's part list in ui/js/board.mjs PARTS shape: {id, kind, color, from: [col, row], to, label, detail}."""
    out = []
    for i, p in enumerate(board):
        spots = []
        for h in p.get("holes", []):
            row, col, rail = parse_hole(h)
            if row is not None:
                spots.append([col or RAIL_UI[rail], row])
        colour = p.get("colour") or None
        kind = p.get("part", "other")
        out.append({"id": p.get("id") or f"{kind}{i + 1}", "kind": kind, "color": colour,
                    "from": spots[0] if spots else None, "to": spots[1] if len(spots) > 1 else None, "pins": spots,
                    "label": f"{colour + ' ' if colour and kind == 'wire' else ''}{kind}".capitalize(),
                    "detail": " -> ".join(hole_label(h) for h in p.get("holes", []))})
    return out


def hand_in_view(after, mask) -> bool:
    """Skin-coloured change too thick to be a cable, plug, LED or resistor: a hand or finger is over the board.
    Fingers are ~6 holes wide; erasing everything under 2 holes thick leaves only them."""
    import cv2
    hsv = cv2.cvtColor(after, cv2.COLOR_BGR2HSV)
    h, sat, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    skin = ((h <= 25) | (h >= 170)) & (sat >= 40) & (sat <= 170) & (v >= 90) & mask
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * PITCH + 1, 2 * PITCH + 1))
    return int(cv2.morphologyEx(skin.astype(np.uint8), cv2.MORPH_OPEN, k).sum()) >= HAND_MIN_AREA


def judge_placed(event: dict, expect: list, wire_colour: str | None) -> CheckResult:
    """Pass/fail for a model-judged placement event against the expected rows / rails ("+", "top -", ...)."""
    got = [(h, *parse_hole(h)) for h in event["placed"]]
    got = [g for g in got if g[1] is not None]

    def matches(want, g):
        _, row, _, rail = g
        return row == want if isinstance(want, int) else (rail is not None and str(want) in rail)

    want_txt = " and ".join(f"row {w}" if isinstance(w, int) else f"the {w} rail" for w in expect)
    rows_found = sorted({g[1] for g in got if g[2]})
    if not got:
        return CheckResult("unsure", "I can't tell where it went. Check it's pushed in.", rows_found)
    missing = [w for w in expect if not any(matches(w, g) for g in got)]
    if missing:
        where = ", ".join(hole_label(g[0]) for g in got)
        return CheckResult("fail", f"That went into {where}, it should be {want_txt}.", rows_found)
    colours = [str(c.get("colour") or "").lower() for c in event.get("parts", []) if c.get("action") == "placed"]
    if wire_colour and colours and not any(wire_colour.lower() in c for c in colours if c):
        return CheckResult("fail", f"Right place, but that looks {colours[0]}, not {wire_colour}.", rows_found)
    return CheckResult("pass", f"Got it, {', '.join(hole_label(g[0]) for g in got)}.", rows_found)


def analyse(board, before, after, expect_rows: list[int], wire_colour: str | None) -> tuple[CheckResult, dict]:
    """Compare two warped boards. Returns the result and an overlay (mask + plugs) for drawing."""
    mask = change_mask(before, after)
    overlay = {"mask": mask, "ends": []}
    if mask.mean() > TOO_MUCH or hand_in_view(after, mask):
        return CheckResult("unsure", "Something big is in the way. Move your hand away, then say done."), overlay
    ends, wire_labels = plug_ends(board, mask, before, after)
    overlay["ends"] = ends
    placed = [e for e in ends if e["label"] is not None and e["kind"] == "placed"]
    if not placed:
        return CheckResult("unsure", "I don't see a wire plugged in yet. Check it's pushed in, then say done."), overlay

    def matches(want, e):                       # want: a row number, or a rail like "+", "-", "top +"
        return e["row"] == want if isinstance(want, int) else (e["rail"] is not None and str(want) in e["rail"])

    def where(e):
        return f"row {e['row']}" if e["row"] is not None else f"the {e['rail']} rail"

    def wanted(w):
        return f"row {w}" if isinstance(w, int) else f"the {w} rail"

    rows_found = sorted({e["row"] for e in placed if e["row"] is not None})
    missing = [w for w in expect_rows if not any(matches(w, e) for e in placed)]
    extra = [e for e in placed if not any(matches(w, e) for w in expect_rows)]
    if missing or extra:
        want = " and ".join(wanted(w) for w in expect_rows)
        if len(expect_rows) == 1 and len(placed) == 1:
            detail = f"That went into {where(placed[0])}, it should be {want}."
        elif extra:
            detail = f"I see a wire in {' and '.join(where(e) for e in extra)}, it should be {want}."
        else:
            detail = f"I only see a wire in {' and '.join(where(e) for e in placed)}, it should be {want}."
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

    rows = " and ".join(str(w) if isinstance(w, int) else f"the {w} rail" for w in expect_rows)
    return CheckResult("pass", f"Row {rows}{', ' + wire_colour if wire_colour else ''}. Looks good.", rows_found), overlay


def draw_result(board, warped, overlay: dict | None, expect_rows=()):
    """Grid, expected rows, changed area and wire ends on a warped board (in place)."""
    import cv2
    board.draw_grid(warped, expect_rows)
    if overlay:
        contours, _ = cv2.findContours(overlay["mask"].astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(warped, contours, -1, (0, 220, 255), 1)
        for e in overlay["ends"]:
            if e.get("label") is None:
                cv2.circle(warped, (int(e["x"]), int(e["y"])), 5, (200, 200, 200), 1)
                continue
            if e["row"] is None:                                   # on a power rail
                x, y = int(e["x"]), int(e["y"])
            else:
                x, y = board.hole_px[board.holes.index((e["row"], e["col"]))].astype(int)
            if e.get("kind") == "removed":
                cv2.circle(warped, (x, y), int(0.45 * PITCH), (160, 160, 160), 1)
                continue
            good = e["row"] in expect_rows or (e["rail"] is not None and any(
                isinstance(w, str) and w in e["rail"] for w in expect_rows))
            colour = (0, 200, 0) if good else (0, 0, 255)
            cv2.circle(warped, (x, y), int(0.45 * PITCH), colour, 2)
            cv2.putText(warped, e["label"], (x + 10, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 1, cv2.LINE_AA)
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
            try:                                  # the last session's grid only decides which way round it is
                prev = calibrate.load() if calibrate.CALIB_PATH.exists() else None
            except (OSError, ValueError, KeyError):
                prev = None
            try:
                board, info = calibrate.calibrate_from_camera(camera, rows, prev=prev)
                print(f"auto-calibrated: {info['holes']}/{info['expected']} holes, "
                      f"{'upright' if info['upright'] else 'rotated 180'}"
                      f"{' (orientation kept from calib.json)' if prev is not None else ''}", flush=True)
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
        self._baseline_raw = None                 # the camera frame behind it (re-flattened if the grid changes)
        self._realign = None                      # candidate new grid, waiting for a second agreeing fit
        self.events: list[dict] = []              # {"t", "kind": placed|removed, "holes": ["i14"], "before", "after", ...}
        self.wires: dict[str, tuple[float, float]] = {}   # wire ends in the board: label -> warped (x, y)
        self.led = {"on": False, "label": None, "xy": None}  # LED state, updated every frame (see _led_step)
        self._led_ref = None                      # brightness of the board with the LED off
        self._led_hits = 0                        # consecutive frames with / without a glow (debounce)
        self._led_ok = None                       # still period the watcher has accounted for (LED judged after)
        self._event_cv = threading.Condition()
        self.parts: list[dict] = []                # what the vision model says is on the board (see vlm.judge)
        self.narration = "The board is empty."    # plain-English description of the whole board, from the model
        self.summary = ""                        # the last change, one sentence
        self.listeners: list = []                 # called with state() whenever it changes (UI server, 3D view)
        self.context: list[str] = []              # recent conversation at the bench, given to the model (see note)
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
        import json
        (out / f"{stamp}_board.json").write_text(json.dumps({"corners": self.board.corners.tolist(),
                                                              "rows": self.board.rows,
                                                              "offsets": self.board.offsets.tolist()}))
        if mask.mean() < 0.005:
            return                                # nothing worth logging
        ends, _ = plug_ends(self.board, mask, before, after)
        print(f"  debug {stamp}: changed {mask.mean():.1%}; plugs " +
              (", ".join(f"{e['kind']} {e['label'] or 'off-grid'}" for e in ends) or "none"), flush=True)

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
            new, info = calibrate.auto_calibrate(raw, self.board.rows, prev=self.board)
        except calibrate.CalibrationError:
            return self.board.warp(raw)
        if info.get("holes", 0) < REALIGN_HOLES * self.board.rows * 10:
            return self.board.warp(raw)                  # parts or a hand cover holes: the fit can slip a hole
        moved = cv2.perspectiveTransform(new.hole_cam.reshape(-1, 1, 2), self.board.H).reshape(-1, 2)
        shift = float(np.linalg.norm(moved - self.board.hole_px, axis=1).mean()) / PITCH
        if shift <= MOVED:
            self._realign = None
            return self.board.warp(raw)
        if self._realign is not None:                    # switch only when two fits in a row agree
            again = cv2.perspectiveTransform(new.hole_cam.reshape(-1, 1, 2), self._realign.H).reshape(-1, 2)
            if float(np.linalg.norm(again - self._realign.hole_px, axis=1).mean()) / PITCH < 0.15:
                self.board, self._realign = new, None
                self._led_ref = None                     # reference was in the old grid
                # the baseline stays as it was flattened: if the board itself moved, the old frame needs the old grid
                self.status = f"board moved {shift:.1f} holes: re-aligned"
                print(f"  {self.status}", flush=True)
                return self.board.warp(raw)
        self._realign = new
        return self.board.warp(raw)
        moved = cv2.perspectiveTransform(new.hole_cam.reshape(-1, 1, 2), self.board.H).reshape(-1, 2)
        shift = float(np.linalg.norm(moved - self.board.hole_px, axis=1).mean()) / PITCH
        if shift > MOVED:
            self.board = new
            self._led_ref = None                  # reference was in the old grid
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
                self.baseline, self._baseline_raw, seen = board_img, raw, period
                self._led_rebase(board_img, period, full=True)
                self._save_board()
                self.status = "watching the board"
                continue
            mask = change_mask(self.baseline, board_img)
            if DEBUG:
                self._debug_dump(self.baseline, board_img, mask)
            if mask.mean() > TOO_MUCH or hand_in_view(board_img, mask):
                big += 1
                seen = period                     # wait for the next movement
                if big >= RELEARN_AFTER:          # it's not going away: accept the board as it is now
                    self.baseline, self._baseline_raw, big = board_img, raw, 0
                    self.status = "re-learned the board"
                else:
                    self.status = "something big is over the board"
                continue
            big = 0
            if self._use_model() and self._model_step(mask, board_img, raw, period):
                seen = period
                continue
            ends, _ = plug_ends(self.board, mask, self.baseline, board_img)
            ends = [self._snap_removed(e) for e in ends]
            ends = [e for e in ends if e["label"] is not None and not self._near_known_wire(e)]
            if not ends:
                rows = self._component_rows(mask)
                if rows:                                    # not a wire plug: a resistor, LED, the radar...
                    event = {"t": time.strftime("%H:%M:%S"), "kind": "changed", "placed": [], "removed": [],
                             "holes": [], "rows": rows, "before": self.baseline, "after": board_img,
                             "overlay": {"mask": mask, "ends": []}}
                    self.overlay = event["overlay"]
                    self.status = f"something changed at rows {rows[0]}-{rows[-1]}"
                    print(f"[{event['t']}] {self.status}", flush=True)
                    self._emit(event)
                self.baseline, self._baseline_raw, seen = board_img, raw, period    # cable moved / lighting drift: absorb it
                self._led_rebase(board_img, period, full=bool(rows))
                continue
            time.sleep(CONFIRM_AFTER)                       # must read the same a moment later
            period2, raw2 = self._stable_board()
            if period2 != period:
                continue                                    # moved again; re-evaluate when still
            board2 = self.board.warp(raw2)
            ends2, _ = plug_ends(self.board, change_mask(self.baseline, board2), self.baseline, board2)
            ends2 = [e for e in map(self._snap_removed, ends2) if not self._near_known_wire(e)]
            key = lambda es: sorted((e["kind"], e["label"]) for e in es if e["label"] is not None)
            if key(ends) != key(ends2):
                continue
            placed = sorted({e["label"] for e in ends if e["kind"] == "placed"})
            removed = sorted({e["label"] for e in ends if e["kind"] == "removed"})
            kind = "moved" if placed and removed else "placed" if placed else "removed"
            event = {"t": time.strftime("%H:%M:%S"), "kind": kind, "placed": placed, "removed": removed,
                     "holes": placed or removed, "rows": sorted({e["row"] for e in ends if e["kind"] == "placed"}),
                     "before": self.baseline, "after": board2, "overlay": {"mask": mask, "ends": ends}}
            for e in ends:
                if e["kind"] == "removed":
                    self.wires.pop(e["label"], None)
                else:
                    self.wires[e["label"]] = (e["x"], e["y"])
            self.overlay = event["overlay"]
            parts = ([f"placed at {', '.join(placed)}"] if placed else []) + \
                    ([f"removed from {', '.join(removed)}"] if removed else [])
            self.status = "wire " + " and ".join(parts)
            print(f"[{event['t']}] {self.status}", flush=True)
            self.baseline, self._baseline_raw, seen = board2, raw2, period
            self._led_rebase(board2, period, full=True)
            self._save_board()
            self._emit(event)

    def note(self, who: str, text: str) -> None:
        """Conversation context for the vision model, e.g. note("User", "the black lead is ground")."""
        if text:
            self.context = (self.context + [f"{who}: {text}"])[-20:]

    def describe(self) -> str:
        """Plain English for the tutor: the last change, then the whole board (from the vision model)."""
        return " ".join(t for t in (self.summary, self.narration) if t)

    def verify(self, step: str) -> CheckResult:
        """Ask the vision model whether the board shows `step` done correctly (uses the part list and the
        conversation). For steps the pixel rules can't check, e.g. "connect the radar's black lead to ground"."""
        import vlm
        with self._lock:
            warped = None if self._warped is None else self._warped.copy()
            raw = None if self._raw is None else self._raw.copy()
        if warped is None or not vlm.available():
            return CheckResult("unsure", "I can't see the board right now.")
        try:
            r = vlm.verify(vlm.labelled_crop(self.board, warped, None, self.expect_rows, pad_rows=0), step,
                           self.parts, "\n".join(self.context), camera=vlm.camera_view(raw, self.board))
        except Exception as e:
            print(f"  [vlm] verify failed: {e!r}", flush=True)
            return CheckResult("unsure", "I couldn't check that just now. Say done to try again.")
        status = r.get("status") if r.get("status") in ("pass", "fail", "unsure") else "unsure"
        result = CheckResult(status, r.get("detail") or "", [])
        result.frame = self._save(warped, status)
        print(f"[{time.strftime('%H:%M:%S')}] verify {step[:50]!r}: {status} - {result.detail}", flush=True)
        self.status = result.detail
        return result

    def _use_model(self) -> bool:
        import vlm
        return vlm.available()

    def _model_step(self, mask, board_img, raw, period) -> bool:
        """Let the vision model judge a settled change: what was plugged in or pulled out, which holes, the
        updated part list and narration. False if it couldn't (API error): the pixel rules take over."""
        import vlm
        if mask.mean() < MODEL_MIN_CHANGE:                  # a few stray pixels: absorb without asking
            self.baseline, self._baseline_raw = board_img, raw
            self._led_rebase(board_img, period, full=False)
            return True
        overlay = {"mask": mask, "ends": []}
        before = self.baseline
        self.status = "looking closely..."
        t0 = time.time()
        try:
            v = vlm.judge(vlm.labelled_crop(self.board, before, overlay, self.expect_rows),
                          vlm.labelled_crop(self.board, board_img, overlay, self.expect_rows), self.parts,
                          context="\n".join(self.context),
                          cam_before=None if self._baseline_raw is None else vlm.camera_view(self._baseline_raw, self.board),
                          cam_after=vlm.camera_view(raw, self.board))
        except Exception as e:                              # never let the model break the loop
            print(f"  [vlm] failed ({e!r}); using pixel rules", flush=True)
            return False
        changes = [c for c in v.get("changes", []) if c.get("action") in ("placed", "removed") and c.get("holes")]
        self.baseline, self._baseline_raw = board_img, raw
        self._led_rebase(board_img, period, full=bool(changes))
        if isinstance(v.get("board"), list):
            self.parts = v["board"]
        self.narration = v.get("narration") or self.narration
        if not changes:
            print(f"  [vlm] {time.time() - t0:.1f}s: nothing plugged in or pulled out", flush=True)
            self.status = "watching the board"
            self._publish()
            return True
        placed = sorted({h for c in changes if c["action"] == "placed" for h in c["holes"]})
        removed = sorted({h for c in changes if c["action"] == "removed" for h in c["holes"]})
        kind = "moved" if placed and removed else "placed" if placed else "removed"
        self.summary = v.get("summary") or f"{kind} {', '.join(placed or removed)}"
        event = {"t": time.strftime("%H:%M:%S"), "kind": kind, "placed": placed, "removed": removed,
                 "holes": placed or removed, "rows": sorted({parse_hole(h)[0] for h in placed} - {None}),
                 "parts": changes, "summary": self.summary, "problem": v.get("problem"), "narration": self.narration,
                 "source": "model", "before": before, "after": board_img, "overlay": overlay}
        self.overlay = overlay
        self.status = self.summary
        print(f"[{event['t']}] {self.summary}  ({time.time() - t0:.1f}s; placed {placed}, removed {removed})", flush=True)
        if v.get("problem"):
            print(f"  problem: {v['problem']}", flush=True)
        print(f"  board: {self.narration}", flush=True)
        self._save_board()
        self._publish()
        self._emit(event)
        return True

    def state(self) -> dict:
        """Everything a viewer needs: parts (ui/js/board.mjs shape), LED, narration, last change."""
        return {"t": time.strftime("%H:%M:%S"), "parts": ui_parts(self.parts), "board": self.parts,
                "led": bool(self.led.get("on")), "led_at": self.led.get("label"), "summary": self.summary,
                "narration": self.narration, "status": self.status}

    def _publish(self) -> None:
        """Write the board state to frames/board_state.json and tell listeners (the UI server streams it)."""
        st = self.state()
        try:
            (FRAMES_DIR / "board_state.json").write_text(json.dumps(st, indent=1))
        except OSError:
            pass
        for fn in list(self.listeners):
            try:
                fn(st)
            except Exception as e:
                print(f"  [state] listener failed: {e!r}", flush=True)

    def _emit(self, event: dict) -> None:
        """Publish an event; pixel-rule events also get a background description from the model (if a key is set)."""
        with self._event_cv:
            self.events.append(event)
            self._event_cv.notify_all()
        if event.get("source") != "model":
            self._describe_async(event)

    def _describe_async(self, event: dict) -> None:
        import vlm
        if not vlm.available():
            return

        def run():
            try:
                img = vlm.labelled_crop(self.board, event["after"], event.get("overlay"), self.expect_rows)
                hint = (f"wire {event['kind']}: placed {event['placed'] or 'nothing'}, removed {event['removed'] or 'nothing'}"
                        if event["kind"] != "changed" else
                        f"something that is not a plain wire changed around rows {event['rows'][0]}-{event['rows'][-1]}")
                res = vlm.describe(img, hint=hint)
            except Exception as e:                          # never let the model break the loop
                print(f"  [vlm] failed: {e!r}", flush=True)
                return
            event["vlm"] = res
            self.status = "AI: " + str(res.get("summary", ""))
            print(f"  [vlm] {res}", flush=True)
            with self._event_cv:
                self.events.append({"t": time.strftime("%H:%M:%S"), "kind": "described", "of": event["kind"],
                                    "vlm": res, "placed": [], "removed": [], "holes": [], "rows": res.get("rows", [])})
                self._event_cv.notify_all()

        threading.Thread(target=run, daemon=True).start()

    def ask(self, question: str) -> dict:
        """Ask the vision model about the board as it is now, e.g. "is the LED the right way round?"."""
        import vlm
        with self._lock:
            warped = self._warped.copy()
        return vlm.describe(vlm.labelled_crop(self.board, warped, self.overlay, self.expect_rows), question)

    def _component_rows(self, mask) -> list[int]:
        """Rows covered by changed blobs that survive erasing thin cable, i.e. a component, not a wire."""
        import cv2
        from calibrate import MARGIN_ROW
        opened = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN,
                                  cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (PLUG_OPEN, PLUG_OPEN)))
        n, labels, stats, _ = cv2.connectedComponentsWithStats(opened)
        rows = set()
        for i in range(1, n):
            if stats[i, cv2.CC_STAT_AREA] < COMPONENT_MIN_AREA:
                continue
            (_, _), (bw, bh), _ = cv2.minAreaRect(np.column_stack(np.nonzero(labels == i)[::-1]).astype(np.float32))
            if stats[i, cv2.CC_STAT_AREA] / max(bw, bh, 1) < 1.2 * PITCH or max(bw, bh) > COMPONENT_MAX_SPAN:
                continue                                  # long and thin, or longer than any part: a cable that moved
            x0, w = stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_WIDTH]
            for r in range(int(round((x0 - MARGIN_ROW) / PITCH)) + 1, int(round((x0 + w - MARGIN_ROW) / PITCH)) + 2):
                if 1 <= r <= self.board.rows:
                    rows.add(r)
        return sorted(rows)

    def _snap_removed(self, end: dict) -> dict:
        """A removal within a hole or so of a wire we saw go in is that wire: report the hole it was placed in."""
        if end["kind"] != "removed" or not self.wires:
            return end
        label, (x, y) = min(self.wires.items(), key=lambda kv: np.hypot(end["x"] - kv[1][0], end["y"] - kv[1][1]))
        if np.hypot(end["x"] - x, end["y"] - y) > 1.5 * PITCH:
            return end
        row = int(label[1:]) if label[0].isalpha() and label[1:].isdigit() else None
        rail = None if row is not None else label.removesuffix(" rail")
        return {**end, "x": x, "y": y, "label": label, "row": row, "col": label[0] if row else None, "rail": rail}

    def _near_known_wire(self, end: dict) -> bool:
        """A 'placement' within a hole of a wire already in the board is that wire's cable swinging."""
        if end["kind"] != "placed" or end["label"] is None:
            return False
        for label, (x, y) in self.wires.items():
            if label != end["label"] and np.hypot(end["x"] - x, end["y"] - y) < 1.5 * PITCH:
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
        if event.get("source") == "model":
            result = judge_placed(event, expect_rows, wire_colour)
            result.frame = self._save(draw_result(self.board, event["after"].copy(), event["overlay"], expect_rows), result.status)
            self.status = result.detail
            return result
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
            self.board.cam_centre = (frame.shape[1] / 2, frame.shape[0] / 2)   # for the parallax correction
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
            self._led_step(warped, still=now - self._still_since >= STILL_FOR)
            t_prev = now

    def _led_step(self, warped, still: bool) -> None:
        """Real-time LED watch: a compact, bright, coloured glow that wasn't there with the LED off.
        Debounced both ways, and only judged while the board is still (a hand under a lamp glows too)."""
        import cv2
        hsv = cv2.cvtColor(warped, cv2.COLOR_BGR2HSV)
        v = hsv[..., 2].astype(np.int16)
        if self._led_ref is None or self._led_ref.shape != v.shape:
            self._led_ref = v.astype(np.float32)
            self._led_since = time.time()
            self._led_area = self._terminal_area(v.shape)
            return
        if time.time() - self._led_since < LED_WARMUP:
            self._led_ref = 0.8 * self._led_ref + 0.2 * v
            return
        if not still or self._led_ok != self._still_since:     # wait until the watcher has seen this still period
            return
        glow = (v >= LED_V) & (hsv[..., 1] >= LED_S) & (v - self._led_ref >= LED_RISE) & self._led_area
        n, labels, stats, cents = cv2.connectedComponentsWithStats(glow.astype(np.uint8))
        spots = [i for i in range(1, n) if LED_MIN_AREA <= stats[i, cv2.CC_STAT_AREA] <= LED_MAX_AREA]
        if spots:                                   # a highlight on a long coloured cable is not an LED
            body = ((hsv[..., 1] >= 90) & (v >= 80)).astype(np.uint8)
            _, blabels, bstats, _ = cv2.connectedComponentsWithStats(body)
            def on_cable(i):
                ids = blabels[labels == i]
                b = int(np.bincount(ids[ids > 0]).argmax()) if (ids > 0).any() else 0
                return b > 0 and max(bstats[b, cv2.CC_STAT_WIDTH], bstats[b, cv2.CC_STAT_HEIGHT]) > LED_BODY_MAX
            spots = [i for i in spots if not on_cable(i)]
        if not self.led["on"]:
            self._led_ref = 0.95 * self._led_ref + 0.05 * v          # learn the board with the LED off
        lit = bool(spots)
        self._led_hits = self._led_hits + 1 if lit != self.led["on"] else 0
        if self._led_hits < (LED_ON_FRAMES if lit else LED_OFF_FRAMES):
            return
        self._led_hits = 0
        if lit:
            i = max(spots, key=lambda k: stats[k, cv2.CC_STAT_AREA])
            x, y = cents[i]
            k = int(np.argmin(np.linalg.norm(self.board.hole_px - (x, y), axis=1)))
            row, col = self.board.holes[k]
            self.led = {"on": True, "label": f"{col}{row}", "row": row, "xy": (float(x), float(y))}
        else:
            self.led = {**self.led, "on": False}
        kind = "led_on" if lit else "led_off"
        self.status = f"LED {'ON near ' + self.led['label'] if lit else 'off'}"
        self.summary = "The LED just lit up." if lit else "The LED went off."
        print(f"[{time.strftime('%H:%M:%S')}] {self.status}", flush=True)
        with self._event_cv:
            self.events.append({"t": time.strftime("%H:%M:%S"), "kind": kind, "led": dict(self.led),
                                "placed": [], "removed": [], "holes": [], "rows": []})
            self._event_cv.notify_all()
        self._publish()

    def _led_rebase(self, board_img, period, full: bool) -> None:
        """The watcher has accounted for this still period: judge LEDs against the board as it accepted it.
        full after a placement (a new red cable or part is not a glow); otherwise only darken the reference,
        so an LED that lit up during the period still stands out."""
        import cv2
        v = cv2.cvtColor(board_img, cv2.COLOR_BGR2HSV)[..., 2].astype(np.float32)
        ref = self._led_ref
        if ref is not None and ref.shape == v.shape and not self.led["on"]:
            self._led_ref = v if full else np.minimum(ref, v)
        self._led_ok = period

    def _terminal_area(self, shape):
        """Where an LED can sit: the hole area plus half a pitch, not the rail stripes."""
        from calibrate import COL_POS, MARGIN_COL, MARGIN_ROW
        area = np.zeros(shape, bool)
        y0, y1 = MARGIN_COL - PITCH, MARGIN_COL + (COL_POS["j"] + 1) * PITCH
        area[int(y0):int(y1), int(MARGIN_ROW - PITCH):int(MARGIN_ROW + self.board.rows * PITCH)] = True
        return area

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
        if self.led["on"] and self.led.get("xy"):
            lx, ly = map(int, self.led["xy"])
            cv2.circle(warped, (lx, ly), int(0.8 * PITCH), (0, 255, 255), 3)
            cv2.putText(warped, "LED ON", (lx + 18, ly + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2, cv2.LINE_AA)
        for x, y in list(self.wires.values()):            # every wire end currently in the board
            x, y = int(x), int(y)
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
