"""Synthetic end-to-end test of the vision analysis: draw a flat board, project it into a tilted
"camera" image, then calibrate, warp back and analyse.

    .venv/bin/python -m pytest tests/      or      .venv/bin/python tests/test_vision.py
"""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from calibrate import COLS, PITCH, Board, auto_calibrate  # noqa: E402
from vision import analyse  # noqa: E402

ROWS = 30
CAM = (1920, 1080)
# Where holes a1, j1, jN, aN land in the camera image: a tilted, keystoned view.
CORNERS = [(420, 380), (470, 700), (1500, 760), (1480, 330)]   # column a along the top, as on our board
BOARD = Board(CORNERS, ROWS)

RED, BLUE = (40, 40, 210), (200, 90, 30)


def plug(img, x, y):
    """A black Dupont housing seen from above, centred on the hole."""
    h = int(0.55 * PITCH)
    cv2.rectangle(img, (x - h, y - h), (x + h, y + h), (25, 25, 25), -1)


def camera_image(wire_row=None, colour=RED, brightness=1.0, hand=False, seed=0):
    """Synthetic camera frame of the board, optionally with a jumper from (row, c) to the rail."""
    w, h = BOARD.size
    flat = np.full((h, w, 3), (215, 220, 222), np.uint8)
    for x, y in BOARD.hole_px.astype(int):
        cv2.rectangle(flat, (x - 3, y - 3), (x + 3, y + 3), (60, 60, 60), -1)
    if wire_row:
        x, y = BOARD.hole_xy(wire_row, "c")
        cv2.line(flat, (x, y), (x, y - 6 * PITCH), colour, 7)          # cable towards the rail above column a
        plug(flat, x, y)
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


def test_wire_lying_on_board_both_ends():
    w, h = BOARD.size
    before = BOARD.warp(camera_image(seed=1))
    flat = BOARD.warp(camera_image(seed=2))
    (x1, y1), (x2, y2) = BOARD.hole_xy(13, "c"), BOARD.hole_xy(20, "c")
    import cv2 as _cv2
    _cv2.line(flat, (int(x1), int(y1)), (int(x2), int(y2)), RED, 7)
    plug(flat, int(x1), int(y1))
    plug(flat, int(x2), int(y2))
    result, overlay = analyse(BOARD, before, flat, [13, 20], "red")
    assert result.status == "pass", (result, overlay["ends"])


class ScriptedCamera:
    """Plays synthetic camera frames at ~30 fps; switch scenes by setting .scene."""

    def __init__(self):
        import threading
        self.scenes = {"empty": camera_image(seed=11), "wire13": camera_image(wire_row=13, seed=12)}
        self.scene, self.frame_id = "empty", 0
        self._rng = np.random.default_rng(0)
        threading.Thread(target=self._tick, daemon=True).start()

    def _tick(self):
        import time
        while True:
            self.frame_id += 1
            time.sleep(1 / 30)

    def latest(self):
        img = self.scenes[self.scene].astype(np.int16) + self._rng.integers(-2, 3, (1, 1, 3))
        return np.clip(img, 0, 255).astype(np.uint8)

    def latest_with_id(self):
        return self.frame_id, self.latest()


def test_watcher_reports_placement_and_removal():
    import time
    from vision import Vision
    cam = ScriptedCamera()
    v = Vision(cam, board=BOARD, rows=ROWS, persist=False)
    deadline = time.time() + 5
    while v.baseline is None and time.time() < deadline:
        time.sleep(0.1)
    assert v.baseline is not None, "no baseline"
    cam.scene = "wire13"
    result = v.wait_for_placement([13], "red", timeout=6)
    assert result is not None and result.status == "pass", result
    assert any(h.endswith("13") for h in v.wires), v.wires
    cam.scene = "empty"
    e = v.wait_for_event(timeout=6)
    assert e is not None and e["kind"] == "removed", e and e["kind"]
    assert not e["placed"], e["placed"]
    assert not v.wires, v.wires


def test_cable_moving_is_not_a_placement():
    before = BOARD.warp(camera_image(wire_row=13, seed=1))
    flat = BOARD.warp(camera_image(seed=2))
    x, y = BOARD.hole_xy(13, "c")
    cv2.line(flat, (x, y), (x + 4 * PITCH, y + 6 * PITCH), RED, 7)    # same plug, cable swung sideways
    plug(flat, x, y)
    result, overlay = analyse(BOARD, before, flat, [13], "red")
    assert result.status != "fail", (result, overlay["ends"])     # never blames a different row


def test_thick_cable_arc_does_not_beat_black_plug():
    before = BOARD.warp(camera_image(seed=1))
    flat = BOARD.warp(camera_image(seed=2))
    w, h = BOARD.size
    x, y = BOARD.hole_xy(12, "i")
    ax, ay = BOARD.hole_xy(9, "j")
    cv2.line(flat, (0, h // 2), (ax, ay), RED, 7)                      # cable from off the board...
    cv2.circle(flat, (ax, ay), int(0.6 * PITCH), RED, -1)              # ...lifted arc: thick, survives opening
    cv2.line(flat, (ax, ay), (x, y), RED, 7)
    plug(flat, x, y)
    result, overlay = analyse(BOARD, before, flat, [12], "red")
    assert result.status == "pass", (result, [(e["col"], e["row"]) for e in overlay["ends"]])


def test_calibration_round_trip():
    pts = BOARD.to_camera([BOARD.hole_xy(1, "a"), BOARD.hole_xy(ROWS, "j")])
    assert np.allclose(pts, [CORNERS[0], CORNERS[2]], atol=0.5)
    assert len(BOARD.holes) == ROWS * len(COLS)


def test_auto_calibration_finds_the_grid():
    board, info = auto_calibrate(camera_image(seed=3), ROWS)
    err = np.linalg.norm(board.hole_cam - BOARD.hole_cam, axis=1).mean()
    camera_pitch = np.linalg.norm(BOARD.hole_cam[1] - BOARD.hole_cam[0]) / (11 / 10)  # a->b is one pitch
    assert info["holes"] > 0.9 * ROWS * 10, info
    assert err < 0.2 * camera_pitch, (err, camera_pitch)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
