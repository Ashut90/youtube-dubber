"""
dub_video.py — Electron adapter for the youtube_dubber engine.

The dubbing logic now lives in the installable `youtube_dubber` package.
This thin wrapper keeps the exact CLI + stdout-JSON contract the Electron
app depends on:

  python3 dub_video.py --url ... --lang ... --gender ... --out ... [--source-lang ...]

Emits one JSON object per line to stdout:
  {"type": "stream_url", "url": "..."}
  {"type": "progress",   "step": "...", "pct": N, "msg": "..."}
  {"type": "segment",    "index": N, "start": .., "end": .., "text": .., "dubbed": .., "audio_file": ..}
  {"type": "done",       "manifest": "path"}
  {"type": "error",      "msg": "..."}
"""

import argparse
import json
import sys

from youtube_dubber.core import Dubber, DubError


def emit(obj: dict):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def main():
    import os
    p = argparse.ArgumentParser()
    p.add_argument("--url",    required=True)
    p.add_argument("--lang",   default="hindi")
    p.add_argument("--gender", default="male")
    p.add_argument("--out",    default="./output")
    p.add_argument("--source-lang", default="auto",
                   help="Source caption language code (e.g. en, zh, ar, ja) or 'auto' to detect.")
    p.add_argument("--tts", default=os.environ.get("YTDUB_TTS", "edge"),
                   choices=["edge", "kokoro"],
                   help="TTS backend. 'kokoro' uses local GPU (opt-in), falls back to edge.")
    args = p.parse_args()

    try:
        Dubber(
            lang=args.lang,
            gender=args.gender,
            out_dir=args.out,
            source_lang=args.source_lang,
            on_event=emit,        # every engine event → a JSON line on stdout
            tts=args.tts,
        ).run(args.url)
    except DubError as e:
        emit({"type": "error", "msg": str(e)})
        sys.exit(1)


if __name__ == "__main__":
    main()
