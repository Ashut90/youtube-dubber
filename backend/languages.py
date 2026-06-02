"""
languages.py
Registry of all supported dubbing languages.

Usage in live_dub_v5.py (before importing other backend modules):
    import languages
    languages.configure("tamil", gender="male")

Other modules call languages.current() / languages.voice() at runtime,
so import order doesn't matter.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LangConfig:
    name: str           # Human-readable name, e.g. "Hindi"
    script: str         # Script description for the LLM prompt
    voice_male: str     # edge-tts male voice name
    voice_female: str   # edge-tts female voice name
    full_stop: str      # Sentence-ending character(s) for this language
    fillers: str        # Sample natural spoken fillers (shown to LLM)
    keep_english: bool  # True = Hinglish/code-switch style; False = full translation


# ── Registry ─────────────────────────────────────────────────────────────────

LANGUAGES: dict[str, LangConfig] = {

    # ── Indian languages ──────────────────────────────────────────────────────

    "hindi": LangConfig(
        name="Hindi", script="Hindi Devanagari",
        voice_male="hi-IN-MadhurNeural",   voice_female="hi-IN-SwaraNeural",
        full_stop="।", fillers="तो, देखिए, यानी, मतलब, सुनो",
        keep_english=True,
    ),
    "tamil": LangConfig(
        name="Tamil", script="Tamil script",
        voice_male="ta-IN-ValluvarNeural",  voice_female="ta-IN-PallaviNeural",
        full_stop=".", fillers="சரி, பாருங்கள், அதாவது, அப்படி",
        keep_english=True,
    ),
    "telugu": LangConfig(
        name="Telugu", script="Telugu script",
        voice_male="te-IN-MohanNeural",     voice_female="te-IN-ShrutiNeural",
        full_stop=".", fillers="సరే, చూడండి, అంటే, అలా అన్నమాట",
        keep_english=True,
    ),
    "bengali": LangConfig(
        name="Bengali", script="Bengali script",
        voice_male="bn-IN-BashkarNeural",   voice_female="bn-IN-TanishaaNeural",
        full_stop="।", fillers="তো, দেখুন, মানে, আসলে",
        keep_english=True,
    ),
    "marathi": LangConfig(
        name="Marathi", script="Devanagari",
        voice_male="mr-IN-ManoharNeural",   voice_female="mr-IN-AarohiNeural",
        full_stop="।", fillers="तर, पहा, म्हणजे, खरंच",
        keep_english=True,
    ),
    "gujarati": LangConfig(
        name="Gujarati", script="Gujarati script",
        voice_male="gu-IN-NiranjanNeural",  voice_female="gu-IN-DhwaniNeural",
        full_stop=".", fillers="તો, જુઓ, એટલે, ખરેખર",
        keep_english=True,
    ),
    "kannada": LangConfig(
        name="Kannada", script="Kannada script",
        voice_male="kn-IN-GaganNeural",     voice_female="kn-IN-SapnaNeural",
        full_stop=".", fillers="ಸರಿ, ನೋಡಿ, ಅಂದರೆ, ನಿಜವಾಗಿ",
        keep_english=True,
    ),
    "malayalam": LangConfig(
        name="Malayalam", script="Malayalam script",
        voice_male="ml-IN-MidhunNeural",    voice_female="ml-IN-SobhanaNeural",
        full_stop=".", fillers="ശരി, നോക്കൂ, അതായത്, യഥാർത്ഥത്തിൽ",
        keep_english=True,
    ),
    "punjabi": LangConfig(
        name="Punjabi", script="Gurmukhi script",
        voice_male="pa-IN-GurpreetNeural",  voice_female="pa-IN-VaaniNeural",
        full_stop="।", fillers="ਤਾਂ, ਦੇਖੋ, ਮਤਲਬ, ਅਸਲ ਵਿੱਚ",
        keep_english=True,
    ),
    "urdu": LangConfig(
        name="Urdu", script="Urdu Nastaliq script",
        voice_male="ur-IN-SalmanNeural",    voice_female="ur-IN-GulNeural",
        full_stop="۔", fillers="تو، دیکھیں، یعنی، اصل میں",
        keep_english=True,
    ),

    # ── International languages ───────────────────────────────────────────────

    "spanish": LangConfig(
        name="Spanish", script="Latin",
        voice_male="es-ES-AlvaroNeural",    voice_female="es-ES-ElviraNeural",
        full_stop=".", fillers="entonces, mira, o sea, es decir",
        keep_english=False,
    ),
    "french": LangConfig(
        name="French", script="Latin",
        voice_male="fr-FR-HenriNeural",     voice_female="fr-FR-DeniseNeural",
        full_stop=".", fillers="alors, donc, voilà, tu vois",
        keep_english=False,
    ),
    "german": LangConfig(
        name="German", script="Latin",
        voice_male="de-DE-ConradNeural",    voice_female="de-DE-KatjaNeural",
        full_stop=".", fillers="also, schau, das heißt, eigentlich",
        keep_english=False,
    ),
    "japanese": LangConfig(
        name="Japanese", script="Japanese (Kanji/Kana)",
        voice_male="ja-JP-KeitaNeural",     voice_female="ja-JP-NanamiNeural",
        full_stop="。", fillers="えっと、つまり、まあ、そうですね",
        keep_english=True,
    ),
    "chinese": LangConfig(
        name="Chinese (Simplified)", script="Chinese characters (Simplified)",
        voice_male="zh-CN-YunxiNeural",     voice_female="zh-CN-XiaoxiaoNeural",
        full_stop="。", fillers="那么, 就是说, 其实, 好的",
        keep_english=True,
    ),
    "korean": LangConfig(
        name="Korean", script="Hangul",
        voice_male="ko-KR-InJoonNeural",    voice_female="ko-KR-SunHiNeural",
        full_stop=".", fillers="그래서, 보세요, 즉, 사실",
        keep_english=True,
    ),
    "arabic": LangConfig(
        name="Arabic", script="Arabic",
        voice_male="ar-SA-HamedNeural",     voice_female="ar-SA-ZariyahNeural",
        full_stop=".", fillers="إذاً، انظر، يعني، في الحقيقة",
        keep_english=False,
    ),
    "portuguese": LangConfig(
        name="Portuguese (Brazil)", script="Latin",
        voice_male="pt-BR-AntonioNeural",   voice_female="pt-BR-FranciscaNeural",
        full_stop=".", fillers="então, olha, ou seja, na verdade",
        keep_english=False,
    ),
    "russian": LangConfig(
        name="Russian", script="Cyrillic",
        voice_male="ru-RU-DmitryNeural",    voice_female="ru-RU-SvetlanaNeural",
        full_stop=".", fillers="итак, смотрите, то есть, на самом деле",
        keep_english=False,
    ),
    "italian": LangConfig(
        name="Italian", script="Latin",
        voice_male="it-IT-DiegoNeural",     voice_female="it-IT-ElsaNeural",
        full_stop=".", fillers="allora, guarda, cioè, in realtà",
        keep_english=False,
    ),
}

# ── Runtime config ────────────────────────────────────────────────────────────

_current: LangConfig = LANGUAGES["hindi"]
_voice: str = _current.voice_male


def configure(lang_key: str, gender: str = "male") -> None:
    """
    Call this once at startup (before other modules are used).
    lang_key: one of the keys in LANGUAGES (e.g. "tamil", "spanish").
    gender:   "male" or "female" — selects the edge-tts voice.
    """
    global _current, _voice
    key = lang_key.lower().strip()
    if key not in LANGUAGES:
        available = ", ".join(sorted(LANGUAGES))
        raise ValueError(f"Unknown language '{key}'. Available: {available}")
    _current = LANGUAGES[key]
    _voice = _current.voice_male if gender == "male" else _current.voice_female
    print(f"[lang] {_current.name}  |  voice: {_voice}")


def current() -> LangConfig:
    return _current


def voice() -> str:
    return _voice
