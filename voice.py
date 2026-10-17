"""Push-to-talk speech-to-text and text-to-speech. Owner: L.

TTS is tuned for latency: ElevenLabs Flash streams raw PCM, which plays chunk by chunk as it arrives and is
cached on disk at the same time. Cached phrases play straight from PCM with no decoding.
"""
import hashlib
import io
import os
import subprocess
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SAMPLE_RATE = 22050                      # matches output_format below; 16-bit mono
OUTPUT_FORMAT = f"pcm_{SAMPLE_RATE}"
DEFAULT_VOICE = "JBFqnCBsd6RMkjVDRZzb"   # ElevenLabs premade "George"; override with ELEVENLABS_VOICE_ID
DEFAULT_MODEL = "eleven_flash_v2_5"      # lowest-latency ElevenLabs model

MIC_RATE = 16000
MIN_CLIP_BYTES = MIC_RATE * 2 * 3 // 10  # 0.3 s of 16-bit audio; shorter is a mis-press
DEFAULT_STT_MODEL = "gpt-4o-mini-transcribe"
STT_PROMPT = ("Electronics bench talk. 555 timer, NE555, resistor, capacitor, LED, ohm, kilohm, 10k, 68k, "
              "330 ohm, microfarad, nanofarad, 10 microfarad, 100 nanofarad, done, it's not working.")


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
    def __init__(self, cache_dir: str = "phrase_cache"):
        from elevenlabs.client import ElevenLabs
        from openai import OpenAI
        self.stt = OpenAI() if os.environ.get("OPENAI_API_KEY") else None   # None -> typed input only
        self.stt_model = os.environ.get("OPENAI_STT_MODEL") or DEFAULT_STT_MODEL
        self.last_stt_ms = None          # time from releasing push-to-talk to transcript; fsm logs it
        self._recording, self._frames, self._mic_stream = False, [], None
        self.tts = ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY"))
        self.voice_id = os.environ.get("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE
        self.model = os.environ.get("ELEVENLABS_MODEL") or DEFAULT_MODEL
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.last_latency_ms = None      # time from say() to first audio out; fsm logs it

    def listen(self) -> str:
        """Enter to start, Enter to stop. Typing text instead of pressing Enter uses it as the transcript."""
        self.last_stt_ms = None
        typed = input("[Enter] to talk, or type> ").strip()
        if typed or self.stt is None:
            return typed
        self._recording, self._frames = True, []
        self._mic()                      # no-op after the first call; the stream stays open
        input("  recording... [Enter] to stop")
        self._recording = False
        t0 = time.perf_counter()
        audio = b"".join(self._frames)
        if len(audio) < MIN_CLIP_BYTES:
            return input("  too short, type it> ")
        try:
            text = self.stt.audio.transcriptions.create(
                model=self.stt_model, file=("clip.wav", _wav(audio)), language="en",
                prompt=STT_PROMPT, response_format="text", timeout=8).strip()
        except Exception as e:
            print(f"[voice] transcription failed ({e!r})")
            text = ""
        self.last_stt_ms = round((time.perf_counter() - t0) * 1000)
        if not text:
            return input("  didn't catch that, type it> ")
        print(f"  heard: {text}")
        return text

    def say(self, text: str) -> None:
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

        self._mic_stream = sd.RawInputStream(samplerate=MIC_RATE, channels=1, dtype="int16", callback=on_audio)
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
