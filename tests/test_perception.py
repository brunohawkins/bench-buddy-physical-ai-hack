"""Offline perception contract and failure-path tests; no camera, network or background threads."""
import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import calibrate
import vision
import vlm
from test_vision import BOARD, camera_image


def judgement(**changes):
    return {"changes": [{"part": "wire", "action": "placed", "colour": "yellow", "holes": ["c14"]}],
            "board": [{"id": "io", "part": "wire", "colour": "yellow", "holes": ["c14"]}],
            "problem": "The IO lead is in c14, but this step needs row 13.",
            "fix": "Move the yellow IO lead from c14 to c13.", "severity": "wrong", "grid": "aligned",
            "summary": "Yellow lead inserted into c14.", "narration": "The yellow lead is in c14.", **changes}


@pytest.fixture
def scene(tmp_path, monkeypatch):
    monkeypatch.setattr(vision, "FRAMES_DIR", tmp_path)
    v = vision.Vision(None, board=BOARD, persist=False, start_threads=False)
    v.baseline = BOARD.warp(camera_image(seed=1))
    v._baseline_raw = camera_image(seed=1)
    raw = camera_image(wire_row=14, seed=2)
    v._raw, v._warped = raw, BOARD.warp(raw)
    v._still_since = time.time() - 2
    v._frame_at = time.monotonic()
    v._force_assess = False
    monkeypatch.setattr(vlm, "labelled_crop", lambda board, img, *args, **kwargs: img)
    monkeypatch.setattr(vlm, "camera_view", lambda img, *args: img)
    return v


def observe(v):
    return v._model_step(vision.change_mask(v.baseline, v._warped), v._warped, v._raw, v._still_since)


def test_wrong_hole_has_fix_in_event_and_ui_state(scene, monkeypatch):
    monkeypatch.setattr(vlm, "judge", lambda *a, **kw: judgement())
    assert observe(scene) is True
    event = scene.events[-1]
    assert event["problem"] and event["fix"] == judgement()["fix"] and event["severity"] == "wrong"
    assert scene.state()["parts"][0]["from"] == ["c", 14]
    assert scene.state()["fix"] == event["fix"]


def test_saved_startup_grid_requires_two_fresh_agreeing_fits(scene, monkeypatch):
    scene._calibration_valid, scene.grid = False, "uncertain"
    monkeypatch.setattr(calibrate, "auto_calibrate", lambda *a, **kw: (BOARD, {"holes": BOARD.rows * 10}))
    scene._aligned(scene._raw)
    assert not scene._calibration_valid and scene.grid == "uncertain"
    scene._aligned(scene._raw)
    assert scene._calibration_valid and scene.grid == "aligned"


def test_activity_updates_preserve_fault_and_observation_fields(scene, monkeypatch):
    monkeypatch.setattr(vlm, "judge", lambda *a, **kw: judgement())
    assert observe(scene)
    updates = []
    scene.listeners.append(updates.append)
    scene._set_activity("looking", rows=[14], holes=["c14"])
    scene._set_activity("looking", rows=[14], holes=["c14"])
    assert len(updates) == 1
    assert updates[0]["activity"] == {"phase": "looking", "rows": [14], "holes": ["c14"]}
    assert updates[0]["fix"] == judgement()["fix"] and updates[0]["severity"] == "wrong"
    assert "observation" in updates[0] and "last_model_error" in updates[0]


def test_watcher_recovers_after_frame_error_and_honours_stop(scene, monkeypatch):
    calls = []
    def watch():
        calls.append(True)
        if len(calls) == 1:
            raise ValueError("bad frame")
        scene._stop.set()
    monkeypatch.setattr(scene, "_watch", watch)
    scene._watch_loop()
    assert len(calls) == 2
    assert scene.state()["activity"]["phase"] == "error"


def test_pixel_view_does_not_invent_connection_between_simultaneous_plugs(scene, monkeypatch):
    monkeypatch.setattr(scene, "_use_model", lambda: False)
    scene._pixel_board([{"kind": "placed", "label": "c14", "x": 20},
                        {"kind": "placed", "label": "c16", "x": 40}])
    assert [p["holes"] for p in scene.parts] == [["c14"], ["c16"]]


def test_problem_and_clear_are_emitted_without_placement(scene, monkeypatch):
    monkeypatch.setattr(vlm, "judge", lambda *a, **kw: judgement(changes=[]))
    assert observe(scene) is True
    assert scene.events[-1]["kind"] == "assessment" and scene.events[-1]["problem"]
    scene._force_assess = True
    monkeypatch.setattr(vlm, "judge", lambda *a, **kw: judgement(changes=[], problem=None, fix=None, severity=None))
    assert observe(scene) is True
    assert scene.events[-1]["assessment"] and scene.problem is None


def test_small_local_insertion_is_judged_but_speckles_are_not(scene, monkeypatch):
    calls = []
    monkeypatch.setattr(vlm, "judge", lambda *a, **kw: calls.append(kw) or judgement())
    mask = np.zeros(scene._warped.shape[:2], bool)
    mask[100:115, 100:115] = True
    assert mask.mean() < vision.MODEL_MIN_CHANGE
    assert scene._model_step(mask, scene._warped, scene._raw, scene._still_since)
    assert len(calls) == 1
    mask[:] = False
    mask[::30, ::30] = True
    assert scene._model_step(mask, scene._warped, scene._raw, scene._still_since)
    assert len(calls) == 1


@pytest.mark.parametrize("invalid", [None, [], {"board": [], "changes": None},
    judgement(board=[None]), judgement(changes=[{"part": "wire", "action": "placed", "holes": [None]}]),
    judgement(board=[{"id": "io", "part": "wire", "holes": ["d999"]}]), judgement(problem={})])
def test_malformed_reply_falls_back_without_mutating_state(scene, monkeypatch, invalid):
    monkeypatch.setattr(vlm, "judge", lambda *a, **kw: invalid)
    before = scene.baseline
    assert observe(scene) is False
    assert scene.parts == [] and scene.baseline is before and not scene.events


def test_api_failure_falls_back(scene, monkeypatch):
    def fail(*args, **kwargs):
        raise TimeoutError("offline")
    monkeypatch.setattr(vlm, "judge", fail)
    assert observe(scene) is False
    assert not scene.events


@pytest.mark.parametrize("change", ["board", "step"])
def test_late_model_reply_is_discarded(scene, monkeypatch, change):
    def judge(*args, **kwargs):
        if change == "board":
            scene._still_since = time.time()
        else:
            scene.set_task({"say": "Next step"})
        return judgement()
    monkeypatch.setattr(vlm, "judge", judge)
    before = scene.baseline
    assert observe(scene) is None
    assert not scene.events and scene.baseline is before and not scene.parts


def test_step_and_whole_circuit_are_passed_to_judge(scene, monkeypatch):
    seen = []
    scene.set_task({"say": "Place IO in row 13"}, [{"say": "IO -> resistor -> LED -> ground"}], "V -> +; G -> -")
    monkeypatch.setattr(vlm, "judge", lambda *a, **kw: seen.append(kw) or judgement())
    observe(scene)
    assert seen[0]["task"]["current_step"]["say"] == "Place IO in row 13"
    assert seen[0]["task"]["target_circuit"] == "V -> +; G -> -"


def test_grid_misalignment_recalibrates_then_rejudges(scene, monkeypatch):
    replies = iter([judgement(grid="misaligned"), judgement()])
    fits = []
    monkeypatch.setattr(vlm, "judge", lambda *a, **kw: next(replies))
    monkeypatch.setattr(calibrate, "auto_calibrate", lambda *a, **kw: fits.append(kw) or (BOARD, {"holes": 300}))
    assert observe(scene) is True
    assert len(fits) == 3                         # two agreeing after fits, one independent before fit
    assert scene.grid == "aligned" and scene.events[-1]["severity"] == "wrong"


def test_unreliable_grid_never_accuses_or_replaces_parts(scene, monkeypatch):
    scene.parts = [{"id": "old", "part": "wire", "holes": ["a12"]}]
    monkeypatch.setattr(vlm, "judge", lambda *a, **kw: judgement(grid="misaligned"))
    monkeypatch.setattr(calibrate, "auto_calibrate", lambda *a, **kw: (BOARD, {"holes": 20}))
    assert observe(scene) is True
    assert scene.grid == "misaligned" and scene.severity == "warning"
    assert scene.parts[0]["id"] == "old" and scene.events[-1]["holes"] == []


def test_repeated_grid_error_gets_only_one_retry(scene, monkeypatch):
    calls = []
    monkeypatch.setattr(vlm, "judge", lambda *a, **kw: calls.append(1) or judgement(grid="misaligned"))
    monkeypatch.setattr(calibrate, "auto_calibrate", lambda *a, **kw: (BOARD, {"holes": 300}))
    assert observe(scene) is True
    assert len(calls) == 2 and scene.severity == "warning"


def test_verify_rejects_a_board_that_moves_during_call(scene, monkeypatch):
    monkeypatch.setattr(vlm, "available", lambda: True)
    def verify(*args, **kwargs):
        scene._still_since = time.time()
        return {"status": "pass", "detail": "Looks good"}
    monkeypatch.setattr(vlm, "verify", verify)
    assert scene.verify("IO in row 13").status == "unsure"


def test_settled_lighting_twitch_does_not_discard_identical_board(scene, monkeypatch):
    def judge(*args, **kwargs):
        scene._still_since = time.time() - 1
        return judgement()
    monkeypatch.setattr(vlm, "judge", judge)
    assert observe(scene) is True
    assert scene.events[-1]["observed_period"] == scene._still_since


def test_settled_but_different_board_still_discards_model_reply(scene, monkeypatch):
    other = camera_image(wire_row=20, seed=2)
    def judge(*args, **kwargs):
        scene._raw = other
        scene._still_since = time.time() - 1
        return judgement()
    monkeypatch.setattr(vlm, "judge", judge)
    assert observe(scene) is None
    assert scene.discarded_observations == 1 and not scene.events


def test_verification_refreshes_tutor_evidence_without_old_empty_board_narration(scene, monkeypatch):
    scene.narration = "The board is empty."
    monkeypatch.setattr(vlm, "available", lambda: True)
    monkeypatch.setattr(vlm, "verify", lambda *a, **kw: {"status": "pass", "detail": "Black V and grey G are in the rails."})
    assert scene.verify("Check power").status == "pass"
    assert scene.observation()["current"] and "Black V" in scene.observation()["detail"]
    assert "empty" not in scene.describe()
    scene._still_since = time.time()
    assert not scene.observation()["current"] and scene.observation()["detail"] == ""


def test_camera_evidence_expires_instead_of_becoming_a_permanent_claim(scene):
    scene._record_observation("Nothing plugged in", scene._still_since, "judge")
    assert scene.observation()["current"]
    scene._observation["at"] -= vision.OBSERVATION_TTL + 1
    assert not scene.observation()["current"] and scene.observation()["detail"] == ""


def test_led_step_gets_an_additional_native_camera_crop(scene, monkeypatch):
    calls = []
    monkeypatch.setattr(vlm, "available", lambda: True)
    monkeypatch.setattr(vlm, "verify", lambda *a, **kw: calls.append(kw) or {"status": "unsure", "detail": "LED legs unclear"})
    scene.verify("An LED in rows 13 and 14")
    assert calls[0]["focus"] is not None
    assert calls[0]["focus"].size < scene._raw.size
    assert vlm.step_rows("Put one leg in row 13 and the other in row 14.") == [13, 14]
    assert vlm.camera_focus(scene._raw, BOARD, []) is None


def test_warning_or_missing_fix_cannot_become_spoken_accusation():
    assert vlm.validate_judgement(judgement(fix=None), 63)["severity"] == "warning"
    assert vlm.validate_judgement(judgement(severity="warning"), 63)["severity"] == "warning"
    assert vlm.validate_judgement(judgement(grid="uncertain"), 63)["severity"] == "warning"


def test_missing_assessment_cannot_silently_clear_a_fault():
    with pytest.raises(ValueError):
        vlm.validate_judgement({"board": [], "changes": []}, 63)


def test_frozen_camera_is_not_accepted_as_a_current_observation(scene, monkeypatch):
    scene._frame_at = time.monotonic() - vision.FRAME_TIMEOUT - 1
    monkeypatch.setattr(vlm, "available", lambda: True)
    assert scene._stable_board() == (None, None)
    assert not scene.is_still()
    assert scene.verify("IO in c13").status == "unsure"


def test_small_local_motion_starts_a_new_settling_period(scene):
    import cv2
    first = scene._raw.copy()
    x, y = BOARD.hole_xy(18, "d")
    second = first.copy()
    corners = BOARD.to_camera([(x - 9, y - 9), (x + 9, y - 9), (x + 9, y + 9), (x - 9, y + 9)])
    cv2.fillConvexPoly(second, corners.astype(np.int32), (20, 20, 20))
    periods = []
    class Camera:
        count = 0
        def latest_with_id(self):
            self.count += 1
            if self.count == 1:
                return 1, first
            if self.count == 2:
                scene._still_since = time.time() - 2
                periods.append(scene._still_since)
                return 2, second
            scene.close()
            return 2, second
    scene.camera = Camera()
    scene._loop()
    assert scene._motion < vision.MOTION_STILL   # the old whole-board threshold missed this
    assert scene._still_since > periods[0]      # local motion still makes us wait for a clear, settled view


def test_user_lead_colours_survive_a_long_tutor_dialogue(scene):
    scene.note("User", "The V lead is black, G grey, IO yellow, TX green, RX blue.")
    for i in range(25):
        scene.note("Bench Buddy", f"Instruction {i}")
    assert "V lead is black" in scene._vision_context()


def test_rail_near_expected_row_is_not_a_terminal_placement():
    event = {"placed": ["+top13"]}
    assert vision.judge_placed(event, [13], None).status == "fail"
    assert vision.judge_placed(event, ["top +"], None).status == "pass"


def test_correct_row_does_not_override_an_observed_fault():
    event = {"placed": ["d13"], "problem": "The lead is on the wrong half.",
             "fix": "Move it from d13 to i13.", "severity": "wrong"}
    result = vision.judge_placed(event, [13], None)
    assert result.status == "fail" and "i13" in result.detail


def test_vision_to_tutor_speaks_the_actual_model_correction(scene, monkeypatch, tmp_path):
    import tutor
    from test_tutor import StubBrain, StubVoice
    monkeypatch.setattr(tutor, "LOG_PATH", tmp_path / "log.jsonl")
    monkeypatch.setattr(vlm, "judge", lambda *a, **kw: judgement())
    t = tutor.Tutor(scene, StubVoice(), StubBrain({"say": "Looks good", "action": "advance"}))
    t.state = "STEP"
    t.steps = [{"id": "io", "say": "IO to row 13", "check": {"kind": "look"}}]
    observe(scene)
    t._queue_vision(scene.events[-1])
    t.handle(t.events.get_nowait())
    assert t.voice.said == [judgement()["problem"] + " " + judgement()["fix"]]
    assert t.step_i == 0 and t.brain.tutor_calls == 0


def test_consumer_does_not_lose_events_while_speaking(scene):
    assert scene.wait_for_event(timeout=0) is None
    for hole in ("c13", "c14", "c15"):
        scene._emit({"source": "model", "kind": "placed", "holes": [hole]})
    assert [scene.wait_for_event(timeout=0)["holes"] for _ in range(3)] == [["c13"], ["c14"], ["c15"]]


def test_prompt_contains_connectivity_and_actionable_fault_contract(monkeypatch):
    prompts = []
    monkeypatch.setattr(vlm, "_ask", lambda text, images, timeout: prompts.append(text) or judgement())
    vlm.judge(None, None, task={"current_step": {"say": "Put IO in c13"}})
    assert "Put IO in c13" in prompts[0] and "DIFFERENT node" in prompts[0]
    assert '"fix"' in prompts[0] and '"severity"' in prompts[0]
