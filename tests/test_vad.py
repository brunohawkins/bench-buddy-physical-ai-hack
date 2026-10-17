"""Hands-free turn detection on generated audio: no mic needed.

    .venv/bin/python -m pytest tests/
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from voice import FRAME, TurnDetector  # noqa: E402

RNG = np.random.default_rng(0)


def frames(seconds: float, amplitude: float) -> list[bytes]:
    """30 ms int16 frames: background noise, plus a 300 Hz tone when amplitude > 0."""
    n = round(seconds * 1000 / 30)
    t = np.arange(FRAME) / 16000
    out = []
    for _ in range(n):
        x = RNG.normal(0, 40, FRAME) + amplitude * np.sin(2 * np.pi * 300 * t)
        out.append(x.astype(np.int16).tobytes())
    return out


def run(det: TurnDetector, chunks: list[bytes]) -> list[bytes]:
    return [u for u in (det.feed(f) for f in chunks) if u is not None]


def test_one_utterance_with_preroll():
    det = TurnDetector()
    got = run(det, frames(0.6, 0) + frames(1.0, 3000) + frames(1.0, 0))
    assert len(got) == 1
    seconds = len(got[0]) / 2 / 16000
    assert 1.0 + 0.2 <= seconds <= 1.0 + 0.3 + 0.7 + 0.1     # speech + some pre-roll + the closing silence


def test_short_blip_is_dropped():
    det = TurnDetector()
    assert run(det, frames(0.6, 0) + frames(0.15, 3000) + frames(1.0, 0)) == []


def test_two_utterances():
    det = TurnDetector()
    got = run(det, frames(0.6, 0) + frames(0.8, 3000) + frames(1.0, 0) + frames(0.8, 3000) + frames(1.0, 0))
    assert len(got) == 2


def test_reset_drops_half_heard_speech():
    det = TurnDetector()
    run(det, frames(0.6, 0) + frames(0.5, 3000))
    det.reset()                                           # e.g. Bench Buddy started speaking
    assert run(det, frames(1.0, 0)) == []


def test_quiet_room_never_triggers():
    det = TurnDetector()
    assert run(det, frames(5.0, 0)) == []


def test_unfinished():
    from voice import unfinished
    assert unfinished("It can be...") and unfinished("I want it by the door and") and unfinished("um")
    assert not unfinished("I plugged it in") and not unfinished("done") and not unfinished("what does TX do?")


def hands_free_voice(transcripts):
    """A Voice with no mic or API: frames come from a queue, transcription returns `transcripts` in order."""
    import queue
    import voice
    v = voice.Voice.__new__(voice.Voice)
    v._audio, v._detector, v._mic_stream = queue.Queue(), TurnDetector(), object()
    v.hands_free, v.last_stt_ms = True, None
    said = iter(transcripts)
    v._transcribe = lambda audio: next(said)
    return v


def test_pause_mid_sentence_is_joined():
    v = hands_free_voice(["It can be...", "by my front door, for when people walk up."])
    for f in frames(0.6, 0) + frames(0.8, 3000) + frames(1.5, 0) + frames(1.0, 3000) + frames(1.5, 0):
        v._audio.put(f)
    assert v.listen() == "It can be... by my front door, for when people walk up."


def test_unfinished_then_silence_returns_what_was_said():
    v = hands_free_voice(["I want it by the door and"])
    for f in frames(0.6, 0) + frames(0.8, 3000) + frames(5.0, 0):
        v._audio.put(f)
    assert v.listen() == "I want it by the door and"
