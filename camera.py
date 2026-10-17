"""Background thread that keeps the newest camera frame. Owner: V.

Source is an int index or a stream URL. On a Mac, an iPhone (Continuity Camera) shows up as an
extra index, and the order can change when it connects. Find it with the preview, then set
CAMERA_SOURCE in .env so every tool uses it:

    python camera.py 1        # q quits; no argument = CAMERA_SOURCE
"""
import os
import sys
import threading
import time


def parse_source(s: str):
    return int(s) if s.isdigit() else s


def default_source():
    """CAMERA_SOURCE from .env or the environment, else 0. Indices shift when an iPhone connects."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    return parse_source(os.environ.get("CAMERA_SOURCE", "0"))


class Camera:
    def __init__(self, source=0, width: int | None = None, height: int | None = None):
        import cv2
        width = width or int(os.environ.get("CAMERA_WIDTH", "3840"))
        height = height or int(os.environ.get("CAMERA_HEIGHT", "2160"))
        if isinstance(source, int) and sys.platform == "darwin":
            self._cap = cv2.VideoCapture(source, cv2.CAP_AVFOUNDATION)
        else:
            self._cap = cv2.VideoCapture(source)
        if not self._cap.isOpened():
            raise RuntimeError(f"can't open camera {source!r} (on macOS, check Camera permission for your terminal/editor)")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        actual = (int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        print(f"[camera] requested {width}x{height}; device reports {actual[0]}x{actual[1]}")
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
    cam = Camera(parse_source(sys.argv[1]) if len(sys.argv) > 1 else default_source())
    while cv2.waitKey(30) & 0xFF != ord("q"):
        frame = cam.latest()
        if frame is not None:
            cv2.imshow("camera", frame)
