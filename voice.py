"""Push-to-talk speech-to-text and text-to-speech. Owner: L."""
import subprocess


def mac_say(text: str) -> None:
    """Offline fallback TTS (macOS only)."""
    subprocess.run(["say", text], check=False)


class Voice:
    def __init__(self, cache_dir: str = "phrase_cache"):
        # TODO(L): OpenAI client for transcription, ElevenLabs client for TTS (keys from .env)
        self.cache_dir = cache_dir

    def listen(self) -> str:
        raise NotImplementedError(
            "TODO(L): Enter to start, Enter to stop; sounddevice 16 kHz mono -> OpenAI transcription; "
            "empty or failed -> fall back to input()")

    def say(self, text: str) -> None:
        raise NotImplementedError(
            "TODO(L): play cached mp3 (keyed by hash of text) if present, else ElevenLabs TTS and cache it; "
            "on error -> mac_say")

    def warm_cache(self, phrases: list[str]) -> None:
        """Pre-generate fixed phrases at startup so they play instantly."""
        raise NotImplementedError("TODO(L)")


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
