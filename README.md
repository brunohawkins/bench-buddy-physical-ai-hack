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

python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env             # fill in keys, serial port, camera source
python main.py --fake vision bench   # e.g. real voice + LLM, fake camera + Arduino
```

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
