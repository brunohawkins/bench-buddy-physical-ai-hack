"""Keep test artifacts out of the live camera session's frames and conversation log."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def isolated_frames(tmp_path, monkeypatch):
    import vision
    import tutor
    import fsm
    monkeypatch.setattr(vision, "FRAMES_DIR", tmp_path)
    monkeypatch.setattr(tutor, "LOG_PATH", tmp_path / "tutor.jsonl")
    monkeypatch.setattr(fsm, "LOG_PATH", tmp_path / "fsm.jsonl")
