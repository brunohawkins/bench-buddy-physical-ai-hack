# Bench Buddy: 5-Hour Plan (3 people)

Revised from the 7-hour, 2-person plan. Same demo, less build time, three owners working in parallel against fixed interfaces.

**Pitch:** a second pair of eyes and hands at your bench. It knows your parts, watches your board, probes your circuit and tells you why it isn't working.

## What changed from v1

| Change | Why |
| --- | --- |
| 3 roles: **Vision**, **Voice + LLM**, **Hardware** | One owner per subsystem; Voice + LLM also owns `main.py` and the state machine |
| Every module ships a **fake** in the first 20 min | `main.py` runs end to end from 0:20, and real modules swap in one at a time |
| **Phone webcam is the primary camera.** The Jetson is used only if its stream already works before the clock starts | Fisheye undistortion, ArUco and a GStreamer stream that OpenCV may not open are too much risk for 5 h |
| **4 hand-clicked corners** replace the ArUco + checkerboard calibration | 15 min instead of an hour. ArUco is a stretch goal |
| **The board is pre-built apart from one jumper** (pin 4 reset), which is placed live under the camera | Vision only has to check one placement well, and the same jumper is the debug fault |
| **10 kΩ pull-down from pin 4 to GND** | A bipolar NE555 with pin 4 left floating often keeps running, so pulling the jumper might not stop the blink. The pull-down makes the fault deterministic and gives A2 a defined 0 V |
| **FREQ measures the period, not an edge count** | At 1 Hz, counting edges for 3 s has ±0.33 Hz resolution, which can't produce "measured 0.97 Hz" |
| VLM, FastAPI dashboard, MediaPipe hand detection: **stretch only** | Default display is a `cv2.imshow` window with the overlay and status text drawn on it |
| macOS `say` as the TTS fallback; typed input as the STT fallback | The demo still runs if Wi-Fi or an API goes down |

Inconsistencies fixed from v1: "Won't have: the Jetson Nano" contradicted using it as the camera head, and `camera.py` still said "Pi stream".

## Roles

| Role | Owner | Owns |
| --- | --- | --- |
| **V: Vision** | _name_ | `camera.py`, `calibrate.py`, `vision.py` (checks), overlay window. Stretch: `vlm.py`, LED blink detection, dashboard |
| **L: Voice + LLM** | _name_ | `voice.py`, `brain.py` (parsing, intent, phrasing), `fsm.py`, `project.py`, `main.py`, integration |
| **H: Hardware** | _name_ | Breadboard layout, the 555 circuit, test-point leads, `bench.ino`, `bench_serial.py`, `physics.py`, `debug.py`; then full-run testing |

## Interfaces (agree at 0:00, don't change without telling the others)

Shared types are in `contracts.py` (`Snapshot`, `CheckResult`, `Intent`, `ProbeResult`). Each module has a real class and a `Fake…` class with the same methods:

```python
# --- V: vision.py, camera.py, calibrate.py --------------------------------
Camera(source).latest() -> np.ndarray | None             # newest BGR frame
Vision(camera).snapshot() -> Snapshot                    # stable warped board image
Vision.check_placement(before, expect_rows, wire_colour) -> CheckResult   # pass | fail | unsure

# --- L: voice.py, brain.py, fsm.py ----------------------------------------
Voice().listen() -> str                                  # push-to-talk transcript
Voice.say(text) -> None                                  # cached phrase, else TTS, else mac_say
Brain().parse_parts(transcript) -> dict                  # parts JSON below
Brain.classify(transcript, state) -> Intent              # PARTS DONE NOT_WORKING QUESTION REPEAT OTHER
Brain.explain(result: dict) -> str                       # one spoken sentence; brain.template() is the fallback

# --- H: bench_serial.py, physics.py, debug.py, firmware/bench/bench.ino ---
Bench(port).ping() / .read(pin) -> mV / .sample(pin, ms) -> (min, max, mean) / .freq(ms) -> Hz
predict(r1, r2, c) -> (hz, duty);  within(measured, predicted, tol=0.25) -> bool
probe(bench) -> ProbeResult
```

`python main.py --fake` runs the whole flow with every module faked; `--fake vision bench` fakes only those. Swap real modules in one at a time.

### Serial protocol (115200 baud, one line each way)

| Command | Reply | Notes |
| --- | --- | --- |
| `PING` | `OK` | Wait ~2 s after opening the port, because the Uno resets |
| `READ A0` | `OK 4980` | mV |
| `SAMPLE A1 3000` | `OK 1690 3310 2510` | min, max, mean mV |
| `FREQ 4000` | `OK 0.98 4` | Hz and edge count. The ISR stores `micros()` of each rising edge on D2; Hz = (edges − 1) / (t_last − t_first). Use 4000 ms so you always get ≥3 edges at 1 Hz |
| other | `ERR <reason>` | Python raises |

### Parts JSON, project step and log line

As in v1, except a measure step names a `pin` rather than a `cmd`:

```
{"parts": [{"type": "resistor", "value": 68000, "qty": 2}, ...], "unclear": [...]}
{"id": "reset", "say": "Connect pin 4 to the 5 volt rail with a red wire.",
 "check": {"kind": "vision", "expect_rows": [13], "wire_colour": "red"}}
{"id": "power-on", "say": "Plug in the Arduino.",
{"t": "14:02:11", "state": "STEP", "step": "reset", "check": "vision",
 "result": "fail", "detail": "inserted in row 15, expected 13", "frame": "frames/0031.jpg"}
```

Row numbers are placeholders until H fixes the layout at 0:20.

## Role details

### V: Vision

1. `camera.py`: background thread holding the latest frame. Source is an index (phone via Continuity Camera / Iriun) or a URL (Jetson), so switching is one config line.
2. `calibrate.py`: click the 4 corners of the hole area once, save them to `calib.json`, warp to a flat top-down board, and map (row, column) ↔ pixel. Draw the grid on the live window. Re-click if the camera gets bumped (tape the stand down).
3. `vision.py`:
   - Wait for 1 s with no motion (frame diff below a threshold) before taking a snapshot.
   - Diff the before and after warped frames and find the hole patches that changed.
   - Map those patches to rows.
   - Check the wire colour with an HSV mask at the expected holes.
   - Take two snapshots 1 s apart, and only pass or fail if they agree. Otherwise return `unsure`.
4. Develop on photos while H is still building the board. At 0:20, H takes about 10 photos for V: the empty board, the chip placed, the jumper in the right row, and the jumper one row off.
5. Stretch: VLM yes/no on a labelled crop when `unsure`; LED blink count; a FastAPI dashboard.

### L: Voice + LLM

1. **STT:** `sounddevice` at 16 kHz mono. Press Enter to start recording and Enter to stop. Holding a key needs macOS accessibility permissions, so skip that. The clip goes to OpenAI transcription. Fallback: type the text.
2. **Understand:** one OpenAI call per utterance with structured output, giving the current state, the transcript and the allowed intents. It returns `{intent, parts?, question?}`. **The LLM never decides a transition or whether a step passed; `fsm.py` does.**
3. **Speak:** ElevenLabs TTS, using a low-latency model.
   - Fixed phrases and every step's `say` line are generated at startup and cached on disk, keyed by a hash of the text, so restarts are free.
   - Dynamic lines (measurement results, debug hints, answers) come from `explain()`: the LLM writes one short sentence from structured data, then it's sent to TTS.
   - Fallback: `subprocess.run(["say", text])`.
4. **Latency target:** under 3 s from releasing push-to-talk to speech starting. Keep LLM prompts tiny and use a small, fast model.
5. **State machine:** `IDLE → INVENTORY → PROPOSE → STEP → CHECK → (pass → next | fail → retry) → MEASURE → DONE`. `DEBUG` can be reached from any state on `NOT_WORKING`. Every transition writes one line to `log.jsonl`.
6. Stretch: free-form bench questions ("what's the voltage on the cap?"), with the LLM calling a tool that maps to `Bench.read`/`sample`.

### H: Hardware

1. **First 20 min:** fix the layout. The 555 straddles the centre channel at known rows, so V and `project.py` share row numbers. Post the pin-to-row map in the team chat.
2. Build the 555 astable: R1 = 10 kΩ, R2 = 68 kΩ, C = 10 µF, which predicts 0.99 Hz at 53% duty.
   - Same wiring as v1, **plus a 10 kΩ pull-down from pin 4 to GND**.
   - The red reset jumper (pin 4 → 5 V) is the one that gets placed live and pulled for the debug demo.
3. Write `bench.ino` (period-based FREQ, see the protocol table) and `bench_serial.py` (timeouts, one retry).
4. Wire the test points. Debug probes them top to bottom and reports the first failure:

   | Pin | Node | Healthy | Fail means |
   | --- | --- | --- | --- |
   | A0 | 555 pin 8 | ~5.0 V | < 4.5 V: power jumper missing |
   | A2 | 555 pin 4 | ~5.0 V | < 0.8 V: reset not tied high (the planted fault) |
   | A1 | pins 2/6 | swings ~1.7–3.3 V | stuck ~0: R2 or C missing; stuck high: pin 7 path |
   | D2 | pin 3 | ~1 Hz | 0 Hz with A0–A2 healthy: output or LED path |

5. Write `physics.py` and `debug.py`. Test them by pulling the reset jumper.
6. After checkpoint 2: run the full flow repeatedly, tape everything down, and label the leads.

## Timeline

Times are elapsed working time. Pause the clock for the 20-min lunch at 1 pm.

| Time | V: Vision | L: Voice + LLM | H: Hardware |
| --- | --- | --- | --- |
| 0:00–0:20 | Agree interfaces; push fake `vision.py`; phone camera visible in OpenCV | Repo skeleton, venv, `.env`; fake `main.py --fake` running; one TTS call plays | Fix the layout and post the row map; Arduino port found; photos for V |
| 0:20–1:30 | `camera.py`, corner calibration, grid overlay on the live window | `voice.py` STT + TTS + phrase cache; `brain.py` `parse_parts` + `classify` | Build the 555; `bench.ino`; `bench_serial.py` |
| **1:30** | **CP1:** overlay lines up with real holes. If not: fix the camera height, re-click the corners | **CP1:** say your parts → hear a spoken reply with the parts list | **CP1:** LED blinks, `FREQ` ≈ 1 Hz. If not: spare 555 → LM358 → LED + resistor |
| 1:30–2:45 | `vision.py` change detection, colour check, two-frame agreement | `fsm.py` + `project.py` + `explain()`; run the flow with real voice and fake V/H | Test points + pull-down; `physics.py`; `debug.py`; then integrate H into the state machine with L |
| **2:45** | **CP2: full flow runs end to end once with real modules.** If not, cut in this order: VLM → parts parser (hard-code the parts) → free-form questions | | |
| 2:45–3:40 | Integrate the vision check with L; tune thresholds on the real board; status text on the overlay | Integration lead; latency; fallbacks (typed input, `say`) | Full runs on repeat; tape down; stretch: dashboard if ahead |
| **3:40** | **Feature freeze** | | |
| 3:40–4:40 | Rehearse 3+ times; record a full-run backup video; write up the submission and one pitch slide; reset the board to the demo start state | | |

## Demo script (~2 min)

1. **Pitch (15 s).**
2. **Parts → project (20 s):** say your parts. It proposes the 555 blinker and predicts 0.99 Hz.
3. **Camera check (30 s):** place the red reset jumper one row off. It says "that went into row 14, it should be row 13". Move it, and it confirms.
4. **Measure (15 s):** "predicted 0.99 Hz, measured 0.97 Hz, within tolerance."
5. **Debug (30 s):** pull the same reset jumper and say "it's not working". It probes, reports reset at 0 V and tells you to tie pin 4 to 5 V. Reconnect it, and it re-measures and passes.
6. **Market (10 s):** hobbyists and kits; hardware bring-up. Roadmap: KiCad import, so it knows the expected voltage at every node of your own design.

## Risks

| Risk | Fallback |
| --- | --- |
| Grid misses holes | Camera straight down and higher; re-click the corners; keep the board centred |
| 555 output high (~3.3–3.8 V on a bipolar NE555) is marginal against the Uno's 3.0 V HIGH threshold, so FREQ reads 0 while the LED blinks | Swap in a CMOS 7555 (rail-to-rail output), or compute frequency from fast `analogRead`s of pin 3 with a 2.5 V threshold |
| Measured frequency far off | Measure R1 and R2; widen tolerance to ±30%; explain capacitor tolerance in the demo |
| Venue noise | Headset mic; push-to-talk; typed input |
| Wi-Fi or API down | Cached phrases + `say`; measurement and debug run offline; backup video |
| Only one breadboard for V and H | V develops on H's photos; borrow a second breadboard if possible |
| Scope creep | Cut list at CP2; freeze at 3:40 |

## Setup

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install opencv-contrib-python numpy pyserial openai elevenlabs sounddevice soundfile python-dotenv
```

`.env` (git-ignored): `OPENAI_API_KEY=...`, `ELEVENLABS_API_KEY=...`
