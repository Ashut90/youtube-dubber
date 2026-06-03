"""
youtube_dubber CLI.

    python -m youtube_dubber --url https://youtu.be/... --lang hindi --gender female

By default it prints human-readable progress. With ``--json`` it prints one
JSON object per line (used by the Electron app to drive its UI).
"""

import argparse
import json
import sys

from .core import Dubber, DubError


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="youtube_dubber",
                                description="Dub a YouTube video into another language.")
    p.add_argument("--url",    required=True, help="YouTube video URL")
    p.add_argument("--lang",   default="hindi", help="Target dub language (default: hindi)")
    p.add_argument("--gender", default="male", choices=["male", "female"])
    p.add_argument("--out",    default="./output", help="Output directory")
    p.add_argument("--source-lang", default="auto",
                   help="Source caption language code (e.g. en, ar, zh) or 'auto'")
    p.add_argument("--json", action="store_true",
                   help="Emit machine-readable JSON lines instead of text")
    args = p.parse_args(argv)

    if args.json:
        def on_event(ev):
            print(json.dumps(ev, ensure_ascii=False), flush=True)
    else:
        def on_event(ev):
            t = ev.get("type")
            if t == "progress":
                print(f"[{ev['step']}] {ev['pct']:>3}%  {ev.get('msg','')}")
            elif t == "segment":
                print(f"  ✓ seg {ev['index']:>4}  {ev.get('dubbed','')[:60]}")
            elif t == "stream_url":
                print("[stream] resolved video URL")
            elif t == "done":
                print(f"[done] manifest → {ev['manifest']}")

    try:
        Dubber(
            lang=args.lang, gender=args.gender, out_dir=args.out,
            source_lang=args.source_lang, on_event=on_event,
        ).run(args.url)
        return 0
    except DubError as e:
        if args.json:
            print(json.dumps({"type": "error", "msg": str(e)}, ensure_ascii=False), flush=True)
        else:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
