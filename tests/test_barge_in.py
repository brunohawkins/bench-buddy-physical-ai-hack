"""Interruption contracts: audio stops before STT, cached/streamed output cancels, no stale advance."""
import queue
import threading
import time
from types import SimpleNamespace

import pytest

from voice import Voice
from test_vad import frames, hands_free_voice


def playback_voice(tmp_path):
    voice = Voice.__new__(Voice)
    voice._play_cancel = threading.Event()
    voice._aec_requested = False
    voice._audio_io = None
    voice._fallback_process = None
    voice._cache_path = lambda text: tmp_path / "phrase.pcm"
    return voice


def test_speech_stops_output_before_transcription_and_preserves_beginning():
    voice = hands_free_voice([])
    voice._play_cancel = threading.Event()
    started = []
    voice.on_speech_start = lambda: started.append(True)
    def transcribe(audio):
        assert voice._play_cancel.is_set() and started == [True]
        assert len(audio) > 16000 * 2 * .8  # includes the first spoken frames, not only audio after stopping TTS
        return "stop, that's the wrong hole"
    voice._transcribe = transcribe
    for frame in frames(.6, 0) + frames(.8, 3000) + frames(1.1, 0):
        voice._audio.put(frame)
    assert voice.listen() == "stop, that's the wrong hole"


def test_blip_does_not_interrupt():
    voice = hands_free_voice([])
    started = []
    voice.on_speech_start = lambda: started.append(True)
    cancel = threading.Event()
    for frame in frames(.6, 0) + frames(.15, 3000) + frames(1.1, 0):
        voice._audio.put(frame)
    thread = threading.Thread(target=lambda: voice.listen_hands_free(cancel), daemon=True)
    thread.start()
    time.sleep(.05)
    cancel.set()
    thread.join(1)
    assert not started


@pytest.mark.parametrize("cached", [True, False])
def test_cached_and_streamed_audio_abort_without_caching_a_fragment(tmp_path, monkeypatch, cached):
    import sounddevice
    voice = playback_voice(tmp_path)
    pcm = bytes(22050 * 2 * 3)
    path = voice._cache_path("long phrase")
    if cached:
        path.write_bytes(pcm)
    else:
        voice._synth = lambda text: iter([pcm])
    writes, operations = [], []
    def write(data):
        writes.append(data)
        voice.interrupt()
    monkeypatch.setattr(sounddevice, "RawOutputStream", lambda **kw: SimpleNamespace(
        start=lambda: None, write=write, abort=lambda: operations.append("abort"),
        stop=lambda: operations.append("drain"), close=lambda: operations.append("close")))
    assert voice.say("long phrase") is False
    assert len(writes) == 1 and len(writes[0]) <= 1320
    assert operations == ["abort", "close"]
    assert path.read_bytes() == pcm if cached else not path.exists()


def test_network_wait_does_not_block_interrupt(tmp_path):
    voice = playback_voice(tmp_path)
    fetching, release = threading.Event(), threading.Event()
    def chunks(text):
        fetching.set()
        release.wait(2)
        yield bytes(100)
    voice._synth = chunks
    result = []
    thread = threading.Thread(target=lambda: result.append(voice.say("slow network")), daemon=True)
    thread.start()
    assert fetching.wait(1)
    voice.interrupt()
    thread.join(.3)
    release.set()
    assert result == [False]


def test_interruption_prevents_follow_on_speech_and_step_advance():
    import tutor
    from test_tutor import StubVoice, StubBrain
    from vision import FakeVision, CheckResult
    voice = StubVoice()
    buddy = tutor.Tutor(FakeVision(), voice, StubBrain())
    buddy.state = "STEP"
    buddy.steps = [{"id": "led", "say": "LED in rows 35 and 36", "check": {"kind": "look"}}]
    def verify(step):
        voice.on_speech_start()
        return CheckResult("pass", "The LED looks correct")
    buddy.vision.verify = verify
    buddy.check()
    assert buddy.state == "STEP" and buddy.step_i == 0
    assert buddy.say("Now plug in USB") is False and voice.said == []


def test_speech_feed_listens_during_tutor_reply():
    import tutor
    from test_tutor import StubBrain
    from vision import FakeVision
    ready = threading.Event()
    voice = SimpleNamespace(hands_free=True, listen=lambda: (ready.set(), "interrupt")[1])
    buddy = tutor.Tutor(FakeVision(), voice, StubBrain())
    # Stop after one capture, without relying on the turn-finished event to permit the first one.
    def listen():
        ready.set()
        voice.listen = lambda: (_ for _ in ()).throw(EOFError())
        return "interrupt"
    voice.listen = listen
    thread = threading.Thread(target=buddy._speech_feed, daemon=True)
    thread.start()
    assert ready.wait(1)
    thread.join(1)
    assert buddy.events.get_nowait() == {"type": "speech", "text": "interrupt"}
    assert buddy.events.get_nowait() == {"type": "eof"}


def test_empty_transcript_releases_ui_turn_after_interrupt():
    from ui_server import UI, UIVoice
    from test_ui_voice import ControlledVoice, listening
    inner = ControlledVoice()
    voice = UIVoice(inner, UI(voice=inner))
    try:
        result, worker = listening(voice)
        _, reply = inner.calls.get(timeout=1)
        reply.put("")
        assert result.get(timeout=1) == ""
        worker.join(1)
    finally:
        voice.close()
