"""Tutor mode: plan a build from what the user asks for, then teach it step by step, reacting to speech and to what
the camera sees. Owner: L. Spec: docs/superpowers/specs/2026-10-17-tutor-voice-llm-design.md

Speech, vision and idle events go into one queue. The controller owns the plan, the current step and pass/fail;
Brain.tutor() decides what to say and suggests an action, which the controller only follows where allowed (it
never passes a camera- or meter-checked step on the LLM's word). Logs the same log.jsonl lines as fsm.py.
"""
import json
import queue
import re
import threading
import time
from collections import deque
from pathlib import Path

import curated
from brain import _quick_intent
from debug import probe
from physics import predict, within

LOG_PATH = Path("log.jsonl")
IDLE_AFTER = 45                          # seconds of quiet during a step before checking in (once per step)
PROBLEM_COOLDOWN = 20                    # repeat a persistent error at most once in this many seconds
CAMERA_NOTE_TTL = 15                     # old notes must never be narrated as a live view
GREETING = "Hi, I'm Bench Buddy. What do you want to build today?"
# In INVENTORY, any of these means "I've got the parts, let's go".
READY = ("next step", "what's next", "whats next", "what do i do", "let's start", "lets start", "let's go",
         "lets go", "start building", "go ahead", "get started", "have them", "have all", "got them", "got all",
         "have everything", "got everything", "all of them", "yes", "yeah", "yep", "sure", "ready", "i do")
NOT_READY = ("don't", "do not", "haven't", "have not", "missing", "no ", "not yet", "nope")
SKIP = ("just start", "skip", "doesn't matter", "don't know", "not sure", "whatever", "no idea")
ACKS = ("Nice.", "Got it.", "Great.", "Perfect.")   # said instead of the LLM's line when it advances a step


class Tutor:
    def __init__(self, vision, voice, brain, bench=None):
        self.vision, self.voice, self.brain, self.bench = vision, voice, brain, bench
        self.state = "IDLE"
        self.events: queue.Queue = queue.Queue()
        self._listening = threading.Event()          # speech feed waits for this, so turns don't overlap
        self.goal, self.project, self.parts, self.steps, self.step_i = None, None, [], [], 0
        self.before = None                           # snapshot taken when a vision step opens
        self.troubleshooting = False
        self.intake = None                           # "use_case" / "parts": the follow-up we're waiting on
        self.use_case, self.plan, self.parts_unknown = None, None, False
        self.recent: deque = deque(maxlen=6)         # (who, text) for the tutor's context
        self.camera: deque = deque(maxlen=3)         # latest camera notes
        self._camera_event, self._camera_at = None, 0.0
        self.last_check = None
        self.last_event, self.nudged = time.time(), False
        self._speech_lock = threading.RLock()       # camera corrections and normal replies share one voice
        self._problem = None
        self._problem_version = 0
        self._spoken_problems = {}
        self._interrupted = threading.Event()
        self.voice.on_speech_start = self._speech_started

    # --- plumbing ------------------------------------------------------------

    def log(self, **fields) -> None:
        line = {"t": time.strftime("%H:%M:%S"), "state": self.state, **fields}
        note = getattr(self.vision, "note", None)       # the vision model gets the conversation as context
        if note and fields.get("said"):
            note("Bench Buddy", fields["said"])
        if note and fields.get("heard"):
            note("User", fields["heard"])
        with LOG_PATH.open("a") as f:
            f.write(json.dumps(line, default=str) + "\n")

    def say(self, text: str, expected_version=None) -> bool:
        if not text:
            return True
        with self._speech_lock:
            if self._interrupted.is_set():
                return False
            if expected_version is not None and expected_version != self._problem_version:
                return False
            completed = self.voice.say(text)
            if completed is False:
                self.log(interrupted=text)
                return False
            self.log(said=text, tts_ms=getattr(self.voice, "last_latency_ms", None))
            self.recent.append(("buddy", text))
        return True

    def _speech_started(self):
        # The audio layer already stopped playback. Suppress the rest of this response until input arrives.
        self._interrupted.set()

    def goto(self, state: str) -> None:
        if state != self.state:
            self.log(transition=state)
            self.state = state

    def phrases(self) -> list[str]:
        """Fixed lines and every curated step, so voice can cache them at startup."""
        out = [GREETING, "Let me work out what you'll need. This takes a few seconds.", "Let me measure.", *ACKS]
        for p in curated.PROJECTS.values():
            out += [s["say"] for s in p["steps"]] + [p["done"], f"Let's build the {p['name']}. It's {len(p['steps'])} steps."]
        return out

    # --- feeds ------------------------------------------------------------------

    def _speech_feed(self) -> None:
        while True:
            if not getattr(self.voice, "hands_free", False):
                self._listening.wait()
                self._listening.clear()
            try:
                text = self.voice.listen()
            except EOFError:
                self.events.put({"type": "eof"})
                return
            self.events.put({"type": "speech", "text": text})

    def _vision_feed(self) -> None:
        while True:
            e = self.vision.wait_for_event(timeout=None)
            if not e:
                continue
            self._queue_vision(e)

    def _queue_vision(self, e: dict) -> None:
        """Use this observation's text, not mutable global state that may already describe a later frame."""
        if hasattr(self.vision, "event_is_current") and not self.vision.event_is_current(e):
            return
        where = ", ".join(e.get("holes", []))
        text = " ".join(t for t in (e.get("problem"), e.get("fix"), e.get("summary"), e.get("narration")) if t)
        ev = {"type": "vision", "kind": e["kind"], "holes": e.get("holes", []), "rows": e.get("rows", []),
              "text": text or f"{e['kind']} at {where}",
              **{k: e.get(k) for k in ("problem", "fix", "severity", "assessment", "grid")},
              **{k: e[k] for k in ("observed_period", "task_version") if k in e}}
        # Do not wait behind a slow tutor LLM call. say() serializes with any speech already playing.
        self._observe_problem(ev)
        ev["feedback_delivered"] = True
        self.events.put(ev)

    def _observe_problem(self, ev: dict) -> bool:
        wrong = ev.get("severity") == "wrong" and ev.get("problem") and ev.get("fix")
        if wrong:
            if not self._problem or any(self._problem[k] != ev.get(k) for k in ("problem", "fix", "severity")):
                self._problem_version += 1
            self._problem = {k: ev.get(k) for k in ("problem", "fix", "severity")}
            self._problem.update({k: ev[k] for k in ("observed_period", "task_version") if k in ev})
            self._speak_problem(self._problem)
            return True
        if ev.get("assessment") and ev.get("grid") == "aligned" and not ev.get("problem"):
            if self._problem:
                self._problem_version += 1
            self._problem = None
            self._spoken_problems.clear()           # the same mistake after a verified fix is a new mistake
        elif ev.get("assessment") and ev.get("grid") == "aligned" and ev.get("severity") == "warning" and self._problem:
            # A new, uncertain view supersedes a previous confident accusation. A fresh check is still
            # required to advance, but don't keep ordering a move based on an obsolete LED reading.
            self._problem_version += 1
            self._problem = None
            self._spoken_problems.clear()
        return False

    def _speak_problem(self, problem: dict) -> None:
        text = " ".join(dict.fromkeys([problem["problem"].strip(), problem["fix"].strip()]))
        key = re.sub(r"\W+", " ", text.lower()).strip()
        with self._speech_lock:
            if problem != self._problem or (hasattr(self.vision, "event_is_current")
                                           and not self.vision.event_is_current(problem)):
                return
            now = time.monotonic()
            if now - self._spoken_problems.get(key, -float("inf")) < PROBLEM_COOLDOWN:
                return
            self._spoken_problems = {k: t for k, t in self._spoken_problems.items() if now - t < PROBLEM_COOLDOWN}
            self.log(check="vision_problem", result="fail", detail=text, **problem)
            if self.say(text):
                self._spoken_problems[key] = now

    def run(self) -> None:
        threading.Thread(target=self.voice.warm_cache, args=(self.phrases(),), daemon=True).start()
        threading.Thread(target=self._speech_feed, daemon=True).start()
        if hasattr(self.vision, "wait_for_event"):
            threading.Thread(target=self._vision_feed, daemon=True).start()
        self.say(GREETING)
        self._listening.set()
        while True:
            try:
                ev = self.events.get(timeout=1)
            except queue.Empty:
                if self.state == "STEP" and not self.nudged and time.time() - self.last_event > IDLE_AFTER:
                    self.nudged = True
                    self.handle({"type": "idle"})
                continue
            if ev["type"] == "eof":
                return
            self.last_event = time.time()
            if ev["type"] == "speech":
                self._interrupted.clear()
            self.handle(ev)
            if ev["type"] == "speech":
                self._listening.set()

    # --- events -------------------------------------------------------------------

    def handle(self, ev: dict) -> None:
        if ev["type"] == "vision":
            if hasattr(self.vision, "event_is_current") and not self.vision.event_is_current(ev):
                return
            if not ev.get("feedback_delivered"):
                self._observe_problem(ev)
            self.camera.clear()
            self.camera.append(ev["text"])
            self._camera_event, self._camera_at = ev, time.monotonic()
            self.log(vision=ev["text"], kind=ev["kind"], holes=ev["holes"])
            if ev.get("problem") or self._problem or ev["kind"] == "assessment":
                return                              # already spoken if confirmed; uncertain readings never advance
            step = self.current()
            if self.state == "STEP" and step and step["check"]["kind"] == "vision" and ev["kind"] == "placed":
                return self.check()
            if self.state in ("STEP", "DONE"):
                self.respond(ev)
            return
        if ev["type"] == "idle":
            return self.respond(ev)

        text = ev["text"].strip()
        if not text:
            return
        self.recent.append(("user", text))
        if self.state in ("IDLE", "INVENTORY"):
            return self.begin(text)
        quick = _quick_intent(text)
        self.log(heard=text, intent=quick.kind if quick else "TUTOR",
                 stt_ms=getattr(self.voice, "last_stt_ms", None), llm_ms=None)
        step = self.current()
        if self.state == "STEP" and step and step["check"]["kind"] in ("look", "vision") \
                and _visual_check_requested(text):
            return self.check()
        if quick and quick.kind == "DONE" and not self.troubleshooting:
            return self.check() if self.state == "STEP" else self.respond(ev)
        if quick and quick.kind == "REPEAT":
            return self.say_step()
        if quick and quick.kind == "NOT_WORKING" and not self.troubleshooting:
            return self.debug()
        self.respond(ev)

    def respond(self, ev: dict) -> None:
        """Let the tutor talk, then follow its action where the controller allows it."""
        version = self._problem_version
        out = self.brain.tutor(self.context(), ev)
        if version != self._problem_version or self._interrupted.is_set():
            return                                  # a camera correction made this model reply obsolete
        self.log(tutor=out["action"], llm_ms=getattr(self.brain, "last_ms", None))
        action = out["action"]
        if self._problem and action == "advance":
            return self._speak_problem(self._problem)
        if action in ("advance", "repeat"):
            # the LLM tends to recite the next instruction itself; the controller says it, so just acknowledge
            line = ACKS[self.step_i % len(ACKS)] if action == "advance" and ev["type"] == "speech" else ""
        else:
            line = out["say"]
        if not self.say(line, expected_version=version) or version != self._problem_version:
            return
        if action == "repeat":
            self.say_step()
        elif action == "debug" and not self.troubleshooting:
            self.debug()
        elif action == "advance" and ev["type"] == "speech":
            if self.troubleshooting:
                self.troubleshooting = False
                self.log(check="troubleshoot", result="pass")
                self.goto("STEP" if self.current() else "DONE")
                step = self.current()
                if step and step["id"] == "finish" and step["check"]["kind"] == "confirm":
                    self.check()                     # "it works now" on the last step is the confirmation
                else:
                    self.say_step()
            elif self.state == "STEP" and self.current()["check"]["kind"] in ("confirm", "look"):
                self.check()
            # "advance" requests a fresh look check; only its result can pass the step.
        elif action == "advance" and ev["type"] == "vision" and self.state == "STEP" and self.current() \
                and self.current()["check"]["kind"] == "look":
            self.check()                             # the camera saw it happen: let the vision model check the step

    # --- plan -------------------------------------------------------------------

    def begin(self, text: str) -> None:
        """Intake, one question at a time: goal -> use case (asked once) -> parts (listed once) -> steps."""
        if self.intake == "use_case":
            return self.got_use_case(text)
        if self.intake == "parts":
            return self.got_parts_answer(text)
        info = self.understand(text)
        if self.goal is None:
            self.goal = info["goal"]
            if info["curated"]:
                self.project = curated.PROJECTS[info["curated"]]
        if self.goal is None:
            self.goto("INVENTORY")
            return self.say(info.get("follow_up") or "What would you like to build? For example, a light that "
                            "turns on when someone walks up.")
        if not info.get("follow_up"):                # they already said enough: straight on
            self.use_case = text
            return self.check_parts()
        self.intake = "use_case"
        self.goto("INVENTORY")
        self.say(info["follow_up"])                 # the LLM's question, tailored to what's unclear

    def understand(self, text: str) -> dict:
        """brain.start() + log + collect any parts mentioned."""
        info = self.brain.start(text)
        self.log(heard=text, intent="START", goal=info["goal"], curated=info["curated"],
                 follow_up=info.get("follow_up"), stt_ms=getattr(self.voice, "last_stt_ms", None),
                 llm_ms=getattr(self.brain, "last_ms", None))
        if info["parts"] is None:
            self.parts_unknown = True                # offline fallback: can't tell, so assume they have them
        else:
            self.parts += info["parts"]
        return info

    def got_use_case(self, text: str) -> None:
        self.intake = None
        if not _skip(text):
            self.use_case = text
            self.understand(text)                    # they often mention parts while describing it
        self.log(use_case=self.use_case)
        self.check_parts()

    def check_parts(self) -> None:
        """List what's needed if they haven't got it all, once. Custom builds are planned here (the plan call
        also works out the parts list), so starting after their answer has no extra wait."""
        if self.project:
            gaps = [] if self.parts_unknown else curated.missing(self.project, self.parts)
            needed = gaps
        else:
            self.say("Let me work out what you'll need. This takes a few seconds.")
            self.plan = self.brain.plan(self.goal, self.parts, self.use_case)
            if self.plan is None:
                self.project = curated.RADAR_LED
                self.say("I couldn't plan that right now, so let's build the radar presence LED instead.")
                return self.start_steps()
            needed, gaps = self.plan["needed"], self.plan["missing"]
        self.log(parts=self.parts, missing=gaps)
        if not gaps:
            return self.start_steps()
        self.intake = "parts"
        self.goto("INVENTORY")
        if not self.parts:                           # nothing named: give the whole list
            self.say(f"For this you'll need {_join(needed if not self.project else gaps)}. Have you got those?")
        else:
            self.say(f"You'll also need {_join(gaps)}. Have you got {'it' if len(gaps) == 1 else 'those'}?")

    def got_parts_answer(self, text: str) -> None:
        self.intake = None
        if _ready(text) or _skip(text):
            self.log(heard=text, intent="READY", stt_ms=getattr(self.voice, "last_stt_ms", None), llm_ms=None)
            return self.start_steps()
        before = len(self.parts)
        self.understand(text)
        new_parts = self.parts[before:]
        if self.project:
            gaps = curated.missing(self.project, self.parts)
        elif new_parts:                              # different parts than planned for: re-plan once with them
            self.say("Okay, let me rework the plan with those parts.")
            plan = self.brain.plan(self.goal, self.parts, self.use_case)
            self.plan = plan or self.plan
            gaps = self.plan["missing"]
        else:
            gaps = self.plan["missing"]
        if gaps:
            self.say(f"You'll still need {_join(gaps)} at some point, but let's get started.")
        self.start_steps()

    def start_steps(self) -> None:
        self.intake = None
        if self.project:
            self.steps = self.project["steps"]
            summary = f"Let's build the {self.project['name']}. It's {len(self.steps)} steps."
        else:
            self.steps, summary = self.plan["steps"], self.plan["summary"]
            threading.Thread(target=self.voice.warm_cache, args=([s["say"] for s in self.steps],),
                             daemon=True).start()
        self.log(plan=[{"id": s["id"], "say": s["say"]} for s in self.steps], goal=self.goal,
                 project=self.project["id"] if self.project else None, use_case=self.use_case)
        self.say(summary)
        self.open_step(0)

    def current(self) -> dict | None:
        return self.steps[self.step_i] if self.step_i < len(self.steps) else None

    def open_step(self, i: int) -> None:
        self.step_i, self.nudged, self.last_check = i, False, None
        step = self.current()
        if step is None:
            return self.finish()
        self.goto("STEP")
        self._set_vision_task(step)
        self.before = self.vision.snapshot() if step["check"]["kind"] == "vision" else None
        self.say_step()

    def say_step(self) -> None:
        if self._problem:
            return self._speak_problem(self._problem)
        step = self.current()
        self.say(step["say"] if step else (self.project or {}).get("done", "We're all done."))

    def finish(self) -> None:
        self.goto("DONE")
        self._set_vision_task(None)
        self.say(self.project["done"] if self.project else
                 "That's every step. Nice work! Tell me if anything isn't working.")

    def _set_vision_task(self, step) -> None:
        setter = getattr(self.vision, "set_task", None)
        if setter:
            plan = [{"id": s["id"], "say": s["say"], "check": s["check"], "completed": i < self.step_i}
                    for i, s in enumerate(self.steps)]
            setter(step=step, plan=plan, circuit=(self.project or self.plan or {}).get("circuit"))

    # --- checks -------------------------------------------------------------------

    def check(self) -> None:
        """Run the current step's check; pass -> next step, otherwise explain and stay."""
        if self._problem:
            return self._speak_problem(self._problem)
        version = self._problem_version
        step = self.current()
        chk = step["check"]
        self.goto("CHECK")
        frame = ""
        if chk["kind"] == "vision":
            r = self.vision.check_placement(self.before, chk["expect_rows"], chk.get("wire_colour"))
            status, detail, frame = r.status, r.detail, r.frame
        elif chk["kind"] == "look" and hasattr(self.vision, "verify"):
            r = self.vision.verify(chk.get("ask") or step["say"])     # the vision model checks the step
            status, detail, frame = r.status, r.detail, r.frame
        elif chk["kind"] == "measure" and self.bench is not None:
            mv = self.bench.read(chk["pin"])
            lo, hi = chk["expect_mv"]
            status = "pass" if lo <= mv <= hi else "fail"
            detail = f"I'm reading {mv / 1000:.2f} volts on {chk['pin']}."
        elif chk["kind"] == "freq" and self.bench is not None:
            return self.measure_freq()
        else:                                        # confirm, or a meter check with no Arduino attached
            status, detail = "pass", "confirmed"
        if version != self._problem_version or self._interrupted.is_set():
            self.goto("STEP")
            return                                  # a problem arrived during verification; never advance past it
        self.last_check = {"step": step["id"], "result": status, "detail": detail}
        if chk["kind"] in ("vision", "look"):
            self.camera.clear()                     # the old empty-board note is superseded, even on an unsure check
            self._camera_event = None
        self.log(step=step["id"], check=chk["kind"], result=status, detail=detail, frame=frame)
        if status == "pass":
            if chk["kind"] in ("vision", "look"):
                self.say(detail, expected_version=version)
            if version != self._problem_version or self._interrupted.is_set():
                self.goto("STEP")
                return
            return self.open_step(self.step_i + 1)
        self.goto("STEP")
        if status == "unsure":
            return self.say(detail or "I can't see it clearly. Move your hand away, then ask me to check again.")
        if chk["kind"] in ("vision", "look"):
            return self.say(detail, expected_version=version)
        out = self.brain.tutor(self.context(), {"type": "check", **self.last_check})
        self.say(out["say"] or detail)

    def measure_freq(self) -> None:
        self.goto("MEASURE")
        self.say("Let me measure.")
        predicted, _ = predict(*_555_values())
        hz = self.bench.freq(4000)
        ok = within(hz, predicted)
        self.log(check="measure", result="pass" if ok else "fail",
                 detail=f"predicted {predicted:.2f} Hz, measured {hz:.2f} Hz")
        self.say(self.brain.explain({"kind": "measure", "predicted": predicted, "measured": hz, "ok": ok}))
        if ok:
            return self.open_step(self.step_i + 1)
        self.debug()

    def debug(self) -> None:
        """Arduino attached and the project has test points: probe them. Otherwise a spoken checklist."""
        resume = self.state if self.state in ("STEP", "DONE") else "STEP"
        self.goto("DEBUG")
        if self.bench is not None and self.project is not None and self.project["id"] == "555":
            self.say("Let me measure.")
            r = probe(self.bench)
            self.log(check="probe", result="pass" if r.ok else "fail", node=r.failed_node, detail=r.reading)
            self.say(self.brain.explain({"kind": "probe", "ok": r.ok, "reading": r.reading, "hint": r.hint}))
            self.goto(resume)
            return
        self.troubleshooting = True
        self.log(check="troubleshoot", result="start")
        out = self.brain.tutor(self.context(), {"type": "speech", "text": "It's not working. Help me find out why."})
        self.say(out["say"] or "Let's check it together. Is the LED's long leg on the resistor side?")
        self.goto(resume)                            # stay in the step; the troubleshooting flag routes replies

    def context(self) -> dict:
        step = self.current()
        camera = []
        if self._camera_event and time.monotonic() - self._camera_at <= CAMERA_NOTE_TTL:
            current = getattr(self.vision, "event_is_current", lambda event: False)
            if current(self._camera_event):
                camera = list(self.camera)
        observation = getattr(self.vision, "observation", None)
        if observation:
            view = observation()
            camera = [view["detail"]] if view["current"] else []
        return {
            "goal": self.goal,
            "use_case": self.use_case,
            "project": self.project["name"] if self.project else None,
            "parts": self.parts,
            "plan": [s["say"] for s in self.steps],
            "step_number": self.step_i + 1 if step else None,
            "step": {"say": step["say"], "why": step.get("why", ""), "check": step["check"]["kind"]} if step else None,
            "finished": step is None and bool(self.steps),
            "troubleshooting": self.troubleshooting,
            "troubleshooting_notes": self.project["troubleshooting"] if self.project and self.troubleshooting else [],
            "recent": [f"{who}: {text}" for who, text in self.recent],
            "camera": camera,
            "camera_status": "current observation" if camera else "no current observation; request a fresh check",
            "last_check": self.last_check,
            "vision_problem": self._problem,
        }


def _ready(text: str) -> bool:
    t = " " + re.sub(r"[^a-z' ]", " ", text.lower()) + " "
    if any(n in t for n in NOT_READY) and "next step" not in t:
        return False
    quick = _quick_intent(text)
    return (quick is not None and quick.kind == "DONE") or any(f" {p} " in t for p in READY)


def _visual_check_requested(text: str) -> bool:
    s = " ".join(re.sub(r"[^a-z' ]", " ", text.lower()).split())
    return any(p in s for p in ("can you check", "could you check", "please check", "check now", "check it",
                               "can you see", "do you see", "does it look right", "does that look right")) \
        and not any(p in s for p in ("don't check", "do not check", "can't check", "cannot check"))


def _skip(text: str) -> bool:
    return any(p in text.lower() for p in SKIP)


def _join(items: list[str]) -> str:
    """["a", "b", "c"] -> "a, b and c"."""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _555_values():
    import project
    return project.R1, project.R2, project.C

