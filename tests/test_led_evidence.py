"""Exact LED placement still rejects wrong holes; ambiguous or contradictory photos never order a move."""
import numpy as np
import pytest

import vlm
from test_perception import scene, judgement, observe
from test_vision import BOARD


def evidence(holes, certain=True):
    return {"holes": holes, "certain": certain}


@pytest.mark.parametrize("holes,status", [(["b35", "c36"], "pass"), (["b36", "c37"], "fail"),
                                         (["b35", "c35"], "fail"), (["b35", "g36"], "fail")])
def test_clear_led_correct_wrong_short_and_wrong_half_are_not_tolerated(scene, monkeypatch, holes, status):
    monkeypatch.setattr(vlm, "available", lambda: True)
    monkeypatch.setattr(vlm, "verify", lambda *a, **kw: {"status": status, "detail": "LED checked", "led_holes": holes})
    monkeypatch.setattr(vlm, "read_led", lambda *a, **kw: evidence(holes))
    assert scene.verify("LED legs in rows 35 and 36 on the same half").status == status


@pytest.mark.parametrize("status", ["pass", "fail"])
@pytest.mark.parametrize("blind", [evidence(["b35", "c36"]), evidence([], False)])
def test_disagreement_or_hidden_entries_cannot_pass_or_order_a_move(scene, monkeypatch, status, blind):
    monkeypatch.setattr(vlm, "available", lambda: True)
    monkeypatch.setattr(vlm, "verify", lambda *a, **kw: {"status": status, "detail": "LED in b36 and c37", "led_holes": ["b36", "c37"]})
    monkeypatch.setattr(vlm, "read_led", lambda *a, **kw: blind)
    result = scene.verify("LED in rows 35 and 36")
    assert result.status == "unsure" and "Leave it in place" in result.detail


@pytest.mark.parametrize("certain", [False, True])
def test_watcher_only_speaks_supported_led_faults(scene, monkeypatch, certain):
    holes = ["b16", "c17"]
    monkeypatch.setattr(vlm, "judge", lambda *a, **kw: judgement(
        board=[{"id": "led", "part": "led", "holes": holes}],
        changes=[{"part": "led", "action": "placed", "holes": holes}], led_holes=holes,
        problem="LED in b16/c17", fix="Move the long leg to row 15", severity="wrong"))
    monkeypatch.setattr(vlm, "read_led", lambda *a, **kw: evidence(holes, certain))
    assert observe(scene)
    assert scene.severity == ("wrong" if certain else "warning")
    assert scene.parts[0]["holes"] == (holes if certain else [])


def test_blind_reading_does_not_receive_target_or_previous_guesses(monkeypatch):
    calls = []
    monkeypatch.setattr(vlm, "_ask", lambda prompt, images, timeout: calls.append(prompt) or {
        "holes": ["b15", "c16"], "present": True, "entries_visible": True, "grid": "aligned"})
    image = np.zeros((BOARD.size[1], BOARD.size[0], 3), np.uint8)
    assert vlm.read_led(BOARD, image, [15, 16])["certain"]
    assert "15" not in calls[0] and "16" not in calls[0]


def test_missing_or_bad_evidence_never_confirms():
    assert not vlm.led_agrees({}, evidence(["b35", "c36"]))
    assert not vlm.led_agrees({"led_holes": ["b35", "c36"]}, None)


def test_detail_rulers_preserve_every_entry_pixel():
    import cv2
    image = np.random.default_rng(4).integers(0, 255, (BOARD.size[1], BOARD.size[0], 3), dtype=np.uint8)
    detail = vlm.hole_detail(BOARD, image, [15, 16])
    # Rows 10-21, columns a-e; rulers occupy only the added 50px margins.
    expected = cv2.resize(image[130:230, 210:450], None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    assert np.array_equal(detail[50:450, 50:-50], expected)


def test_model_pass_cannot_override_clear_wrong_rows(scene, monkeypatch):
    holes = ["b16", "c17"]
    monkeypatch.setattr(vlm, "available", lambda: True)
    monkeypatch.setattr(vlm, "verify", lambda *a, **kw: {"status": "pass", "detail": "Looks fine", "led_holes": holes})
    monkeypatch.setattr(vlm, "read_led", lambda *a, **kw: evidence(holes))
    result = scene.verify("LED legs in rows 15 and 16 on the same half")
    assert result.status == "fail" and "b16 and c17" in result.detail


def test_led_evidence_failure_does_not_hide_an_independent_wrong_wire(scene, monkeypatch):
    monkeypatch.setattr(vlm, "judge", lambda *a, **kw: judgement(
        board=[{"id": "led", "part": "led", "holes": ["b15", "c16"]}]))
    monkeypatch.setattr(vlm, "read_led", lambda *a, **kw: evidence([], False))
    assert observe(scene)
    assert scene.severity == "wrong" and "IO lead" in scene.problem


def test_uncertain_new_led_assessment_allows_a_fresh_check():
    from test_tutor import make, StubBrain, fault
    buddy = make(StubBrain())
    buddy.handle(fault(problem="LED in row 17", fix="Move LED to row 16"))
    buddy.handle(fault(problem=vlm.LED_UNCLEAR, fix=None, severity="warning", grid="aligned"))
    assert buddy._problem is None and buddy.step_i == 0
