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
# Plans are one call per build and must be electrically right: a reasoning model gets circuits right where
# gpt-4.1 put a light sensor's divider the wrong way round (~6 s, said while "Let me think..." plays).
PLAN_MODEL = "gpt-5.4-mini"              # override with OPENAI_PLAN_MODEL
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

PARTS_RULES = """Parts: one string per distinct part, "<type> <value> <qty>".
type is resistor, capacitor, ic, led or other. value is in base SI units (ohms, farads) for resistors and
capacitors; for an ic or other it is a short name with no spaces (a plain "555 timer" is 555; keep a stated part
number such as NE555P or LD2402; "radar module" -> radar; breadboard; jumper-wires; usb-power; "9 volt battery" ->
9v-battery; photoresistor; 2N2222); for an led it is -. Include power sources (batteries, USB) as parts.
"68k" / "sixty-eight k" -> 68000; "1k" / "one kilohm" -> 1000; "three-thirty ohms" -> 330 (qty 1);
"1 meg" -> 1000000; "10 micro" / "10uF" -> 1e-5; "100 nano" / "point one micro" -> 1e-7; "10 nanofarad" -> 1e-8.
"two of" -> qty 2; "some" or "a few" -> qty 1.
Examples: "resistor 68000 2", "capacitor 1e-5 1", "ic NE555 1", "other LD2402 1", "other breadboard 1", "led - 1".
Put anything you cannot pin down in `unclear` as the user's words."""

UNDERSTAND_PROMPT = """You are the language-understanding step of Bench Buddy, a voice assistant that guides someone
building a circuit on a breadboard. The user's words come from speech-to-text and may be messy.

Return the user's intent, given the current state:
- PARTS: they are listing electronic parts they have.
- DONE: they finished the current instruction, or agree/are ready ("done", "it's in", "yep", "let's go").
- NOT_WORKING: something is broken, not lighting up, not blinking, or not working.
- QUESTION: they ask a question. Put it in `question`.
- REPEAT: they want the last instruction again.
- OTHER: anything else.

If intent is PARTS, fill `parts` as below. Otherwise `parts` and `unclear` are empty.
""" + PARTS_RULES

EXPLAIN_PROMPT = """You are Bench Buddy, speaking out loud to someone at an electronics bench.
Write ONE short spoken sentence (at most 25 words) that tells them the result in the JSON.
Keep every number exactly as given, with its unit. Never change the verdict or the advice. No markdown, no lists."""

def _schema(name: str, props: dict) -> dict:
    return {"name": name, "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": list(props), "properties": props}}


_STRINGS = {"type": "array", "items": {"type": "string"}}

START_SCHEMA = _schema("start", {
    "goal": {"type": ["string", "null"], "description": "what they want to build, short; null if not said"},
    "curated": {"type": "string", "description": "id of the matching curated project, or none"},
    "follow_up": {"type": ["string", "null"]},
    "parts": _STRINGS, "unclear": _STRINGS,
})
START_PROMPT = """You are the first step of Bench Buddy, a voice tutor at an electronics bench. The user says what they
want to build and usually what parts they have. Their words come from speech-to-text and may be messy.

Return `goal` (short, e.g. "LED that lights when someone walks up"). Even a loose idea is a goal ("something with a
buzzer"). null only if they haven't said anything about what to build (e.g. just "hi").
Set `curated` to the id of the curated project below that their goal matches, or "none":
{menu}
`follow_up`: Bench Buddy wants just enough context to tailor the build, and no more. A project NAME is not a use
case, even a descriptive one. Ask if they only named it or gave a loose idea; don't ask if they said, in their own
words, what it should do, what triggers it, or where/how they'll use it, even briefly.
- "I wanna build a radar presence LED today" -> ask (name only)
- "a night light" / "something with a buzzer" -> ask
- "a radar LED that lights up when it detects a person" -> null (they said what it does)
- "a night light for my hallway" -> null (they said where)
To ask, write ONE short, friendly spoken question (max 20 words) about the most useful missing detail for THIS
project, e.g. what should trigger it, where it will live, or what it's for. Never ask about parts. If `goal` is
null, ask what they'd like to build.
""" + PARTS_RULES

PLAN_SCHEMA = _schema("plan", {
    "circuit": {"type": "string", "description": "netlist and a check of how it works, written before the steps"},
    "needed": _STRINGS, "missing": _STRINGS,
    "summary": {"type": "string"},
    "steps": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["say", "why"],
              "properties": {"say": {"type": "string"}, "why": {"type": "string"}}}},
})
PLAN_PROMPT = """You are Bench Buddy, a voice tutor guiding a beginner through building a circuit on a breadboard.
Given their goal and parts, first work out the circuit in `circuit`: list every net (what connects to what,
including the power source), then check it: trace what happens in each condition the goal describes (e.g. dark vs
light) and confirm the output does the right thing, that every part has the right orientation and polarity, and
that currents are safe. Fix the netlist until it is right. Fit it to their use case (where and how it's used).
`needed`: every part the circuit uses, as short spoken names with values ("a 10 kilohm resistor", "a 2N2222
transistor", "a 9 volt battery", "a breadboard", "jumper wires"). One entry per kind of part: merge repeats
with a count ("two 100 kilohm resistors"). Prefer parts they already have.
`missing`: the entries of `needed` that are not in their parts list (all of them if their list is empty).
Then write a build plan of 4 to 10 steps. Each step is ONE physical action, spoken out loud:
- say: one or two short spoken sentences, with plain words for values ("1 kilohm", "5 volt rail"). No markdown.
- why: one sentence explaining why the step matters, for teaching.
The last step is turning it on and checking that it works. summary: one short spoken sentence saying how many steps
it takes, without restating their request or listing their parts. Prefer safe, low-voltage builds; if the goal is unsafe (mains voltage), say so in the summary
and plan a safe low-voltage version instead."""

TUTOR_SCHEMA = _schema("tutor", {
    "say": {"type": "string"},
    "action": {"type": "string", "enum": ["none", "advance", "repeat", "debug"]},
})
TUTOR_PROMPT = """You are Bench Buddy, a friendly voice tutor at an electronics bench, teaching a beginner to build the
circuit in `context`. You get the current situation and one new event; reply with what to say out loud and an action.

Events: "speech" (the user talked), "vision" (the camera layer saw something on the board), "idle" (the user has
been quiet for a while), "check" (a check ran; its result is final, explain it and how to fix it).

say: at most 2 short spoken sentences (40 words). Teach: explain why when it helps, answer questions about the
current step or the circuit, encourage. Use the step's `why`. Only mention what the camera saw if it's in the
event or `camera`. No markdown. Use "" if nothing is worth saying (e.g. a camera event that needs no comment).
action:
- advance: the user clearly says the current step is done, or (troubleshooting) that it works now.
- repeat: they want the current instruction again.
- debug: they report something is wrong or not working, and you are not already troubleshooting.
- none: anything else (questions, chatter, camera comments, idle check-ins).
Never repeat, quote or paraphrase back what the user just said ("So you want to..."): respond to it directly.
With advance or repeat, `say` is only a brief acknowledgment ("Nice.") or "": the controller speaks the next or
current instruction itself, so never say it yourself.
When `troubleshooting` is true, walk through `troubleshooting_notes` one check at a time: ask one yes/no question
or give one thing to check per turn, based on what they've already ruled out in `recent`."""

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


class Brain:
    def __init__(self):
        from openai import OpenAI
        self.client = OpenAI()
        self.model = os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL
        self.plan_model = os.environ.get("OPENAI_PLAN_MODEL") or PLAN_MODEL
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

    # --- tutor mode (tutor.py) ---------------------------------------------

    def start(self, utterance: str) -> dict:
        """First request -> {"goal", "curated", "parts", "unclear"}. curated is a curated.PROJECTS id or None."""
        import curated
        menu = "\n".join(f"- {p['id']}: {p['name']} ({p['match']})" for p in curated.PROJECTS.values())
        try:
            out = self._json(START_PROMPT.format(menu=menu), utterance, START_SCHEMA, max_tokens=300, timeout=4)
        except Exception as e:
            print(f"[brain] start failed ({e!r}), using keywords")
            return _start_fallback(utterance)
        parts, unclear = _parse_parts(out["parts"], out["unclear"])
        cur = out["curated"] if out["curated"] in curated.PROJECTS else None
        follow_up = (out["follow_up"] or "").strip() or None
        return {"goal": out["goal"], "curated": cur, "follow_up": follow_up, "parts": parts, "unclear": unclear}

    def plan(self, goal: str, parts: list[dict], use_case: str | None = None) -> dict | None:
        """LLM-written build plan -> {"summary", "needed", "missing", "steps": [{"id", "say", "why", "check"}]};
        needed/missing are spoken part names ("a 10 kilohm resistor"). None on error."""
        try:
            out = self._json(PLAN_PROMPT, json.dumps({"goal": goal, "use_case": use_case, "parts": parts}),
                             PLAN_SCHEMA,
                             max_tokens=6000, timeout=30, model=self.plan_model)
        except Exception as e:
            print(f"[brain] plan failed ({e!r})")
            return None
        steps = [{"id": f"s{i + 1}", "say": s["say"], "why": s["why"], "check": {"kind": "confirm"}}
                 for i, s in enumerate(out["steps"]) if s["say"].strip()]
        if not steps:
            return None
        return {"summary": out["summary"], "needed": out["needed"], "missing": out["missing"], "steps": steps,
                "circuit": out.get("circuit")}

    def tutor(self, context: dict, event: dict) -> dict:
        """One tutoring turn -> {"say": str, "action": "none" | "advance" | "repeat" | "debug"}.
        tutor.py validates the action; the LLM never decides that a camera- or meter-checked step passed."""
        try:
            out = self._json(TUTOR_PROMPT, json.dumps({"context": context, "event": event}), TUTOR_SCHEMA,
                             max_tokens=150, timeout=3)
            return {"say": out["say"].strip(), "action": out["action"]}
        except Exception as e:
            print(f"[brain] tutor failed ({e!r}), using keywords")
            return _tutor_fallback(event)

    def _json(self, system: str, user: str, schema: dict, max_tokens: int, timeout: float, model=None) -> dict:
        return json.loads(self._chat(system, user, max_tokens=max_tokens, timeout=timeout, schema=schema,
                                     model=model))

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
            parts, unclear = _parse_parts(out["parts"], out["unclear"])
            self._parsed[transcript] = {"parts": parts, "unclear": unclear}
        return out

    def _chat(self, system: str, user: str, max_tokens: int, timeout: float, schema: dict | None = None,
              model: str | None = None) -> str:
        t0 = time.perf_counter()
        model = model or self.model
        kwargs = {"response_format": {"type": "json_schema", "json_schema": schema}} if schema else {}
        if model.startswith(("gpt-5", "o")):     # reasoning models: no temperature, different token limit
            kwargs.update(reasoning_effort="low", max_completion_tokens=max_tokens)
        else:
            kwargs.update(temperature=0, max_tokens=max_tokens)
        try:
            r = self.client.chat.completions.create(
                model=model, timeout=timeout,
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
    if any(p in s for p in ("not working", "doesn't work", "isn't working", "not blinking", "stopped", "broken",
                                 "not lighting", "doesn't light", "won't light", "didn't light")):
        return Intent("NOT_WORKING")
    if len(t) <= 6 and any(p in s for p in ("repeat", "say again", "say that again", "what was that", "pardon")):
        return Intent("REPEAT")
    if len(t) <= 4 and "not" not in t and set(t) & {"done", "ok", "okay", "next", "yes", "yep", "yeah", "ready", "in"}:
        return Intent("DONE")
    return None


def _parse_parts(strings: list[str], unclear: list[str]) -> tuple[list[dict], list[str]]:
    parts, unclear = [], list(unclear)
    for s in strings:
        p = _parse_part(s)
        parts.append(p) if p else unclear.append(s)
    return parts, unclear


def _start_fallback(utterance: str) -> dict:
    """No LLM: pick a curated project by keyword (the radar demo by default) and assume its parts are there."""
    import curated
    t = utterance.lower()
    cur = "555" if any(w in t for w in ("555", "blink", "flash")) else "radar_led"
    return {"goal": curated.PROJECTS[cur]["name"], "curated": cur, "follow_up": None, "parts": None, "unclear": []}


def _tutor_fallback(event: dict) -> dict:
    """No LLM: keyword intent -> action, with a plain line."""
    if event.get("type") != "speech":
        return {"say": "", "action": "none"}
    intent = FakeBrain().classify(event.get("text", ""), "STEP").kind
    action = {"DONE": "advance", "NOT_WORKING": "debug", "REPEAT": "repeat"}.get(intent, "none")
    say = "" if action != "none" else "Sorry, I can't think that through right now. Say done when the step is finished."
    return {"say": say, "action": action}


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
        elif kind == "other":
            p["part"] = value.lower()
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

    def start(self, utterance: str) -> dict:
        return _start_fallback(utterance)

    def plan(self, goal: str, parts: list[dict], use_case: str | None = None) -> dict | None:
        return None

    def tutor(self, context: dict, event: dict) -> dict:
        return _tutor_fallback(event)
