# Tutor mode: flexible voice + LLM layer

Date: 2026-10-17 · Owner: L (voice + LLM) · Status: approved design, awaiting spec review

## Goal

Turn Bench Buddy from a fixed 555 script into a tutor. The user says "I want to build X, here's what I have", and
Bench Buddy plans the build, teaches it step by step, reacts on its own to what the camera sees, and answers
questions, hands-free. Pass/fail stays deterministic: the LLM plans, teaches and talks; whether a wire is in the
right hole or a voltage is right comes from vision or the Arduino, never from the LLM.

**Scope:** voice + LLM only. No edits to `vision.py`, `camera.py`, `calibrate.py`, `ui/` or `ui_server.py`.
`contracts.py` is unchanged.

**Time budget:** 1–2 hours. Anything not listed here is out of scope.

## Decisions

| Question | Decision |
| --- | --- |
| Project scope | Any project the user asks for is planned by the LLM; "555 blinker" loads the curated `project.STEPS` (exact rows, voltage checks) so the demo is reliable |
| Talk mode | Hands-free (energy-based voice activity detection), half-duplex (mic ignored while speaking). `--ptt` keeps Enter-to-talk |
| Approach | Plan-driven tutor: one event queue, a controller that owns plan/step/pass-fail, one LLM tutor call per event that returns what to say plus an action the controller validates |
| Old flow | `fsm.py` kept unchanged, reachable with `--script` |

## Architecture

```
 mic ──► Voice.listen() (hands-free) ──► speech feed ──┐
                                                       ├──► queue ──► Tutor controller ──► Voice.say
 Vision.wait_for_event() ──► vision feed ──────────────┘                │       ▲
 idle timer (45 s silence) ────────────────────────────┘                ▼       │ {say, action}
                                                                   Brain.tutor()
```

### Units

**`voice.py` — hands-free listening**
- `Voice(hands_free=True)`; `listen()` blocks until the next utterance and returns its transcript.
- Detection on 16 kHz mono int16 frames of 30 ms: speech when the frame's RMS is above `max(noise_floor * 3,
  VAD_MIN_RMS)`. Noise floor is measured over the first 0.5 s and then tracked slowly while not in speech.
- An utterance starts after 3 consecutive speech frames, keeps 0.3 s of audio from before the start, ends after
  0.7 s of non-speech, and is dropped if shorter than 0.4 s of speech. Maximum length 20 s.
- Half-duplex: frames are ignored while `say()` is playing and for 0.3 s after.
- Transcribe with `record_stop()`'s existing code path (same model, vocab prompt). Empty transcript: keep listening.
- `hands_free=False` keeps the current Enter-to-talk behaviour. `record_start/record_stop` unchanged.
- Env: `VAD_MIN_RMS` (default 300) to tune for a noisy room.

**`brain.py` — planner and tutor** (existing `classify`, `parse_parts`, `explain` stay)
- `start(utterance) -> {"goal": str, "parts": [...], "unclear": [...], "curated": "555" | None}`: one
  structured-output call. `curated` is "555" when the goal is a 555 blinker/flasher/timer LED.
- `plan(goal, parts) -> list[step]`: one LLM call for non-curated goals; 4–10 steps, each
  `{"id", "say", "why", "check": {"kind": "confirm"}}`. `say` is one or two spoken sentences.
- `tutor(context, event) -> {"say": str, "action": "none" | "advance" | "repeat" | "debug"}`: one
  structured-output call, `gpt-4.1-mini`, temperature 0, timeout 3 s, `say` at most 2 sentences / 40 words.
  `context` = goal, parts, plan outline (ids + say), current step (say, why, check kind), last 6 turns, last 3
  camera notes, last check result if any.
- Fallbacks: `start` → `classify`/`parse_parts` keywords and curated 555; `plan` → curated 555; `tutor` →
  keyword intent mapped to an action plus `template()`-style text.

**`tutor.py` — event queue, feeds, controller** (new)
- Feeds (daemon threads) put dicts on one `queue.Queue`:
  - speech: `{"type": "speech", "text"}` from a loop over `voice.listen()`
  - vision: `{"type": "vision", "kind", "holes", "rows", "text"}` from a loop over `vision.wait_for_event()` when
    the vision object has it; `text` is `vision.describe()` if that exists, else built from kind/holes
    ("wire placed at i14")
  - idle: `{"type": "idle"}` after 45 s with no event while a step is open
- Controller `Tutor(vision, voice, brain, bench).run()`:
  - **Start:** first speech event goes to `brain.start`. Curated: `project.missing()` check (say missing parts
    and wait for more speech), then the plan is `project.STEPS`. Otherwise `brain.plan`. Step lines are passed to
    `voice.warm_cache` in a background thread. Says a one-sentence plan summary, then step 1.
  - **Fast paths, no LLM:** speech whose keyword intent is DONE, REPEAT or NOT_WORKING (`brain._quick_intent`).
  - **Step checks:**
    - `confirm` steps: DONE fast path or tutor action `advance` → next step.
    - `vision` steps: a vision `placed` event runs `vision.check_placement(before, expect_rows, wire_colour)`
      (snapshot taken when the step opens); pass → next step; fail/unsure → tutor phrases the detail with a hint.
      Tutor `advance` is ignored on these steps; DONE triggers the same check.
    - `measure` steps: DONE runs `bench.read(pin)` against `expect_mv`.
    - After the last step: `bench.freq(4000)` vs `physics.predict`, as in `fsm.measure`, for curated plans;
      non-curated plans finish with a spoken wrap-up.
  - **Debug:** NOT_WORKING or tutor `debug` → `debug.probe(bench)` → tutor phrases the result; returns to the
    current step.
  - **Other events:** speech and vision events with no check to run go to `brain.tutor`; its `say` is spoken and
    its action validated as above. `repeat` re-says the current step.
- Logging: same `log.jsonl` line shapes as `fsm.py` (`said` with `tts_ms`, `heard` with `intent`/`stt_ms`/
  `llm_ms`, `transition`, `parts`/`missing`, `check` with `step`/`result`/`detail`/`frame`) so the UI keeps
  working. States used in `state`: `INVENTORY`, `STEP`, `CHECK`, `MEASURE`, `DEBUG`, `DONE`.

**`main.py`** — default runs `Tutor`; `--script` runs `fsm.BenchBuddy`; `--ptt` sets `Voice(hands_free=False)`.
`FakeVoice` (typed input) is used with `--fake` as now. Minimal edit; threading/UI code untouched.

## Latency budget (end of speech → audio starts)

Turn detection 0.7 s + transcription 1–1.5 s + LLM 0 s (fast path) or ~1 s + TTS ~0 s (cached) or 0.5–1 s (live).
Target under 2.5 s; every line is logged with `stt_ms`, `llm_ms`, `tts_ms`.

## Failure handling

| Failure | Behaviour |
| --- | --- |
| LLM error or > 3 s | Keyword intent + template text; curated plan if no plan yet |
| TTS error | macOS `say` |
| Transcription error / empty | Ignore, keep listening |
| False triggers in a noisy room | Raise `VAD_MIN_RMS`, or `--ptt` |
| No vision events | Speech-only; DONE triggers checks |
| Anything else on stage | `--script` |

## Testing

No hardware or API keys needed:
- `tests/test_vad.py`: generated audio (silence → tone → silence) yields exactly one utterance with pre-roll;
  short blips are dropped; frames while speaking are ignored.
- `tests/test_tutor.py`: scripted speech and vision events into the queue with `FakeVision`/`FakeBench`/a stub
  brain → expected `said`, `check`, `transition` log lines; tutor `advance` on a vision step is ignored; DONE on a
  confirm step advances with no brain call.
- `tests/test_brain.py`: plan JSON → steps conversion; fallbacks when the client raises.
- `python main.py --fake` runs end to end in tutor mode; `python main.py --fake --script` runs the old flow.
- Live checks against OpenAI for `start`, `plan`, `tutor` latency and output.

## Out of scope

Barge-in (talking over Bench Buddy), Realtime API, tool-calling agent, live Arduino readings for free-form
questions, changes to vision or UI code.
