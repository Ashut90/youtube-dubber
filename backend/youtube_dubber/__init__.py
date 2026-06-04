"""
youtube_dubber — dub any YouTube video into Hindi (and 19 other languages)
with a casual, engaging voice.

Quick start:

    from youtube_dubber import dub
    dub("https://youtu.be/VIDEO_ID", lang="hindi", gender="female", out="./out")

The dubbed audio clips land in ``out/audio/<videoId>_<lang>_<gender>/`` and a
``manifest.json`` describes every segment (timing, text, dubbed text, file).

Requires the ``yt-dlp``, ``ffmpeg`` system tools and a free Groq API key
(set ``GROQ_API_KEY`` or pass ``groq_api_key=``).
"""

from .core import Dubber, dub, DubError, video_id
from .languages import LANGUAGES, LangConfig

__version__ = "0.1.1"

__all__ = [
    "Dubber",
    "dub",
    "DubError",
    "video_id",
    "LANGUAGES",
    "LangConfig",
    "__version__",
]
