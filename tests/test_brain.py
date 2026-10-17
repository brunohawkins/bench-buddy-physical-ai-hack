"""Brain parsing and fallbacks with no API calls.

    .venv/bin/python -m pytest tests/
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import brain  # noqa: E402
import curated  # noqa: E402


def test_parse_part():
    assert brain._parse_part("resistor 68000 2") == {"type": "resistor", "value": 68000.0, "qty": 2}
    assert brain._parse_part("ic ne555p 1") == {"type": "ic", "part": "NE555P", "qty": 1}
    assert brain._parse_part("other LD2402 1") == {"type": "other", "part": "ld2402", "qty": 1}
    assert brain._parse_part("led - 1") == {"type": "led", "qty": 1}
    assert brain._parse_part("resistor big 1") is None
    assert brain._parse_part("a radar") is None


def test_radar_parts_matching():
    have = [{"type": "other", "part": "radar", "qty": 1}, {"type": "led", "qty": 1},
            {"type": "resistor", "value": 220.0, "qty": 1}, {"type": "other", "part": "breadboard", "qty": 1}]
    assert curated.missing(curated.RADAR_LED, have) == []
    assert curated.missing(curated.RADAR_LED, have[:1]) == ["an LED", "a 1 kilohm resistor", "a breadboard"]


class Broken:
    """Stands in for the OpenAI client when the network is down."""

    class chat:
        class completions:
            @staticmethod
            def create(**kwargs):
                raise ConnectionError("offline")


def offline_brain() -> brain.Brain:
    b = brain.Brain.__new__(brain.Brain)          # skip __init__: no OpenAI client, no warm-up thread
    b.client, b.model, b.plan_model, b.last_ms, b._parsed = Broken, "m", "m", None, {}
    b.fallback = brain.FakeBrain()
    return b


def test_offline_fallbacks():
    b = offline_brain()
    assert b.start("I want a light that turns on when someone walks by")["curated"] == "radar_led"
    assert b.start("a 555 blinker")["curated"] == "555"
    assert b.plan("night light", []) is None
    assert b.tutor({}, {"type": "speech", "text": "done"})["action"] == "advance"
    assert b.tutor({}, {"type": "speech", "text": "it's not working"})["action"] == "debug"
    assert b.tutor({}, {"type": "vision", "text": "wire placed at i3"}) == {"say": "", "action": "none"}


def test_quick_intent():
    q = brain._quick_intent
    assert q("done").kind == "DONE" and q("ok it's in").kind == "DONE"
    assert q("I'm not done yet") is None
    assert q("it didn't light").kind == "NOT_WORKING"
    assert q("can you say that again").kind == "REPEAT"
    assert q("why do we need a resistor") is None


def test_custom_plan_preserves_circuit_for_perception():
    b = offline_brain()
    b._json = lambda *a, **kw: {"summary": "Two steps", "needed": [], "missing": [],
                                "circuit": "IO -> resistor -> LED -> ground",
                                "steps": [{"say": "Connect the LED", "why": "Show presence"}]}
    assert b.plan("presence light", [])["circuit"] == "IO -> resistor -> LED -> ground"
