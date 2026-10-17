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


def test_short_confirmation_is_heard():
    # Brief replies such as "yes" and "done" can be shorter than the old 0.4 s minimum.
    det = TurnDetector()
    assert len(run(det, frames(0.6, 0) + frames(0.27, 3000) + frames(1.1, 0))) == 1


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
    def mic():
        # Deliver this turn's prepared device frames after capture has been armed.
        while not v._audio.empty():
            v._capture[0].put(v._audio.get_nowait())
    v._mic = mic
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


def test_muted_gap_discards_unfinished_transcript():
    v = hands_free_voice(["I want it by the door and", "done"])
    for f in frames(0.6, 0) + frames(0.8, 3000) + frames(1.1, 0) + [None] + frames(0.8, 3000) + frames(1.1, 0):
        v._audio.put(f)
    assert v.listen() == "done"


def test_cancel_while_transcribing_discards_reply():
    import threading
    cancel = threading.Event()
    v = hands_free_voice([])
    def transcribe(audio):
        cancel.set()
        return "stale done"
    v._transcribe = transcribe
    for f in frames(0.6, 0) + frames(0.8, 3000) + frames(1.1, 0):
        v._audio.put(f)
    assert v.listen_hands_free(cancel=cancel) == ""
    assert v._capture is None


def test_cancel_silent_microphone_stops_listener():
    import threading
    v = hands_free_voice([])
    ready, cancel = threading.Event(), threading.Event()
    result = []
    worker = threading.Thread(target=lambda: result.append(v.listen_hands_free(cancel, lambda state: ready.set())), daemon=True)
    worker.start()
    assert ready.wait(1)
    cancel.set()
    worker.join(1)
    assert result == [""]
    assert v._capture is None


def test_next_turn_does_not_replay_queued_audio():
    import threading
    v = hands_free_voice(["first", "second"])
    for f in frames(0.6, 0) + frames(0.8, 3000) + frames(1.1, 0) + frames(0.8, 3000) + frames(1.1, 0):
        v._audio.put(f)
    assert v.listen() == "first"
    ready, cancel = threading.Event(), threading.Event()
    result = []
    worker = threading.Thread(target=lambda: result.append(v.listen_hands_free(cancel, lambda state: ready.set())), daemon=True)
    worker.start()
    try:
        assert ready.wait(1)
        assert worker.is_alive() and not result
        for f in frames(0.8, 3000) + frames(1.1, 0):
            v._capture[0].put(f)
        worker.join(1)
        assert result == ["second"]
    finally:
        cancel.set()
        worker.join(1)


def test_device_callback_ignores_pauses_and_own_speech(monkeypatch):
    import queue
    import threading
    from types import SimpleNamespace
    import sounddevice
    from voice import Voice
    callbacks = []
    def stream(**kwargs):
        callbacks.append(kwargs["callback"])
        return SimpleNamespace(start=lambda: None)
    monkeypatch.setattr(sounddevice, "RawInputStream", stream)
    v = Voice.__new__(Voice)
    v._mic_stream, v._capture = None, None
    v._recording, v.hands_free = False, True
    v._speaking, v._mute_until, v._gap_sent = False, 0, False
    v._mic()
    frame = frames(0.03, 3000)[0]
    callback = lambda: callbacks[0](frame, FRAME, None, None)
    callback()                                       # no active listen turn
    audio, cancel = queue.Queue(), threading.Event()
    v._capture = (audio, cancel)
    callback()
    assert audio.get_nowait() == frame
    v._speaking = True
    callback()
    callback()
    assert audio.get_nowait() is None and audio.empty()
    v._speaking, v._mute_until = False, float("inf")
    callback()                                       # speaker echo tail is also ignored
    assert audio.empty()
    v._mute_until = 0
    callback()
    assert audio.get_nowait() == frame
    cancel.set()
    callback()                                       # pause takes effect before transcription finishes
    assert audio.empty()


def test_device_can_retry_after_start_failure(monkeypatch):
    from types import SimpleNamespace
    import pytest
    import sounddevice
    from voice import Voice
    closed = []
    def fail():
        raise RuntimeError("device unavailable")
    monkeypatch.setattr(sounddevice, "RawInputStream", lambda **kw: SimpleNamespace(start=fail, close=lambda: closed.append(True)))
    v = Voice.__new__(Voice)
    v._mic_stream = None
    with pytest.raises(RuntimeError):
        v._mic()
    assert v._mic_stream is None and closed == [True]
    stream = SimpleNamespace(start=lambda: None)
    monkeypatch.setattr(sounddevice, "RawInputStream", lambda **kw: stream)
    v._mic()
    assert v._mic_stream is stream


def test_browser_wrapper_detects_audio_without_any_button_input():
    from ui_server import UI, UIVoice
    inner = hands_free_voice(["can you check the LED?"])
    for f in frames(0.6, 0) + frames(0.8, 3000) + frames(1.1, 0):
        inner._audio.put(f)
    ui = UI(voice=inner)
    voice = UIVoice(inner, ui)
    try:
        assert ui.inbox.empty()
        assert voice.listen() == "can you check the LED?"
    finally:
        voice.close()
