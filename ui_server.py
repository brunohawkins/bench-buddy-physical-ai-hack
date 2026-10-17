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
            "camera": hasattr(vision, "camera") and hasattr(vision, "board"),
            "session": self.session,
        }

    # --- events ------------------------------------------------------------------

    def emit(self, event: dict) -> None:
        with self._lock:
            if event.get("type") == "status":
                self._status.update({k: v for k, v in event.items() if k != "type"})
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
                if self._status:
                    q.put((len(self._history) - 1, {"type": "status", **self._status}))
            self._clients.append(q)
        return q

    def _unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)

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
                    ui.inbox.put(json.loads(body or b"{}"))
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
    """Wraps the real or fake voice: input comes from the page, replies go to the page and to the inner voice."""

    def __init__(self, inner, ui: UI):
        self.inner, self.ui = inner, ui

    def listen(self) -> str:
        self.ui.emit({"type": "status", "waiting": True})
        try:
            while True:
                msg = self.ui.inbox.get()
                if msg.get("text", "").strip():
                    return msg["text"].strip()
                if msg.get("ptt") == "start" and hasattr(self.inner, "record_start"):
                    self.inner.record_start()
                elif msg.get("ptt") == "stop" and hasattr(self.inner, "record_stop"):
                    text = self.inner.record_stop()        # -> transcript; BenchBuddy logs it as `heard`
                    if text:
                        return text
        finally:
            self.ui.emit({"type": "status", "waiting": False})

    def say(self, text: str) -> None:
        self.ui.emit({"type": "status", "speaking": True})
        try:
            self.inner.say(text)
        finally:
            self.ui.emit({"type": "status", "speaking": False})

    def warm_cache(self, phrases: list[str]) -> None:
        self.inner.warm_cache(phrases)
