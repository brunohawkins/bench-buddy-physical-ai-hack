"""LLM layer: parse parts, classify intent, phrase replies. Owner: L.

The LLM never decides a transition or whether a step passed; fsm.py does.
"""
import project
from contracts import Intent


def template(result: dict) -> str:
    """Plain-text reply for each result kind. Used by FakeBrain, and as the fallback if the LLM call fails."""
    kind = result["kind"]
    if kind == "missing":
        return "You're missing " + ", ".join(result["missing"]) + ". Tell me your parts again when you have them."
    if kind == "propose":
        return (f"You have everything for a 555 blinker. With your parts it should blink at "
                f"{result['f']:.2f} hertz. Say done when you're ready to start.")
    if kind == "measure":
        verdict = "within tolerance" if result["ok"] else "outside tolerance"
        return f"Predicted {result['predicted']:.2f} hertz, measured {result['measured']:.2f}, {verdict}."
    if kind == "probe":
        return result["hint"] if result["ok"] else f"I measured that {result['reading']}. {result['hint']}"
    raise ValueError(f"unknown result kind {kind!r}")


class Brain:
    def __init__(self):
        from openai import OpenAI
        self.client = OpenAI()

    def parse_parts(self, transcript: str) -> dict:
        """-> {"parts": [{"type", "value" | "part", "qty"}], "unclear": [...]} (see PLAN.md)."""
        raise NotImplementedError("TODO(L): structured output with a small fast model")

    def classify(self, transcript: str, state: str) -> Intent:
        raise NotImplementedError("TODO(L): structured output; enum of IntentKind; pass the current state")

    def explain(self, result: dict) -> str:
        # TODO(L): LLM writes one short spoken sentence from `result`; fall back to template() on error
        return template(result)


class FakeBrain:
    """Keyword intents and a hard-coded parts list (also the CP2 fallback if the parser gets cut)."""

    def parse_parts(self, transcript: str) -> dict:
        return {"parts": [dict(p) for p in project.REQUIRED], "unclear": []}

    def classify(self, transcript: str, state: str) -> Intent:
        t = transcript.lower().strip()
        if any(w in t for w in ("not working", "doesn't work", "isn't working", "broken")):
            return Intent("NOT_WORKING")
        if any(w in t for w in ("again", "repeat")):
            return Intent("REPEAT")
        if t.endswith("?"):
            return Intent("QUESTION", question=transcript)
        if any(w in t for w in ("resistor", "capacitor", "555", "led", "ohm", "farad")):
            return Intent("PARTS")
        if any(w in t for w in ("done", "ok", "okay", "next", "yes", "ready")):
            return Intent("DONE")
        return Intent("OTHER")

    def explain(self, result: dict) -> str:
        return template(result)
