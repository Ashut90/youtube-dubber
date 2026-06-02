"""
live_dub_v6.py  —  5-agent real-time dubbing pipeline

  Agent 1: CAPTURE     parec → VAD → audio chunks
  Agent 2: STT         Groq whisper-large-v3-turbo  (free, 7200s/day)
  Agent 3: TRANSLATE   Groq llama-3.1-8b-instant    (free, 500k tokens/day)
  Agent 4: TTS         edge-tts neural voice         (free, Microsoft)
  Agent 5: PLAYBACK    ffmpeg | pacat                (local)

Why Groq Whisper instead of local:
  - Returns properly punctuated, complete sentences (no more fragments)
  - whisper-large-v3-turbo is faster than local base on RTX 2060
  - Frees GPU for other tasks

Run:
  export GROQ_API_KEY=your_key
  python3 live_dub_v6.py [--lang hindi] [--gender male]
"""

import argparse
import io
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import wave

import numpy as np

# ── CLI args ──────────────────────────────────────────────────────────────────
_p = argparse.ArgumentParser()
_p.add_argument("--lang",   default="hindi")
_p.add_argument("--gender", default="male")
_args, _ = _p.parse_known_args()

import languages
languages.configure(_args.lang, _args.gender)

from groq import Groq
from vad import PhraseDetector, FRAME_SIZE

# ── Config ────────────────────────────────────────────────────────────────────
CAPTURE_SOURCE   = "DubCapture.monitor"
REAL_SPEAKER_SINK = "alsa_output.pci-0000_00_1f.3.analog-stereo"
CAPTURE_RATE     = 16000
PLAY_RATE        = 24000
BYTES_PER_SAMPLE = 2

# VAD — larger chunks = more complete sentences
VAD_SILENCE_MS   = 700
VAD_MAX_PHRASE_S = 7.0
VAD_MIN_PHRASE_S = 1.2

# Drop audio phrase if it has been sitting unprocessed this long.
STALE_S = 10.0

# Groq models
STT_MODEL        = "whisper-large-v3-turbo"
TRANSLATE_MODEL  = "llama-3.1-8b-instant"

# ── Shared queues between agents ──────────────────────────────────────────────
# (capture_time, pcm_float32)
audio_q:   "queue.Queue[tuple[float, np.ndarray]]" = queue.Queue(maxsize=8)
# (capture_time, english_text)
text_q:    "queue.Queue[tuple[float, str]]"         = queue.Queue(maxsize=8)
# (emotion, hinglish_text)
tts_q:     "queue.Queue[tuple[str, str]]"           = queue.Queue(maxsize=8)
# mp3 bytes
play_q:    "queue.Queue[bytes]"                     = queue.Queue(maxsize=8)

stop_flag  = threading.Event()
groq_client: Groq | None = None


def get_groq() -> Groq:
    global groq_client
    if groq_client is None:
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            print("ERROR: GROQ_API_KEY not set.")
            sys.exit(1)
        groq_client = Groq(api_key=key)
    return groq_client


# ── Agent 1: Capture ──────────────────────────────────────────────────────────
def agent_capture():
    detector = PhraseDetector(
        threshold=0.5,
        min_silence_ms=VAD_SILENCE_MS,
        max_phrase_s=VAD_MAX_PHRASE_S,
        min_phrase_s=VAD_MIN_PHRASE_S,
    )
    proc = subprocess.Popen(
        ["parec", "-d", CAPTURE_SOURCE,
         "--rate", str(CAPTURE_RATE), "--channels", "1", "--format", "s16le"],
        stdout=subprocess.PIPE,
    )
    frame_bytes = FRAME_SIZE * BYTES_PER_SAMPLE
    print("[capture] listening — play a video now...\n")

    try:
        while not stop_flag.is_set():
            raw = proc.stdout.read(frame_bytes)
            if not raw or len(raw) < frame_bytes:
                continue
            frame = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            phrase = detector.process_frame(frame)
            if phrase is not None:
                try:
                    audio_q.put_nowait((time.monotonic(), phrase))
                except queue.Full:
                    pass
    finally:
        proc.terminate()


# ── Agent 2: STT (Groq Whisper) ───────────────────────────────────────────────
def _pcm_to_wav(pcm: np.ndarray) -> io.BytesIO:
    """Convert float32 PCM array → WAV bytes buffer for Groq."""
    raw = (np.clip(pcm, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(CAPTURE_RATE)
        wf.writeframes(raw)
    buf.seek(0)
    return buf


def agent_stt():
    client = get_groq()
    while not stop_flag.is_set():
        try:
            ts, pcm = audio_q.get(timeout=0.5)
        except queue.Empty:
            continue

        age = time.monotonic() - ts
        if age > STALE_S:
            print(f"[stt] dropped stale audio ({age:.1f}s old)")
            continue

        try:
            wav_buf = _pcm_to_wav(pcm)
            resp = client.audio.transcriptions.create(
                file=("audio.wav", wav_buf),
                model=STT_MODEL,
                response_format="text",
                language=None,   # auto-detect source language
            )
            text = (resp or "").strip()
            if text:
                print(f"[stt] {text}")
                try:
                    text_q.put_nowait((ts, text))
                except queue.Full:
                    pass
        except Exception as e:
            print(f"[stt] failed: {e}")


# ── Agent 3: Translate (Groq llama) ──────────────────────────────────────────
_SYSTEM_PROMPT: str | None = None

def _get_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is not None:
        return _SYSTEM_PROMPT
    lang = languages.current()

    if lang.keep_english:
        _SYSTEM_PROMPT = f"""You are dubbing a tech/educational YouTube video into {lang.name}.
Translate English into natural spoken Hinglish — the way educated Indians actually talk.

HINGLISH RULES (strictly follow):
- Keep ALL technical/computing terms in English: text, binary, process, tool, data, file, edit, network, portable, shell, command, script, endian, architecture, login, editor, etc.
- Use English verbs with Hindi grammar: "use करते हैं", "edit कर सकते हो", "process होता है"
- Only these Hindi words for grammar: है, हैं, कर, को, का, की, के, में, पर, से, भी, तो, यह, वो, जो, क्योंकि, और, लेकिन, नहीं, क्या, कैसे
- Sound like a YouTube tech channel voiceover — casual, clear, energetic. NOT a textbook.

GOOD vs BAD examples:
❌ "हमें टेक्स्ट का उपयोग क्यों करना चाहिए?" (too formal)
✅ "text use क्यों करें?"

❌ "बहुत सारे पहले से मौजूद टूल्स हैं जो जानते हैं"
✅ "बहुत सारे existing tools हैं already जो text के साथ काम करते हैं"

❌ "नेटवर्क्स और मशीन आर्किटेक्चर्स के बीच पोर्टेबल"
✅ "networks और machine architectures के across portable है"

❌ "प्रक्रिया करें: टेक्स्ट की लाइनें"
✅ "text lines process करो"

OUTPUT FORMAT — exactly one line:
EMOTION|hinglish sentence

EMOTION must be one of: excited neutral sad humorous concerned angry surprised
Use ! for excitement, ? for questions, ... for pauses/thinking, , for breath pauses."""

    else:
        _SYSTEM_PROMPT = (
            f"Dub this YouTube video to {lang.name}. "
            f"Sound natural and spoken, not formal. "
            f"Output: EMOTION|translation. "
            f"EMOTION: excited neutral sad humorous concerned angry surprised. "
            f"Use !, ?, ... for intonation."
        )
    return _SYSTEM_PROMPT


def agent_translate():
    client  = get_groq()
    history = []

    while not stop_flag.is_set():
        try:
            ts, text = text_q.get(timeout=0.5)
        except queue.Empty:
            continue

        age = time.monotonic() - ts
        if age > STALE_S:
            print(f"[translate] dropped stale phrase ({age:.1f}s old)")
            continue

        try:
            messages = [{"role": "system", "content": _get_system_prompt()}]
            messages.extend(history[-4:])   # last 2 turns for context
            messages.append({"role": "user", "content": text})

            resp = client.chat.completions.create(
                model=TRANSLATE_MODEL,
                messages=messages,
                temperature=0.6,
                max_tokens=180,
                timeout=12,
            )
            raw = (resp.choices[0].message.content or "").strip().splitlines()[0]

            if "|" not in raw:
                continue
            emotion, dubbed = raw.split("|", 1)
            emotion = emotion.strip().lower()
            dubbed  = dubbed.strip()

            VALID = {"excited","neutral","sad","humorous","concerned","angry","surprised"}
            if emotion not in VALID:
                emotion = "neutral"
            if not dubbed:
                continue

            print(f"[translate] [{emotion}] {dubbed}  (lag {age:.1f}s)\n")
            history.extend([
                {"role": "user",      "content": text},
                {"role": "assistant", "content": raw},
            ])
            if len(history) > 8:
                history = history[-8:]

            try:
                tts_q.put_nowait((emotion, dubbed))
            except queue.Full:
                pass

        except Exception as e:
            if "rate_limit" in str(e) or "429" in str(e):
                print("[translate] rate-limited — skipping")
            else:
                print(f"[translate] error: {e}")


# ── Agent 4: TTS (edge-tts) ───────────────────────────────────────────────────
from natural_tts import to_speech_mp3

def agent_tts():
    while not stop_flag.is_set():
        try:
            emotion, text = tts_q.get(timeout=0.5)
        except queue.Empty:
            continue

        mp3 = to_speech_mp3(text, emotion)
        if not mp3:
            continue
        try:
            play_q.put_nowait(mp3)
        except queue.Full:
            try:
                play_q.get_nowait()   # drop oldest
            except queue.Empty:
                pass
            try:
                play_q.put_nowait(mp3)
            except queue.Full:
                pass


# ── Agent 5: Playback ─────────────────────────────────────────────────────────
def agent_playback():
    while not stop_flag.is_set():
        try:
            mp3 = play_q.get(timeout=0.5)
        except queue.Empty:
            continue

        # Drop if queue backed up
        if play_q.qsize() >= 3:
            dropped = 0
            while play_q.qsize() > 1:
                try:
                    play_q.get_nowait()
                    dropped += 1
                except queue.Empty:
                    break
            if dropped:
                print(f"[playback] dropped {dropped} clip(s) to catch up")

        try:
            result = subprocess.run(
                ["ffmpeg", "-loglevel", "quiet", "-i", "pipe:0",
                 "-f", "s16le", "-ac", "1", "pipe:1"],
                input=mp3, capture_output=True,
            )
            pcm = result.stdout
            if not pcm:
                continue
            subprocess.run(
                ["pacat", "--playback",
                 "--device", REAL_SPEAKER_SINK,
                 "--format=s16le", f"--rate={PLAY_RATE}", "--channels=1"],
                input=pcm, check=False,
            )
        except Exception as e:
            print(f"[playback] error: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    lang = languages.current()
    print("=" * 60)
    print(f" YT Dubber v6 — 5-agent pipeline")
    print(f" Language : {lang.name}  |  Voice: {languages.voice()}")
    print(f" STT      : Groq {STT_MODEL}")
    print(f" Translate: Groq {TRANSLATE_MODEL}")
    print(f" TTS      : edge-tts")
    print(f" Capture  : {CAPTURE_SOURCE}")
    print(" Ctrl+C to stop")
    print("=" * 60)

    agents = [
        threading.Thread(target=agent_capture,   daemon=True, name="capture"),
        threading.Thread(target=agent_stt,        daemon=True, name="stt"),
        threading.Thread(target=agent_translate,  daemon=True, name="translate"),
        threading.Thread(target=agent_tts,        daemon=True, name="tts"),
        threading.Thread(target=agent_playback,   daemon=True, name="playback"),
    ]
    for a in agents:
        a.start()

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[stop] stopping...")
        stop_flag.set()
        time.sleep(1.0)


if __name__ == "__main__":
    main()
