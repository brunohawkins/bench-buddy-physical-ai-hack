"""Hands-free (or push-to-talk) speech-to-text and text-to-speech. Owner: L.

Hands-free: the mic stays open and TurnDetector finds where an utterance starts and ends from loudness against
the room's noise floor. The mic is ignored while Bench Buddy is speaking, so it doesn't hear itself.

TTS is tuned for latency: ElevenLabs Flash streams raw PCM, which plays chunk by chunk as it arrives and is
cached on disk at the same time. Cached phrases play straight from PCM with no decoding.
"""
import hashlib
import io
import os
import queue
import subprocess
import time
import wave
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

SAMPLE_RATE = 22050                      # matches output_format below; 16-bit mono
OUTPUT_FORMAT = f"pcm_{SAMPLE_RATE}"
DEFAULT_VOICE = "JBFqnCBsd6RMkjVDRZzb"   # ElevenLabs premade "George"; override with ELEVENLABS_VOICE_ID
DEFAULT_MODEL = "eleven_flash_v2_5"      # lowest-latency ElevenLabs model

MIC_RATE = 16000
MIN_CLIP_BYTES = MIC_RATE * 2 * 3 // 10  # 0.3 s of 16-bit audio; shorter is a mis-press
DEFAULT_STT_MODEL = "gpt-4o-mini-transcribe"
STT_PROMPT = ("Electronics bench talk. LD2402 radar module, breadboard, jumper wires, 555 timer, NE555, resistor, "
              "capacitor, LED, long leg, short leg, ohm, kilohm, 1k, 10k, 68k, 330 ohm, microfarad, nanofarad, "
              "5 volt rail, ground rail, done, it's not working.")
FRAME = MIC_RATE * 30 // 1000            # 30 ms mic blocks for turn detection
CONTINUE_FOR = 4.0                       # after an unfinished-sounding utterance, wait this long for the rest
# An utterance ending like this was probably a pause mid-thought, not the end of the sentence.
TRAILING = ("and", "so", "but", "or", "um", "uh", "er", "erm", "because", "the", "a", "an", "to", "with", "if",
            "then", "which", "my", "for", "of")
MUTE_TAIL = 0.6                          # keep ignoring the mic this long after speaking ends (echo, Bluetooth lag)


class TurnDetector:
    """Feed 30 ms int16 frames; returns a whole utterance (bytes) when one ends, else None."""

    def __init__(self, min_rms: float = 300, start_frames: int = 3, end_silence: float = 1.0, preroll: float = 0.3,
                 min_speech: float = 0.4, max_len: float = 20, calibrate: float = 0.5):
        per_s = 1000 / 30
        self.min_rms, self.start_frames = min_rms, start_frames
        self.end_frames, self.min_speech = round(end_silence * per_s), round(min_speech * per_s)
        self.max_frames, self.calib_frames = round(max_len * per_s), round(calibrate * per_s)
        self.preroll = deque(maxlen=round(preroll * per_s))
        self.floor, self._calib = None, []
        self.reset()

    def reset(self) -> None:
        """Drop any half-heard utterance (e.g. when the mic was muted mid-way)."""
        self.in_speech, self.buf, self.run, self.speech, self.silence = False, [], 0, 0, 0
        self.preroll.clear()

    def threshold(self) -> float:
        return max((self.floor or 0) * 3, self.min_rms)

    def feed(self, frame: bytes) -> bytes | None:
        samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        rms = float(np.sqrt(np.mean(samples ** 2))) if samples.size else 0.0
        if self.floor is None:                       # learn the room's noise floor first
            self._calib.append(rms)
            if len(self._calib) >= self.calib_frames:
                self.floor = float(np.median(self._calib))
            return None
        loud = rms > self.threshold()
        if not self.in_speech:
            self.preroll.append(frame)
            self.run = self.run + 1 if loud else 0
            if not loud:
                self.floor = 0.95 * self.floor + 0.05 * rms   # track slow changes in background noise
            if self.run >= self.start_frames:
                self.in_speech, self.buf, self.speech, self.silence = True, list(self.preroll), self.run, 0
            return None
        self.buf.append(frame)
        if loud:
            self.speech, self.silence = self.speech + 1, 0
        else:
            self.silence += 1
        if self.silence < self.end_frames and len(self.buf) < self.max_frames:
            return None
        audio, enough = b"".join(self.buf), self.speech >= self.min_speech
        self.reset()
        return audio if enough else None


def unfinished(text: str) -> bool:
    """Does this sound like they paused mid-sentence ("It can be...", "I want it by the door and")?"""
    t = text.strip().lower()
    if t.endswith(("...", "…", ",", "-")):
        return True
    words = t.rstrip(".!?").split()
    return bool(words) and words[-1] in TRAILING and not t.endswith(("?", "!"))


def _wav(pcm: bytes) -> bytes:
    """Wrap 16 kHz 16-bit mono PCM in a WAV header."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(MIC_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


def mac_say(text: str) -> None:
    """Offline fallback TTS (macOS only)."""
    subprocess.run(["say", text], check=False)


class Voice:
    def __init__(self, cache_dir: str = "phrase_cache", hands_free: bool = True):
        from elevenlabs.client import ElevenLabs
        from openai import OpenAI
        self.stt = OpenAI() if os.environ.get("OPENAI_API_KEY") else None   # None -> typed input only
        self.stt_model = os.environ.get("OPENAI_STT_MODEL") or DEFAULT_STT_MODEL
        self.last_stt_ms = None          # time from releasing push-to-talk to transcript; fsm logs it
        self._recording, self._frames, self._mic_stream = False, [], None
        self.hands_free = hands_free and self.stt is not None
        self._audio: queue.Queue = queue.Queue()     # hands-free mic frames; None marks a muted gap
        self._speaking, self._mute_until, self._gap_sent = False, 0.0, False
        self._detector = TurnDetector(min_rms=float(os.environ.get("VAD_MIN_RMS", 300)),
                                      end_silence=float(os.environ.get("VAD_END_SILENCE", 1.0)))
        self.tts = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))
        self.voice_id = os.environ.get("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE
        self.model = os.environ.get("ELEVENLABS_MODEL") or DEFAULT_MODEL
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.last_latency_ms = None      # time from say() to first audio out; fsm logs it

    def listen(self) -> str:
        """Hands-free: block until the next utterance and return its transcript. Push-to-talk: Enter to start,
        Enter to stop; typing text instead of pressing Enter uses it as the transcript."""
        if self.hands_free:
            return self._listen_hands_free()
        self.last_stt_ms = None
        typed = input("[Enter] to talk, or type> ").strip()
        if typed or self.stt is None:
            return typed
        self.record_start()
        input("  recording... [Enter] to stop")
        text = self.record_stop()
        if not text:
            return input("  didn't catch that, type it> ")
        print(f"  heard: {text}")
        return text

    def record_start(self) -> None:
        """Start push-to-talk. Also used by the browser UI's mic button (ui_server.UIVoice)."""
        self._frames = []
        self._mic()                      # no-op after the first call; the stream stays open
        self._recording = True

    def record_stop(self) -> str:
        """Stop push-to-talk -> transcript, or "" if the clip was too short or transcription failed."""
        self._recording = False
        return self._transcribe(b"".join(self._frames))

    def _listen_hands_free(self) -> str:
        self._mic()
        if self._detector.floor is None:
            print("[voice] listening for room noise...")
        announced, pending, waited = False, "", 0
        wait_frames = round(CONTINUE_FOR * 1000 / 30)
        while True:
            frame = self._audio.get()
            if frame is None:                        # we were speaking: forget anything half-heard
                self._detector.reset()
                continue
            if not announced and self._detector.floor is not None:
                print("  (listening)")
                announced = True
            utterance = self._detector.feed(frame)
            if utterance is None:
                if pending and not self._detector.in_speech:
                    waited += 1
                    if waited >= wait_frames:        # they really were done
                        print(f"  heard: {pending}")
                        return pending
                continue
            text = self._transcribe(utterance)
            if not text:
                continue
            pending = f"{pending} {text}".strip() if pending else text
            if unfinished(pending):
                print(f"  heard so far: {pending}")
                waited = 0
                continue
            print(f"  heard: {pending}")
            return pending

    def _transcribe(self, audio: bytes) -> str:
        self.last_stt_ms = None
        if self.stt is None or len(audio) < MIN_CLIP_BYTES:
            return ""
        t0 = time.perf_counter()
        try:
            text = self.stt.audio.transcriptions.create(
                model=self.stt_model, file=("clip.wav", _wav(audio)), language="en",
                prompt=STT_PROMPT, response_format="text", timeout=8).strip()
        except Exception as e:
            print(f"[voice] transcription failed ({e!r})")
            text = ""
        self.last_stt_ms = round((time.perf_counter() - t0) * 1000)
        return text

    def say(self, text: str) -> None:
        print(f"buddy> {text}", flush=True)
        self._speaking = True
        try:
            self._say(text)
        finally:
            self._speaking, self._mute_until = False, time.time() + MUTE_TAIL

    def _say(self, text: str) -> None:
        t0 = time.perf_counter()
        path = self._cache_path(text)
        if path.exists():
            self._play(path.read_bytes(), t0)
            return
        try:
            pcm = self._play_stream(self._synth(text), t0)
        except Exception as e:
            print(f"[voice] TTS failed ({e!r}), using say")
            self.last_latency_ms = None
            mac_say(text)
            return
        self._write_cache(path, pcm)

    def warm_cache(self, phrases: list[str]) -> None:
        """Pre-generate fixed phrases at startup so they play instantly."""
        todo = [p for p in dict.fromkeys(phrases) if not self._cache_path(p).exists()]
        if not todo:
            return
        print(f"[voice] caching {len(todo)} phrases...")

        def fetch(text):
            try:
                self._write_cache(self._cache_path(text), b"".join(self._synth(text)))
            except Exception as e:
                print(f"[voice] couldn't cache {text!r}: {e!r}")

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(fetch, todo))

    # --- internals ---------------------------------------------------------

    def _mic(self) -> None:
        """Open the mic once and leave it running, so the first word isn't clipped by device start-up."""
        if self._mic_stream is not None:
            return
        import sounddevice as sd

        def on_audio(data, frames, t, status):
            if self._recording:
                self._frames.append(bytes(data))
            if not self.hands_free:
                return
            if self._speaking or time.time() < self._mute_until:
                if not self._gap_sent:
                    self._audio.put(None)
                    self._gap_sent = True
                return
            self._gap_sent = False
            self._audio.put(bytes(data))

        self._mic_stream = sd.RawInputStream(samplerate=MIC_RATE, channels=1, dtype="int16", blocksize=FRAME,
                                             callback=on_audio)
        self._mic_stream.start()

    def _synth(self, text: str):
        """Iterator of raw 16-bit mono PCM chunks."""
        return self.tts.text_to_speech.stream(
            voice_id=self.voice_id, text=text, model_id=self.model, output_format=OUTPUT_FORMAT)

    def _cache_path(self, text: str) -> Path:
        key = hashlib.sha1(f"{self.voice_id}|{self.model}|{text}".encode()).hexdigest()[:16]
        return self.cache_dir / f"{key}.pcm"

    @staticmethod
    def _write_cache(path: Path, pcm: bytes) -> None:
        if pcm:
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(pcm)
            tmp.replace(path)            # atomic, so a crash never leaves a half phrase in the cache

    def _play(self, pcm: bytes, t0: float) -> None:
        self._play_stream([pcm], t0)

    def _play_stream(self, chunks, t0: float) -> bytes:
        """Play PCM chunks as they arrive; return everything played. Raises before any audio if the API fails."""
        import sounddevice as sd
        played, carry, stream = bytearray(), b"", None
        try:
            for chunk in chunks:
                if not chunk:
                    continue
                if stream is None:       # open only once audio exists, so an API error falls back cleanly
                    stream = sd.RawOutputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16")
                    stream.start()
                    self.last_latency_ms = round((time.perf_counter() - t0) * 1000)
                data = carry + chunk
                cut = len(data) - len(data) % 2      # chunks can split a 16-bit sample
                stream.write(data[:cut])
                carry = data[cut:]
                played += data[:cut]
        finally:
            if stream is not None:
                stream.stop()            # stop() drains the buffer before returning
                stream.close()
        return bytes(played)


class FakeVoice:
    """Typed input, printed output. --speak also reads replies aloud with macOS say."""

    def __init__(self, speak: bool = False):
        self.speak = speak

    def listen(self) -> str:
        return input("you> ")

    def say(self, text: str) -> None:
        print(f"buddy> {text}")
        if self.speak:
            mac_say(text)

    def warm_cache(self, phrases: list[str]) -> None:
        pass
