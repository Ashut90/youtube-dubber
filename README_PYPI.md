# 🎙️ youtube-dubber

[![PyPI version](https://img.shields.io/pypi/v/youtube-dubber.svg)](https://pypi.org/project/youtube-dubber/)
[![Python](https://img.shields.io/pypi/pyversions/youtube-dubber.svg)](https://pypi.org/project/youtube-dubber/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://github.com/Ashut90/youtube-dubber/blob/main/LICENSE)
[![GitHub](https://img.shields.io/badge/GitHub-Ashut90%2Fyoutube--dubber-181717?logo=github)](https://github.com/Ashut90/youtube-dubber)

**Dub any YouTube video into Hindi (and 19 other languages) with a casual, engaging neural voice — like a desi YouTuber, not a robotic narrator.**

Give it a URL → it pulls the captions, translates them to natural casual speech, generates a neural voice, and saves synced dubbed audio clips + a manifest. Fully headless — use it in scripts, servers, or pipelines.

![How it works](https://raw.githubusercontent.com/Ashut90/youtube-dubber/main/assets/how-it-works.png)

---

## ⚡ Quick start

```bash
pip install youtube-dubber
export GROQ_API_KEY=gsk_xxxxxxxx        # free key → https://console.groq.com/keys
```

```python
from youtube_dubber import dub

manifest = dub(
    "https://www.youtube.com/watch?v=VIDEO_ID",
    lang="hindi",       # any of 20 languages
    gender="female",    # "male" or "female"
    out="./out",
)
print(len(manifest["segments"]), "segments dubbed")
```

Or from the command line:

```bash
youtube-dubber --url https://youtu.be/VIDEO_ID --lang hindi --gender female --out ./out
```

**Output:** `out/audio/<videoId>_<lang>_<gender>/seg_NNNNN.mp3` clips + `out/manifest.json`.

---

## ⚠️ System Requirements

`pip install` brings the Python code, **but you must also have these on your system** (they are *not* pip-installable Python packages):

| Requirement | Why | Install |
|---|---|---|
| 🐍 **Python 3.10+** | runtime | — |
| 🎬 **ffmpeg** | audio conversion / time-stretch | `sudo apt install ffmpeg` · `brew install ffmpeg` · [windows](https://ffmpeg.org/download.html) |
| ⬇️ **yt-dlp** | fetches captions & stream info | `pip install -U yt-dlp` |
| 🔑 **Groq API key** | translation + Whisper STT (free tier) | [console.groq.com/keys](https://console.groq.com/keys) |
| 🌐 **Internet** | edge-tts calls Microsoft's neural voices | — |

> 💡 Install yt-dlp alongside the package: `pip install "youtube-dubber[ytdlp]"`
> **ffmpeg must be on your PATH** — it is a system binary, not a pip package.

---

## 🌍 Supported languages (20)

**Indian** (casual Hinglish / code-switch style — tech terms stay English):
Hindi · Tamil · Telugu · Bengali · Marathi · Gujarati · Kannada · Malayalam · Punjabi · Urdu

**International** (full translation):
Spanish · French · German · Japanese · Chinese · Korean · Arabic · Portuguese · Russian · Italian

Each has a **male & female** neural voice. **Source language is auto-detected** — dub an Arabic, Chinese, or English video into Hindi, all the same way.

---

## 🧠 Live progress (callback API)

```python
from youtube_dubber import Dubber

def on_event(ev):
    if ev["type"] == "progress":
        print(f"[{ev['step']}] {ev['pct']}%  {ev['msg']}")
    elif ev["type"] == "segment":
        print("dubbed:", ev["dubbed"])

Dubber(lang="hindi", gender="male", out_dir="./out", on_event=on_event).run(url)
```

**Event types:** `stream_url` · `progress` · `segment` · `done` · `error`

---

## ✨ Why it's different

- **Casual, not robotic** — prompt-tuned to sound like a real creator (*"तो भाई, scene ये है…"*), not a textbook
- **Auto language detection** — works on any source language out of the box
- **Disk cache** — re-running the same video is instant (no re-translation/TTS)
- **Rate-limit resilient** — automatic retries so segments never silently vanish
- **Fit-to-window timing** — clips are speed-matched (≤1.4×) so dubbing stays in sync without sounding sped-up

---

## 🖥️ Want the desktop app instead?

This package is the **headless engine**. There's also a full **Electron desktop app** (paste a URL, watch the dubbed video live with subtitles) and a **real-time Live Dub** mode — see the GitHub repo:

👉 **[github.com/Ashut90/youtube-dubber](https://github.com/Ashut90/youtube-dubber)**

---

## 📄 License

GPL-3.0 — © 2026 Ashutosh ([@Ashut90](https://github.com/Ashut90)).
Forks must stay open source and credit the original. See [LICENSE](https://github.com/Ashut90/youtube-dubber/blob/main/LICENSE).

Built with [Groq](https://groq.com) · [edge-tts](https://github.com/rany2/edge-tts) · [yt-dlp](https://github.com/yt-dlp/yt-dlp) · [ffmpeg](https://ffmpeg.org).
