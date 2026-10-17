"""Board calibration: click the 4 corners of the hole area once, then map (row, column) <-> pixel. Owner: V.

Run `python calibrate.py [source]` to click corners; saves calib.json.
"""
import json
from pathlib import Path

CALIB_PATH = Path("calib.json")
BOARD_ROWS = 63              # TODO(V): count the numbered rows on your breadboard
BOARD_COLS = "abcdefghij"


def save(corners: list[tuple[int, int]]) -> None:
    CALIB_PATH.write_text(json.dumps({"corners": corners}))


def load() -> list[tuple[int, int]]:
    return [tuple(c) for c in json.loads(CALIB_PATH.read_text())["corners"]]


def click_corners(frame) -> list[tuple[int, int]]:
    """Show the frame, collect 4 clicks: top-left, top-right, bottom-right, bottom-left."""
    raise NotImplementedError("TODO(V): cv2.setMouseCallback, collect 4 points")


def warp(frame, corners):
    """Flat top-down board image."""
    raise NotImplementedError("TODO(V): cv2.getPerspectiveTransform + cv2.warpPerspective")


def hole_px(row: int, col: str) -> tuple[int, int]:
    """Pixel centre of a hole in the warped image."""
    raise NotImplementedError("TODO(V): linear interpolation across the warped board")


def draw_grid(board):
    """Draw hole centres and row numbers on the warped image."""
    raise NotImplementedError("TODO(V)")


if __name__ == "__main__":
    import sys
    from camera import Camera, parse_source
    cam = Camera(parse_source(sys.argv[1] if len(sys.argv) > 1 else "0"))
    # TODO(V): wait for a frame, click_corners, save, then show warp + draw_grid live
