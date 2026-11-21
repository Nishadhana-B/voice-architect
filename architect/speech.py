"""macOS text-to-speech for the scripted caller (headless tests only)."""
from __future__ import annotations

import subprocess
import tempfile
import wave
from pathlib import Path

from .audio_io import SAMPLE_RATE


def say_to_pcm(text: str, voice: str = "Samantha") -> bytes:
    """Speak text with macOS `say` and return 16 kHz mono PCM16 bytes."""
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "u.wav"
        subprocess.run(["say", "-v", voice, "-o", str(f), "--file-format=WAVE",
                        f"--data-format=LEI16@{SAMPLE_RATE}", text], check=True)
        with wave.open(str(f), "rb") as w:
            assert w.getframerate() == SAMPLE_RATE and w.getnchannels() == 1
            return w.readframes(w.getnframes())


def tts(text: str, voice: str | None = None) -> bytes:
    return say_to_pcm(text, voice) if voice else say_to_pcm(text)
