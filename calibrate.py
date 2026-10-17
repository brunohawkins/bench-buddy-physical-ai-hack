"""Board geometry and calibration. Owner: V.

Click 4 hole centres once (a1, j1, jN, aN). A homography then maps every camera frame to a flat,
top-down board where each hole sits on a known pixel.

    python calibrate.py --rows 63 [--source N]

Keys: click = place point (a magnifier follows the mouse), u = undo, r = reset, Enter or s = save, q = quit.
After saving, the window keeps showing the live grid so you can check it lines up.
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
    """Breadboard geometry for one calibration. x in the warped image runs along rows, y across columns."""

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
        return MARGIN_ROW + (row - 1) * PITCH, MARGIN_COL + COL_POS[col] * PITCH

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
                x, y = self.hole_xy(r, "a")
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


if __name__ == "__main__":
    from camera import Camera, default_source, parse_source
    p = argparse.ArgumentParser(description="Click 4 hole centres to calibrate the board")
    p.add_argument("--rows", type=int, required=True, help="number of numbered rows on the breadboard")
    p.add_argument("--source", default=None, help="camera index or stream URL (default: CAMERA_SOURCE)")
    args = p.parse_args()
    run(Camera(parse_source(args.source) if args.source else default_source()), args.rows)
