"""Synthetic end-to-end test of the vision analysis: draw a flat board, project it into a tilted
"camera" image, then calibrate, warp back and analyse.

    .venv/bin/python -m pytest tests/      or      .venv/bin/python tests/test_vision.py
"""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from calibrate import COLS, MARGIN_COL, PITCH, Board  # noqa: E402
from vision import analyse  # noqa: E402

ROWS = 30
CAM = (1920, 1080)
# Where holes a1, j1, jN, aN land in the camera image: a tilted, keystoned view.
CORNERS = [(420, 380), (470, 700), (1500, 760), (1480, 330)]
BOARD = Board(CORNERS, ROWS)

RED, BLUE = (40, 40, 210), (200, 90, 30)


def camera_image(wire_row=None, colour=RED, brightness=1.0, hand=False, seed=0):
    """Synthetic camera frame of the board, optionally with a jumper from (row, c) to the rail."""
    w, h = BOARD.size
    flat = np.full((h, w, 3), (215, 220, 222), np.uint8)
    for x, y in BOARD.hole_px.astype(int):
        cv2.rectangle(flat, (x - 3, y - 3), (x + 3, y + 3), (60, 60, 60), -1)
    if wire_row:
        x, y = BOARD.hole_xy(wire_row, "c")
        cv2.line(flat, (x, y), (x, MARGIN_COL - 3 * PITCH), colour, 7)
        cv2.circle(flat, (x, y), 5, colour, -1)
    if hand:
        cv2.ellipse(flat, (w // 2, h // 2), (w // 3, h // 2), 0, 0, 360, (120, 160, 210), -1)
    cam = cv2.warpPerspective(flat, BOARD.H_inv, CAM, borderValue=(40, 40, 40))
    noise = np.random.default_rng(seed).normal(0, 3, cam.shape)
    return np.clip(cam * brightness + noise, 0, 255).astype(np.uint8)


def run(after_kwargs, expect=(13,), colour="red"):
    before = BOARD.warp(camera_image(seed=1))
    after = BOARD.warp(camera_image(seed=2, **after_kwargs))
    result, _ = analyse(BOARD, before, after, list(expect), colour)
    return result


def test_correct_row_passes():
    r = run({"wire_row": 13})
    assert r.status == "pass", r


def test_wrong_row_fails_with_both_rows():
    r = run({"wire_row": 14})
    assert r.status == "fail" and "row 14" in r.detail and "row 13" in r.detail, r


def test_wrong_colour_fails():
    r = run({"wire_row": 13, "colour": BLUE})
    assert r.status == "fail" and "blue" in r.detail, r


def test_exposure_drift_still_passes():
    r = run({"wire_row": 13, "brightness": 0.85})
    assert r.status == "pass", r


def test_hand_in_frame_is_unsure():
    r = run({"wire_row": 13, "hand": True})
    assert r.status == "unsure", r


def test_nothing_changed_is_unsure():
    r = run({})
    assert r.status == "unsure", r


def test_calibration_round_trip():
    pts = BOARD.to_camera([BOARD.hole_xy(1, "a"), BOARD.hole_xy(ROWS, "j")])
    assert np.allclose(pts, [CORNERS[0], CORNERS[2]], atol=0.5)
    assert len(BOARD.holes) == ROWS * len(COLS)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
