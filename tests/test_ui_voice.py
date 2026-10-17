"""Browser voice integration: automatic turns, typed input, pause and manual fallback."""
import queue
import threading

from ui_server import UI, UIVoice


class ControlledVoice:
    hands_free = True

    def __init__(self):
        self.calls = queue.Queue()
        self.active = 0
        self.max_active = 0

    def listen_hands_free(self, cancel, on_state):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        reply = queue.Queue()
        self.calls.put((cancel, reply))
        on_state("listening")
        try:
            result = reply.get(timeout=3)  # simulate even an STT request that finishes after cancellation
            if isinstance(result, Exception):
                raise result
            return result
        finally:
            self.active -= 1

    def record_start(self):
        raise AssertionError("automatic mode must not start a manual recording")

    def record_stop(self):
        raise AssertionError("automatic mode must not stop a manual recording")


def listening(voice):
    result = queue.Queue()
    worker = threading.Thread(target=lambda: result.put(voice.listen()), daemon=True)
    worker.start()
    return result, worker


def test_automatic_speech_rearms_without_ptt():
    inner = ControlledVoice()
    ui = UI(voice=inner)
    voice = UIVoice(inner, ui)
    try:
        assert ui.hello["hands_free"]
        for text in ("hi", "can you see the LED?"):
            result, worker = listening(voice)
            cancel, reply = inner.calls.get(timeout=1)
            reply.put(text)
            assert result.get(timeout=1) == text
            worker.join(1)
            assert cancel.is_set()
        assert inner.max_active == 1
    finally:
        voice.close()


def test_typed_input_wins_and_late_transcript_is_discarded():
    inner = ControlledVoice()
    ui = UI(voice=inner)
    voice = UIVoice(inner, ui)
    try:
        result, worker = listening(voice)
        cancel, old_reply = inner.calls.get(timeout=1)
        ui.submit({"text": "typed answer"})
        assert result.get(timeout=1) == "typed answer"
        worker.join(1)
        assert cancel.is_set()
        result, worker = listening(voice)
        old_reply.put("stale spoken answer")
        cancel, reply = inner.calls.get(timeout=1)
        reply.put("fresh spoken answer")
        assert result.get(timeout=1) == "fresh spoken answer"
        worker.join(1)
        assert inner.max_active == 1
    finally:
        voice.close()


def test_pause_resume_discards_in_flight_speech():
    inner = ControlledVoice()
    ui = UI(voice=inner)
    voice = UIVoice(inner, ui)
    try:
        result, worker = listening(voice)
        cancel, old_reply = inner.calls.get(timeout=1)
        ui.submit({"mic": "pause"})
        assert cancel.is_set() and ui._status["mic_paused"]
        ui.submit({"mic": "resume"})
        old_reply.put("discard me")
        _, reply = inner.calls.get(timeout=1)
        reply.put("after resume")
        assert result.get(timeout=1) == "after resume"
        worker.join(1)
        assert inner.max_active == 1
    finally:
        voice.close()


def test_pause_while_tutor_busy_persists_and_typing_still_works():
    inner = ControlledVoice()
    ui = UI(voice=inner)
    voice = UIVoice(inner, ui)
    try:
        ui.submit({"mic": "pause"})
        result, worker = listening(voice)
        ui.submit({"text": "still works"})
        assert result.get(timeout=1) == "still works"
        worker.join(1)
        assert inner.calls.empty() and ui._status["mic_paused"]
    finally:
        voice.close()


def test_microphone_failure_is_visible_and_can_retry():
    inner = ControlledVoice()
    ui = UI(voice=inner)
    voice = UIVoice(inner, ui)
    events = ui._subscribe(None)
    try:
        result, worker = listening(voice)
        _, reply = inner.calls.get(timeout=1)
        reply.put(RuntimeError("device unavailable"))
        while True:
            _, ev = events.get(timeout=1)
            if ev.get("mic_state") == "error":
                break
        assert ev["mic_paused"] and "You can still type" in ev["mic_error"]
        ui.submit({"mic": "resume"})
        _, reply = inner.calls.get(timeout=1)
        reply.put("retried")
        assert result.get(timeout=1) == "retried"
        worker.join(1)
    finally:
        voice.close()


def test_space_does_not_duplicate_automatic_recording():
    inner = ControlledVoice()
    ui = UI(voice=inner)
    voice = UIVoice(inner, ui)
    try:
        result, worker = listening(voice)
        _, reply = inner.calls.get(timeout=1)
        ui.submit({"ptt": "start"})
        ui.submit({"ptt": "stop"})
        reply.put("done")
        assert result.get(timeout=1) == "done"
        worker.join(1)
    finally:
        voice.close()


def test_manual_ptt_and_fake_voice_still_work():
    class ManualVoice:
        hands_free = False
        def record_start(self):
            self.started = True
        def record_stop(self):
            assert self.started
            return "manual speech"
    for inner, messages, expected in (
        (ManualVoice(), [{"ptt": "start"}, {"ptt": "stop"}], "manual speech"),
        (object(), [{"text": "fake typed"}], "fake typed"),
    ):
        ui = UI(voice=inner)
        voice = UIVoice(inner, ui)
        assert not ui.hello["hands_free"]
        for msg in messages:
            ui.submit(msg)
        assert voice.listen() == expected


def test_invalid_browser_messages_cannot_crash_listener():
    ui = UI()
    for msg in ([], None, {"text": 123}, {"mic": "invalid"}):
        assert not ui.submit(msg)
    assert ui.inbox.empty()
    ui.submit({"text": "hello", "_voice_cancel": None})
    assert ui.inbox.get_nowait() == {"text": "hello"}


def test_reconnect_restores_current_mic_status():
    ui = UI()
    ui.emit({"type": "log", "line": {"heard": "hello"}})
    ui.emit({"type": "status", "hands_free": True, "mic_paused": True, "waiting": True})
    events = ui._subscribe(f"{ui.session}-0")
    _, ev = events.get_nowait()
    assert ev == {"type": "status", "hands_free": True, "mic_paused": True, "waiting": True}
    assert events.empty()
