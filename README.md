# YT Dubber

[![CI](https://github.com/Ashut90/youtube-dubber/actions/workflows/ci.yml/badge.svg)](https://github.com/Ashut90/youtube-dubber/actions/workflows/ci.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Discussions](https://img.shields.io/badge/💬-Discuss-blueviolet)](../../discussions)
[![Download](https://img.shields.io/badge/⬇️-Download%20AppImage-orange.svg)](../../releases/latest)

> If you want to try it or build on it, please **fork the repo** instead of cloning straight —
> that way you can actually open a PR and contribute back.
>
> It's **GPL-3.0**: build on it all you want, just keep your version open-source and
> credit the original. Details in [LICENSE](LICENSE).

"Learn from anywhere" sounds great — until you find an amazing tutorial and it's in a language you don't understand. That's happened to me more than a few times.

I'd come across genuinely good, hands-on content, but the language barrier would kill the momentum. I tried following along with slides and auto-generated subtitles, but it just wasn't the same.

So I built **youtube-dubber** — a tool that actually solves this, for me and hopefully for others. You point it at any YouTube video and it dubs the thing into Hindi (or 20 other languages) with a natural, casual-sounding voice, not a flat robotic narrator.

You get the original video, the dubbed audio, and synced subtitles, all playing together. There's also a **Live Dub** mode that translates anything playing on your machine in real time — a browser, a media player, a call. And it works both as a desktop app and as a Python package you can drop into your own code.

Under the hood I used Groq for fast translation, Whisper for transcription, and good neural voices (with a local option too). It caches everything, so watching the same video again is instant, and it works hard to keep the timing natural.

This started as my own fix for a problem I kept hitting as a learner. I'm hoping it helps other students, developers, and anyone who wants to learn from global content without getting stuck on the language.

---

## Demo

A quick run-through — dubbing a video and switching between languages:

https://github.com/Ashut90/youtube-dubber/releases/download/v0.2.0/youtube-dubber-demo.mp4

*(If the player doesn't load, [watch/download the demo here](https://github.com/Ashut90/youtube-dubber/releases/download/v0.2.0/youtube-dubber-demo.mp4).)*

---

## What it looks like

![App UI Preview](assets/ui-preview.svg)

The **video plays in a separate mpv window** (full quality). The Electron window is the control panel — subtitles, progress, and volume sliders. Both stay in sync via mpv's IPC socket.

---

## How It Works

![How It Works](assets/how-it-works.svg)

---

## The two modes

There are two ways to use it, depending on what you're dubbing:

| | **Video URL** | **Live Dub** |
|---|---|---|
| **Works on** | Linux, macOS, Windows | Linux only |
| **Source** | YouTube captions (any language) | Live mic / system audio |
| **Lag** | ~15s first run, instant on re-run | Always ~3–5s |
| **Cache** | ✅ Saves MP3 + JSON per segment | ❌ Real-time only |
| **Best for** | YouTube courses, tutorials | Streams, calls, any video |

---

## Source & Target Languages

- **Source:** Any language — the app auto-detects via the video's declared language
  and fetches its native captions. Pass `--source-lang <code>` (e.g. `ar`, `zh`, `en`) to force one.
- **Target:** 21 languages. **Hindi** gets the full educational-instructor Hinglish
  prompt; the rest get a clear, conversational prompt in their own language.
- **Voice engine:** **edge-tts** (cloud, all languages) by default, or opt-in
  **Kokoro-82M** (local, more natural, Hindi/English) via `--tts kokoro` /
  `YTDUB_TTS=kokoro` — falls back to edge-tts automatically. See [KOKORO_SETUP.md](KOKORO_SETUP.md).

---

## Why mpv instead of a built-in video player

Electron's `<video>` element and Web Audio API crash with a **SIGSEGV** on Linux
machines with Optimus (Intel + NVIDIA) graphics — the GPU driver kills Chromium's
software renderer the moment it tries to decode video or create an `AudioContext`.

The fix: hand all media off to **mpv** (a native video player) and control it via
its JSON IPC socket. The Electron window becomes a pure HTML/CSS control panel
that never touches the GPU — it just shows subtitles, sliders, and status.

---

## Requirements

- **OS** — Linux (primary). **Video URL** mode also runs on macOS and **Windows**
  (the mpv IPC uses a named pipe on Windows, a socket elsewhere). **Live Dub** is
  **Linux-only** (it shells out to PulseAudio `parec`/`pacat`).
- **mpv** — `sudo apt install mpv` (macOS `brew install mpv`; Windows: add `mpv.exe` to PATH)
- **yt-dlp** — `pip install -U yt-dlp` (or distro package)
- **ffmpeg** — `sudo apt install ffmpeg`
- **Node.js 18+** and npm (for the Electron frontend)
- **Python 3.10+**
- A free **[Groq API key](https://console.groq.com/keys)**
- For **Live Dub** only: `pulseaudio-utils` (`parec`/`pacat`)

---

## Setup

### 0. Fork & clone

```bash
# 1. Click "Fork" on GitHub first, then:
git clone https://github.com/<YOUR_USERNAME>/youtube-dubber.git
cd youtube-dubber
git remote add upstream https://github.com/Ashut90/youtube-dubber.git
```

> Cloning the original repo directly means you can't contribute back. Fork first.

### 1. Backend (Python)

```bash
cd backend
pip3 install --break-system-packages -r requirements.txt
pip install -U yt-dlp        # must also be on PATH
```

> **Video URL** mode only needs `edge-tts` + `groq` + `yt-dlp`. The extra `numpy`/`silero-vad` deps are for **Live Dub** mode.

### 2. Frontend (Electron)

```bash
cd frontend
npm install
```

### 3. Groq API key

```bash
export GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxx
```

Get a free key at [console.groq.com/keys](https://console.groq.com/keys). Export it in the same shell you launch the app from, so the spawned Python process inherits it.

---

## Running — Video URL mode (main feature)

```bash
cd frontend
export GROQ_API_KEY=gsk_xxxx
npm start
```

1. Paste a YouTube URL and pick a language + voice.
2. Click **Dub It**. An mpv window opens with the video (it starts **paused** while the first few seconds of dub are generated, then plays automatically).
3. Watch the video in the mpv window; the dubbed audio + subtitles play through the app.

**First run on a new video** rebuilds the cache and is gated by Groq's rate limit (~5s between batches), so a long video takes a while to fully process — but playback begins as soon as the opening buffer is ready, and the buffer-sync keeps audio aligned. **Subsequent runs on the same video are near-instant** thanks to the disk cache.

> Tip: don't seek far ahead during the first pass — the dub is generated sequentially from `0:00`. After a full run, the cache covers the whole video and seeking anywhere works instantly. (The app also strips any `&t=` start-time from the URL and forces the video to start at `0:00` to stay aligned with generation.)

---

## Running — Live Dub mode (any system audio)

This dubs whatever is playing on your machine in real time.

### 1. Create a virtual audio sink

```bash
pactl load-module module-null-sink sink_name=DubCapture \
  sink_properties=device.description=DubCapture
```

### 2. Route the source audio to it

Open **pavucontrol** → **Playback** tab → set the browser/player output to **DubCapture**.

### 3. Start it

Use the **Live Dub** tab in the app, or run the backend directly:

```bash
cd backend
export GROQ_API_KEY=gsk_xxxx
python3 live_dub_v6.py --lang hindi --gender male
```

The 5-agent pipeline (capture → Groq Whisper STT → Groq translate → edge-tts → playback) prints the live transcript and plays the dub through your speakers within a few seconds of each phrase. `Ctrl+C` to stop.

> **Lag floor ~3–5s** is inherent to live mode: a full phrase must be heard before it can be transcribed and translated.

---

## Use as a Python library

The dubbing engine ships as an installable package — use it in your own code,
scripts, or server with no GUI.

```bash
pip install youtube-dubber      # plus: yt-dlp + ffmpeg on PATH, and a Groq key
export GROQ_API_KEY=gsk_xxxx
```

```python
from youtube_dubber import dub

# One call → dubbed MP3 clips + a manifest.json in ./out
manifest = dub(
    "https://www.youtube.com/watch?v=VIDEO_ID",
    lang="hindi",      # any of the 20 supported languages
    gender="female",   # "male" or "female"
    out="./out",
)
print(len(manifest["segments"]), "segments dubbed")
```

Want live progress? Pass an `on_event` callback:

```python
from youtube_dubber import Dubber

def on_event(ev):
    if ev["type"] == "progress":
        print(ev["step"], ev["pct"], ev["msg"])
    elif ev["type"] == "segment":
        print("dubbed:", ev["dubbed"])

Dubber(lang="hindi", gender="male", out_dir="./out", on_event=on_event).run(url)
```

Or from the command line:

```bash
youtube-dubber --url https://youtu.be/VIDEO_ID --lang hindi --gender female --out ./out
```

> Output: `out/audio/<videoId>_<lang>_<gender>/seg_NNNNN.mp3` clips + `out/manifest.json`.
> The Electron desktop app is just one consumer of this same engine.

---

## Supported languages

Hindi, Tamil, Telugu, Bengali, Marathi, Gujarati, Kannada, Malayalam, Punjabi, Urdu, Spanish, French, German, Japanese, Chinese, Korean, Arabic, Portuguese, Russian, Italian, English.

Each has a configured male/female edge-tts neural voice. Indian languages use a **Hinglish/code-switch** style (technical terms stay English); others translate fully. See `backend/youtube_dubber/languages.py`.

---

## Project layout

```
youtube-dubber/
├── pyproject.toml             pip package config (youtube-dubber)
├── setup.sh / setup.bat       one-command dependency installers
│
├── frontend/                  Electron desktop app
│   ├── main.js                main process: mpv control, dub queue, spawns Python
│   ├── preload.js             contextBridge IPC API
│   ├── package.json           electron + build config
│   └── renderer/
│       ├── index.html         control-panel UI
│       ├── app.js             buffer/sync logic, subtitle + playback scheduling
│       └── styles.css
│
└── backend/
    ├── youtube_dubber/        ★ the installable dubbing-engine package
    │   ├── __init__.py        public API: Dubber, dub, LANGUAGES
    │   ├── core.py            the engine (captions → translate → TTS → cache)
    │   ├── cli.py             `youtube-dubber` command + `python -m youtube_dubber`
    │   └── languages.py       20-language registry (voices, script, style)
    ├── dub_video.py           thin Electron adapter → calls the package
    ├── live_dub_v6.py         Live mode: 5-agent real-time pipeline
    ├── natural_tts.py         edge-tts wrapper used by Live Dub
    ├── vad.py                 Silero voice-activity detection (Live Dub)
    ├── languages.py           compatibility shim → youtube_dubber.languages
    └── requirements.txt
```

---

## Configuration

**Translation / TTS** — `backend/youtube_dubber/core.py`:

| Knob | Where | Effect |
|---|---|---|
| `BATCH_SIZE` | top of file | Segments per Groq call (fewer API round-trips vs. faster first audio) |
| model | `client.chat.completions.create(...)` | `llama-3.1-8b-instant` (reliable) vs. `llama-3.3-70b-versatile` (more casual, stricter rate limit) |
| `stretch()` cap | `stretch()` | Max speed-up to fit a clip to its window (default `1.4×`) |
| slang map | `_SLANG` dict | Formal → casual phrase replacements |
| TTS rate/pitch | `_synth_one()` | edge-tts `rate`/`pitch` per language |

**Playback sync** — `frontend/renderer/app.js`:

| Knob | Effect |
|---|---|
| `START_BUFFER` | Seconds of dub ready before first play (default 6) |
| `PAUSE_GAP` / `RESUME_GAP` | When to pause/resume mpv as it approaches the generation frontier |
| `STALE_DROP` (in `main.js`) | Drop a dub clip if its segment ended this far behind the playhead |

**Voices** — `backend/languages.py` (`voice_male` / `voice_female` per language).

---

## Stuff to know before you expect too much

I'd rather be upfront about the rough edges than have you discover them the hard way:

- **mpv plays in its own window**, not embedded in the app — a deliberate workaround for the Chromium SIGSEGV on Optimus systems.
- **8b translations are sometimes verbose**, so an occasional long sentence finishes slightly late or gets dropped to stay in sync (never cut mid-word). The cure is shorter translations / a stronger prompt.
- **Hindi is the best-tuned target.** The other 19 languages get a casual prompt too, but quality depends on the 8b model's fluency in that language.
- **Non-English source** relies on the video having captions in its own language (or being detectable by Whisper). Auto-detection via the declared language is reliable but not infallible — use `--source-lang` to force it.
- **Live Dub is Linux-only** (PulseAudio); the Video URL mode is the cross-platform one.
- **Groq free-tier rate limits** make the *first* pass on a long video slow; the cache makes re-runs fast.
- **edge-tts needs internet** (it calls Microsoft's servers).
- **Live Dub lag floor ~3–5s** is inherent to listen-then-translate.
- **Mixed Devanagari + Latin** script can occasionally trip TTS intonation.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| No dub audio at all | Groq key not exported in the launch shell; wait ~20–30s for first batch to clear the rate limit. |
| Female voice sounds like first run is slow | It is — female cache is separate from male. First female run generates everything fresh; re-runs are instant. |
| Dub plays but goes silent after a while | Video ran ahead of generation. Don't seek ahead on first pass; let the buffer-sync handle pacing. |
| Live Dub plays nothing | Make sure you routed your app's audio to **DubCapture** in pavucontrol first. |
| Live Dub crashes immediately on macOS/Windows | Live Dub is Linux-only (PulseAudio). Use Video URL mode on other OS. |
| mpv window doesn't open | `mpv` not installed — `sudo apt install mpv`. |
| Dub reads out URLs or bash commands | Cleared by `clean_text()`; if it persists, delete the cache and re-run. |
| Want fresh translations for a video | `rm -rf ~/.config/yt-dubber/dubout/audio/<videoId>_<lang>_<gender>/` |
| Want to force a specific source language | Add `--source-lang ar` (or `zh`, `en`, etc.) to the Python CLI or wait for UI support. |

Cache location: `~/.config/yt-dubber/dubout/audio/`.

---

## Contributing

I'd genuinely love help on this — more languages, better dubbing quality, bug fixes, anything.

- Found a bug or have an idea? [Open an issue](../../issues) or [start a discussion](../../discussions).
- Want to send code? Fork it, make your change, and open a PR (there's a short [CONTRIBUTING.md](CONTRIBUTING.md) with the steps).
- Built something on top of it? Show me in Discussions — I'd really like to see what people make with it.

---

## Credits

Built by [Ashutosh (@Ashut90)](https://github.com/Ashut90), GPL-3.0 ([LICENSE](LICENSE)).
If you fork it, please keep the credit and link back here, say what you changed, and keep your version open-source.

Standing on the shoulders of: [Groq](https://groq.com) · [edge-tts](https://github.com/rany2/edge-tts) · [Kokoro](https://github.com/thewh1teagle/kokoro-onnx) · [mpv](https://mpv.io) · [yt-dlp](https://github.com/yt-dlp/yt-dlp) · [Electron](https://www.electronjs.org)
