"""
natural_tts.py
Emotion-aware TTS via edge-tts.

Each phrase gets an emotion label from the translator.
We map each emotion to a prosody profile (pitch + rate) so the voice
actually sounds different for excited vs sad vs humorous content.
Within each phrase, sentences are synthesised concurrently with their own
micro-variation so consecutive sentences don't sound identical.
"""

import asyncio
import re
import threading
import edge_tts
import languages

# ── Emotion → base prosody ────────────────────────────────────────────────────
# (pitch_hz_offset, rate_percent)
_EMOTION_BASE = {
    "excited":   ("+12Hz", "+28%"),
    "humorous":  ("+8Hz",  "+22%"),
    "surprised": ("+10Hz", "+20%"),
    "neutral":   ("+0Hz",  "+15%"),
    "concerned": ("+2Hz",  "+8%"),
    "angry":     ("+6Hz",  "+25%"),
    "sad":       ("-6Hz",  "+0%"),
}

# Per-sentence variation layered on top of the emotion base.
# Each sentence in a phrase uses the next slot (cycles).
_SENTENCE_DELTA = [
    ("+0Hz",  "+0%"),
    ("+3Hz",  "-4%"),
    ("-2Hz",  "+5%"),
    ("+2Hz",  "-3%"),
]

# ── Persistent event loop ─────────────────────────────────────────────────────
_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()

def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            t = threading.Thread(target=_loop.run_forever, daemon=True)
            t.start()
    return _loop

# ── Sentence splitting ────────────────────────────────────────────────────────
def _split_sentences(text: str) -> list[str]:
    parts = re.split(r'(?<=[।。۔.!?])\s+', text.strip())
    result = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) > 70 and ',' in p:
            halves = p.split(',', 1)
            result.append(halves[0].strip() + ',')
            if halves[1].strip():
                result.append(halves[1].strip())
        else:
            result.append(p)
    return result

def _combine_pitch(base: str, delta: str) -> str:
    """Add two Hz offsets like '+12Hz' + '+3Hz' = '+15Hz'."""
    try:
        b = int(base.replace("Hz", "").replace("+", ""))
        d = int(delta.replace("Hz", "").replace("+", ""))
        v = b + d
        return f"+{v}Hz" if v >= 0 else f"{v}Hz"
    except Exception:
        return base

def _combine_rate(base: str, delta: str) -> str:
    """Add two rate offsets like '+28%' + '-4%' = '+24%'."""
    try:
        b = int(base.replace("%", "").replace("+", ""))
        d = int(delta.replace("%", "").replace("+", ""))
        v = b + d
        return f"+{v}%" if v >= 0 else f"{v}%"
    except Exception:
        return base

# ── Synthesis ─────────────────────────────────────────────────────────────────
async def _synth_one(sentence: str, pitch: str, rate: str, voice: str) -> bytes:
    communicate = edge_tts.Communicate(sentence, voice, rate=rate, pitch=pitch)
    audio = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio += chunk["data"]
    return audio

async def _synthesize(text: str, emotion: str) -> bytes:
    voice     = languages.voice()
    sentences = _split_sentences(text)
    if not sentences:
        return b""

    base_pitch, base_rate = _EMOTION_BASE.get(emotion, _EMOTION_BASE["neutral"])

    tasks = []
    for i, s in enumerate(sentences):
        dp, dr = _SENTENCE_DELTA[i % len(_SENTENCE_DELTA)]
        # Questions always get rising pitch regardless of emotion
        if s.rstrip().endswith('?'):
            pitch = _combine_pitch(base_pitch, "+6Hz")
            rate  = _combine_rate(base_rate, "-5%")
        else:
            pitch = _combine_pitch(base_pitch, dp)
            rate  = _combine_rate(base_rate, dr)
        tasks.append(_synth_one(s, pitch, rate, voice))

    # All sentences synthesised concurrently → total time ≈ slowest one.
    parts = await asyncio.gather(*tasks, return_exceptions=True)
    return b"".join(p for p in parts if isinstance(p, bytes))


def to_speech_mp3(text: str, emotion: str = "neutral",
                  voice_sample: str | None = None) -> bytes:
    """
    Convert text to audio with emotion-matched prosody.
    If voice_sample path is provided, uses XTTS v2 voice cloning (returns WAV).
    Otherwise uses edge-tts neural voice (returns MP3).
    Returns b'' on failure.
    """
    text = (text or "").strip()
    if not text:
        return b""

    if voice_sample:
        import voice_clone_tts
        import languages
        return voice_clone_tts.synthesize(text, voice_sample, languages.current().name.lower())

    loop   = _get_loop()
    future = asyncio.run_coroutine_threadsafe(_synthesize(text, emotion), loop)
    try:
        return future.result(timeout=20)
    except Exception as e:
        print(f"[tts] failed: {e}")
        return b""

# Backwards compat
def hinglish_to_speech_mp3(text: str) -> bytes:
    return to_speech_mp3(text, "neutral")
