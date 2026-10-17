# Bench Buddy UI

Landing page → "Start building" → the bench: a floating chat card on the left (mic + text box) and the board on a green cutting mat.

The live backend listens hands-free through the computer's microphone by default. A pause of about a second
sends the turn. On macOS, speak while the tutor talks to interrupt it; capture/playback use native echo cancellation.
Click the mic to pause/resume capture. Typed input can be sent at any time and also stops speech. Microphone failures show a
retry hint and leave typing available. `--ptt` retains manual Space/mic recording.

```bash
python main.py --ui                    # opens http://localhost:8000
```

Everything on the bench comes from the running app: there is no canned demo. Opened without the server, the page says how
to start it and connects by itself once it is up. Voice in uses the browser's speech recognition (Chrome/Safari) unless
the server transcribes.

## Running with `main.py`

`.venv/bin/python main.py --fake bench --ui` runs the real camera, voice and tutor with a fake meter.

The UI is driven by the tutor's (or `fsm.py`'s) log lines, the same dicts written to `log.jsonl`, plus vision's board state:

| Route | Direction | Body |
| --- | --- | --- |
| `GET /api/hello` | → UI | `{"project": {"steps": project.STEPS, "predicted": 0.99}, "browser_tts": false, "server_stt": true, "hands_free": true, "barge_in": true, "camera": true}` |
| `GET /events` (SSE) | → UI | `{"type": "log", "line": <log line>}`, `{"type": "status", "waiting": true, "hands_free": true, "mic_state": "listening", "mic_paused": false}`; also `speaking` and `mic_error` |
| `POST /api/input` | UI → | `{"text": "done"}`, `{"mic": "pause" \| "resume"}` in hands-free mode, or `{"ptt": "start" \| "stop"}` in manual mode |
| `GET /camera.mjpg` | → UI | optional MJPEG of the phone camera with the hole grid |
| `GET /frames/...` | → UI | annotated jpgs from `CheckResult.frame`, shown in the check card |
| `GET /api/board` | → UI | live board state from vision (below) |

Log lines the UI reacts to: `said`, `heard`, `transition`, `parts`/`missing`, `check: vision` (`step`, `result`, `detail`, `rows_found`, `frame`),
`check: measure` (`detail: "predicted X Hz, measured Y Hz"`), `check: probe` (`node`, `detail`).

Files: `index.html`, `styles.css`, `js/app.mjs` (controller), `js/board.mjs` (isometric board for the landing hero, built with
[anatomy](https://github.com/wheresryan22/anatomy)'s kit in `vendor/`, MIT), `js/mat.mjs` (mat rulers),
`js/hero.mjs` (landing animation: line-art board, the parts channel and the swap loop). `assets/raspberry-pi.svg` is the
`<svg>` cut out of `figures/raspberry-pi/raspberry-pi.html`; re-extract it if that figure is rebuilt.

## Live board state from vision (for the 3D view)

Whenever the board settles after a change, vision asks the OpenAI vision model (`vlm.judge`) what was plugged in or
pulled out, keeps a part list, and writes a plain-English narration. The UI server pushes it as an SSE event
`{"type": "board", ...}` (latest only, also sent to a page that connects later) and serves it on `GET /api/board`;
it is also written to `frames/board_state.json`.

```json
{"t": "13:25:02",
 "parts": [{"id": "wire1", "kind": "wire", "color": "red", "from": ["d", 20], "to": ["+L", 20],
            "pins": [["d", 20], ["+L", 20]], "label": "Red wire", "detail": "d20 -> top + rail (row 20)"}],
 "board": [{"id": "wire1", "part": "wire", "colour": "red", "holes": ["d20", "+top20"]}],
 "led": false, "led_at": null,
 "summary": "The red wire's other end went into the top + rail.",
 "narration": "A red jumper wire runs from d20 to the top + rail. Nothing else is on the board.",
 "status": "..."}
```

`parts` uses the `PARTS` shape in `js/board.mjs` (rails `+L -L +R -R` = top +, top -, bottom +, bottom -), so it can
be drawn directly. `kind` is `wire`, `radar`, `resistor`, `led` or `other`; `to` is null until a wire's second end is in;
`pins` lists every hole (the radar module has several).

## 3D twin in the board pane: the board as it is being built

The bench's board pane is the breadboard twin from `figures/parts` (three.js plus a circuit solver), bundled to
`vendor/twin.bundle.mjs`. It follows the real board as it changes:

| At the bench | On screen (chip top right, highlights on the 3D board) |
|---|---|
| App starts, camera fitting the grid | "Finding the board · keep hands off" |
| A step is said ("…into row 30…", "…the plus rail…") | its rows / rails glow green, "Next: rows 30–35" |
| Hands over the board | "Hands on the board…" |
| Hands off, board settles | the changed rows glow amber and the plug holes white: "Looking at rows 30–35…" (pixel read, instant) |
| Vision decides what changed | the part drops into those holes; the circuit re-simulates; narration updates |
| LED lights on the bench | compared with the simulated LED; a mismatch turns the chip red with a hint |

Vision sends `activity` (`calibrating` / `hands` / `looking` with `rows` and `holes` / `ready` / `error`) in every `board` state.
With the model disabled, pixel rules show individual plug ends without assuming which ends belong to one wire.
Failed model calls preserve the last known part list. The layout comes from `figures/parts/from-vision.js`.
A radar is drawn once vision or the conversation mentions one. Its leads use the user's colour-to-pin mapping,
including descriptions such as “V black, G grey, IO yellow”; an unidentified lead stays loose. Moving V to the
wrong rail keeps its V identity. The resistor takes the value from the parts
the user listed. A step that powers the rails ("power the rails", "USB", "5 volts") turns the simulated supply on when it
passes. The panel at the bottom left lists the simulated parts and net voltages and has USB and presence toggles;
hovering a hole shows its voltage. An empty, unpowered board has no prefilled components. The drawn power module
represents the simulated supply, and LED orientation is assumed from the resistor connection, not independently
verified. The simulation supplements the camera checks. Session resets clear the old board and colour map.

Rebuild the bundle after changing anything in `figures/parts`:

```bash
cd figures && npm ci && npm test && npm run build:ui
```

With `--fake vision` there is no camera, so the board stays empty and the chip says so; use the real camera to see it move.
