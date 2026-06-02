# YT Dubber

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Discussions](https://img.shields.io/badge/💬-Discuss-blueviolet)](../../discussions)

> **Want to try it or contribute? [Fork this repo](../../fork) — do not clone directly.**
>
> 🔒 **This project is GPL-3.0 licensed.** You must credit the original author and
> keep your modifications open source. Forking for private/commercial use without
> releasing your source code is not permitted. See [LICENSE](LICENSE).

Desktop app that **dubs YouTube videos into Hindi (and 19 other languages)** with a casual, engaging voice — like an Indian tech YouTuber, not a flat textbook narrator.

Paste a YouTube URL, and the app plays the video while generating and playing a synced dub on top. It pulls the video's captions, translates them to natural spoken Hinglish, synthesizes neural speech, and plays everything in sync — with a live transcript and on-screen subtitles.

A second **Live Dub** mode dubs *any* system audio in real time (browser, media player, calls) by capturing the audio device directly.

---

## What it looks like

```
┌──────────────────────────────────────────────────────────┐
│  🎙 YT Dubber                                 ▶ Playing   │
│  ┌────────────────────────────────────────────────────┐  │
│  │ [ Video URL ]   Live Dub                            │  │
│  │                                                     │  │
│  │  https://youtube.com/watch?v=...        [ ▶ Dub It ]│  │
│  │  Language: Hindi ▾     Voice: ( Male ) Female        │  │
│  │  ████████░░░░░  Translating batch 12/242…           │  │
│  │                                                     │  │
│  │  ▶ Video playing in mpv window — keep it open  22:25│  │
│  │                                                     │  │
│  │  subject matter of the course, the audience…        │  │
│  │  ┌────────────────────────────────────────────────┐ │  │
│  │  │ अब बॉस, regular expressions की बारी है! ये       │ │  │
│  │  │ powerful text matching और substitution देते हैं! │ │  │
│  │  └────────────────────────────────────────────────┘ │  │
│  │  🔇 Original ──●────   🔊 Dubbed ──────────●        │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

The **video renders in a separate mpv window** (more on why below). The Electron window is the control panel: it shows progress, original + dubbed subtitles, and volume sliders, and it plays the dubbed audio in sync with mpv's playhead.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                         ELECTRON APP                               │
│                                                                    │
│  Renderer (renderer/app.js)          Main process (main.js)        │
│  ────────────────────────────        ──────────────────────────    │
│  • Control panel UI                  • spawns mpv (video window)    │
│  • Subtitles + sliders               • mpv IPC socket: time-pos,   │
│  • Buffer/sync logic                   pause, volume                │
│  • Decides which dub clip       ───► • sequential dub-audio queue   │
│    to play at the current              (mpv, one clip at a time)    │
│    playhead                          • spawns Python backend        │
│                                                                    │
└───────────────────────────────┬──────────────────────────────────┘
                                 │ JSON lines over stdout
                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│              PYTHON BACKEND — Video URL mode (dub_video.py)         │
│                                                                    │
│  yt-dlp ──► caption VTT ──► parse + merge into ~5s segments         │
│      │                                                             │
│      ▼  (batches of 20)                                            │
│  Groq llama-3.1-8b-instant  ──  English → casual spoken Hinglish    │
│      │   (retry on rate-limit, English fallback)                   │
│      ▼                                                             │
│  edge-tts (MadhurNeural / SwaraNeural)  ──  neural TTS (free)       │
│      │   slang dictionary + URL/code stripping                     │
│      ▼                                                             │
│  ffmpeg atempo  ──  fit clip to its time window (≤1.4×, no chipmunk)│
│      │                                                             │
│      ▼                                                             │
│  cache to disk: seg_NNNNN.mp3 + seg_NNNNN.json  ──  instant re-runs │
└──────────────────────────────────────────────────────────────────┘
```

### Two modes

| Mode | Backend | Source of speech | Best for |
|---|---|---|---|
| **Video URL** | `backend/dub_video.py` | YouTube caption track (yt-dlp) | YouTube videos, courses, tutorials |
| **Live Dub** | `backend/live_dub_v6.py` | System audio → Groq Whisper STT | Anything playing on your machine |

### Source & target languages

- **Source** can be any language. The Video URL mode reads the video's *declared*
  language and pulls its native captions automatically (falling back to English,
  then to Whisper transcription). Pass `--source-lang <code>` to force one.
  Live Dub auto-detects the spoken language with Whisper.
- **Target** is any of the 20 languages below. **Hindi** has the most-tuned
  casual-creator prompt; the other 19 now also get an engaging, casual prompt
  (using each language's natural fillers) rather than flat textbook translation.

---

## Why mpv instead of an in-app `<video>` player

Early versions played video with an HTML5 `<video>` element + the Web Audio API inside Electron. On Linux machines with **Optimus (Intel + NVIDIA) graphics**, Chromium's software video/audio path **segfaults** (`exit code 139`) the moment it decodes video or creates an `AudioContext`.

The fix was to stop using Chromium for media entirely:
- **Video** plays in a real `mpv` window, launched and controlled by the Electron main process over mpv's JSON IPC socket (`time-pos`, `pause`, `volume`).
- **Dubbed audio** plays as short `mpv` clips spawned by the main process — never touching the browser audio engine.

The Electron window stays a pure HTML/CSS control panel, which never crashes.

---

## Key design decisions

- **Sequential dub queue (no mid-sentence cutoff).** Dub clips play one at a time, each to completion. If a clip falls more than ~4s behind the video, it's dropped whole rather than cut mid-word. (`main.js` → `pumpDubQueue`)
- **Buffer-then-play sync.** mpv starts paused. Once ~6s of dub is generated, it's released. If the playhead catches up to where Python has dubbed, mpv pauses and rebuilds buffer, then resumes. (`renderer/app.js` → `checkBuffer`)
- **Fit-to-window time-stretch.** Hinglish is often longer than the English it replaces. Clips that overrun their slot are sped up via `ffmpeg atempo`, capped at **1.4×** so they never sound like a chipmunk; shorter clips are left untouched.
- **Disk cache.** Every segment is saved as `seg_NNNNN.mp3` + a `.json` sidecar (text, timing, emotion). Re-running the same video skips translation/TTS entirely and starts almost instantly.
- **Rate-limit resilience.** Groq batches retry up to 6× on `429`; if all retries fail, the segment dubs the original text so audio never silently disappears.
- **Casual Hinglish.** The translation prompt is tuned for an energetic creator voice (`तो भाई`, `यार`, `बॉस`, keep technical terms in English), with a slang dictionary post-pass and code/URL stripping so the TTS never reads out `www.…` or raw bash.

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
git clone https://github.com/<YOUR_USERNAME>/yt-hindi-dubber.git
cd yt-hindi-dubber
git remote add upstream https://github.com/ahsutosh/yt-hindi-dubber.git
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

## Supported languages

Hindi, Tamil, Telugu, Bengali, Marathi, Gujarati, Kannada, Malayalam, Punjabi, Urdu, Spanish, French, German, Japanese, Chinese, Korean, Arabic, Portuguese, Russian, Italian.

Each has a configured male/female edge-tts neural voice. Indian languages use a **Hinglish/code-switch** style (technical terms stay English); others translate fully. See `backend/languages.py`.

---

## Project layout

```
yt-hindi-dubber/
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
    ├── dub_video.py           ★ Video URL mode: yt-dlp → translate → TTS → cache
    ├── live_dub_v6.py         ★ Live mode: 5-agent real-time pipeline
    ├── natural_tts.py         edge-tts wrapper used by Live Dub
    ├── vad.py                 Silero voice-activity detection (Live Dub)
    ├── languages.py           20-language registry (voices, script, style)
    └── requirements.txt
```

---

## Configuration

**Translation / TTS** — `backend/dub_video.py`:

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

## Known limitations & trade-offs

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
| No dub audio at all | Groq key not exported in the launch shell; or first batch still clearing the rate limit (wait ~20–30s). |
| Dub plays but is silent past a point | Python hasn't generated that region yet — don't seek ahead on the first pass. |
| Renderer window goes black | Old `<video>`/WebAudio path — current build uses mpv and shouldn't hit this. |
| mpv window doesn't open | `mpv` not installed or not on PATH (`sudo apt install mpv`). |
| Dub reads out URLs/code | Should be stripped by `clean_text()`; clear the cache (`rm -rf ~/.config/yt-dubber/dubout/audio`) and re-run. |
| Want fresh translations | Delete the cache dir above to force regeneration. |

Cache location: `~/.config/yt-dubber/dubout/audio/`.

---

## Contributing & Discussions

Found a bug? Have an idea? Want to add a language or improve the dubbing quality?

**Don't just fork silently — come talk:**

- 💬 **[Start a Discussion](../../discussions)** — ideas, questions, show your fork
- 🐛 **[Open an Issue](../../issues)** — bug reports
- 🔀 **[Submit a PR](../../pulls)** — code contributions (read [CONTRIBUTING.md](CONTRIBUTING.md) first)

If you've built something on top of this project, share it in Discussions — I want to see what people are creating.

---

## Credits & Attribution

**Original project:** YT Dubber  
**Author:** [ahsutosh](https://github.com/ahsutosh)  
**License:** GPL-3.0 — see [LICENSE](LICENSE)

If you fork this project, you **must**:
1. Keep this credits section or link back to this repo
2. State clearly what you changed
3. License your fork under GPL-3.0

Built with: [Groq API](https://groq.com) · [edge-tts](https://github.com/rany2/edge-tts) · [mpv](https://mpv.io) · [yt-dlp](https://github.com/yt-dlp/yt-dlp) · [Electron](https://www.electronjs.org)
