"""Keep test artifacts out of the live camera session's frames directory."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def isolated_frames(tmp_path, monkeypatch):
    import vision
    monkeypatch.setattr(vision, "FRAMES_DIR", tmp_path)
