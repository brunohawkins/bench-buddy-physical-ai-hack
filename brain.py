"""LLM layer: parse parts, classify intent, phrase replies. Owner: L.

The LLM never decides a transition or whether a step passed; fsm.py does.

Latency: short replies ("done", "it's not working") are classified by keyword with no LLM call. Anything else is
one structured-output call that returns the intent and, if the user listed parts, the parts too, so the parts
utterance costs one call rather than classify + parse. Every LLM path falls back to FakeBrain/template() on error.
"""
import json
import os
import re
import threading
import time

import project
from contracts import Intent

DEFAULT_MODEL = "gpt-4.1-mini"           # fast, non-reasoning; override with OPENAI_MODEL
INTENTS = ["PARTS", "DONE", "NOT_WORKING", "QUESTION", "REPEAT", "OTHER"]


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


# Parts come back as compact "<type> <value> <qty>" strings, not objects: about 80 output tokens instead of 200
# for a full parts list, which roughly halves the call (~1.2 s vs ~2 s with gpt-4.1-mini).
UNDERSTAND_SCHEMA = {
    "name": "understand", "strict": True,
    "schema": {
        "type": "object", "additionalProperties": False, "required": ["intent", "parts", "unclear", "question"],
        "properties": {
            "intent": {"type": "string", "enum": INTENTS},
            "parts": {"type": "array", "items": {"type": "string"}},
            "unclear": {"type": "array", "items": {"type": "string"}},
            "question": {"type": ["string", "null"]},
        },
    },
}

UNDERSTAND_PROMPT = """You are the language-understanding step of Bench Buddy, a voice assistant that guides someone
building a 555 timer blinker on a breadboard. The user's words come from speech-to-text and may be messy.

Return the user's intent, given the current state:
- PARTS: they are listing electronic parts they have.
- DONE: they finished the current instruction, or agree/are ready ("done", "it's in", "yep", "let's go").
- NOT_WORKING: something is broken, not blinking, or not working.
- QUESTION: they ask a question. Put it in `question`.
- REPEAT: they want the last instruction again.
- OTHER: anything else.

If intent is PARTS, fill `parts` with one string per distinct part: "<type> <value> <qty>".
type is resistor, capacitor, ic, led or other. value is in base SI units (ohms, farads), the part number for an
ic (a plain "555 timer" is 555; keep a stated one such as NE555P), or - for an led or other.
"68k" / "sixty-eight k" -> 68000; "three-thirty ohms" -> 330 (qty 1); "1 meg" -> 1000000;
"10 micro" / "10uF" -> 1e-5; "100 nano" / "point one micro" -> 1e-7; "10 nanofarad" -> 1e-8. "two of" -> qty 2.
Examples: "resistor 68000 2", "capacitor 1e-5 1", "ic NE555 1", "led - 1".
Put anything you cannot pin down in `unclear` as the user's words. Otherwise `parts` and `unclear` are empty."""

EXPLAIN_PROMPT = """You are Bench Buddy, speaking out loud to someone at an electronics bench.
Write ONE short spoken sentence (at most 25 words) that tells them the result in the JSON.
Keep every number exactly as given, with its unit. Never change the verdict or the advice. No markdown, no lists."""

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


class Brain:
    def __init__(self):
        from openai import OpenAI
        self.client = OpenAI()
        self.model = os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL
        self.fallback = FakeBrain()
        self.last_ms = None              # duration of the last LLM call (None if no call); fsm logs it
        self._parsed: dict[str, dict] = {}   # transcript -> parts, filled by classify()
        # Open the HTTPS connection now so the first real call doesn't pay for the handshake.
        threading.Thread(target=self._warm, daemon=True).start()

    def _warm(self) -> None:
        try:
            self.client.chat.completions.create(model=self.model, max_tokens=1, timeout=5,
                                                messages=[{"role": "user", "content": "hi"}])
        except Exception:
            pass

    def parse_parts(self, transcript: str) -> dict:
        """-> {"parts": [{"type", "value" | "part", "qty"}], "unclear": [...]} (see PLAN.md)."""
        if transcript not in self._parsed:
            self._understand(transcript, "INVENTORY")
        return self._parsed.pop(transcript, None) or self.fallback.parse_parts(transcript)

    def classify(self, transcript: str, state: str) -> Intent:
        self.last_ms = None
        quick = _quick_intent(transcript)
        if quick:
            return quick
        out = self._understand(transcript, state)
        if out is None:
            return self.fallback.classify(transcript, state)
        return Intent(out["intent"], question=out["question"] if out["intent"] == "QUESTION" else None)

    def explain(self, result: dict) -> str:
        """template() by default: in testing the LLM's sentence matched it almost word for word and cost ~0.6 s.
        BRAIN_LLM_EXPLAIN=1 lets the LLM phrase measure/probe results (missing/propose stay fixed so TTS caches them)."""
        if result["kind"] in ("missing", "propose") or os.environ.get("BRAIN_LLM_EXPLAIN") != "1":
            return template(result)
        try:
            text = self._chat(EXPLAIN_PROMPT, json.dumps(result), max_tokens=80, timeout=2.5).strip()
        except Exception as e:
            print(f"[brain] explain failed ({e!r}), using template")
            return template(result)
        return text if _keeps_numbers(text, result) else template(result)

    # --- internals ---------------------------------------------------------

    def _understand(self, transcript: str, state: str) -> dict | None:
        """One LLM call -> {intent, parts, unclear, question}; caches parts for parse_parts(). None on error."""
        try:
            raw = self._chat(UNDERSTAND_PROMPT, f"State: {state}\nUser said: {transcript}",
                             max_tokens=300, timeout=4, schema=UNDERSTAND_SCHEMA)
            out = json.loads(raw)
        except Exception as e:
            print(f"[brain] understand failed ({e!r}), using keywords")
            self._parsed[transcript] = None      # so parse_parts() doesn't wait on a second failing call
            return None
        if out["intent"] == "PARTS":
            parts, unclear = [], list(out["unclear"])
            for s in out["parts"]:
                p = _parse_part(s)
                parts.append(p) if p else unclear.append(s)
            self._parsed[transcript] = {"parts": parts, "unclear": unclear}
        return out

    def _chat(self, system: str, user: str, max_tokens: int, timeout: float, schema: dict | None = None) -> str:
        t0 = time.perf_counter()
        kwargs = {"response_format": {"type": "json_schema", "json_schema": schema}} if schema else {}
        try:
            r = self.client.chat.completions.create(
                model=self.model, temperature=0, max_tokens=max_tokens, timeout=timeout,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}], **kwargs)
        finally:
            self.last_ms = round((time.perf_counter() - t0) * 1000)
        return r.choices[0].message.content


def _quick_intent(transcript: str) -> Intent | None:
    """Keyword shortcut for the common short replies, so they skip the LLM. None means ask the LLM."""
    t = re.sub(r"[^a-z' ]", " ", transcript.lower()).split()
    s = " ".join(t)
    if not t:
        return Intent("OTHER")
    if any(p in s for p in ("not working", "doesn't work", "isn't working", "not blinking", "stopped", "broken")):
        return Intent("NOT_WORKING")
    if len(t) <= 6 and any(p in s for p in ("repeat", "say again", "say that again", "what was that", "pardon")):
        return Intent("REPEAT")
    if len(t) <= 4 and "not" not in t and set(t) & {"done", "ok", "okay", "next", "yes", "yep", "yeah", "ready", "in"}:
        return Intent("DONE")
    return None


def _parse_part(s: str) -> dict | None:
    """"resistor 68000 2" -> {"type": "resistor", "value": 68000.0, "qty": 2}; "ic NE555 1" -> part. None if malformed."""
    bits = s.split()
    if len(bits) != 3 or bits[0] not in ("resistor", "capacitor", "ic", "led", "other"):
        return None
    kind, value, qty = bits
    try:
        p = {"type": kind, "qty": int(qty)}
        if kind == "ic":
            p["part"] = value.upper()
        elif kind in ("resistor", "capacitor"):
            p["value"] = float(value)
        return p
    except ValueError:
        return None


def _keeps_numbers(text: str, result: dict) -> bool:
    """The spoken line must contain the result's numbers as we'd say them, or it's thrown away."""
    if result["kind"] == "measure":
        need = [f"{result['predicted']:.2f}", f"{result['measured']:.2f}"]
    else:
        need = _NUMBER.findall(result.get("reading", ""))
    return all(n in text for n in need)


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
