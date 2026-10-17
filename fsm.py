"""State machine: the only place that decides what happens next or whether a step passed. Owner: L.

IDLE -> INVENTORY -> PROPOSE -> STEP <-> CHECK -> MEASURE -> DONE, with DEBUG reachable from
any state that listens. Every transition writes one line to log.jsonl.
"""
import json
import time
from pathlib import Path

import project
from brain import template
from debug import probe
from physics import predict, within

LOG_PATH = Path("log.jsonl")


class BenchBuddy:
    STEP_SUFFIX = " Say done when it's in."
    UNSURE = "I can't see it clearly. Move your hand away or show me closer, then say done."

    def __init__(self, vision, voice, brain, bench):
        self.vision, self.voice, self.brain, self.bench = vision, voice, brain, bench
        self.state = "IDLE"
        self.resume = "MEASURE"          # where DEBUG goes once the circuit measures healthy
        self.step_i = 0
        self.before = None               # snapshot taken before the current vision step
        self.retry_prompt = None
        self.predicted, _ = predict(project.R1, project.R2, project.C)

    # --- plumbing ----------------------------------------------------------

    def log(self, **fields) -> None:
        line = {"t": time.strftime("%H:%M:%S"), "state": self.state, **fields}
        note = getattr(self.vision, "note", None)       # the vision model gets the conversation as context
        if note and fields.get("said"):
            note("Bench Buddy", fields["said"])
        if note and fields.get("heard"):
            note("User", fields["heard"])
        with LOG_PATH.open("a") as f:
            f.write(json.dumps(line) + "\n")

    def say(self, text: str) -> None:
        self.voice.say(text)
        self.log(said=text, tts_ms=getattr(self.voice, "last_latency_ms", None))

    def phrases(self) -> list[str]:
        """Every fixed line, so voice can cache them at startup."""
        fixed = ["Hi, I'm Bench Buddy.", "Tell me what parts you have.", "Power's good.",
                 "Measuring the blink rate.", "Let me measure.", "Say done when you've fixed it.",
                 "Your blinker is working. Tell me if anything stops working.", self.UNSURE]
        fixed += [s["say"] + self.STEP_SUFFIX for s in project.STEPS]
        f, duty = predict(project.R1, project.R2, project.C)
        fixed.append(template({"kind": "propose", "f": f, "duty": duty}))
        return fixed + ["Sorry, I didn't catch that. " + p for p in fixed]

    def ask(self, prompt: str, accept: set[str]):
        """Say prompt, then listen until an accepted intent. NOT_WORKING always returns so the caller can go to DEBUG."""
        self.say(prompt)
        while True:
            text = self.voice.listen()
            intent = self.brain.classify(text, self.state)
            self.log(heard=text, intent=intent.kind, stt_ms=getattr(self.voice, "last_stt_ms", None),
                     llm_ms=getattr(self.brain, "last_ms", None))
            if intent.kind in accept or intent.kind == "NOT_WORKING":
                return text, intent
            if intent.kind == "REPEAT":
                self.say(prompt)
            elif intent.kind == "QUESTION":
                self.say("I can't answer questions yet. " + prompt)     # TODO(L): stretch, bench tools
            else:
                self.say("Sorry, I didn't catch that. " + prompt)

    def run(self) -> None:
        handlers = {
            "IDLE": self.idle, "INVENTORY": self.inventory, "PROPOSE": self.propose,
            "STEP": self.step, "CHECK": self.check, "MEASURE": self.measure,
            "DONE": self.done, "DEBUG": self.debug,
        }
        self.voice.warm_cache(self.phrases())
        while True:
            nxt = handlers[self.state]()
            if nxt == "DEBUG" and self.state != "DEBUG":
                self.resume = "MEASURE" if self.state in ("MEASURE", "DONE") else self.state
            if nxt != self.state:
                self.log(transition=nxt)
            self.state = nxt

    # --- states --------------------------------------------------------------

    def idle(self) -> str:
        self.say("Hi, I'm Bench Buddy.")
        return "INVENTORY"

    def inventory(self) -> str:
        text, intent = self.ask("Tell me what parts you have.", {"PARTS"})
        if intent.kind == "NOT_WORKING":
            return "DEBUG"
        parts = self.brain.parse_parts(text)
        gaps = project.missing(parts["parts"])
        self.log(parts=parts, missing=gaps)
        if gaps:
            self.say(self.brain.explain({"kind": "missing", "missing": gaps}))
            return "INVENTORY"
        return "PROPOSE"

    def propose(self) -> str:
        f, duty = predict(project.R1, project.R2, project.C)
        _, intent = self.ask(self.brain.explain({"kind": "propose", "f": f, "duty": duty}), {"DONE"})
        return "DEBUG" if intent.kind == "NOT_WORKING" else "STEP"

    def step(self) -> str:
        if self.step_i >= len(project.STEPS):
            return "MEASURE"
        step = project.STEPS[self.step_i]
        if step["check"]["kind"] == "vision" and self.before is None:
            self.before = self.vision.snapshot()
        prompt = self.retry_prompt or step["say"] + self.STEP_SUFFIX
        self.retry_prompt = None
        _, intent = self.ask(prompt, {"DONE"})
        return "DEBUG" if intent.kind == "NOT_WORKING" else "CHECK"

    def check(self) -> str:
        step = project.STEPS[self.step_i]
        chk = step["check"]
        frame = ""
        if chk["kind"] == "vision":
            r = self.vision.check_placement(self.before, chk["expect_rows"], chk.get("wire_colour"))
            status, detail, frame = r.status, r.detail, r.frame
        else:
            mv = self.bench.read(chk["pin"])
            lo, hi = chk["expect_mv"]
            status = "pass" if lo <= mv <= hi else "fail"
            detail = f"I'm reading {mv / 1000:.2f} volts on {chk['pin']}."
        self.log(step=step["id"], check=chk["kind"], result=status, detail=detail, frame=frame)

        if status == "pass":
            self.say(detail if chk["kind"] == "vision" else "Power's good.")
            self.step_i += 1
            self.before = None
        elif status == "fail":
            self.retry_prompt = detail + (" Move it and say done." if chk["kind"] == "vision"
                                          else " Check the connection and say done.")
        else:
            self.retry_prompt = self.UNSURE
        return "STEP"

    def measure(self) -> str:
        self.say("Measuring the blink rate.")
        hz = self.bench.freq(4000)
        ok = within(hz, self.predicted)
        self.log(check="measure", result="pass" if ok else "fail",
                 detail=f"predicted {self.predicted:.2f} Hz, measured {hz:.2f} Hz")
        self.say(self.brain.explain({"kind": "measure", "predicted": self.predicted, "measured": hz, "ok": ok}))
        return "DONE" if ok else "DEBUG"

    def done(self) -> str:
        self.ask("Your blinker is working. Tell me if anything stops working.", set())
        return "DEBUG"

    def debug(self) -> str:
        self.say("Let me measure.")
        r = probe(self.bench)
        self.log(check="probe", result="pass" if r.ok else "fail", node=r.failed_node, detail=r.reading)
        self.say(self.brain.explain({"kind": "probe", "ok": r.ok, "reading": r.reading, "hint": r.hint}))
        if r.ok:
            return self.resume
        self.ask("Say done when you've fixed it.", {"DONE"})
        return "DEBUG"
