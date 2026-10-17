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

Log lines the UI reacts to: `said`, `heard`, `transition`, `parts`/`missing`, `check: vision` (`step`, `result`, `detail`, `rows_found`, `frame`),
`check: measure` (`detail: "predicted X Hz, measured Y Hz"`), `check: probe` (`node`, `detail`).

Files: `index.html`, `styles.css`, `js/app.mjs` (controller), `js/demo.mjs`, `js/board.mjs` (isometric board, built with
[anatomy](https://github.com/wheresryan22/anatomy)'s kit in `vendor/`, MIT), `js/mat.mjs` (mat rulers).
