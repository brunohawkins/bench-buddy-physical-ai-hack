# Bench Buddy: handoff

Hand-off for the next coding agent (Codex). Read this first, then `README.md`, `PLAN.md`, `ui/README.md`.

## What this is

Bench Buddy is a voice tutor for breadboard electronics, built for the Physical AI Hack (submission 16:00: public repo, ~1 min public demo video, team, description, tech). A phone camera watches a breadboard from above. The user talks to it, it plans a build step by step, and it checks each step with computer vision plus an OpenAI vision model.

The demo build is the LD2402 radar presence LED (`radar-led-demo.md`): the radar's IO output drives an LED through a 1 kΩ resistor, with no microcontroller.

- Team: Bruno (brunohawkins, vision), Zoe (SummerRainZozo, voice + LLM/tutor), Parthiv (parthiv-n, UI/hardware).
- Repo: https://github.com/brunohawkins/bench-buddy-physical-ai-hack (`main`). It is still private; make it public before submitting.
- Commits: never add a "Co-Authored-By: Claude" line (team rule).

## Run it

```bash
.venv/bin/python main.py --fake bench --ui      # tutor + real voice + real vision + browser UI on :8000
.venv/bin/python vision.py                      # vision alone: prints every event/narration, OpenCV window
.venv/bin/python tests/test_vision.py           # 16 vision tests (offline; the model path is faked)
.venv/bin/python tests/test_tutor.py            # (and test_brain.py, test_vad.py; pytest not installed, run as scripts)
VISION_DEBUG=1 ...                               # saves every judged before/after pair + grid json to frames/debug/
```

- `.env` is git-ignored and holds `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `CAMERA_SOURCE=0` (the iPhone via Continuity Camera; the indices shift when the phone connects) and `SERIAL_PORT`. Never print key values.
- Optional settings:
  - `OPENAI_VISION_MODEL` (default `gpt-6-astra`)
  - `VISION_VLM=0` (pixel rules only, no API)
  - `VISION_PARALLAX` (default 0.022)
- Physical setup: the phone sits on a stand looking down, with Center Stage off. **Tape the breadboard down**; pushing plugs in moves it, and that is the main cause of misreads. Keep hands off for about 3 s at startup (calibration).

## Architecture

```
camera.py      threaded capture (AVFoundation), latest()/latest_with_id()
calibrate.py   automatic hole-grid calibration from one frame: Otsu board mask, black-hat holes, deskew,
               1-D line clustering, RANSAC homography, per-row offsets, orientation from the red/blue rail
               stripes (+ lock to calib.json / previous grid). Board.hole_xy/warp/rail_at. Our board: row 1 on
               the left, column a at the top (A_AT_BOTTOM=False), rails "top +/-", "bottom +/-".
vision.py      Vision: real-time loop (warp, motion/stillness, LED glow every frame) + watcher thread.
               When the board settles after a change:
                 hand over the board (thick skin-coloured change) or >12% changed -> wait
                 change < 0.4%                     -> absorb (noise)
                 else, with an API key            -> vlm.judge(...)  (the model decides)
                 API error / no key               -> pixel rules (plug_ends: black plug housings, parallax fix)
               Keeps: parts (model's part list), narration, summary, problem, led, context (conversation).
               API: wait_for_event, wait_for_placement, check_placement, verify(step), describe(), state(),
                    note(who, text), ask(question), view(), listeners (callbacks with state()).
vlm.py         OpenAI Responses API. judge(): images = camera BEFORE/AFTER (raw, cropped to the board) +
               flattened BEFORE/AFTER with every row numbered and the change outlined (set-of-mark prompting).
               Returns {changes:[{part, action, holes, colour}], board:[{id, part, colour, holes}], problem,
               summary, narration}. Holes: "d20" or rail "+top9"/"-bottom12". verify(): one board photo + the step
               -> {status pass|fail|unsure, detail}. Prompts list the project parts and the breadboard rules, and
               say the computed grid can be off: trust the board's printed numbers, report "grid misaligned".
tutor.py       (Zoe) default mode: hands-free voice tutor. Speech, vision and idle events go into one queue; the LLM
               (brain.tutor) suggests what to say/do, the controller owns pass/fail. Vision events arrive via
               vision.wait_for_event + vision.describe(). Step check kinds: confirm | vision | look | measure.
               "look" = vision.verify(step["check"]["ask"]). The tutor also runs a look-check by itself when the
               camera saw a change and the LLM says advance. Every said/heard line goes to vision.note() (context).
curated.py     hand-checked projects; RADAR_LED is the demo (steps below). 555 = old project.py script.
fsm.py         old fixed 555 script (--script). project.py = 555 data.
brain.py       (Zoe) LLM layer: keyword fast path + structured output; start/tutor/parse.
voice.py       (Zoe) ElevenLabs Flash streaming TTS with a disk cache; OpenAI gpt-4o-mini-transcribe STT, hands-free VAD.
ui_server.py   (Parthiv) stdlib HTTP: serves ui/, SSE /events (fsm/tutor log lines + {"type":"board"} vision
               state), POST /api/input, /camera.mjpg (vision.view()), GET /api/board (vision.state()).
ui/            (Parthiv) landing page, chat card with push-to-talk, isometric board (js/board.mjs, PARTS format).
```

### Vision board state (for the 3D/isometric view)

`vision.state()` is pushed on every change as an SSE `board` event, served at `/api/board`, and written to `frames/board_state.json`:

```json
{"parts": [{"id": "wire1", "kind": "wire", "color": "red", "from": ["d", 20], "to": ["+L", 9],
            "pins": [["d", 20], ["+L", 9]], "label": "Red wire", "detail": "d20 -> top + rail (row 9)"}],
 "board": [...model's raw list...], "led": false, "led_at": null,
 "summary": "...", "narration": "One red jumper connects d20 to the top positive rail at row 9.", "status": "..."}
```

`parts` uses the `ui/js/board.mjs` PARTS shape. Rails map as top + `+L`, top − `-L`, bottom + `+R`, bottom − `-R`. The UI draws it in 3D: the board pane holds the breadboard twin (`figures/parts`, bundled to `ui/vendor/twin.bundle.mjs`), which simulates whatever vision reports. See `ui/README.md`.

## The radar demo build (curated.py RADAR_LED)

The user's radar lead colours, said at the bench and remembered as context: **V black, G grey, IO yellow, TX green, RX blue**. Extra jumpers are **orange** (avoid the radar's colours).

| step | say | check |
|---|---|---|
| radar | which lead colour is V/G/IO/TX/RX? | confirm (gives the model the colours) |
| power | V lead to + rail, G lead to − rail | look |
| io | IO lead in row 30; resistor row 30 to row 35 | look |
| led | LED long leg row 35, short leg row 36 | look |
| ground | jumper row 36 to − rail | look |
| usb | power the rails (5 V / GND) | confirm |
| finish | walk in front of the radar; did the LED light? | confirm (+ OpenCV `led_on` event) |

TX and RX stay unplugged; tape them out of view.

## What was validated live (phone camera, real board)

- Calibration: about 620–634 of 630 holes. Orientation locked to `calib.json` (a fresh fit once came out 180° flipped).
- Model bake-off on frames with known holes:

  | model | correct | time |
  |---|---|---|
  | `gpt-6-astra` | 4/4 | ~3.5 s |
  | `gpt-6.1-sol` | 4/4 | ~3.5 s |
  | `gpt-6-sol`, `gpt-5.6-sol` | 2/4 | |
  | `gpt-4.1` | 0/4 | |
  | `gpt-4o-mini` | 0/4 | |

  The pixel-only tracker missed or misread these (glare, parallax).
- Live, the model correctly reported:
  - a wire placed in d20;
  - the other end in the top + rail at row 9 (joined as one wire);
  - the black (V) lead into the top + rail, then the grey (G) lead into the top − rail, named by colour from the conversation;
  - "three jumper wires, resistor and red LED removed", with every hole.
- `verify` passed a true step and failed a false one with a spoken fix ("Connect a jumper from d36 to a − rail").
- The tutor reacts to vision ("I see the breadboard is empty now…", "Great, the V lead is in the plus rail. Now plug the G lead…").

## Known issues

- **The board moving** makes the grid stale. Mitigations:
  - re-align needs ≥80% of holes and two agreeing fits;
  - the model also sees raw camera photos and can say "grid misaligned".

  The real fix is taping the board down, plus making "grid misaligned" trigger a recalibration (TODO below).
- **Latency:** each model call takes about 3–15 s (four images at detail "original"). The watcher blocks while it waits, which is fine at bench pace.
- **The tutor's LLM sometimes recites the next step early** while the controller is still on the current one. Saying "done" re-syncs.
- **ElevenLabs** caching sometimes returns ApiError (concurrency). Phrases are generated live instead. Lower `max_workers` in voice.py if it persists.
- **The tests write `log.jsonl`** (shared with the running app).
- **LED polarity and resistor value** can't be seen once parts are in; they come from what the user says.
- **`bench_serial.py` is Arduino serial,** but the team is on a Raspberry Pi. The radar demo doesn't need the meter (run with `--fake bench`).

## NEXT: real-time spoken error reports (requested)

Goal: the vision model notices what is WRONG as soon as it happens and Bench Buddy says it out loud, with the fix ("The LED's legs are both in row 35, so it's shorted. Move the short leg to row 36."), without waiting for "done".

**Already in place:**
- `vlm.judge` returns `problem` for every settled change; its prompt asks for things like LED legs in the same row and wrong rails.
- `Vision._model_step` stores it in `vision.problem`, prints it, and puts it in the event (`event["problem"]`).
- `vision.describe()` now starts with `PROBLEM: ...` when there is one. The tutor's `_vision_feed` passes `describe()` to its LLM, so the tutor already gets told.

**To do:**
1. **Speak it deterministically.** In `tutor.py` `_vision_feed`, put `"problem": e.get("problem")` on the queued event. In `handle()`, if `ev.get("problem")`, `self.say(...)` the problem plus the fix right away, without waiting for the tutor's choice of action, and log it (`check="vision_problem"`).
2. **Make the problem actionable.** Extend the `JUDGE_PROMPT` reply with `"fix": "<exact move: which lead/leg from which hole to which hole>"` and `"severity": "wrong"|"warning"|null`. Speak only `wrong`.
3. **Step-aware checking.** Pass the current step's `say`/`ask` into `judge()` (e.g. `vision.note("Step", step["say"])` when a step opens, or a dedicated `vision.step` field in the prompt). The model can then judge "is this change right for this step?" on every change, which is effectively `verify()` on every change.
4. **Whole-circuit sanity pass.** After each change, also check the full netlist against the target circuit (V to +, G to −, IO to R to LED+ to LED− to −). Cheap option: a text-only call with `vision.parts` plus the target netlist, so the model call stays image-free.
5. **Grid self-heal.** If `problem` contains "grid misaligned", force a recalibration (`calibrate.calibrate_from_camera(..., prev=self.board)`) and re-judge.
6. Voice must not talk over itself. Use the tutor's existing `say()` queueing, and de-duplicate the same problem within about 20 s.
7. Tests: extend `test_model_judges_placement_and_tracks_state` with a fake judge returning a problem, and assert the tutor says it (FakeVoice records `say`).

## Also before the deadline

- Parthiv: live 3D view done (`ui/README.md`, "3D twin"); make the presentation.
- Record the ~1 min demo video: radar build guided by voice, vision catching a mistake, walk past, LED lights.
- Make the repo public, then submit (team name, members, description, repo, video, tech: OpenCV, OpenAI gpt-6-astra vision + gpt-4o-mini-transcribe, ElevenLabs Flash TTS, Python stdlib web UI).
