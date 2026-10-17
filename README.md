# Bench Buddy

Our project for the **Physical AI Hack**: a second pair of eyes and hands at your bench. It knows your parts, watches your board, probes your circuit and tells you why it isn't working.

The plan, roles, interfaces and timeline are in [PLAN.md](PLAN.md).

## Team

- Bruno Hawkins ([@brunohawkins](https://github.com/brunohawkins))
- Zoe Gong [@SummerRainZozo](https://github.com/SummerRainZozo)
- Parthiv Naidu [@parthiv-n](https://github.com/parthiv-n)

## Quick start

```bash
git clone https://github.com/brunohawkins/bench-buddy-physical-ai-hack.git
cd bench-buddy-physical-ai-hack

python main.py --fake            # whole flow, typed input, no hardware/keys/packages needed
python main.py --fake --ui       # same flow in the browser UI at http://localhost:8000

python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env             # fill in keys, serial port, camera source
python main.py --fake vision bench   # e.g. real voice + LLM, fake camera + Arduino
```

For the radar demo with the phone camera and spoken guidance:

```bash
.venv/bin/python main.py --fake bench --ui
```

Vision checks each settled change against the current instruction and the whole circuit. A clearly observed
mistake produces an immediate spoken correction with the observed hole and the intended move, without saying
“done” or waiting for the tutor model. It finishes any speech already playing, suppresses repeated corrections
for 20 seconds, and holds the current step until a fresh camera assessment clears the fault. Detection still
requires an unobstructed, still board and the vision API response (typically 3–15 seconds in the previous live
tests). Uncertain holes and grid alignment problems do not produce wiring accusations.

Small local changes now trigger checks, and a misaligned grid gets a bounded recalibration and recheck. Delayed
results are discarded if the board or current step changed. Use `VISION_VLM=0` for the existing pixel-only wire
checks; full circuit checking needs the vision model. Camera corrections also appear in the browser chat.

“Can you check?”, “can you see the LED?” and “I just did that” trigger a fresh camera check during a placement
step. Old camera descriptions expire instead of being treated as a current view. LED checks include an extra
close-up around the requested rows and distinguish a visible LED body from clearly resolved leg holes. If the
body hides the entry points, angle the camera slightly to expose both legs; an unlit LED still counts as present.

Run the offline regression suite (fake model responses, synthetic camera frames and captured speech text):

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Pytest uses temporary directories for frame artifacts and tutor logs. A physical camera/voice rehearsal is still
needed to assess recognition accuracy on your lighting, board position and components.

## Layout

| File | Owner | What |
| --- | --- | --- |
| `contracts.py` | all | Shared types passed between modules |
| `main.py` | L | Entry point; `--fake [modules]` picks fakes |
| `fsm.py` | L | State machine, the only thing that decides pass/fail and what's next; writes `log.jsonl` |
| `project.py` | L + H | The 555 project as data: required parts, steps, R/C values |
| `voice.py` | L | Push-to-talk STT (OpenAI) and TTS (ElevenLabs) with a phrase cache |
| `brain.py` | L | LLM: parts parsing, intent, phrasing replies |
| `camera.py` | V | Threaded frame grabber; `python camera.py 1` to preview a camera index |
| `calibrate.py` | V | `python calibrate.py`: finds the board and every hole automatically → (row, col) ↔ pixel |
| `vision.py` | V | Real-time view + placement check; `python vision.py --row 13 --colour red` to test live |
| `ui_server.py` | UI | `--ui`: serves `ui/`, streams fsm log lines to the page, takes typed/spoken input |
| `ui/` | UI | Browser front end (landing page, chat card, board view); see `ui/README.md` |
| `tests/` | all | `.venv/bin/python tests/test_vision.py` |
| `firmware/bench/bench.ino` | H | Arduino serial firmware (PING, READ, SAMPLE, FREQ) |
| `bench_serial.py` | H | Python side of the serial protocol |
| `physics.py` | H | 555 frequency prediction and tolerance |
| `debug.py` | H | Test-point probe sequence, first failure wins |

Search for `TODO(V)`, `TODO(L)` and `TODO(H)` to find your work.

## Workflow

- Branch off `main` for each feature: `git checkout -b <name>/<feature>`
- Keep `python main.py --fake` working on `main`
- Pull often: `git pull --rebase origin main`
- Change `contracts.py` or a method signature only after telling the others
