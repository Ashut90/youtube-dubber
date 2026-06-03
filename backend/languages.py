"""
languages.py — compatibility shim.

The real language registry now lives in the installable package at
`youtube_dubber/languages.py`. This shim re-exports it so the backend
scripts that still do `import languages` (live_dub_v6.py, natural_tts.py)
keep working unchanged.
"""

from youtube_dubber.languages import (   # noqa: F401
    LangConfig,
    LANGUAGES,
    configure,
    current,
    voice,
)
