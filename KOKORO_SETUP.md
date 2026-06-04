# Kokoro-82M TTS — Local GPU Setup & Verification (RTX 2060)

This is the **opt-in** local TTS backend. It is **not required** — if anything
below isn't set up, the app automatically uses edge-tts and works normally.
Supported languages for Kokoro right now: **Hindi, English**. Everything else
uses edge-tts.

> ⚠️ I (the author's assistant) could **not** test this on a real GPU. Treat every
> step as "verify, don't assume." The exact voice IDs and language codes can vary
> between `kokoro-onnx` versions — Step 4 shows how to confirm them on your box.

---

## Step 1 — Install the runtime

```bash
# Ubuntu 24.04+ blocks system-wide pip by default (PEP 668). Use the same
# --break-system-packages flag your other deps (edge-tts, groq) use, so Kokoro
# lands where the app's system python3 can find it:
pip install kokoro-onnx onnxruntime-gpu numpy --break-system-packages

# CPU-only (or if CUDA is flaky) — plain onnxruntime instead of -gpu:
# pip install kokoro-onnx onnxruntime numpy --break-system-packages
```

> Why not a venv? The Electron app runs the **system** `python3`. A venv-installed
> Kokoro wouldn't be visible to it — so for this project, system-wide install is
> the working choice.

✅ **Check:** `python -c "import kokoro_onnx; print('kokoro-onnx OK')"`

---

## Step 2 — Download the model files (~310 MB)

```bash
cd ~/yt-hindi-dubber/backend     # keep them next to where you run from

# Model + voices (from the kokoro-onnx releases):
wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```

✅ **Check:** both files exist and `kokoro-v1.0.onnx` is ~310 MB.

> If you store them elsewhere, point the app at them:
> ```bash
> export KOKORO_MODEL=/path/to/kokoro-v1.0.onnx
> export KOKORO_VOICES=/path/to/voices-v1.0.bin
> ```

---

## Step 3 — Confirm CUDA is actually used (RTX 2060)

```bash
python -c "import onnxruntime as ort; print(ort.get_available_providers())"
```

✅ **Want to see:** `['CUDAExecutionProvider', 'CPUExecutionProvider']`
❌ If you only see `CPUExecutionProvider`, CUDA isn't wired up — Kokoro still
runs on CPU (fine for dubbing saved videos, slower for real-time). Your NVIDIA
driver must be loaded (`nvidia-smi` should work).

---

## Step 4 — Verify the voice IDs & language codes for YOUR version

The app maps languages → Kokoro voices in `backend/youtube_dubber/core.py`
(`KOKORO_VOICES`). Defaults:

| Language | Male | Female | lang code |
|---|---|---|---|
| English | `am_michael` | `af_heart` | `en-us` |
| Hindi | `hm_omega` | `hf_alpha` | `hi` |

Confirm these voices exist in your downloaded `voices-v1.0.bin`:

```bash
python - <<'PY'
from kokoro_onnx import Kokoro
k = Kokoro("kokoro-v1.0.onnx", "voices-v1.0.bin")
voices = list(getattr(k, "voices", []) or [])
print("Total voices:", len(voices))
print("Hindi:",   [v for v in voices if v.startswith(("hf_","hm_"))])
print("English:", [v for v in voices if v.startswith(("af_","am_"))][:8])
PY
```

If the Hindi voices are named differently in your build, edit `KOKORO_VOICES`
in `core.py` to match.

---

## Step 5 — Smoke-test synthesis directly (no YouTube, no Groq)

```bash
python - <<'PY'
from kokoro_onnx import Kokoro
import numpy as np, soundfile as sf   # pip install soundfile if needed
k = Kokoro("kokoro-v1.0.onnx", "voices-v1.0.bin")

for text, voice, lang, out in [
    ("Hello, this is a Kokoro test.", "af_heart", "en-us", "/tmp/k_en.wav"),
    ("नमस्ते दोस्तों, यह एक test है।", "hf_alpha", "hi",    "/tmp/k_hi.wav"),
]:
    samples, sr = k.create(text, voice=voice, speed=1.0, lang=lang)
    sf.write(out, samples, sr)
    print("wrote", out, "sr=", sr, "len=", len(samples))
PY
# Listen:
ffplay -nodisp -autoexit /tmp/k_en.wav
ffplay -nodisp -autoexit /tmp/k_hi.wav
```

✅ **Want:** clear, natural English and Hindi audio.
❌ If `k.create(...)` errors on the `lang=` arg, your version may use a different
code (e.g. `"h"` instead of `"hi"`). Adjust the `lang` value in `KOKORO_VOICES`.

---

## Step 6 — Test through the library (with fallback safety)

```bash
export GROQ_API_KEY=gsk_xxxx
python - <<'PY'
from youtube_dubber import Dubber
def ev(e):
    if e["type"] == "segment": print("DUB:", e["dubbed"][:60])
    elif e["type"] == "progress": print(e["step"], e.get("msg","")[:50])
# Hindi via Kokoro — falls back to edge-tts automatically if Kokoro fails
Dubber(lang="hindi", gender="female", out_dir="/tmp/kokoro_run",
       tts="kokoro", on_event=ev).run("https://www.youtube.com/watch?v=SHORT_VIDEO")
PY
```

- Kokoro audio is cached under `/tmp/kokoro_run/audio/<id>_hindi_female_kokoro/`
  (note the `_kokoro` suffix — it never overwrites your edge-tts cache).
- Watch stderr: `[kokoro] loaded (...)` = Kokoro active.
  `[kokoro] unavailable → using edge-tts (...)` = it fell back (and still worked).

---

## Step 7 — Use Kokoro in the desktop app

```bash
cd ~/yt-hindi-dubber/frontend
export GROQ_API_KEY=gsk_xxxx
export YTDUB_TTS=kokoro        # opt in; unset or "edge" → edge-tts
npm start
```

Dub a Hindi or English video. If Kokoro isn't set up, the app **still works**
on edge-tts — you'll just see the `[kokoro] unavailable` note in the terminal.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `[kokoro] unavailable` always | model files missing / wrong path → set `KOKORO_MODEL`, `KOKORO_VOICES` |
| Only `CPUExecutionProvider` | install `onnxruntime-gpu`; check `nvidia-smi` works |
| `create()` errors on `lang=` | your version uses a different code — adjust in `KOKORO_VOICES` |
| Voice not found | run Step 4, use a voice ID that actually exists in your `.bin` |
| Hindi sounds wrong/garbled | try the other Hindi voice (`hf_beta` / `hm_psi`) |
| Out of VRAM | Kokoro is ~300 MB; close other GPU apps, or use CPU provider |

---

## How to expand to more languages later

Kokoro v1.0 also supports Spanish, French, Italian, Portuguese, Japanese,
Chinese. Once Hindi + English are verified, add entries to `KOKORO_VOICES` in
`core.py` (voice IDs + lang code per Step 4) — unsupported languages keep using
edge-tts automatically.
