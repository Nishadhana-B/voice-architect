"""Headless audio IO for repeatable tests: a scripted caller and a recorder (copied from voice-sous-chef).

ScriptedAudioInput speaks pre-recorded utterances (16 kHz mono PCM16) in real time and sends silence
otherwise. Recorder keeps the model's audio, transcripts and tool calls, and tells the input when the
model has finished answering, so the next utterance is only 'spoken' after the previous reply ended.
"""
import asyncio
import base64
import json
import statistics
import time
import wave
from dataclasses import dataclass
from pathlib import Path

from strands.bidi.types.media import AudioDelta

SAMPLE_RATE = 16000
CHUNK_MS = 20
BYTES_PER_CHUNK = SAMPLE_RATE * 2 * CHUNK_MS // 1000


@dataclass
class Say:
    text: str
    voice: str | None = None  # text-to-speech voice for the scripted cook (e.g. an Indian-English voice)


@dataclass
class Interrupt:
    """Say `first`, wait until the model is speaking, then talk over it with `second` (barge-in)."""
    first: str
    second: str
    after_s: float = 2.0
    voice: str | None = None


@dataclass
class Wait:
    seconds: float
    expect_response: bool = False  # e.g. waiting for a timer alert that makes the agent speak


class Recorder:
    """Output stream that records everything and signals the end of each model response."""

    def __init__(self):
        self.turn_done = asyncio.Event()
        self.audio = bytearray()
        self.turn_audio: list[bytearray] = [bytearray()]
        self.transcripts: list[dict] = []
        self.tool_calls: list[dict] = []
        self.event_types: list[str] = []
        self.sample_rate = SAMPLE_RATE
        self.latencies: list[float] = []  # seconds from end of the cook's speech to the first audio back
        self._speech_end: float | None = None
        self.speaking = asyncio.Event()  # set while the model is producing audio
        self.barge_ins = 0
        self.audio_bytes_at_interrupt: int | None = None
        self.last_audio = 0.0  # monotonic time of the most recent audio chunk from the model

    def mark_speech_end(self):
        self._speech_end = time.monotonic()

    def assistant_count(self) -> int:
        return sum(1 for t in self.transcripts if t["role"] == "assistant")

    def user_count(self) -> int:
        return sum(1 for t in self.transcripts if t["role"] == "user")

    def answered_after_user(self, n: int) -> bool:
        """True once the n-th user transcript has been followed by an assistant transcript."""
        seen = 0
        for t in self.transcripts:
            if t["role"] == "user":
                seen += 1
            elif seen >= n:
                return True
        return False

    async def start(self, agent):
        return

    async def stop(self):
        return

    async def __call__(self, event):
        t = event.get("type")
        self.event_types.append(t)
        if t == "bidi_audio_delta":
            if self._speech_end is not None:
                self.latencies.append(round(time.monotonic() - self._speech_end, 2))
                self._speech_end = None
            data = base64.b64decode(event["audio"])
            self.sample_rate = event.get("sample_rate", self.sample_rate)
            self.audio += data
            self.turn_audio[-1] += data
            self.speaking.set()
            self.last_audio = time.monotonic()
        elif t == "bidi_barge_in":
            self.barge_ins += 1
        elif t == "bidi_transcript_block":
            self.transcripts.append({"role": event["role"], "text": event["transcript"]})
        elif t == "bidi_tool_use_blocks":
            for u in event["tool_uses"]:
                self.tool_calls.append({"tool": u.get("name"), "input": u.get("input")})
        elif t == "bidi_response_stop":
            self.turn_audio.append(bytearray())
            self.turn_done.set()
            self.speaking.clear()

    def save(self, out_dir: str | Path) -> dict:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        with wave.open(str(out / "agent-reply.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.sample_rate)
            w.writeframes(bytes(self.audio))
        (out / "transcript.json").write_text(json.dumps(self.transcripts, indent=2))
        (out / "tool-calls.json").write_text(json.dumps(self.tool_calls, indent=2))
        summary = {"audio_seconds": round(len(self.audio) / 2 / self.sample_rate, 1),
                   "transcript_lines": len(self.transcripts), "tool_calls": len(self.tool_calls)}
        if self.barge_ins or self.audio_bytes_at_interrupt is not None:
            summary["barge_in_events"] = self.barge_ins
        if self.latencies:
            (out / "latencies.json").write_text(json.dumps(self.latencies))
            summary["median_latency_s"] = round(statistics.median(self.latencies), 2)
            summary["max_latency_s"] = max(self.latencies)
        return summary


class ScriptedAudioInput:
    def __init__(self, steps, tts, recorder: Recorder, *, realtime: bool = True,
                 settle_s: float = 1.0, response_timeout_s: float = 90.0,
                 reply_timeout_s: float = 45.0, quiet_s: float = 2.5):
        self.steps, self.tts, self.rec = list(steps), tts, recorder
        self.realtime, self.settle_s, self.timeout_s = realtime, settle_s, response_timeout_s
        # A person waits for the architect to finish talking. One sentence of ours can trigger several tool calls,
        # each ending in its own 'response finished' signal, so that signal alone is NOT the end of the reply.
        # The reply is over when a spoken answer has arrived AND the model has been quiet for quiet_s.
        self.reply_timeout_s, self.quiet_s = reply_timeout_s, quiet_s
        self.finished = asyncio.Event()
        self._gen = self._script()
        self.silence = bytes(BYTES_PER_CHUNK)

    async def start(self, agent):
        return

    async def stop(self):
        return

    async def _pace(self):
        if self.realtime:
            await asyncio.sleep(CHUNK_MS / 1000)
        else:
            await asyncio.sleep(0)

    async def _silence_until(self, seconds: float, until_response: bool):
        """Yield silence for `seconds`, then (optionally) keep going until the model finishes a response."""
        n = int(seconds * 1000 / CHUNK_MS)
        for _ in range(n):
            yield self.silence
        if until_response:
            waited = 0.0
            while not self.rec.turn_done.is_set() and waited < self.timeout_s:
                yield self.silence
                waited += CHUNK_MS / 1000

    async def _await_reply(self, assistant_before: int):
        """Silence until a NEW spoken answer arrived (or reply_timeout_s passed), then until the model is quiet."""
        waited = 0.0
        while self.rec.assistant_count() <= assistant_before and waited < self.reply_timeout_s:
            yield self.silence
            waited += CHUNK_MS / 1000
        while time.monotonic() - self.rec.last_audio < self.quiet_s and waited < self.reply_timeout_s + 30:
            yield self.silence
            waited += CHUNK_MS / 1000

    def _speak(self, text: str, voice: str | None):
        pcm = self.tts(text, voice) if voice else self.tts(text)
        for i in range(0, len(pcm), BYTES_PER_CHUNK):
            yield pcm[i:i + BYTES_PER_CHUNK].ljust(BYTES_PER_CHUNK, b"\0")

    async def _script(self):
        yield self.silence  # first chunk opens the stream
        for step in self.steps:
            self.rec.turn_done.clear()
            if isinstance(step, Say):
                assistant_before = self.rec.assistant_count()
                for c in self._speak(step.text, step.voice):
                    yield c
                self.rec.mark_speech_end()
                async for c in self._await_reply(assistant_before):
                    yield c
            elif isinstance(step, Interrupt):
                users_before = self.rec.user_count()
                for c in self._speak(step.first, step.voice):
                    yield c
                waited = 0.0
                while not self.rec.speaking.is_set() and waited < 30:  # wait until the model starts talking
                    yield self.silence
                    waited += CHUNK_MS / 1000
                async for c in self._silence_until(step.after_s, until_response=False):
                    yield c
                self.rec.audio_bytes_at_interrupt = len(self.rec.audio)
                for c in self._speak(step.second, step.voice):  # talk over the model
                    yield c
                # The interrupted answer also ends with a response stop, which can arrive late and must not
                # end the test. Wait until there is an assistant transcript AFTER the interrupting sentence.
                target, waited = users_before + 2, 0.0  # first sentence + the interrupting one
                while not self.rec.answered_after_user(target) and waited < self.timeout_s:
                    yield self.silence
                    waited += CHUNK_MS / 1000
            else:
                async for c in self._silence_until(step.seconds, until_response=step.expect_response):
                    yield c
            async for c in self._silence_until(self.settle_s, until_response=False):
                yield c
        self.finished.set()
        while True:
            yield self.silence

    async def __call__(self) -> AudioDelta:
        chunk = await anext(self._gen)
        await self._pace()
        return AudioDelta(format="pcm", source={"bytes": chunk})
