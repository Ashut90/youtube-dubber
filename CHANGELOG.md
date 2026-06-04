# Changelog

All notable changes to **youtube-dubber** are documented here.

## [0.2.0] — 2026-06-05

A big quality + features release. Headline: an opt-in **local Kokoro-82M TTS
backend**, much more natural **educational Hinglish**, and **audio pacing** that
respects timing and punctuation.

### ✨ New
- **Kokoro-82M local TTS backend** (opt-in) — `Dubber(tts="kokoro")`,
  `dub(..., tts="kokoro")`, CLI `--tts kokoro`, or `YTDUB_TTS=kokoro`.
  More natural than edge-tts, runs locally (~300 MB, CPU or CUDA). Supports
  **Hindi + English** today; other languages and any failure **transparently
  fall back to edge-tts** — nothing breaks. See `KOKORO_SETUP.md`.
- **English as a dub target** (now 21 languages).
- **Emotion-based prosody** — per-segment emotion drives edge-tts pitch.
- **Live Dub (`live_dub_v6.py`): Kokoro + strict clock anchor** for the
  real-time pipeline (drift-safe over long runs).

### 🔧 Fixed
- **Translation quality / "welcome yaar" street slang** — the old slang
  dictionary literally forced `स्वागत है → वेलकम यार`. Replaced with a few-shot
  **educational-instructor prompt** (keeps a fluent Hindi spine, English only for
  technical terms) + a `polish_hinglish()` cleaner that rewrites slang artifacts
  back to natural forms (all spellings/cases).
- **Gender grammar** — the prompt now tells the model the speaker's gender, so a
  female voice uses feminine forms (रही हूँ, करूँगी) and male uses masculine.
- **Subtitle ≠ audio mismatch** — text is processed once, so the on-screen
  subtitle is exactly what's spoken.
- **Audio pacing** — punctuation → natural pauses (Hindi `।` → period; `…`
  breaths), and **bidirectional duration-matching** (0.85–1.15×) instead of the
  old one-way speed-up. No chipmunk, no dead air.
- **Sentence skipping / cut-offs** — Video URL mode no longer hard-trims clips
  (was cutting long Hindi sentence ends); seek detection is now backward-only so
  normal playback hiccups don't drop sentences.
- **Translation reliability** — try `llama-3.3-70b-versatile` first, fall back to
  `llama-3.1-8b-instant` on rate-limit, so output never stalls.
- **Interactive bugs** — seek-backward now replays the dub; changing voice or
  language **auto-re-dubs** (was a silent no-op); cross-language code-line
  handling.

### ⚠️ Notes
- Kokoro audio is cached separately (`*_kokoro` suffix) — never collides with
  edge-tts cache. Clearing `~/.config/yt-dubber/dubout/audio/` forces a fresh
  regen if you change the prompt/voice.

## [0.1.2] — 2026-06-03
- Fixed `Author: None` metadata on PyPI.

## [0.1.1] — 2026-06-03
- Dedicated library-focused PyPI README with rendered diagram.

## [0.1.0] — 2026-06-03
- First release: headless dubbing engine (`Dubber`, `dub`), 20 languages,
  YouTube captions → translate → edge-tts → cached MP3 segments + manifest.
