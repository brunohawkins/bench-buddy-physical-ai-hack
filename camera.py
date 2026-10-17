"""Background thread that keeps the newest camera frame. Owner: V.

Source is an int index or a stream URL. On a Mac, an iPhone (Continuity Camera) shows up as an
extra index next to the built-in camera. Try 0, 1, 2 with the preview:

    python camera.py 1        # q quits
"""
import sys
import threading
import time


def parse_source(s: str):
    return int(s) if s.isdigit() else s


class Camera:
    def __init__(self, source=0, width: int = 1920, height: int = 1080):
        import cv2
        if isinstance(source, int) and sys.platform == "darwin":
            self._cap = cv2.VideoCapture(source, cv2.CAP_AVFOUNDATION)
        else:
            self._cap = cv2.VideoCapture(source)
        if not self._cap.isOpened():
            raise RuntimeError(f"can't open camera {source!r} (on macOS, check Camera permission for your terminal/editor)")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self._frame = None
        self.frame_id = 0                # increments on every new frame
        self._lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            ok, frame = self._cap.read()
            if ok:
                with self._lock:
                    self._frame = frame
                    self.frame_id += 1
            else:
                time.sleep(0.05)

    def latest(self):
        """Newest BGR frame, or None before the first one arrives."""
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def latest_with_id(self):
        with self._lock:
            return self.frame_id, None if self._frame is None else self._frame.copy()


if __name__ == "__main__":
    import cv2
    cam = Camera(parse_source(sys.argv[1] if len(sys.argv) > 1 else "0"))
    while cv2.waitKey(30) & 0xFF != ord("q"):
        frame = cam.latest()
        if frame is not None:
            cv2.imshow("camera", frame)
