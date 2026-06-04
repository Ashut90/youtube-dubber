"""
youtube_dubber.core — the headless dubbing engine.

Takes a YouTube URL and produces synced dubbed audio clips (one MP3 per
segment) plus a manifest. No GUI, no stdout assumptions — progress is
reported through an `on_event` callback so any caller (a CLI, the Electron
app, a web server) can consume it.

Public API:
    from youtube_dubber import Dubber, dub

    # Convenience:
    manifest = dub("https://youtu.be/...", lang="hindi", gender="female",
                   out="./dubbed")

    # Or with live progress:
    def on_event(ev): print(ev["type"], ev.get("msg", ""))
    Dubber(lang="hindi", out_dir="./dubbed", on_event=on_event).run(url)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Optional

import edge_tts

from . import languages

# ── Shared regexes ────────────────────────────────────────────────────────────
_URL_RE    = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_FILLER_RE = re.compile(r"^\s*\[.*?\]\s*$")
_CODE_PATTERNS = re.compile(
    r"^\s*(sudo|chmod|grep|ls |cat |echo |for |while |if \[|\.\/|#!/|<[^>]+>|\$\w+)",
    re.IGNORECASE,
)

BATCH_SIZE = 20   # segments per Groq call

# Translation models, best-quality first. The pipeline tries [0]; if it
# rate-limits (429) it falls back to [1] so output never stops.
TRANSLATE_MODELS = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]

# Emotion → prosody. Gives the voice dynamic intonation instead of a flat tone.
#   (edge_rate_percent, edge_pitch_Hz, kokoro_speed)
# Excited/surprised speak faster & higher; sad/concerned slower & lower.
EMOTION_PROSODY = {
    "excited":   (18,  4, 1.12),
    "surprised": (15,  5, 1.08),
    "humorous":  (14,  3, 1.06),
    "neutral":   (10,  0, 1.00),
    "angry":     (14,  1, 1.08),
    "concerned": ( 6, -2, 0.95),
    "sad":       ( 2, -3, 0.90),
}

# ── Kokoro TTS (opt-in, local GPU) ────────────────────────────────────────────
# Maps a dub-language key → (male voice, female voice, kokoro language code).
# Only languages listed here can use Kokoro; everything else (and any failure)
# transparently falls back to edge-tts. Voice IDs are Kokoro v1.0 voices.
# Start small (Hindi + English) — verified working before expanding.
KOKORO_VOICES = {
    "english": {"male": "am_michael", "female": "af_heart",  "lang": "en-us"},
    "hindi":   {"male": "hm_omega",   "female": "hf_alpha",  "lang": "hi"},
}
# Model/voice file locations — override with env vars if stored elsewhere.
KOKORO_MODEL_PATH  = os.environ.get("KOKORO_MODEL",  "kokoro-v1.0.onnx")
KOKORO_VOICES_PATH = os.environ.get("KOKORO_VOICES", "voices-v1.0.bin")


class _KokoroEngine:
    """Lazily-loaded singleton wrapper around kokoro-onnx.

    The model is loaded once on first use. If kokoro-onnx isn't installed, the
    model files are missing, or CUDA isn't available, it marks itself failed and
    returns None forever after — callers then fall back to edge-tts.
    """
    _engine = None
    _tried  = False

    @classmethod
    def get(cls):
        if cls._tried:
            return cls._engine
        cls._tried = True
        try:
            from kokoro_onnx import Kokoro   # type: ignore
            cls._engine = Kokoro(KOKORO_MODEL_PATH, KOKORO_VOICES_PATH)
            print(f"[kokoro] loaded ({KOKORO_MODEL_PATH})", file=sys.stderr)
        except Exception as e:
            print(f"[kokoro] unavailable → using edge-tts ({e})", file=sys.stderr)
            cls._engine = None
        return cls._engine

_SLANG = {
    "स्वागत है":       "वेलकम यार",
    "कृपया ध्यान दें": "तो भाई देखो",
    "उदाहरण के लिए":  "जैसे कि मतलब",
    "शुरू करते हैं":   "चलो शुरू करते हैं!",
    "यह बहुत अच्छा है":"ये एकदम गज़ब है!",
    "नमस्ते दोस्तों":  "हे दोस्तों",
    "धन्यवाद":         "थैंक यू यार",
    "कृपया":           "प्लीज़",
    "सदस्यता":         "subscribe",
    "चलचित्र":         "video",
    "निर्देशिका":      "directory / folder",
    "प्रक्रिया":       "process",
    "पथ":              "path",
    "पुनरावृत्ति":     "loop",
    "त्रुटि":          "error",
    "समाधान":          "solution / jugaad",
    "जटिल":            "complex / भारी",
    "समारोह":          "function",
    "आइए समझते हैं":   "तो भाई scene ये है कि",
    "यह महत्वपूर्ण है":"इसे दिमाग में बिठा लो!",
    "निष्कर्ष":        "सच्चाई तो ये है",
    "समस्या":          "locha",
}


class DubError(Exception):
    """Raised on an unrecoverable error (no captions, bad URL, missing key)."""


# ── Pure helpers (no instance state) ──────────────────────────────────────────
def video_id(url: str) -> str:
    """Stable per-video cache key from a YouTube URL (falls back to a hash)."""
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)
    return hashlib.md5(url.encode()).hexdigest()[:11]


def parse_timestamp(ts: str) -> float:
    parts = ts.strip().split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    return int(parts[0]) * 60 + float(parts[1])


def parse_vtt(vtt_path: Path) -> list[dict]:
    text   = Path(vtt_path).read_text(encoding="utf-8", errors="ignore")
    blocks = re.split(r"\n{2,}", text)
    segs   = []
    ts_re  = re.compile(
        r"(\d{1,2}:\d{2}:\d{2}\.\d+|\d{2}:\d{2}\.\d+)"
        r"\s*-->\s*"
        r"(\d{1,2}:\d{2}:\d{2}\.\d+|\d{2}:\d{2}\.\d+)"
    )
    for block in blocks:
        lines = block.strip().split("\n")
        ts_line = next((l for l in lines if "-->" in l), None)
        if not ts_line:
            continue
        m = ts_re.search(ts_line)
        if not m:
            continue
        start = parse_timestamp(m.group(1))
        end   = parse_timestamp(m.group(2))
        content = [
            re.sub(r"<[^>]+>", "", l).strip()
            for l in lines
            if "-->" not in l and l.strip() and not l.strip().isdigit()
        ]
        if not content:
            continue
        body = re.sub(r"\s+", " ", content[-1]).strip()
        body = _URL_RE.sub("", body).strip()
        if body and end - start > 0.1:
            segs.append({"start": start, "end": end, "text": body})
    return segs


def merge_segments(segs: list[dict], min_dur=2.5, max_dur=7.0) -> list[dict]:
    if not segs:
        return []
    merged = []
    buf = segs[0].copy()
    for s in segs[1:]:
        dur = s["end"] - buf["start"]
        combined = buf["text"] + " " + s["text"]
        if buf["end"] - buf["start"] < min_dur or (
            dur <= max_dur and not buf["text"].rstrip().endswith((".", "!", "?", "..."))
        ):
            buf["end"]  = s["end"]
            buf["text"] = combined.strip()
        else:
            merged.append(buf)
            buf = s.copy()
    merged.append(buf)
    return merged


def clean_text(text: str) -> str:
    """Strip URLs, bracket fillers, and raw code lines before TTS.

    Code/command lines are skipped (returns "") rather than read aloud — the
    viewer can see them on screen. (Previously this injected a Hindi sentence,
    which was wrong for the other 19 target languages.)"""
    text = _URL_RE.sub("", text).strip()
    if _FILLER_RE.match(text):
        return ""
    if _CODE_PATTERNS.search(text):
        return ""
    return text


def apply_slang(text: str) -> str:
    for formal, casual in _SLANG.items():
        text = text.replace(formal, casual)
    return text


def get_audio_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def stretch(src: str, target_dur: float):
    """Compress dubbed audio to fit the segment window (speed-up only, ≤1.4×)."""
    actual = get_audio_duration(src)
    if actual <= 0 or target_dur <= 0:
        return
    if actual <= target_dur * 1.05:
        return
    ratio = min(1.4, actual / target_dur)
    out = src.replace(".mp3", "_s.mp3")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "quiet",
                    "-i", src, "-af", f"atempo={ratio:.3f}", out], check=False)
    if Path(out).exists():
        Path(src).unlink(missing_ok=True)
        Path(out).rename(src)


# ── The engine ────────────────────────────────────────────────────────────────
class Dubber:
    """Headless YouTube → dubbed-audio engine.

    Parameters
    ----------
    lang : target dub language key (see youtube_dubber.languages.LANGUAGES)
    gender : "male" or "female" — selects the neural voice
    out_dir : where caption/audio/manifest files are written
    source_lang : source caption language code, or "auto" to detect
    on_event : optional callback receiving event dicts (progress/segment/done)
    groq_api_key : Groq key; falls back to the GROQ_API_KEY env var
    tts : "edge" (default, cloud, all languages) or "kokoro" (local GPU, opt-in,
          higher quality, only the languages in KOKORO_VOICES). Kokoro falls back
          to edge-tts automatically if it isn't installed or the language/voice
          isn't supported — so nothing breaks.
    """

    def __init__(
        self,
        lang: str = "hindi",
        gender: str = "male",
        out_dir: str | Path = "./output",
        source_lang: str = "auto",
        on_event: Optional[Callable[[dict], None]] = None,
        groq_api_key: Optional[str] = None,
        tts: str = "edge",
    ):
        languages.configure(lang, gender)
        self.lang        = languages.current()
        self.voice       = languages.voice()
        self.lang_key    = lang
        self.gender      = gender
        self.source_lang = source_lang
        self.out_dir     = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._on_event   = on_event
        self._api_key    = groq_api_key or os.environ.get("GROQ_API_KEY")
        self.tts         = (tts or "edge").lower()

        # per-run state
        self.detected_src   = "en"
        self._system_prompt: Optional[str] = None
        self._last_dub      = ""

    # ── event helpers ─────────────────────────────────────────────────────────
    def _emit(self, obj: dict):
        if self._on_event:
            self._on_event(obj)

    def _progress(self, step: str, pct: int, msg: str = ""):
        self._emit({"type": "progress", "step": step, "pct": pct, "msg": msg})

    # ── Step 1: stream URL ────────────────────────────────────────────────────
    def get_stream_url(self, url: str) -> str:
        self._progress("stream", 0, "Getting video stream URL…")
        result = subprocess.run(
            ["yt-dlp", "--get-url",
             "-f", "best[height<=720][ext=mp4]/bestvideo[height<=720]+bestaudio/best[height<=720]/best",
             "--no-playlist", url],
            capture_output=True, text=True,
        )
        urls = [u.strip() for u in result.stdout.strip().split("\n") if u.strip()]
        if not urls:
            raise DubError("Could not get stream URL. Check the URL.")
        return urls[0]

    # ── Step 2: captions ──────────────────────────────────────────────────────
    @staticmethod
    def _video_language(url: str) -> str | None:
        r = subprocess.run(
            ["yt-dlp", "--print", "%(language)s", "--skip-download", "--no-playlist", url],
            capture_output=True, text=True,
        )
        code = r.stdout.strip().split("\n")[0].strip()
        return code if code and code.lower() not in ("na", "none", "") else None

    def _fetch_subs(self, url: str, langs: str) -> Path | None:
        cap_out = self.out_dir / "caps"
        for f in self.out_dir.glob("caps.*.vtt"):
            f.unlink(missing_ok=True)
        subprocess.run([
            "yt-dlp", url,
            "--write-subs", "--write-auto-subs", "--sub-langs", langs,
            "--sub-format", "vtt", "--skip-download",
            "-o", str(cap_out), "--quiet", "--no-playlist",
        ], check=False)
        vtts = list(self.out_dir.glob("caps.*.vtt"))
        return vtts[0] if vtts else None

    def get_captions(self, url: str) -> Path | None:
        self._progress("captions", 0, "Fetching captions…")
        if self.source_lang and self.source_lang != "auto":
            target = self.source_lang
        else:
            target = self._video_language(url) or "en"

        for code in [target, "en"]:
            vtt = self._fetch_subs(url, f"{code}.*,{code}")
            if vtt:
                self.detected_src = code.split("-")[0].lower()
                self._progress("captions", 100, f"Captions ({code}) downloaded")
                return vtt

        self._progress("captions", 100, "No captions — will transcribe with Whisper")
        return None

    def transcribe_fallback(self, url: str) -> list[dict]:
        self._progress("transcribe", 0, "No captions — downloading audio for transcription…")
        audio_path = self.out_dir / "audio.wav"
        subprocess.run([
            "yt-dlp", url, "-x", "--audio-format", "wav", "--audio-quality", "0",
            "-o", str(audio_path.with_suffix("")), "--quiet",
        ], check=False)
        if not audio_path.exists():
            raise DubError("Could not extract audio for transcription.")

        from groq import Groq
        client = Groq(api_key=self._api_key)
        self._progress("transcribe", 50, "Transcribing with Whisper…")
        with open(audio_path, "rb") as f:
            stt_kwargs = dict(
                file=("audio.wav", f),
                model="whisper-large-v3-turbo",
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )
            if self.source_lang and self.source_lang != "auto":
                stt_kwargs["language"] = self.source_lang
            resp = client.audio.transcriptions.create(**stt_kwargs)
        segments = [
            {"start": float(s["start"]), "end": float(s["end"]), "text": s["text"].strip()}
            for s in resp.segments
        ]
        self._progress("transcribe", 100, f"{len(segments)} segments transcribed")
        return segments

    # ── Step 3: prompt ────────────────────────────────────────────────────────
    def get_system_prompt(self) -> str:
        if self._system_prompt:
            return self._system_prompt
        lang = self.lang

        if lang.keep_english and lang.name == "Hindi":
            eng = (
                "You are a high-energy Indian YouTube creator dubbing a video into casual Hinglish.\n\n"
                "RULES:\n"
                "1. Use punchy hooks: 'तो भाई', 'यार', 'देखो', 'मतलब', 'बॉस', 'चलो', 'सुनो'.\n"
                "2. NEVER translate technical terms — keep them English but may phonetically hint: "
                "'chmod', 'sudo', 'grep', 'pointer', 'loop', 'array', 'function', 'RAM', 'GPIO', etc.\n"
                "3. Use casual endings: 'करो'/'कर देना' instead of 'करें'; 'है' instead of 'हैं'.\n"
                "4. Add '!' for exciting moments to drive TTS expression.\n"
                "5. For pure code lines (bash commands, syntax) output ONLY: "
                "'स्क्रीन पर दिख रहे इस code को ध्यान से देखो।'\n"
                "6. Keep output SHORT — match original speech timing.\n\n"
                "EXAMPLES:\n"
                "❌ 'यदि आपके पास रूट विशेषाधिकार नहीं हैं'\n"
                "✅ 'तो भाई, अगर तुम्हारे पास sudo power नहीं है'\n"
                "❌ 'हमें text का उपयोग क्यों करना चाहिए'\n"
                "✅ 'यार, text use क्यों करते हैं देखो!'\n"
            )
        elif lang.keep_english:
            eng = (
                f"You are a high-energy {lang.name} YouTuber dubbing a video.\n"
                f"RULES:\n"
                f"1. NEVER translate technical terms (code, command names, library/brand "
                f"names, RAM, GPU, function, loop, array…) — keep them in English.\n"
                f"2. Open clauses with casual spoken hooks/fillers like: {lang.fillers}.\n"
                f"3. Use everyday casual speech, NOT textbook/formal grammar.\n"
                f"4. Add '!' on exciting lines so the voice sounds energetic.\n"
                f"5. For pure code/command lines, just tell the viewer to look at the screen.\n"
                f"6. Keep each line SHORT to match the original speech timing."
            )
        else:
            eng = (
                f"You are an engaging, friendly {lang.name} YouTuber dubbing a video.\n"
                f"RULES:\n"
                f"1. Translate into natural, casual spoken {lang.name} — like talking to a "
                f"friend, NOT a formal textbook or news anchor.\n"
                f"2. Open clauses with casual spoken connectors/fillers like: {lang.fillers}.\n"
                f"3. Keep widely-known technical/brand terms in their common form "
                f"(don't force awkward literal translations).\n"
                f"4. Add '!' on exciting lines so the voice sounds energetic.\n"
                f"5. Keep each line SHORT to match the original speech timing."
            )

        # Speaker-gender grammar: many languages (Hindi, Urdu, Punjabi, Spanish,
        # French, Italian, Portuguese, Russian, Marathi, Gujarati…) inflect verbs/
        # adjectives by the speaker's gender. Tell the model who is speaking so a
        # female voice says "जा रही हूँ / करूँगी" and a male voice "जा रहा हूँ / करूँगा".
        if self.gender == "female":
            gender_note = (
                "\nSPEAKER GENDER: The narrator is FEMALE. Use first-person FEMININE "
                "verb/adjective forms (Hindi: रही हूँ, करूँगी, गई, सकती; "
                "Spanish: -a; etc.). Never use masculine self-reference."
            )
        else:
            gender_note = (
                "\nSPEAKER GENDER: The narrator is MALE. Use first-person MASCULINE "
                "verb/adjective forms (Hindi: रहा हूँ, करूँगा, गया, सकता; Spanish: -o; etc.)."
            )

        self._system_prompt = (
            f"Dub this video to {lang.name}. The source text may be in any language — "
            f"translate from whatever language it is. {eng}{gender_note}\n\n"
            f"For EACH numbered source line output: N|EMOTION|{lang.name} translation\n"
            f"EMOTION: excited neutral sad humorous concerned angry surprised\n"
            f"One output line per input line. No explanations."
        )
        return self._system_prompt

    # ── Step 4: TTS ───────────────────────────────────────────────────────────
    def _is_duplicate_dub(self, text: str) -> bool:
        if text.strip() == self._last_dub.strip() and text.strip():
            return True
        self._last_dub = text
        return False

    async def _synth_one(self, text: str, path: str, emotion: str = "neutral") -> bool:
        """Synthesize one clip. Text is already cleaned/slang-applied by the
        caller (so subtitle == audio). Dispatches to Kokoro if requested &
        supported, otherwise (or on any Kokoro failure) uses edge-tts."""
        text = (text or "").strip()
        if not text:
            return False

        # Opt-in Kokoro path — only for supported languages; falls back on failure
        if self.tts == "kokoro" and self.lang_key in KOKORO_VOICES:
            if await self._synth_kokoro(text, path, emotion):
                return True
            # else: silently fall through to edge-tts below

        return await self._synth_edge(text, path, emotion)

    async def _synth_edge(self, text: str, path: str, emotion: str = "neutral") -> bool:
        r, p, _ = EMOTION_PROSODY.get(emotion, EMOTION_PROSODY["neutral"])
        if self.lang.name == "Hindi":
            r += 2; p += 1                      # a touch more energy for Hindi
        rate  = f"{'+' if r >= 0 else ''}{r}%"
        pitch = f"{'+' if p >= 0 else ''}{p}Hz"
        communicate = edge_tts.Communicate(text, self.voice, rate=rate, pitch=pitch)
        mp3 = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3 += chunk["data"]
        if mp3:
            with open(path, "wb") as f:
                f.write(mp3)
            return True
        return False

    async def _synth_kokoro(self, text: str, path: str, emotion: str = "neutral") -> bool:
        """Local Kokoro-82M synthesis. Returns False on any problem so the
        caller falls back to edge-tts — never raises into the pipeline."""
        engine = _KokoroEngine.get()
        if engine is None:
            return False
        cfg = KOKORO_VOICES.get(self.lang_key)
        if not cfg:
            return False
        voice = cfg["male"] if self.gender == "male" else cfg["female"]
        speed = EMOTION_PROSODY.get(emotion, EMOTION_PROSODY["neutral"])[2]
        try:
            import numpy as np
            # kokoro.create is synchronous → run off the event loop
            samples, sr = await asyncio.to_thread(
                lambda: engine.create(text, voice=voice, speed=speed, lang=cfg["lang"])
            )
            if samples is None or len(samples) == 0:
                return False
            # float32 [-1,1] → 16-bit PCM → mp3 via ffmpeg (keeps .mp3 cache format)
            pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "quiet",
                 "-f", "s16le", "-ar", str(int(sr)), "-ac", "1",
                 "-i", "pipe:0", path],
                input=pcm, check=False,
            )
            return Path(path).exists() and Path(path).stat().st_size > 0
        except Exception as e:
            print(f"[kokoro] synth failed for {self.lang_key} → edge-tts ({e})",
                  file=sys.stderr)
            return False

    async def _translate_tts_pipeline(self, segments: list[dict], audio_dir: Path):
        from groq import Groq
        client = Groq(api_key=self._api_key)
        total  = len(segments)
        sem    = asyncio.Semaphore(4)

        async def do_tts(gi: int, seg: dict):
            path      = str(audio_dir / f"seg_{gi:05d}.mp3")
            meta_path = audio_dir / f"seg_{gi:05d}.json"

            if Path(path).exists():
                if meta_path.exists():
                    cached = json.loads(meta_path.read_text())
                else:
                    cached = {"start": seg["start"], "end": seg["end"],
                              "text": seg["text"], "dubbed": seg["text"], "emotion": "neutral"}
                self._emit({"type": "segment", "index": gi, **cached, "audio_file": path})
                return

            dubbed = seg.get("dubbed", "")
            if not dubbed:
                return
            # Process ONCE here (slang + URL/code cleaning) so the on-screen
            # subtitle and the spoken audio are always identical. Previously this
            # ran only inside synthesis, so the subtitle showed "स्वागत है" while
            # the voice said "वेलकम यार".
            spoken = apply_slang(clean_text(dubbed))
            if not spoken:
                return
            if self._is_duplicate_dub(spoken):
                print(f"[dedup] skipped duplicate dubbed segment {gi}", file=sys.stderr)
                return
            emotion = seg.get("emotion", "neutral")
            try:
                async with sem:
                    ok = await self._synth_one(spoken, path, emotion)
            except Exception as e:
                print(f"[tts] segment {gi} failed: {e}", file=sys.stderr)
                return
            if ok:
                stretch(path, seg["end"] - seg["start"])
                metadata = {"start": seg["start"], "end": seg["end"],
                            "text": seg["text"], "dubbed": spoken, "emotion": emotion}
                meta_path.write_text(json.dumps(metadata, ensure_ascii=False))
                self._emit({"type": "segment", "index": gi, **metadata, "audio_file": path})

        for b in range(0, total, BATCH_SIZE):
            batch = segments[b: b + BATCH_SIZE]
            b_end = b + len(batch)
            pct   = int(b / total * 100)

            if all((audio_dir / f"seg_{b+i:05d}.mp3").exists() for i in range(len(batch))):
                self._progress("tts", int(b_end / total * 100), f"{b_end}/{total} segments ready (cached)")
                await asyncio.gather(*[do_tts(b + i, s) for i, s in enumerate(batch)])
                continue

            self._progress("translate", pct,
                           f"Batch {b//BATCH_SIZE + 1}/{(total+BATCH_SIZE-1)//BATCH_SIZE} — segments {b+1}–{b_end}")

            lines = "\n".join(f"{i+1}. {s['text']}" for i, s in enumerate(batch))
            got_translation = False
            # Quality-first with graceful fallback: try the big 70B model, but the
            # moment it rate-limits (429) drop to the fast 8B so the pipeline never
            # stalls. Attempt 0 → 70B; attempts 1-5 → 8B with backoff.
            for attempt in range(6):
                model = TRANSLATE_MODELS[0] if attempt == 0 else TRANSLATE_MODELS[1]
                try:
                    resp = client.chat.completions.create(
                        model=model,
                        messages=[{"role": "system", "content": self.get_system_prompt()},
                                  {"role": "user",   "content": lines}],
                        temperature=0.6, max_tokens=BATCH_SIZE * 80, timeout=30,
                    )
                    for line in (resp.choices[0].message.content or "").strip().split("\n"):
                        line = line.strip()
                        if "|" not in line:
                            continue
                        parts = line.split("|", 2)
                        if len(parts) < 3:
                            continue
                        try:
                            n = int(re.match(r"\d+", parts[0]).group()) - 1
                            if 0 <= n < len(batch):
                                batch[n]["emotion"] = parts[1].strip().lower()
                                batch[n]["dubbed"]  = parts[2].strip()
                        except (ValueError, AttributeError):
                            pass
                    got_translation = True
                    break
                except Exception as e:
                    msg = str(e)
                    if "rate_limit" in msg or "429" in msg:
                        if attempt == 0:
                            # 70B is busy — switch to 8B immediately, no wait
                            self._progress("translate", pct, "70B busy → using fast model…")
                        else:
                            self._progress("translate", pct, f"Rate limited — retry {attempt}/5 in 6s…")
                            await asyncio.sleep(6)
                    else:
                        print(f"[translate] error ({model}): {e}", file=sys.stderr)
                        await asyncio.sleep(2)

            if not got_translation and self.detected_src == "en":
                for s in batch:
                    if not s.get("dubbed"):
                        s["dubbed"] = s["text"]

            await asyncio.gather(*[do_tts(b + i, s) for i, s in enumerate(batch)])
            self._progress("tts", int(b_end / total * 100), f"{b_end}/{total} segments ready")

    # ── Orchestration ─────────────────────────────────────────────────────────
    def run(self, url: str) -> dict:
        """Run the full pipeline. Returns the manifest dict."""
        if not self._api_key:
            raise DubError("GROQ_API_KEY not set.")

        stream_url = self.get_stream_url(url)
        self._emit({"type": "stream_url", "url": stream_url})

        vtt = self.get_captions(url)
        if vtt:
            segments = merge_segments(parse_vtt(vtt))
        else:
            segments = merge_segments(self.transcribe_fallback(url))

        self._progress("captions", 100, f"{len(segments)} segments")

        vid = video_id(url)
        # Namespace cache by engine so Kokoro and edge-tts audio never collide.
        # edge keeps the historical "{vid}_{lang}_{gender}" path (caches stay valid).
        tts_suffix = "" if self.tts == "edge" else f"_{self.tts}"
        audio_dir = self.out_dir / "audio" / f"{vid}_{self.lang_key}_{self.gender}{tts_suffix}"
        audio_dir.mkdir(parents=True, exist_ok=True)

        existing   = len(list(audio_dir.glob("seg_*.mp3")))
        total_segs = len(segments)
        if existing == 0:
            self._progress("tts", 0,
                           f"Generating {self.lang.name} ({self.gender}) dub from scratch — first run takes ~1 min…")
        elif existing < total_segs:
            self._progress("tts", int(existing/total_segs*100),
                           f"Resuming {self.lang.name} ({self.gender}) dub — {existing}/{total_segs} cached…")

        asyncio.run(self._translate_tts_pipeline(segments, audio_dir))

        manifest = {
            "stream_url": stream_url,
            "lang":       self.lang.name,
            "segments": [
                {
                    "start":      s["start"],
                    "end":        s["end"],
                    "text":       s["text"],
                    "dubbed":     s.get("dubbed", ""),
                    "emotion":    s.get("emotion", "neutral"),
                    "audio_file": s.get("audio_file"),
                }
                for s in segments
            ],
        }
        manifest_path = self.out_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        self._progress("tts", 100, "All segments ready")
        self._emit({"type": "done", "manifest": str(manifest_path.resolve())})
        return manifest


def dub(
    url: str,
    lang: str = "hindi",
    gender: str = "male",
    out: str | Path = "./output",
    source_lang: str = "auto",
    on_event: Optional[Callable[[dict], None]] = None,
    groq_api_key: Optional[str] = None,
    tts: str = "edge",
) -> dict:
    """One-call convenience wrapper around :class:`Dubber`.

    Set ``tts="kokoro"`` to use the local Kokoro-82M backend (Hindi/English for
    now); it falls back to edge-tts automatically if unavailable.
    """
    return Dubber(
        lang=lang, gender=gender, out_dir=out, source_lang=source_lang,
        on_event=on_event, groq_api_key=groq_api_key, tts=tts,
    ).run(url)
