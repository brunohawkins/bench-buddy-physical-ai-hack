"""Browser UI for the state machine: serves ui/, streams fsm log lines to the page and takes its input.

    python main.py --fake --ui            # then open http://localhost:8000

Standard library only. The page gets every log line BenchBuddy writes (Server-Sent Events on /events)
and sends typed or browser-transcribed text back (POST /api/input), which UIVoice.listen() returns.
See ui/README.md for the event shapes.
"""
import json
import queue
import threading
import time
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import project
from physics import predict

ROOT = Path(__file__).parent
UI_DIR = ROOT / "ui"


class UI:
    def __init__(self, port: int = 8000, vision=None, voice=None):
        self.port = port
        self.vision = vision
        self.inbox: queue.Queue[dict] = queue.Queue()
        self.mic_control = None
        self.session = uuid.uuid4().hex[:8]       # lets a page notice the server restarted
        self._history: list[tuple[int, dict]] = []
        self._clients: list[queue.Queue] = []
        self._status: dict = {}
        self._lock = threading.Lock()
        f, duty = predict(project.R1, project.R2, project.C)
        # FakeVoice without --speak is silent, so let the browser read replies aloud instead.
        silent = type(voice).__name__ == "FakeVoice" and not getattr(voice, "speak", False)
        self.hello = {
            "project": {"name": "555 blinker", "steps": project.STEPS, "predicted": f, "duty": duty},
            "browser_tts": silent,
            "server_stt": hasattr(voice, "record_start") and hasattr(voice, "record_stop"),
            "hands_free": bool(getattr(voice, "hands_free", False)),
            "barge_in": bool(getattr(voice, "barge_in", False)),
            "camera": hasattr(vision, "camera") and hasattr(vision, "board"),
            "session": self.session,
        }
        self._board: dict | None = None
        if hasattr(vision, "listeners"):            # live board state from vision: parts, LED, narration
            vision.listeners.append(lambda st: self.emit({"type": "board", **st}))

    # --- events ------------------------------------------------------------------

    def emit(self, event: dict) -> None:
        with self._lock:
            if event.get("type") == "status":
                self._status.update({k: v for k, v in event.items() if k != "type"})
            elif event.get("type") == "board":          # latest only, not history
                self._board = event
            else:
                self._history.append((len(self._history), event))
            n = len(self._history) - 1
            for q in self._clients:
                q.put((n, event))

    def _subscribe(self, last_event_id: str | None) -> queue.Queue:
        """New client queue, pre-filled with whatever that page hasn't seen yet."""
        q: queue.Queue = queue.Queue()
        session, _, last = (last_event_id or "").partition("-")
        with self._lock:
            if session == self.session and last.isdigit():
                for n, ev in self._history[int(last) + 1:]:
                    q.put((n, ev))
            else:
                # Fresh page or restarted server: wipe the page, then replay without speaking.
                q.put((-1, {"type": "reset"}))
                for n, ev in self._history:
                    q.put((n, {**ev, "replay": True}))
                if self._board:
                    q.put((len(self._history) - 1, self._board))
            if self._status:
                q.put((len(self._history) - 1, {"type": "status", **self._status}))
            self._clients.append(q)
        return q

    def _unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)

    def submit(self, message) -> bool:
        """Mic pause takes effect even while the tutor is thinking or speaking."""
        if not isinstance(message, dict) or not isinstance(message.get("text", ""), str):
            return False
        if "mic" in message:
            if message["mic"] not in ("pause", "resume"):
                return False
            if self.mic_control:
                self.mic_control(message["mic"] == "resume")
        else:
            if message.get("text", "").strip() or message.get("ptt") == "start":
                interrupt = getattr(self, "interrupt", None)
                if interrupt:
                    interrupt()
            self.inbox.put({k: v for k, v in message.items() if k in ("text", "ptt")})
        return True

    def attach(self, buddy) -> None:
        """Mirror every BenchBuddy.log() line to the page."""
        original = buddy.log

        def log(**fields):
            original(**fields)
            self.emit({"type": "log", "line": {"t": time.strftime("%H:%M:%S"), "state": buddy.state, **fields}})

        buddy.log = log

    # --- server ------------------------------------------------------------------

    def start(self, open_browser: bool = True) -> None:
        ui = self

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(UI_DIR), **kwargs)

            def log_message(self, *args):
                pass

            def translate_path(self, path):
                if path.startswith("/frames/"):           # annotated check frames saved by vision.py
                    return str(ROOT / "frames" / Path(path.split("?")[0]).name)
                return super().translate_path(path)

            def end_headers(self):
                self.send_header("Cache-Control", "no-store")
                super().end_headers()

            def do_GET(self):
                if self.path == "/api/hello":
                    return self._json(ui.hello)
                if self.path == "/api/board":              # vision's board state, see Vision.state()
                    st = ui.vision.state() if hasattr(ui.vision, "state") else {}
                    return self._json(st)
                if self.path == "/events":
                    return self._events()
                if self.path.startswith("/camera.mjpg"):
                    return self._camera()
                return super().do_GET()

            def do_POST(self):
                if self.path != "/api/input":
                    return self.send_error(404)
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
                try:
                    if not ui.submit(json.loads(body or b"{}")):
                        return self.send_error(400)
                except json.JSONDecodeError:
                    return self.send_error(400)
                self.send_response(204)
                self.end_headers()

            def _json(self, data):
                raw = json.dumps(data, default=str).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _events(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                q = ui._subscribe(self.headers.get("Last-Event-ID"))
                try:
                    while True:
                        try:
                            n, ev = q.get(timeout=15)
                            self.wfile.write(f"id: {ui.session}-{n}\ndata: {json.dumps(ev, default=str)}\n\n".encode())
                        except queue.Empty:
                            self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
                finally:
                    ui._unsubscribe(q)

            def _camera(self):
                """MJPEG of the phone camera with the calibrated hole grid, ~10 fps."""
                import cv2
                vision = ui.vision
                if not ui.hello["camera"]:
                    return self.send_error(404)
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()
                try:
                    while True:
                        # vision.view(): camera + grid, flat board with detected plugs/wires, status line
                        frame = vision.view() if hasattr(vision, "view") else None
                        if frame is None:
                            frame = vision.camera.latest()
                            if frame is not None:
                                vision.board.draw_on_camera(frame, getattr(vision, "expect_rows", ()))
                        if frame is not None:
                            frame = cv2.resize(frame, (960, int(frame.shape[0] * 960 / frame.shape[1])))
                            ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                            if ok:
                                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n")
                                self.wfile.flush()
                        time.sleep(0.1)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

        server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://localhost:{self.port}"
        print(f"UI on {url}")
        if open_browser:
            import webbrowser
            webbrowser.open(url)


class UIVoice:
    """Race automatic speech with page input; a single worker owns the microphone detector."""

    def __init__(self, inner, ui: UI):
        self.inner, self.ui = inner, ui
        self.hands_free = bool(getattr(inner, "hands_free", False))
        self._lock = threading.RLock()
        self._waiting, self._paused = False, False
        self._cancel = None
        self._requests: queue.Queue = queue.Queue()
        self.ui.mic_control = self.set_mic_enabled
        self.ui.interrupt = self.interrupt
        if self.hands_free:
            threading.Thread(target=self._speech_worker, daemon=True, name="ui-speech").start()

    def _begin_listening(self) -> None:
        """Called under _lock. Supersede any in-flight transcription without blocking typed input."""
        if self._cancel:
            self._cancel.set()
        if self.hands_free and self._waiting and not self._paused:
            self._cancel = threading.Event()
            self._requests.put(self._cancel)
            self.ui.emit({"type": "status", "mic_state": "starting", "mic_error": ""})

    def set_mic_enabled(self, enabled: bool) -> None:
        with self._lock:
            if not self.hands_free:
                return
            self._paused = not enabled
            self.ui.emit({"type": "status", "mic_paused": self._paused,
                          "mic_state": "idle" if enabled else "paused", "mic_error": ""})
            self._begin_listening()

    def _speech_worker(self) -> None:
        while True:
            cancel = self._requests.get()
            if cancel is None:
                return
            if cancel.is_set():
                continue

            def status(state):
                with self._lock:
                    if self._cancel is cancel and not cancel.is_set():
                        self.ui.emit({"type": "status", "mic_state": state})

            try:
                text = self.inner.listen_hands_free(cancel=cancel, on_state=status)
            except Exception as exc:
                print(f"[voice] microphone unavailable ({exc!r})")
                with self._lock:
                    if self._cancel is cancel and not cancel.is_set():
                        self._paused = True
                        cancel.set()
                        self.ui.emit({"type": "status", "mic_paused": True, "mic_state": "error",
                                      "mic_error": "Microphone unavailable. Check microphone permission or device, "
                                                   "then tap the mic to retry. You can still type."})
                continue
            with self._lock:
                if self._cancel is cancel and not cancel.is_set():
                    self.ui.inbox.put({"text": text, "_voice_cancel": cancel})

    def close(self) -> None:
        with self._lock:
            if self._cancel:
                self._cancel.set()
            self._requests.put(None)
        close = getattr(self.inner, "close", None)
        if close:
            close()

    @property
    def on_speech_start(self):
        return getattr(self.inner, "on_speech_start", None)

    @on_speech_start.setter
    def on_speech_start(self, callback):
        self.inner.on_speech_start = callback

    def interrupt(self):
        stop = getattr(self.inner, "interrupt", None)
        if stop:
            stop()
        callback = self.on_speech_start
        if callback:
            callback()

    def listen(self) -> str:
        with self._lock:
            self._waiting = True
            self.ui.emit({"type": "status", "waiting": True, "hands_free": self.hands_free,
                          "mic_paused": self._paused})
            self._begin_listening()
        try:
            while True:
                msg = self.ui.inbox.get()
                if "_voice_cancel" in msg:
                    with self._lock:
                        cancel = msg["_voice_cancel"]
                        if cancel is not self._cancel or cancel.is_set():
                            continue
                    return msg["text"].strip()
                if msg.get("text", "").strip():
                    return msg["text"].strip()
                if self.hands_free:                 # Space cannot start a second recording in automatic mode
                    continue
                if msg.get("ptt") == "start" and hasattr(self.inner, "record_start"):
                    self.inner.record_start()
                elif msg.get("ptt") == "stop" and hasattr(self.inner, "record_stop"):
                    text = self.inner.record_stop()        # -> transcript; BenchBuddy logs it as `heard`
                    if text:
                        return text
        finally:
            with self._lock:
                self._waiting = False
                if self._cancel:
                    self._cancel.set()
                self.ui.emit({"type": "status", "waiting": False,
                              "mic_state": "paused" if self._paused else "idle"})

    def say(self, text: str) -> None:
        self.ui.emit({"type": "status", "speaking": True})
        try:
            return self.inner.say(text)
        finally:
            self.ui.emit({"type": "status", "speaking": False})

    def warm_cache(self, phrases: list[str]) -> None:
        self.inner.warm_cache(phrases)
