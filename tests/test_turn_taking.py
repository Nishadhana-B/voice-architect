import asyncio
import base64

from architect.audio_io import BYTES_PER_CHUNK, Recorder, Say, ScriptedAudioInput


def audio_event():
    return {"type": "bidi_audio_delta", "audio": base64.b64encode(b"\x01\x00" * 160).decode(), "sample_rate": 16000}


def test_a_tool_call_turn_ending_does_not_count_as_the_reply():
    """One spoken sentence can trigger several tool calls, each ending with its own response-stop.
    The scripted caller must wait for a SPOKEN answer plus a quiet moment before the next sentence."""
    rec, spoken = Recorder(), []

    def tts(text, voice=None):
        spoken.append(text)
        return b"\x02\x00" * (BYTES_PER_CHUNK // 2) * 2

    mic = ScriptedAudioInput([Say("one"), Say("two")], tts, rec, realtime=False, settle_s=0.0,
                             reply_timeout_s=400, quiet_s=0.05)

    async def go():
        n, phase = 0, 0
        while not mic.finished.is_set():
            await asyncio.wait_for(mic(), 5)
            n += 1
            if len(spoken) == 1 and phase == 0 and n > 8:
                phase = 1                                   # a tool-call turn ends: NOT a spoken reply
                await rec({"type": "bidi_response_stop", "response_id": "r-tool"})
            elif len(spoken) == 1 and phase == 1 and n > 4000:
                assert spoken == ["one"], "second sentence started before the architect answered"
                phase = 2                                   # now the architect really speaks
                await rec(audio_event())
                rec.transcripts.append({"role": "assistant", "text": "Got it, one risk."})
            elif len(spoken) == 2 and phase == 2:
                phase = 3                                   # second sentence only after answer + quiet period
                rec.transcripts.append({"role": "assistant", "text": "Done."})
                await rec(audio_event())
        return phase

    assert asyncio.run(go()) == 3 and spoken == ["one", "two"]


def test_a_silent_architect_does_not_hang_the_script_forever():
    rec = Recorder()
    mic = ScriptedAudioInput([Say("one")], lambda t, v=None: b"\x02\x00" * BYTES_PER_CHUNK, rec,
                             realtime=False, settle_s=0.0, reply_timeout_s=1, quiet_s=0.01)

    async def go():
        for _ in range(200_000):
            await asyncio.wait_for(mic(), 5)
            if mic.finished.is_set():
                return True
        return False

    assert asyncio.run(go())
