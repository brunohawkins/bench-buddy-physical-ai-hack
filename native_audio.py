"""Small subprocess bridge to macOS voice-processing I/O (AEC, 16 kHz mic, 22.05 kHz TTS)."""
import atexit
import base64
import hashlib
import json
import os
import subprocess
import threading
import time
from pathlib import Path


def build_helper():
    source = Path(__file__).parent / "native" / "voice_io.swift"
    cache = Path(__file__).parent / ".audio-cache"
    cache.mkdir(exist_ok=True)
    executable = cache / ("voice-io-" + hashlib.sha256(source.read_bytes()).hexdigest()[:16])
    if not executable.exists():
        subprocess.run(["xcrun", "swiftc", "-O", "-module-cache-path", str(cache / "modules"),
                        str(source), "-o", str(executable)], check=True, capture_output=True, timeout=90)
    return executable


class MacAudio:
    def __init__(self, callback):
        self.callback = callback
        self._lock = threading.RLock()
        self._cv = threading.Condition(self._lock)
        self._ready = threading.Event()
        self._pending = set()
        self._serial = 0
        self._error = None
        self._closed = False
        self.process = subprocess.Popen([str(build_helper())], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=None if os.environ.get("VOICE_DEBUG") else subprocess.DEVNULL,
                                        text=True, bufsize=1)
        threading.Thread(target=self._read, daemon=True, name="mac-audio").start()
        atexit.register(self.close)
        if not self._ready.wait(12) or self._error:
            self.close()
            raise RuntimeError(self._error or "Microphone did not start; check macOS microphone permission")

    def _read(self):
        carry = b""
        try:
            for line in self.process.stdout:
                message = json.loads(line)
                if "error" in message:
                    raise RuntimeError(message["error"])
                if message.get("ready"):
                    if not message.get("echo_cancellation"):
                        raise RuntimeError("Voice processing is unavailable")
                    self._ready.set()
                if "mic" in message:
                    carry += base64.b64decode(message["mic"])
                    while len(carry) >= 960:
                        self.callback(carry[:960], 480, None, None)
                        carry = carry[960:]
                if "played" in message:
                    with self._cv:
                        self._pending.discard(message["played"])
                        self._cv.notify_all()
        except Exception as exc:
            self._error = str(exc)
        finally:
            with self._cv:
                if not self._closed:
                    self._error = self._error or "Audio device disconnected"
                self._ready.set()
                self._cv.notify_all()

    def check(self):
        if self._error or self._closed:
            raise RuntimeError(self._error or "Audio device closed")

    def _send(self, message):
        with self._lock:
            self.check()
            self.process.stdin.write(json.dumps(message) + "\n")
            self.process.stdin.flush()

    def write(self, pcm, cancel):
        # At most 120 ms scheduled ahead. A stopped phrase can never refill the queue.
        with self._cv:
            deadline = time.monotonic() + 5
            while len(self._pending) >= 4 and not cancel.is_set():
                self.check()
                if time.monotonic() >= deadline:
                    raise TimeoutError("Audio playback stalled")
                self._cv.wait(.03)
            if cancel.is_set():
                return
            self._serial += 1
            self._pending.add(self._serial)
            self._send({"op": "play", "id": self._serial, "pcm": base64.b64encode(pcm).decode()})

    def drain(self, cancel):
        with self._cv:
            deadline = time.monotonic() + 5
            while self._pending and not cancel.is_set():
                self.check()
                if time.monotonic() >= deadline:
                    raise TimeoutError("Audio playback stalled")
                self._cv.wait(.03)

    def abort(self):
        with self._cv:
            if not self._closed and not self._error:
                self._send({"op": "stop"})
            self._pending.clear()
            self._cv.notify_all()

    def close(self):
        with self._cv:
            if self._closed:
                return
            self._closed = True
            self._cv.notify_all()
        self.process.terminate()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)
