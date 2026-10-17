"""Background thread that keeps the newest camera frame. Owner: V.

Source is an int index (phone via Continuity Camera / Iriun, webcam) or a URL (Jetson stream).
Run `python camera.py [source]` for a live preview; press q to quit.
"""
import sys
import threading
import time


def parse_source(s: str):
    return int(s) if s.isdigit() else s


class Camera:
    def __init__(self, source=0):
        import cv2
        self._cap = cv2.VideoCapture(source)
        if not self._cap.isOpened():
            raise RuntimeError(f"can't open camera {source!r}")
        self._frame = None
        self._lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            ok, frame = self._cap.read()
            if ok:
                with self._lock:
                    self._frame = frame
            else:
                time.sleep(0.05)

    def latest(self):
        """Newest BGR frame, or None before the first one arrives."""
        with self._lock:
            return None if self._frame is None else self._frame.copy()


if __name__ == "__main__":
    import cv2
    cam = Camera(parse_source(sys.argv[1] if len(sys.argv) > 1 else "0"))
    while cv2.waitKey(30) & 0xFF != ord("q"):
        frame = cam.latest()
        if frame is not None:
            cv2.imshow("camera", frame)
