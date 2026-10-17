# Bench Buddy UI

Landing page → "Start building" → the bench: a floating chat card on the left (push-to-talk mic + text box) and the board on a green cutting mat.

```bash
python3 -m http.server 8000 -d ui      # then open http://localhost:8000
```

With no backend it runs a **built-in demo** (`js/demo.mjs`, a port of `fsm.py` + the fakes). Add `?demo` to force it.
Voice in uses the browser's speech recognition (Chrome/Safari); voice out uses the browser's speech synthesis in demo mode.

## Hooking it to `main.py` (not built yet)

The UI is driven entirely by `fsm.py` log lines, the same dicts written to `log.jsonl`. A backend only needs:

| Route | Direction | Body |
| --- | --- | --- |
| `GET /api/hello` | → UI | `{"project": {"steps": project.STEPS, "predicted": 0.99}, "browser_tts": false, "server_stt": false, "camera": true}` |
| `GET /events` (SSE) | → UI | `{"type": "log", "line": <log line>}`, `{"type": "status", "waiting": true}` / `{"speaking": true}` |
| `POST /api/input` | UI → | `{"text": "done"}` (typed or browser-transcribed) or `{"ptt": "start" \| "stop"}` when `server_stt` |
| `GET /camera.mjpg` | → UI | optional MJPEG of the phone camera with the hole grid |
| `GET /frames/...` | → UI | annotated jpgs from `CheckResult.frame`, shown in the check card |
| `GET /api/board` | → UI | live board state from vision (below) |

Log lines the UI reacts to: `said`, `heard`, `transition`, `parts`/`missing`, `check: vision` (`step`, `result`, `detail`, `rows_found`, `frame`),
`check: measure` (`detail: "predicted X Hz, measured Y Hz"`), `check: probe` (`node`, `detail`).

Files: `index.html`, `styles.css`, `js/app.mjs` (controller), `js/demo.mjs`, `js/board.mjs` (isometric board, built with
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

## 3D twin in the board pane

The bench's board pane is the breadboard twin from `figures/parts` (three.js plus a circuit solver), bundled to
`vendor/twin.bundle.mjs`. Every `board` event is turned into a layout on a full-size 63-row board by
`figures/parts/from-vision.js` and simulated, so the view shows what is really plugged in and whether the LED should be lit.
A wire with one end on the board counts as a radar lead: + rail → V, − rail → G, a row → IO, unless the user said which
colour is which at the radar step. The chip at the top right compares the simulated LED with vision's `led`. The panel
at the bottom left has the simulated parts and net voltages, plus USB and presence toggles; hovering a hole shows its voltage.
Tutor lines also feed it: the `usb` step powers the rails. In demo mode the twin follows the 555 script instead (`live.js`).
The 2D board (`js/board.mjs`) is only the fallback when WebGL is missing.

Rebuild the bundle after changing anything in `figures/parts`:

```bash
cd figures && npm install && npm test && npm run build:ui
```

`python main.py --fake --ui` plays a whole radar build through `vision.ScriptedFakeVision`, so you can try the 3D view
with no camera.

