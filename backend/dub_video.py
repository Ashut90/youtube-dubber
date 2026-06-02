"""
dub_video.py — Video dubbing pipeline (streaming, no full download)

Flow:
  1. Get direct stream URL from yt-dlp  (~3s, no download)
  2. Download only captions VTT         (~2s)
  3. Merge + translate captions          (batch, Groq)
  4. Generate TTS per segment            (parallel, edge-tts)
  5. Time-stretch audio clips            (ffmpeg)

Output: JSON lines to stdout for Electron to parse.
  {"type": "stream_url", "url": "..."}              → video plays immediately
  {"type": "progress",   "step": "...", "pct": N}   → progress bar
  {"type": "segment",    ...}                        → one dubbed segment ready
  {"type": "done",       "manifest": "path"}         → all done
  {"type": "error",      "msg": "..."}
"""

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

import edge_tts
import languages

# Compiled at module level so parse_vtt and clean_text can both use them
_URL_RE    = re.compile(r'https?://\S+|www\.\S+', re.IGNORECASE)
_FILLER_RE = re.compile(r'^\s*\[.*?\]\s*$')

# ── Args ──────────────────────────────────────────────────────────────────────
_p = argparse.ArgumentParser()
_p.add_argument("--url",    required=True)
_p.add_argument("--lang",   default="hindi")
_p.add_argument("--gender", default="male")
_p.add_argument("--out",    default="./output")
_p.add_argument("--source-lang", default="auto",
                help="Source caption language code (e.g. en, zh, ar, ja) or 'auto' to detect.")
args = _p.parse_args()

languages.configure(args.lang, args.gender)
lang    = languages.current()
VOICE   = languages.voice()
OUT_DIR = Path(args.out)
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Helpers ───────────────────────────────────────────────────────────────────
def emit(obj: dict):
    print(json.dumps(obj, ensure_ascii=False), flush=True)

def progress(step: str, pct: int, msg: str = ""):
    emit({"type": "progress", "step": step, "pct": pct, "msg": msg})

def error(msg: str):
    emit({"type": "error", "msg": msg})
    sys.exit(1)

def _video_id(url: str) -> str:
    """Stable per-video cache key from a YouTube URL (falls back to a hash)."""
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)
    import hashlib
    return hashlib.md5(url.encode()).hexdigest()[:11]


# ── Step 1: Get stream URL (no download) ──────────────────────────────────────
def get_stream_url(url: str) -> str:
    progress("stream", 0, "Getting video stream URL…")
    result = subprocess.run(
        ["yt-dlp", "--get-url",
         "-f", "best[height<=720][ext=mp4]/bestvideo[height<=720]+bestaudio/best[height<=720]/best",
         "--no-playlist", url],
        capture_output=True, text=True,
    )
    urls = [u.strip() for u in result.stdout.strip().split("\n") if u.strip()]
    if not urls:
        error("Could not get stream URL. Check the URL.")
    # If yt-dlp returns two URLs (video + audio), use the first (video only for now).
    # Most yt-dlp calls for YouTube return a muxed URL when using 'best'.
    return urls[0]


# ── Step 2: Download captions only ───────────────────────────────────────────
def _video_language(url: str) -> str | None:
    """The video's declared spoken language (e.g. 'en', 'zh', 'ar'), or None."""
    r = subprocess.run(
        ["yt-dlp", "--print", "%(language)s", "--skip-download", "--no-playlist", url],
        capture_output=True, text=True,
    )
    code = r.stdout.strip().split("\n")[0].strip()
    return code if code and code.lower() not in ("na", "none", "") else None

def _fetch_subs(url: str, langs: str) -> Path | None:
    cap_out = OUT_DIR / "caps"
    for f in OUT_DIR.glob("caps.*.vtt"):
        f.unlink(missing_ok=True)
    subprocess.run([
        "yt-dlp", url,
        "--write-subs", "--write-auto-subs", "--sub-langs", langs,
        "--sub-format", "vtt", "--skip-download",
        "-o", str(cap_out), "--quiet", "--no-playlist",
    ], check=False)
    vtts = list(OUT_DIR.glob("caps.*.vtt"))
    return vtts[0] if vtts else None

# The source language actually used (set by get_captions); read by the fallback.
DETECTED_SRC = "en"

def get_captions(url: str) -> Path | None:
    global DETECTED_SRC
    progress("captions", 0, "Fetching captions…")

    # Decide which caption language to fetch:
    #   explicit --source-lang wins; otherwise use the video's declared language;
    #   otherwise fall back to English.
    if args.source_lang and args.source_lang != "auto":
        target = args.source_lang
    else:
        target = _video_language(url) or "en"

    # Try the chosen language, then English as a safety net
    for code in [target, "en"]:
        vtt = _fetch_subs(url, f"{code}.*,{code}")
        if vtt:
            DETECTED_SRC = code.split("-")[0].lower()   # e.g. 'ar-orig' → 'ar'
            progress("captions", 100, f"Captions ({code}) downloaded")
            return vtt

    progress("captions", 100, "No captions — will transcribe with Whisper")
    return None


# ── Step 3: Parse + merge captions ───────────────────────────────────────────
def parse_timestamp(ts: str) -> float:
    parts = ts.strip().split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    return int(parts[0]) * 60 + float(parts[1])


def parse_vtt(vtt_path: Path) -> list[dict]:
    text   = vtt_path.read_text(encoding="utf-8", errors="ignore")
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

        # YouTube rolling captions: each block has the previous complete line
        # on top and the NEW active line at the bottom (with <c> word tags).
        # Taking ALL lines and joining them doubles/triples the text.
        # Fix: strip HTML tags per line, then take only the LAST non-empty line
        # (the active/newest one). Also skip ~10 ms "snapshot" transition frames.
        content = [
            re.sub(r"<[^>]+>", "", l).strip()
            for l in lines
            if "-->" not in l and l.strip() and not l.strip().isdigit()
        ]
        if not content:
            continue
        body = re.sub(r"\s+", " ", content[-1]).strip()
        body = _URL_RE.sub('', body).strip()   # strip URLs before they reach the LLM
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


def transcribe_fallback(url: str) -> list[dict]:
    """Use Groq Whisper when no captions are available."""
    progress("transcribe", 0, "No captions — downloading audio for transcription…")
    audio_path = OUT_DIR / "audio.wav"
    subprocess.run([
        "yt-dlp", url, "-x", "--audio-format", "wav",
        "--audio-quality", "0",
        "-o", str(audio_path.with_suffix("")),
        "--quiet",
    ], check=False)

    if not audio_path.exists():
        error("Could not extract audio for transcription.")

    from groq import Groq
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    progress("transcribe", 50, "Transcribing with Whisper…")
    with open(audio_path, "rb") as f:
        stt_kwargs = dict(
            file=("audio.wav", f),
            model="whisper-large-v3-turbo",
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
        # Hint the source language when the user specified one; else auto-detect
        if args.source_lang and args.source_lang != "auto":
            stt_kwargs["language"] = args.source_lang
        resp = client.audio.transcriptions.create(**stt_kwargs)
    segments = [
        {"start": float(s["start"]), "end": float(s["end"]), "text": s["text"].strip()}
        for s in resp.segments
    ]
    progress("transcribe", 100, f"{len(segments)} segments transcribed")
    return segments


# ── Steps 4+5: Translate + TTS interleaved ───────────────────────────────────
BATCH_SIZE = 20  # larger batches = fewer API calls = less rate-limit wait total

SYSTEM_PROMPT = None
def get_system_prompt() -> str:
    global SYSTEM_PROMPT
    if SYSTEM_PROMPT:
        return SYSTEM_PROMPT

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
        # Code-switch languages (other Indian langs, Japanese, Chinese, Korean):
        # keep technical terms in English, translate everything else casually.
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
        # Full-translation languages (Spanish, French, German, Arabic, Russian…):
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

    SYSTEM_PROMPT = (
        f"Dub this video to {lang.name}. The source text may be in any language — "
        f"translate from whatever language it is. {eng}\n\n"
        f"For EACH numbered source line output: N|EMOTION|{lang.name} translation\n"
        f"EMOTION: excited neutral sad humorous concerned angry surprised\n"
        f"One output line per input line. No explanations."
    )
    return SYSTEM_PROMPT


# ── Post-processing: slang replacements & code masking ───────────────────────
_CODE_PATTERNS = re.compile(
    r'^\s*(sudo|chmod|grep|ls |cat |echo |for |while |if \[|\.\/|#!/|<[^>]+>|\$\w+)',
    re.IGNORECASE,
)

def clean_text(text: str) -> str:
    """Strip URLs, bracket fillers, and raw code from text before TTS."""
    # Remove URLs entirely (don't read them aloud)
    text = _URL_RE.sub('', text).strip()
    # Skip pure filler lines
    if _FILLER_RE.match(text):
        return ''
    # Replace code lines with a screen-prompt
    if _CODE_PATTERNS.search(text):
        return 'स्क्रीन पर दिख रहे इस code को ध्यान से देखो।'
    return text

# Keep the old name as alias so existing calls still work
mask_code_syntax = clean_text


_SLANG = {
    # Formal → casual
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
    # Tech jargon fixes
    "निर्देशिका":      "directory / folder",
    "प्रक्रिया":       "process",
    "पथ":              "path",
    "पुनरावृत्ति":     "loop",
    "त्रुटि":          "error",
    "समाधान":          "solution / jugaad",
    "जटिल":            "complex / भारी",
    "समारोह":          "function",
    # Engagement
    "आइए समझते हैं":   "तो भाई scene ये है कि",
    "यह महत्वपूर्ण है":"इसे दिमाग में बिठा लो!",
    "निष्कर्ष":        "सच्चाई तो ये है",
    "समस्या":          "locha",
}

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
    """Compress dubbed audio to fit the segment window so it doesn't get cut off
    by the next segment. ONLY speeds up (never slows down), capped at 1.4x to
    stay natural — no chipmunk. Short audio is left at its natural speed."""
    actual = get_audio_duration(src)
    if actual <= 0 or target_dur <= 0:
        return
    # Leave it alone if it already fits (within 5% headroom) or is shorter
    if actual <= target_dur * 1.05:
        return
    ratio = min(1.4, actual / target_dur)   # cap speed-up so it stays understandable
    out = src.replace(".mp3", "_s.mp3")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "quiet",
                    "-i", src, "-af", f"atempo={ratio:.3f}", out], check=False)
    if Path(out).exists():
        Path(src).unlink(missing_ok=True)
        Path(out).rename(src)


# ── Deduplication: skip segments too similar to recent ones ──────────────────
def is_duplicate_dub(text: str) -> bool:
    """Only skip exact character-for-character repeats of the immediately previous line."""
    if not hasattr(is_duplicate_dub, '_last'):
        is_duplicate_dub._last = ''
    if text.strip() == is_duplicate_dub._last.strip() and text.strip():
        return True
    is_duplicate_dub._last = text
    return False


async def _synth_one(text: str, path: str) -> bool:
    text = apply_slang(clean_text(text.strip()))
    if not text:
        return False

    # Hindi: slightly faster + higher pitch for YouTuber energy
    # Other languages: standard +10% rate
    rate  = "+12%" if lang.name == "Hindi" else "+10%"
    pitch = "+1Hz" if lang.name == "Hindi" else "+0Hz"

    communicate = edge_tts.Communicate(text, VOICE, rate=rate, pitch=pitch)
    mp3 = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3 += chunk["data"]
    if mp3:
        with open(path, "wb") as f:
            f.write(mp3)
        return True
    return False


async def translate_tts_pipeline(segments: list[dict], audio_dir: Path):
    """
    Interleaved pipeline: translate batch → TTS batch → emit → next batch.
    First dubbed audio arrives ~30s after start, not after all 4000+ translate.
    """
    from groq import Groq
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    total  = len(segments)
    sem    = asyncio.Semaphore(4)

    async def do_tts(b_offset: int, seg: dict, audio_dir: Path):
        gi        = b_offset
        path      = str(audio_dir / f"seg_{gi:05d}.mp3")
        meta_path = audio_dir / f"seg_{gi:05d}.json"

        # Cache hit — emit immediately without re-generating
        if Path(path).exists():
            if meta_path.exists():
                cached = json.loads(meta_path.read_text())
            else:
                cached = {"start": seg["start"], "end": seg["end"],
                          "text": seg["text"], "dubbed": seg["text"], "emotion": "neutral"}
            emit({"type": "segment", "index": gi, **cached, "audio_file": path})
            return

        # Cache miss — translate result must already be in seg["dubbed"]
        dubbed = seg.get("dubbed", "")
        if not dubbed:
            return

        # Skip if dubbed text is too similar to a recent segment (slide header loop)
        if is_duplicate_dub(dubbed):
            print(f"[dedup] skipped duplicate dubbed segment {gi}", file=sys.stderr)
            return

        # One bad TTS call must never crash the whole pipeline
        try:
            async with sem:
                ok = await _synth_one(dubbed, path)
        except Exception as e:
            print(f"[tts] segment {gi} failed: {e}", file=sys.stderr)
            return
        if ok:
            stretch(path, seg["end"] - seg["start"])
            metadata = {"start": seg["start"], "end": seg["end"],
                        "text": seg["text"], "dubbed": dubbed,
                        "emotion": seg.get("emotion", "neutral")}
            meta_path.write_text(json.dumps(metadata, ensure_ascii=False))
            emit({"type": "segment", "index": gi, **metadata, "audio_file": path})

    for b in range(0, total, BATCH_SIZE):
        batch  = segments[b: b + BATCH_SIZE]
        b_end  = b + len(batch)
        pct    = int(b / total * 100)

        # All audio cached — skip translate API entirely
        if all((audio_dir / f"seg_{b+i:05d}.mp3").exists() for i in range(len(batch))):
            progress("tts", int(b_end / total * 100), f"{b_end}/{total} segments ready (cached)")
            await asyncio.gather(*[do_tts(b + i, s, audio_dir) for i, s in enumerate(batch)])
            continue

        progress("translate", pct, f"Batch {b//BATCH_SIZE + 1}/{(total+BATCH_SIZE-1)//BATCH_SIZE} — segments {b+1}–{b_end}")

        # Translate this batch — RETRY on rate limit so no segment is ever dropped
        lines = "\n".join(f"{i+1}. {s['text']}" for i, s in enumerate(batch))
        got_translation = False
        for attempt in range(6):           # up to 6 tries per batch
            try:
                resp = client.chat.completions.create(
                    model="llama-3.1-8b-instant",   # high rate limit on free tier
                    messages=[{"role": "system", "content": get_system_prompt()},
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
                    progress("translate", pct, f"Rate limited — retry {attempt+1}/6 in 6s…")
                    await asyncio.sleep(6)
                else:
                    print(f"[translate] error: {e}", file=sys.stderr)
                    await asyncio.sleep(2)

        # Fallback when translation never succeeded (rate-limited/down):
        #   - English source → dub the original text (still understandable-ish)
        #   - other source   → skip; dubbing e.g. Arabic with a Hindi voice fails
        #     (edge-tts NoAudioReceived) and would crash/garble. Leave silent.
        if not got_translation and DETECTED_SRC == "en":
            for s in batch:
                if not s.get("dubbed"):
                    s["dubbed"] = s["text"]

        await asyncio.gather(*[do_tts(b + i, s, audio_dir) for i, s in enumerate(batch)])
        progress("tts", int(b_end / total * 100), f"{b_end}/{total} segments ready")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if not os.environ.get("GROQ_API_KEY"):
        error("GROQ_API_KEY not set.")

    # 1. Stream URL — sent immediately so video plays while rest processes
    stream_url = get_stream_url(args.url)
    emit({"type": "stream_url", "url": stream_url})

    # 2. Captions
    vtt = get_captions(args.url)
    if vtt:
        segments = parse_vtt(vtt)
        segments = merge_segments(segments)
    else:
        segments = merge_segments(transcribe_fallback(args.url))

    progress("captions", 100, f"{len(segments)} segments")

    # 3 + 4. Translate + TTS interleaved:
    #   Translate batch N → immediately TTS batch N → user hears first audio
    #   in ~30-60s instead of waiting for all 4000+ segments to translate first.
    #   Cache is namespaced by video + target lang + gender so different videos
    #   (and different dub languages) never reuse each other's audio.
    vid = _video_id(args.url)
    audio_dir = OUT_DIR / "audio" / f"{vid}_{args.lang}_{args.gender}"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # Tell the UI which voice is being used so the user knows it's generating
    existing = len(list(audio_dir.glob("seg_*.mp3")))
    total_segs = len(segments)
    if existing == 0:
        progress("tts", 0, f"Generating {lang.name} ({args.gender}) dub from scratch — first run takes ~1 min…")
    elif existing < total_segs:
        progress("tts", int(existing/total_segs*100), f"Resuming {lang.name} ({args.gender}) dub — {existing}/{total_segs} cached…")

    asyncio.run(translate_tts_pipeline(segments, audio_dir))

    # 5. Final manifest
    manifest = {
        "stream_url": stream_url,
        "lang":       lang.name,
        "segments":   [
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
    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    progress("tts", 100, "All segments ready")
    emit({"type": "done", "manifest": str(manifest_path.resolve())})


if __name__ == "__main__":
    main()
