"""Board geometry and calibration. Owner: V.

A homography maps every camera frame to a flat, top-down board where each hole sits on a known
pixel. It is found automatically from the camera image (see auto_calibrate); no clicking.

    python calibrate.py [--rows 63] [--source N]     # auto: finds the board, saves calib.json, shows the grid
    python calibrate.py --manual                     # fallback: click holes a1, j1, jN, aN

Manual keys: click = place point (a magnifier follows the mouse), u = undo, r = reset, Enter or s = save, q = quit.
"""
import argparse
import json
from pathlib import Path

import numpy as np

CALIB_PATH = Path("calib.json")
COLS = "abcdefghij"
# Column positions in hole pitches (0.1"). The centre channel is 3 pitches wide, so e -> f jumps by 3.
COL_POS = {c: i for i, c in enumerate("abcde")} | {c: i + 7 for i, c in enumerate("fghij")}
PITCH = 20                   # warped pixels per hole pitch
MARGIN_ROW = 2 * PITCH       # beyond row 1 and row N
MARGIN_COL = 5 * PITCH       # beyond columns a and j: room for the power rails

GRID = (150, 150, 150)
HIGHLIGHT = (0, 200, 0)


class Board:
    """Breadboard geometry for one calibration. In the warped image x runs along the rows (row 1 on the
    left) and y across the columns (j at the top, a at the bottom), as you'd read the board."""

    def __init__(self, corners, rows: int):
        import cv2
        self.rows = rows
        self.corners = np.float32(corners)
        self.size = ((rows - 1) * PITCH + 2 * MARGIN_ROW, COL_POS["j"] * PITCH + 2 * MARGIN_COL)  # (w, h)
        dst = np.float32([self.hole_xy(1, "a"), self.hole_xy(1, "j"), self.hole_xy(rows, "j"), self.hole_xy(rows, "a")])
        self.H = cv2.getPerspectiveTransform(self.corners, dst)
        self.H_inv = np.linalg.inv(self.H)
        self.holes = [(r, c) for r in range(1, rows + 1) for c in COLS]
        self.hole_px = np.float32([self.hole_xy(r, c) for r, c in self.holes])
        self.hole_cam = self.to_camera(self.hole_px)

    @staticmethod
    def hole_xy(row: int, col: str) -> tuple[int, int]:
        """Pixel centre of a terminal hole in the warped image."""
        return MARGIN_ROW + (row - 1) * PITCH, MARGIN_COL + (COL_POS["j"] - COL_POS[col]) * PITCH

    def warp(self, frame):
        import cv2
        return cv2.warpPerspective(frame, self.H, self.size)

    def to_camera(self, pts) -> np.ndarray:
        import cv2
        return cv2.perspectiveTransform(np.float32(pts).reshape(-1, 1, 2), self.H_inv).reshape(-1, 2)

    def draw_grid(self, board, highlight_rows=()):
        """Hole dots, row numbers every 5 rows and column letters, on the warped image (in place)."""
        import cv2
        for (r, c), (x, y) in zip(self.holes, self.hole_px.astype(int)):
            cv2.circle(board, (x, y), 2, HIGHLIGHT if r in highlight_rows else GRID, -1)
        for r in range(1, self.rows + 1):
            if r == 1 or r % 5 == 0 or r in highlight_rows:
                x, y = self.hole_xy(r, "j")
                cv2.putText(board, str(r), (x - 8, y - PITCH), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                            HIGHLIGHT if r in highlight_rows else GRID, 1, cv2.LINE_AA)
        for c in COLS:
            x, y = self.hole_xy(1, c)
            cv2.putText(board, c, (x - PITCH - 12, y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, GRID, 1, cv2.LINE_AA)
        return board

    def draw_on_camera(self, frame, highlight_rows=()):
        """Projected hole dots on the raw camera frame (in place)."""
        import cv2
        for (r, _), (x, y) in zip(self.holes, self.hole_cam.astype(int)):
            cv2.circle(frame, (x, y), 2, HIGHLIGHT if r in highlight_rows else GRID, -1)
        for r in highlight_rows:
            a, j = self.to_camera([self.hole_xy(r, "a"), self.hole_xy(r, "j")]).astype(int)
            cv2.line(frame, tuple(a), tuple(j), HIGHLIGHT, 2, cv2.LINE_AA)
        return frame


def save(corners, rows: int) -> None:
    CALIB_PATH.write_text(json.dumps({"corners": [list(map(float, c)) for c in corners], "rows": rows}))


def load() -> Board:
    data = json.loads(CALIB_PATH.read_text())
    return Board(data["corners"], data["rows"])


# --- automatic calibration -------------------------------------------------------------
#
# 1. The board is the largest bright region: its 4-cornered outline gives a rough top-down warp.
# 2. Holes are small dark blobs (morphological black-hat) inside it.
# 3. Hole y-positions cluster into lines; the 5 lines either side of the centre channel are the
#    terminal strip. Their x-positions cluster into the N rows.
# 4. Every matched hole gives a (camera pixel -> grid pixel) pair; a RANSAC homography over ~600
#    pairs is far more accurate than 4 clicks.
# 5. A breadboard looks the same rotated 180 degrees; the red/blue rail stripes break the tie.

ROW1_LEFT = True      # with the red rail stripes above the blue ones, row 1 is on the left...
A_AT_BOTTOM = True    # ...and column a is the bottom line of holes. Flip these if your board is printed the other way.
WORK_LEN = 1400       # rough-warp length of the board's long side, in pixels


class CalibrationError(RuntimeError):
    pass


def _order(quad):
    """(TL, TR, BR, BL) with TL->TR a long edge running left to right, plus the mean side lengths."""
    quad = np.float32(quad)
    centre = quad.mean(axis=0)
    quad = quad[np.argsort(np.arctan2(quad[:, 1] - centre[1], quad[:, 0] - centre[0]))]   # clockwise on screen
    edges = [np.linalg.norm(quad[(k + 1) % 4] - quad[k]) for k in range(4)]
    k = 0 if edges[0] + edges[2] >= edges[1] + edges[3] else 1                           # a long edge
    d = quad[(k + 1) % 4] - quad[k]
    if d[0] < 0 or (abs(d[0]) < 1e-6 and d[1] < 0):
        k += 2                                       # the opposite long edge runs left-to-right
    quad = np.roll(quad, -(k % 4), axis=0)
    length = (np.linalg.norm(quad[1] - quad[0]) + np.linalg.norm(quad[2] - quad[3])) / 2
    width = (np.linalg.norm(quad[3] - quad[0]) + np.linalg.norm(quad[2] - quad[1])) / 2
    return quad, length, width


def _board_candidates(frame):
    """Possible board outlines: the 4-cornered outline (corrects perspective, but glare or a tab can
    pull a corner out) and the rotated bounding box (robust, but ignores perspective)."""
    import cv2
    grey = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (7, 7), 0)
    _, mask = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise CalibrationError("no bright board found")
    c = max(contours, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.02 * frame.shape[0] * frame.shape[1]:
        raise CalibrationError("board too small or not found")
    hull = cv2.convexHull(c)
    quad = cv2.approxPolyDP(hull, 0.02 * cv2.arcLength(hull, True), True).reshape(-1, 2)
    out = [_order(quad)] if len(quad) == 4 else []
    return out + [_order(cv2.boxPoints(cv2.minAreaRect(c)))]


def _deskew(pts, p0):
    """Rotate hole centres so the lines of holes are horizontal. The outline's angle can be off by a
    degree or two (glare, tabs), which over a 1000 px board is a whole pitch; the holes themselves
    tell us the angle: pick the one where their y-positions bunch into the sharpest lines."""
    best_score, best = -1.0, 0.0
    for deg in np.arange(-5, 5.01, 0.2):
        t = np.radians(deg)
        y = pts[:, 1] * np.cos(t) - pts[:, 0] * np.sin(t)
        h, _ = np.histogram(y, bins=np.arange(y.min(), y.max() + 0.25 * p0, 0.2 * p0))
        score = float((h.astype(float) ** 2).sum())
        if score > best_score:
            best_score, best = score, t
    c, s_ = np.cos(best), np.sin(best)
    return np.stack([pts[:, 0] * c + pts[:, 1] * s_, pts[:, 1] * c - pts[:, 0] * s_], axis=1)


def _clusters(values, gap):
    """Split sorted 1-D values wherever consecutive values differ by more than gap."""
    order = np.sort(values)
    groups, start = [], 0
    for i in range(1, len(order) + 1):
        if i == len(order) or order[i] - order[i - 1] > gap:
            groups.append(order[start:i])
            start = i
    return groups


def auto_calibrate(frame, rows: int = 63) -> tuple["Board", dict]:
    """Board from one camera frame, no clicks. Raises CalibrationError if the board can't be found."""
    best, errors = None, []
    for box, length, width in _board_candidates(frame):
        try:
            board, info = _fit(frame, box, length, width, rows)
        except CalibrationError as e:
            errors.append(str(e))
            continue
        if best is None or (info["holes"], -info["rms_pitch"]) > (best[1]["holes"], -best[1]["rms_pitch"]):
            best = board, info
    if best is None:
        raise CalibrationError("; ".join(errors))
    return _refine(frame, *best)


def _refine(frame, board: "Board", info: dict) -> tuple["Board", dict]:
    """Second pass: warp with the first fit, re-detect every hole on the now-flat board, snap each to
    its nearest grid hole and refit. Recovers holes the first pass missed at the far ends."""
    import cv2
    flat = cv2.cvtColor(board.warp(frame), cv2.COLOR_BGR2GRAY)
    k = int(PITCH * 0.8) | 1
    blackhat = cv2.morphologyEx(flat, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    _, bw = cv2.threshold(blackhat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, _, stats, cents = cv2.connectedComponentsWithStats(bw)
    area = stats[1:, cv2.CC_STAT_AREA]
    cents = cents[1:][(area > 0.02 * PITCH ** 2) & (area < 0.5 * PITCH ** 2)]
    if len(cents) == 0:
        return board, info
    # nearest grid hole for every blob
    d = np.linalg.norm(cents[:, None, :] - board.hole_px[None, :, :], axis=2)
    nearest = d.argmin(axis=1)
    dist = d[np.arange(len(cents)), nearest]
    ok = dist < 0.3 * PITCH
    for h in np.unique(nearest[ok]):                 # a hole can split into two blobs: keep the closer one
        same = np.nonzero(ok & (nearest == h))[0]
        ok[same[dist[same] != dist[same].min()]] = False
    src = board.to_camera(cents[ok])
    dst = board.hole_px[nearest[ok]]
    H, inliers = cv2.findHomography(src, dst, cv2.RANSAC, 0.2 * PITCH)
    if H is None:
        return board, info
    inliers = inliers.ravel().astype(bool)
    if inliers.sum() <= info["holes"]:
        return board, info                            # only keep the refit if it explains more holes
    fitted = cv2.perspectiveTransform(src[inliers].reshape(-1, 1, 2), H).reshape(-1, 2)
    rms = float(np.sqrt(((fitted - dst[inliers]) ** 2).sum(axis=1).mean())) / PITCH
    anchors = [Board.hole_xy(1, "a"), Board.hole_xy(1, "j"), Board.hole_xy(board.rows, "j"), Board.hole_xy(board.rows, "a")]
    corners = cv2.perspectiveTransform(np.float32(anchors).reshape(-1, 1, 2), np.linalg.inv(H)).reshape(-1, 2)
    return Board(corners.tolist(), board.rows), {**info, "holes": int(inliers.sum()), "rms_pitch": rms}


def _fit(frame, box, length, width, rows: int) -> tuple["Board", dict]:
    """Detect holes inside one candidate outline and fit the grid."""
    import cv2
    out_w, out_h = WORK_LEN, int(round(WORK_LEN * width / length))
    M = cv2.getPerspectiveTransform(box, np.float32([(0, 0), (out_w, 0), (out_w, out_h), (0, out_h)]))
    rect = cv2.warpPerspective(frame, M, (out_w, out_h))
    p0 = WORK_LEN / (rows + 2)                          # a board is ~2 pitches longer than its rows

    # Holes: dark blobs smaller than a pitch.
    grey = cv2.cvtColor(rect, cv2.COLOR_BGR2GRAY)
    k = int(p0 * 0.8) | 1
    blackhat = cv2.morphologyEx(grey, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    _, bw = cv2.threshold(blackhat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    n, _, stats, cents = cv2.connectedComponentsWithStats(bw)
    area = stats[1:, cv2.CC_STAT_AREA]
    bw_w, bw_h = stats[1:, cv2.CC_STAT_WIDTH], stats[1:, cv2.CC_STAT_HEIGHT]
    keep = (area > 0.02 * p0 ** 2) & (area < 0.5 * p0 ** 2) & (bw_w < 0.9 * p0) & (bw_h < 0.9 * p0)
    raw = cents[1:][keep]                                # hole centres in the rough warp
    if len(raw) < rows * 5:
        raise CalibrationError(f"only {len(raw)} holes found")
    pts = _deskew(raw, p0)                              # same holes, lines made horizontal

    # Lines of holes across the board; keep well-populated ones.
    lines = [g.mean() for g in _clusters(pts[:, 1], 0.4 * p0) if len(g) >= rows // 3]
    if len(lines) < 10:
        raise CalibrationError(f"only {len(lines)} lines of holes found")
    gaps = np.diff(lines)
    mids = (np.array(lines[:-1]) + np.array(lines[1:])) / 2
    channel = int(np.argmin(np.abs(mids - (lines[0] + lines[-1]) / 2)))   # the gap nearest the middle
    if channel < 4 or channel + 5 >= len(lines):
        raise CalibrationError("couldn't find 5 lines of holes either side of the centre channel")
    terminal = lines[channel - 4:channel + 6]
    pitch_y = float(np.median(np.concatenate([np.diff(terminal[:5]), np.diff(terminal[5:])])))
    if gaps[channel] < 2 * pitch_y:
        raise CalibrationError("centre channel not found")

    # Rows along the board, from the terminal holes only.
    line_of = np.full(len(pts), -1)
    for j, ly in enumerate(terminal):
        line_of[np.abs(pts[:, 1] - ly) < 0.3 * pitch_y] = j
    term = pts[line_of >= 0]
    cols_x = np.array([g.mean() for g in _clusters(term[:, 0], 0.4 * pitch_y) if len(g) >= 3])
    if len(cols_x) < rows // 2:
        raise CalibrationError(f"only {len(cols_x)} rows of holes found")
    pitch_x = float(np.median(np.diff(cols_x)))
    # Number the rows by walking neighbour to neighbour, so a pitch that shrinks towards the far end
    # (camera not quite overhead) doesn't accumulate into an off-by-one.
    steps = np.maximum(1, np.round(np.diff(cols_x) / pitch_x)).astype(int)
    index = np.concatenate([[0], np.cumsum(steps)])
    if index[-1] != rows - 1:
        raise CalibrationError(f"found {index[-1] + 1} rows, expected {rows}")

    # Orientation from the rail stripes: red above blue = upright.
    hsv = cv2.cvtColor(rect, cv2.COLOR_BGR2HSV)
    red = (cv2.inRange(hsv, (0, 50, 80), (10, 255, 255)) | cv2.inRange(hsv, (165, 50, 80), (180, 255, 255))) > 0
    blue = cv2.inRange(hsv, (95, 50, 60), (130, 255, 255)) > 0
    ry, by = np.nonzero(red)[0], np.nonzero(blue)[0]
    stripes = len(ry) > 200 and len(by) > 200
    upright = ry.mean() < by.mean() if stripes else True

    # (camera pixel, grid pixel) pairs for every terminal hole.
    src, dst = [], []
    M_inv = np.linalg.inv(M)
    for (x, _), raw_xy, j in zip(pts, raw, line_of):
        if j < 0:
            continue
        k = int(np.argmin(np.abs(cols_x - x)))           # nearest row of holes
        if abs(x - cols_x[k]) > 0.35 * pitch_x:
            continue
        i = int(index[k])
        if not upright:
            i, j = rows - 1 - i, 9 - j
        row = i + 1 if ROW1_LEFT else rows - i
        col = COLS[9 - j] if A_AT_BOTTOM else COLS[j]
        src.append(cv2.perspectiveTransform(np.float32([[raw_xy]]), M_inv)[0, 0])
        dst.append(Board.hole_xy(row, col))
    src, dst = np.float32(src), np.float32(dst)
    H, inliers = cv2.findHomography(src, dst, cv2.RANSAC, 0.25 * PITCH)
    if H is None:
        raise CalibrationError("homography fit failed")
    inliers = inliers.ravel().astype(bool)
    fitted = cv2.perspectiveTransform(src[inliers].reshape(-1, 1, 2), H).reshape(-1, 2)
    rms = float(np.sqrt(((fitted - dst[inliers]) ** 2).sum(axis=1).mean()))

    H_inv = np.linalg.inv(H)
    anchors = [Board.hole_xy(1, "a"), Board.hole_xy(1, "j"), Board.hole_xy(rows, "j"), Board.hole_xy(rows, "a")]
    corners = cv2.perspectiveTransform(np.float32(anchors).reshape(-1, 1, 2), H_inv).reshape(-1, 2)
    info = {"holes": int(inliers.sum()), "expected": rows * 10, "rms_pitch": rms / PITCH,
            "upright": bool(upright), "stripes": bool(stripes), "camera_pitch_px": pitch_x * length / WORK_LEN}
    if info["holes"] < 0.5 * rows * 10 or info["rms_pitch"] > 0.2:
        raise CalibrationError(f"poor fit: {info}")
    return Board(corners.tolist(), rows), info


def _magnifier(frame, x: int, y: int, size: int = 60, zoom: int = 4):
    """Zoomed crop around (x, y) with a crosshair, pasted into the top-left corner (in place)."""
    import cv2
    h, w = frame.shape[:2]
    x0, y0 = min(max(x - size // 2, 0), w - size), min(max(y - size // 2, 0), h - size)
    crop = cv2.resize(frame[y0:y0 + size, x0:x0 + size], None, fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST)
    cx, cy = (x - x0) * zoom, (y - y0) * zoom
    cv2.line(crop, (cx, 0), (cx, crop.shape[0]), (0, 0, 255), 1)
    cv2.line(crop, (0, cy), (crop.shape[1], cy), (0, 0, 255), 1)
    frame[:crop.shape[0], :crop.shape[1]] = crop


def run(camera, rows: int) -> None:
    import cv2
    win = "calibrate"
    labels = ["a1", "j1", f"j{rows}", f"a{rows}"]
    pts: list[tuple[int, int]] = []
    mouse = [0, 0]
    board = None

    def on_mouse(event, x, y, flags, _):
        mouse[:] = [x, y]
        if event == cv2.EVENT_LBUTTONDOWN and len(pts) < 4:
            pts.append((x, y))

    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(win, on_mouse)
    while True:
        frame = camera.latest()
        if frame is None:
            cv2.waitKey(30)
            continue
        raw = frame.copy()
        if len(pts) == 4:
            board = board or Board(pts, rows)
            board.draw_on_camera(frame)
            flat = board.draw_grid(board.warp(raw))
            cv2.imshow("warped", flat)
            msg = "Enter or s = save, u = undo, r = reset, q = quit"
        else:
            board = None
            msg = f"Click the centre of hole {labels[len(pts)]} ({len(pts) + 1}/4). u = undo, r = reset, q = quit"
        for p, label in zip(pts, labels):
            cv2.drawMarker(frame, p, (0, 0, 255), cv2.MARKER_CROSS, 16, 1)
            cv2.putText(frame, label, (p[0] + 6, p[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
        _magnifier(frame, *mouse) if len(pts) < 4 else None
        cv2.putText(frame, msg, (10, frame.shape[0] - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, cv2.LINE_AA)
        cv2.imshow(win, frame)

        key = cv2.waitKey(30) & 0xFF
        if key == ord("q"):
            break
        if key == ord("u") and pts:
            pts.pop()
        elif key == ord("r"):
            pts.clear()
        elif key in (13, 10, 3, ord("s")) and len(pts) == 4:
            save(pts, rows)
            print(f"saved {CALIB_PATH}")
    cv2.destroyAllWindows()


def calibrate_from_camera(camera, rows: int, timeout: float = 15.0) -> tuple[Board, dict]:
    """Retry auto_calibrate on fresh frames until it succeeds or times out."""
    import time
    last: Exception | str = "no camera frames"
    deadline = time.time() + timeout
    while time.time() < deadline:
        frame = camera.latest()
        if frame is not None:
            try:
                return auto_calibrate(frame, rows)
            except CalibrationError as e:
                last = e
        time.sleep(0.2)
    raise CalibrationError(f"auto-calibration failed: {last}")


def run_auto(camera, rows: int, show: bool = True) -> None:
    import cv2
    board, info = calibrate_from_camera(camera, rows)
    save(board.corners.tolist(), rows)
    print(f"saved {CALIB_PATH}: {info['holes']}/{info['expected']} holes, "
          f"fit error {info['rms_pitch']:.2f} pitch, {info['camera_pitch_px']:.1f} camera px per hole, "
          f"{'upright' if info['upright'] else 'rotated 180'}{'' if info['stripes'] else ' (no rail stripes seen)'}")
    while show:
        frame = camera.latest()
        cv2.imshow("calibrate", board.draw_on_camera(frame.copy()))
        cv2.imshow("warped", board.draw_grid(board.warp(frame)))
        if cv2.waitKey(30) & 0xFF == ord("q"):
            break
    cv2.destroyAllWindows()


if __name__ == "__main__":
    from camera import Camera, default_source, parse_source
    p = argparse.ArgumentParser(description="Calibrate the board (automatic unless --manual)")
    p.add_argument("--rows", type=int, default=63, help="number of numbered rows on the breadboard")
    p.add_argument("--source", default=None, help="camera index or stream URL (default: CAMERA_SOURCE)")
    p.add_argument("--manual", action="store_true", help="click 4 holes instead")
    p.add_argument("--no-show", action="store_true", help="save and exit without the preview window")
    args = p.parse_args()
    cam = Camera(parse_source(args.source) if args.source else default_source())
    if args.manual:
        run(cam, args.rows)
    else:
        run_auto(cam, args.rows, show=not args.no_show)
