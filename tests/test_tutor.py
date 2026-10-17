"""Tutor controller rules, driven with fake vision/bench and stub voice/brain: no hardware, keys or threads.

    .venv/bin/python -m pytest tests/
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import curated  # noqa: E402
import tutor  # noqa: E402
from bench_serial import FakeBench  # noqa: E402
from brain import FakeBrain  # noqa: E402
from vision import FakeVision  # noqa: E402


class StubVoice:
    def __init__(self):
        self.said = []

    def say(self, text):
        self.said.append(text)

    def warm_cache(self, phrases):
        pass


class StubBrain(FakeBrain):
    """FakeBrain, but tutor() returns a scripted reply and counts calls."""

    def __init__(self, reply=None, curated_id="radar_led"):
        self.reply = reply or {"say": "", "action": "none"}
        self.tutor_calls = 0
        self.curated_id = curated_id

    def start(self, utterance):
        return {"goal": "x", "curated": self.curated_id, "follow_up": None, "parts": None, "unclear": []}

    def tutor(self, context, event):
        self.tutor_calls += 1
        return dict(self.reply)


@pytest.fixture(autouse=True)
def tmp_log(tmp_path, monkeypatch):
    monkeypatch.setattr(tutor, "LOG_PATH", tmp_path / "log.jsonl")


def speech(t, text):
    t.handle({"type": "speech", "text": text})


def make(brain, bench=None):
    return tutor.Tutor(FakeVision(), StubVoice(), brain, bench)


def test_radar_flow_done_through_every_step():
    t = make(FakeBrain())
    speech(t, "I want a radar light, I have a radar module, an LED, a 1k resistor and a breadboard")
    assert t.project is curated.RADAR_LED and t.state == "STEP"
    for _ in curated.RADAR_LED["steps"]:
        speech(t, "done")
    assert t.state == "DONE"
    assert t.voice.said[-1] == curated.RADAR_LED["done"]


def test_done_on_confirm_step_skips_the_llm():
    b = StubBrain()
    t = make(b)
    speech(t, "radar light please")
    speech(t, "done")
    assert t.step_i == 1 and b.tutor_calls == 0


def test_llm_advance_on_confirm_step_advances_with_short_ack():
    b = StubBrain({"say": "Great, now connect IO to the resistor.", "action": "advance"})
    t = make(b)
    speech(t, "radar light please")
    speech(t, "alright the radar is plugged in")
    assert t.step_i == 1
    assert "connect IO" not in " ".join(t.voice.said)          # the LLM's recited instruction is dropped
    assert t.voice.said[-1] == curated.RADAR_LED["steps"][1]["say"]


def test_llm_advance_on_vision_step_is_ignored():
    b = StubBrain({"say": "Looks good!", "action": "advance"}, curated_id="555")
    t = make(b, FakeBench(fault=None))
    speech(t, "555 blinker")
    assert t.current()["check"]["kind"] == "vision"
    speech(t, "I think I put the wire in")
    assert t.step_i == 0                                       # only the camera check can pass it
    speech(t, "done")                                          # FakeVision fails the first check...
    assert t.step_i == 0
    speech(t, "done")                                          # ...and passes the second
    assert t.step_i == 1


def test_vision_event_runs_the_check_on_vision_steps():
    t = make(StubBrain(curated_id="555"), FakeBench(fault=None))
    speech(t, "555 blinker")
    for _ in range(2):
        t.handle({"type": "vision", "kind": "placed", "holes": ["i13"], "rows": [13], "text": "wire placed at i13"})
    assert t.step_i == 1


def test_troubleshooting_without_arduino_then_fixed_on_last_step():
    b = StubBrain({"say": "Is the LED's long leg on the resistor side?", "action": "none"})
    t = make(b)
    speech(t, "radar light please")
    for _ in curated.RADAR_LED["steps"][:-1]:
        speech(t, "done")
    speech(t, "it didn't light")
    assert t.troubleshooting and t.state == "STEP"
    b.reply = {"say": "", "action": "advance"}
    speech(t, "I flipped the LED and now it lights")
    assert not t.troubleshooting and t.state == "DONE"


def test_missing_parts_then_supplied():
    class Parts(StubBrain):
        def start(self, utterance):
            have = [{"type": "other", "part": "ld2402", "qty": 1}, {"type": "led", "qty": 1},
                    {"type": "other", "part": "breadboard", "qty": 1}]
            if "resistor" in utterance:
                have = [{"type": "resistor", "value": 1000.0, "qty": 1}]
            return {"goal": "radar light", "curated": "radar_led", "follow_up": None, "parts": have, "unclear": []}

    t = make(Parts())
    speech(t, "radar light, I have an LD2402, an LED and a breadboard")
    assert t.state == "INVENTORY" and "1 kilohm resistor" in t.voice.said[-1]
    speech(t, "found a 1k resistor")
    assert t.state == "STEP"


def test_project_named_without_parts_asks_once_then_goes():
    class NoParts(StubBrain):
        def start(self, utterance):
            return {"goal": "radar presence LED", "curated": "radar_led", "follow_up": None, "parts": [],
                    "unclear": []}

    t = make(NoParts())
    speech(t, "Hello, I wanna build a radar presence LED today.")
    assert t.state == "INVENTORY" and t.voice.said[-1].endswith("Have you got those?")
    speech(t, "so here's the materials that I have, and what's the next step that I should do?")
    assert t.state == "STEP" and t.voice.said[-1] == curated.RADAR_LED["steps"][0]["say"]


def test_parts_question_is_not_repeated():
    class NoParts(StubBrain):
        def start(self, utterance):
            return {"goal": "radar presence LED", "curated": "radar_led", "follow_up": None, "parts": [],
                    "unclear": []}

    t = make(NoParts())
    speech(t, "radar presence LED")
    speech(t, "I don't have a resistor")
    assert t.state == "STEP"                                   # asked once; now it gets going
    assert sum("Have you got" in s for s in t.voice.said) == 1


class Intake(StubBrain):
    """start(): vague first request, parts only when the text names them; plan(): a custom build."""

    def __init__(self, curated_id="radar_led"):
        super().__init__(curated_id=curated_id)
        self.plans = []

    def start(self, utterance):
        parts = [{"type": "other", "part": "bc547", "qty": 1}] if "bc547" in utterance.lower() else []
        follow_up = None if "hallway" in utterance else "Where will it go?"
        return {"goal": "night light", "curated": self.curated_id, "follow_up": follow_up,
                "parts": parts, "unclear": []}

    def plan(self, goal, parts, use_case=None):
        self.plans.append((parts, use_case))
        missing = ["a photoresistor", "a 2N2222 transistor"] if not parts else ["a photoresistor"]
        return {"summary": "It's 2 steps.", "needed": ["a photoresistor", "a 2N2222 transistor"], "missing": missing,
                "steps": [{"id": "s1", "say": "Place the photoresistor.", "why": "", "check": {"kind": "confirm"}},
                          {"id": "s2", "say": "Power it on.", "why": "", "check": {"kind": "confirm"}}]}


def test_vague_radar_request_asks_use_case_then_parts():
    t = make(Intake())
    speech(t, "I wanna build a radar presence LED")
    assert t.voice.said[-1] == "Where will it go?"
    speech(t, "by my front door so it lights up when someone comes in")
    assert t.use_case.startswith("by my front door")
    assert "Have you got those?" in t.voice.said[-1]
    speech(t, "yes")
    assert t.state == "STEP"


def test_clear_request_skips_use_case_question():
    t = make(Intake(curated_id=None))
    speech(t, "a night light for my hallway that turns on when it gets dark")
    assert "Where will it go?" not in t.voice.said
    assert "a photoresistor and a 2N2222 transistor" in t.voice.said[-1]


def test_skip_use_case():
    t = make(Intake())
    speech(t, "radar LED")
    speech(t, "not sure, just start")
    assert t.use_case is None and t.intake == "parts"


def test_custom_build_ready_starts_without_replanning():
    b = Intake(curated_id=None)
    t = make(b)
    speech(t, "a night light")
    speech(t, "in my hallway, on when it's dark")
    assert b.plans[-1][1] == "in my hallway, on when it's dark"   # the use case goes into the plan
    speech(t, "yep I've got those")
    assert t.state == "STEP" and len(b.plans) == 1 and t.voice.said[-1] == "Place the photoresistor."


def test_substitute_parts_replan_once():
    b = Intake(curated_id=None)
    t = make(b)
    speech(t, "a night light for my hallway")
    speech(t, "I don't have a 2N2222 but I have a BC547")
    assert len(b.plans) == 2 and t.state == "STEP"
    assert any("still need a photoresistor" in x for x in t.voice.said)


def fault(**changes):
    return {"type": "vision", "kind": "placed", "holes": ["d34"], "rows": [34], "text": "LED in d34.",
            "problem": "The LED leg is in d34; it needs row 35.", "fix": "Move that LED leg from d34 to d35.",
            "severity": "wrong", "assessment": True, "grid": "aligned", **changes}


def test_wrong_hole_is_spoken_without_brain_or_done_and_blocks_advancement():
    b = StubBrain({"say": "Looks good", "action": "advance"})
    t = make(b)
    speech(t, "radar light please")
    t.voice.said.clear()
    t.handle(fault())
    assert t.voice.said == [fault()["problem"] + " " + fault()["fix"]]
    assert b.tutor_calls == 0 and t.step_i == 0
    speech(t, "done")
    assert t.step_i == 0 and b.tutor_calls == 0
    assert '"check": "vision_problem"' in tutor.LOG_PATH.read_text()


def test_duplicate_problem_suppressed_for_twenty_seconds_and_reset_after_fix(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(tutor.time, "monotonic", lambda: now[0])
    t = make(StubBrain())
    t.handle(fault())
    now[0] += 19
    t.handle(fault())
    assert len(t.voice.said) == 1
    now[0] += 2
    t.handle(fault())
    assert len(t.voice.said) == 2
    t.handle(fault(kind="assessment", problem=None, fix=None, severity=None))
    assert t._problem is None
    t.handle(fault())
    assert len(t.voice.said) == 3


def test_uncertain_camera_warning_does_not_accuse_or_advance():
    b = StubBrain({"say": "Wrong hole!", "action": "advance"})
    t = make(b)
    speech(t, "radar light please")
    t.voice.said.clear()
    t.handle(fault(severity="warning", problem="Possibly the wrong row; the hand hides it."))
    assert t.voice.said == [] and t.step_i == 0 and b.tutor_calls == 0


def test_warning_does_not_clear_an_existing_fault():
    t = make(StubBrain())
    t.handle(fault())
    t.handle(fault(severity="warning", problem="Grid misaligned", grid="misaligned"))
    assert t._problem is not None


def test_fault_is_spoken_even_without_placement_event():
    t = make(StubBrain())
    t.handle(fault(kind="assessment", holes=[], rows=[]))
    assert fault()["fix"] in t.voice.said[0]


def test_queue_preserves_fault_and_speaks_before_the_controller_receives_it():
    t = make(StubBrain())
    t._queue_vision(fault(summary="LED in d34"))
    assert len(t.voice.said) == 1
    e = t.events.get_nowait()
    assert e["fix"] == fault()["fix"] and e["severity"] == "wrong"
    t.handle(e)
    assert len(t.voice.said) == 1 and t.brain.tutor_calls == 0


def test_camera_corrects_while_tutor_model_is_busy_and_discards_its_reply():
    import threading
    entered, release = threading.Event(), threading.Event()
    class SlowBrain(StubBrain):
        def tutor(self, context, event):
            entered.set()
            assert release.wait(2)
            return {"say": "Looks perfect!", "action": "advance"}
    t = make(SlowBrain())
    speech(t, "radar light please")
    t.voice.said.clear()
    thread = threading.Thread(target=t.respond, args=({"type": "speech", "text": "Is this right?"},))
    thread.start()
    try:
        assert entered.wait(2)
        t._queue_vision(fault())
        assert t.voice.said == [fault()["problem"] + " " + fault()["fix"]]
    finally:
        release.set()
        thread.join(2)
    assert t.step_i == 0 and "Looks perfect!" not in t.voice.said


def test_correction_waits_for_existing_speech_without_overlapping():
    import threading
    entered, release = threading.Event(), threading.Event()
    t = make(StubBrain())
    class BlockingVoice(StubVoice):
        def say(self, text):
            self.said.append(text)
            if text == "Current instruction":
                entered.set()
                assert release.wait(2)
    t.voice = BlockingVoice()
    normal = threading.Thread(target=t.say, args=("Current instruction",))
    normal.start()
    assert entered.wait(2)
    alert = threading.Thread(target=t._queue_vision, args=(fault(),))
    alert.start()
    try:
        assert t.voice.said == ["Current instruction"]
    finally:
        release.set()
        normal.join(2)
        alert.join(2)
    assert len(t.voice.said) == 2 and fault()["fix"] in t.voice.said[1]


def test_verified_correction_releases_step_and_does_not_repeat_fault():
    t = make(StubBrain())
    speech(t, "radar light please")
    t.handle(fault())
    t.handle(fault(kind="assessment", problem=None, fix=None, severity=None))
    speech(t, "done")
    assert t.step_i == 1 and t._problem is None


def test_open_step_sends_explicit_task_and_circuit_to_vision():
    t = make(StubBrain())
    tasks = []
    t.vision.set_task = lambda **kw: tasks.append(kw)
    speech(t, "radar light please")
    speech(t, "done")
    assert tasks[-1]["step"]["id"] == "power"
    assert tasks[-1]["plan"][0]["completed"] is True
    assert "IO -> row 30" in tasks[-1]["circuit"]
