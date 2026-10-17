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
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q                  # full offline suite; synthetic camera + stubbed model/voice
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
                 change < 0.4%, no local blob       -> ignore as noise (retain baseline for cumulative change)
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
ui/            (Parthiv) landing page, chat with hands-free voice / optional push-to-talk, isometric board.
```

### Vision board state (for the 3D/isometric view)

`vision.state()` is pushed on every change as an SSE `board` event, served at `/api/board`, and written to `frames/board_state.json`:

```json
{"parts": [{"id": "wire1", "kind": "wire", "color": "red", "from": ["d", 20], "to": ["+L", 9],
            "pins": [["d", 20], ["+L", 9]], "label": "Red wire", "detail": "d20 -> top + rail (row 9)"}],
 "board": [...model's raw list...], "led": false, "led_at": null,
 "summary": "...", "narration": "One red jumper connects d20 to the top positive rail at row 9.", "status": "..."}
```

`parts` uses the `ui/js/board.mjs` PARTS shape. Rails map as top + `+L`, top − `-L`, bottom + `+R`, bottom − `-R`. **Not done yet:** `board.mjs` still draws the hard-coded 555 parts. Parthiv's view should render `parts` from the board event instead.

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

  Keep taping the board down. Model-reported misalignment now triggers two agreeing calibration fits and one
  re-judgement; an unreliable fit stays a warning and does not overwrite the known part list.
- **Latency:** each model call takes about 3–15 s (four images at detail "original"). The watcher blocks while it waits, which is fine at bench pace.
- **Tutor phrasing:** advance/repeat replies now leave instructions to the controller, including camera events.
  Ordinary LLM replies still need live observation for conversational drift.
- **ElevenLabs** caching sometimes returns ApiError (concurrency). Phrases are generated live instead. Lower `max_workers` in voice.py if it persists.
- **Pytest isolates tutor logs and frame artifacts** in temporary directories. The standalone vision test script
  still writes frame artifacts; use pytest during live sessions.
- **LED polarity and resistor value** can't be seen once parts are in; they come from what the user says.
- **`bench_serial.py` is Arduino serial,** but the team is on a Raspberry Pi. The radar demo doesn't need the meter (run with `--fake bench`).

## Implemented: real-time spoken error reports

Goal: the vision model notices what is WRONG as soon as it happens and Bench Buddy says it out loud, with the fix ("The LED's legs share the same connected strip in row 35. Move the short leg to row 36."), without waiting for "done".

`vlm.judge` now returns validated `problem`, `fix`, `severity` (`wrong` / `warning` / null), and `grid`
(`aligned` / `misaligned` / `uncertain`). Confirmed problems are spoken directly by the vision feed through
the tutor's shared speech lock, even while the tutor LLM is waiting. They are logged as `vision_problem`
and shown as a wiring correction in the UI. Uncertain problems stay silent. The same correction is suppressed
for 20 seconds; a clean assessment resets that suppression. A known fault blocks advancement until vision
clears it. Camera checks that fail also speak their exact correction without another tutor LLM call.

`Vision.set_task(step, plan, circuit)` receives the explicit current step, completed/future steps and target
circuit on each step transition. The same vision call checks the whole visible circuit, so there is no second
netlist API call. Custom plans preserve their generated circuit description. User lead identities are retained
separately from the last 20 conversation lines. Prompts distinguish the two halves of a row, separate/split
rails, incomplete builds, hidden polarity and unknown wire identity.

Perception now detects small local motion/changes as well as whole-board changes. It never absorbs a detected
hand into its baseline. Grid errors trigger a bounded two-fit recovery and re-judgement. Malformed model
responses fall back to pixel rules, and a frozen camera or a result from an older board/step cannot pass a check.
The event stream retains a per-consumer cursor so events arriving during speech are not lost. Problems and
their resolution emit assessment events even when no placement was recorded. Board state JSON includes all
four assessment fields.

New regression coverage is in `tests/test_perception.py` and `tests/test_tutor.py`: wrong-hole speech end to end,
warning suppression, cooldown/recovery, speech serialization, busy tutor calls, stale frames/results,
small changes, malformed replies, API failures, grid recovery and circuit context. These tests are offline;
the updated prompts and thresholds still need a live phone-camera rehearsal. Model latency remains, typically
3–15 seconds in the earlier live tests, plus 0.8 seconds of settling and any speech already playing.

### Follow-up: stale empty-board replies and LED visibility

Reproduced from the running session: “I just did that” / “can you check?” went to the text tutor, which repeated
an old empty-board observation. Saying “done” invoked `Vision.verify` and correctly identified V/G, then IO and
the resistor. These requests now invoke a fresh check directly; a tutor `advance` on a look step requests a
verification too. Old camera evidence expires after 15 seconds, disappears on board motion, and is replaced by
fresh verification detail. An empty evidence list means unknown, not an empty breadboard.

`/api/board` includes `observation` (current, observed_at, age_seconds, detail, source), `last_model_error` and
`discarded_observations` for diagnosis. A model reply after a harmless motion can be retained only if a settled
pixel comparison shows the same board; actual plug changes still invalidate it. Exact obscured-leg feedback
is spoken instead of the previous generic unsure phrase.

Judge/verify also get a native-resolution raw close-up of rows named in the current step, alongside the full
overview. Prompts separate LED presence from glow and from the ability to read its legs. Tested the revised
verification prompt against the captured live preview: it identified the red LED body and returned unsure
because its leg holes were obscured. It did not claim the LED was missing. Camera angle can still hide the
entry points; the close-up cannot recover physically occluded legs. Restart the running app to load these changes.

### Follow-up: hands-free browser voice

The browser wrapper previously bypassed `Voice.listen()` and waited only for typed text or PTT messages, even
though the real voice was configured for hands-free mode. `UIVoice` now runs one cancellable speech worker
beside the input queue. It detects speech automatically whenever the tutor is accepting a turn. Typed input
or mic pause cancels that turn immediately; late STT results cannot leak into the next turn. Each turn has a
fresh, bounded audio queue, and speech is ignored during TTS and its echo tail. An unfinished sentence is also
discarded across a muted gap.

`/api/hello` advertises `hands_free`; SSE status includes `mic_state`, `mic_paused` and `mic_error`. The mic
button pauses/resumes, Space is no longer required, and microphone startup failures leave typing available
with a retry hint. Pause is handled immediately even while the tutor is busy; reconnects restore mic status.
`--ptt` and fake/demo voice retain the manual path. Restart the Python app and refresh the browser to activate.
Regression coverage uses generated audio, stubbed transcription/device callbacks and threaded UI input;
an actual microphone conversation still needs a live rehearsal.

## Also before the deadline

- Parthiv: render `/api/board` `parts` in `board.mjs` (live 3D view) and make the presentation.
- Record the ~1 min demo video: radar build guided by voice, vision catching a mistake, walk past, LED lights.
- Make the repo public, then submit (team name, members, description, repo, video, tech: OpenCV, OpenAI gpt-6-astra vision + gpt-4o-mini-transcribe, ElevenLabs Flash TTS, Python stdlib web UI).
