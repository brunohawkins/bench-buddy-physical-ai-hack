"""Stream the FSM's log.jsonl to the breadboard twin (figures/parts) as Server-Sent Events.

    python twin_feed.py                  # http://localhost:8766/events, reading ./log.jsonl
    python main.py --fake                # in another terminal: the twin follows the run

Standard library only, read-only: it tails the same log.jsonl that fsm.py appends to, so nothing in
the FSM or UI changes. A new page gets the current run (from the last "Hi, I'm Bench Buddy." line)
replayed, then every new line as it is written. Events match ui_server.py's: {"type": "log", "line": …}.
CORS is open so the twin page works when opened straight from disk.
"""
import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RUN_START = "Hi, I'm Bench Buddy."


def current_run(path: Path) -> tuple[list[dict], int]:
    """Lines of the latest run, and the byte offset to keep tailing from."""
    if not path.exists():
        return [], 0
    raw = path.read_bytes()
    lines = []
    for text in raw.decode("utf-8", "replace").splitlines():
        try:
            lines.append(json.loads(text))
        except json.JSONDecodeError:
            continue
    start = max((i for i, ln in enumerate(lines) if ln.get("said") == RUN_START), default=0)
    return lines[start:], len(raw)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--log", default="log.jsonl", help="the FSM's log file (default: ./log.jsonl)")
    p.add_argument("--port", type=int, default=8766)
    args = p.parse_args()
    log = Path(args.log)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.split("?")[0] != "/events":
                self.send_response(404)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            send = lambda ev: self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
            try:
                lines, offset = current_run(log)
                send({"type": "reset"})
                for ln in lines:
                    send({"type": "log", "line": ln, "replay": True})
                self.wfile.flush()
                buf, idle = b"", 0.0
                while True:
                    size = log.stat().st_size if log.exists() else 0
                    if size < offset:                     # file truncated or replaced: start over
                        offset, buf = 0, b""
                    if size > offset:
                        with log.open("rb") as f:
                            f.seek(offset)
                            buf += f.read()
                        offset = size
                        *done, buf = buf.split(b"\n")
                        for text in done:
                            try:
                                send({"type": "log", "line": json.loads(text)})
                            except json.JSONDecodeError:
                                pass
                        self.wfile.flush()
                        idle = 0.0
                    else:
                        time.sleep(0.1)
                        idle += 0.1
                        if idle >= 15:
                            self.wfile.write(b": ping\n\n")
                            self.wfile.flush()
                            idle = 0.0
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    print(f"twin feed on http://localhost:{args.port}/events, tailing {log.resolve()}")
    server.serve_forever()


if __name__ == "__main__":
    main()
