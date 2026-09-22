"""Local CPU translation model registry.

The local fallback translates *to English*. Models are downloaded lazily from
Hugging Face the first time a selected source language needs local fallback.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LocalModelSpec:
    code: str
    label: str
    model_id: str
    license: str
    note: str = ""


# Keep the order close to the legacy src_lang combo so existing users can find
# familiar entries. ``auto`` / ``en`` / ``[No Translation]`` are intentionally
# not part of this registry: local fallback performs no language detection and
# all registered models translate a non-English source into English. ``auto`` is handled
# by resolving it to the configured Local CPU Auto Source Language before model selection.
LOCAL_MODEL_SPECS = {
    "ja": LocalModelSpec("ja", "Japanese", "Helsinki-NLP/opus-mt-ja-en", "Apache-2.0"),
    "zh-CN": LocalModelSpec(
        "zh-CN", "Chinese (Simplified)", "Helsinki-NLP/opus-mt-zh-en", "CC-BY-4.0",
        "Shares the Chinese -> English model with zh-TW.",
    ),
    "zh-TW": LocalModelSpec(
        "zh-TW", "Chinese (Traditional)", "Helsinki-NLP/opus-mt-zh-en", "CC-BY-4.0",
        "Shares the Chinese -> English model with zh-CN.",
    ),
    "ko": LocalModelSpec("ko", "Korean", "Helsinki-NLP/opus-mt-ko-en", "Apache-2.0"),
    "fr": LocalModelSpec("fr", "French", "Helsinki-NLP/opus-mt-fr-en", "Apache-2.0"),
    "de": LocalModelSpec("de", "German", "Helsinki-NLP/opus-mt-de-en", "Apache-2.0"),
    "es": LocalModelSpec("es", "Spanish", "Helsinki-NLP/opus-mt-es-en", "Apache-2.0"),
    "it": LocalModelSpec("it", "Italian", "Helsinki-NLP/opus-mt-it-en", "Apache-2.0"),
    "ru": LocalModelSpec("ru", "Russian", "Helsinki-NLP/opus-mt-ru-en", "CC-BY-4.0"),
    "pt": LocalModelSpec(
        "pt", "Portuguese", "Helsinki-NLP/opus-mt-ROMANCE-en", "Apache-2.0",
        "Uses the shared Romance-languages -> English Marian model.",
    ),
    "nl": LocalModelSpec("nl", "Dutch", "Helsinki-NLP/opus-mt-nl-en", "Apache-2.0"),
    "pl": LocalModelSpec("pl", "Polish", "Helsinki-NLP/opus-mt-pl-en", "Apache-2.0"),
    "tr": LocalModelSpec("tr", "Turkish", "Helsinki-NLP/opus-mt-tr-en", "Apache-2.0"),
    "ar": LocalModelSpec("ar", "Arabic", "Helsinki-NLP/opus-mt-ar-en", "Apache-2.0"),
    "hi": LocalModelSpec("hi", "Hindi", "Helsinki-NLP/opus-mt-hi-en", "Apache-2.0"),
    "bn": LocalModelSpec("bn", "Bengali", "Helsinki-NLP/opus-mt-bn-en", "Apache-2.0"),
    "pa": LocalModelSpec("pa", "Punjabi", "Helsinki-NLP/opus-mt-pa-en", "Apache-2.0"),
    "jw": LocalModelSpec(
        "jw", "Javanese", "Helsinki-NLP/opus-mt-mul-en", "Apache-2.0",
        "Uses the shared multilingual -> English Marian model (Javanese is 'jav' in OPUS).",
    ),
    "ms": LocalModelSpec(
        "ms", "Malay", "Helsinki-NLP/opus-mt-mul-en", "Apache-2.0",
        "Uses the shared multilingual -> English Marian model.",
    ),
    "vi": LocalModelSpec("vi", "Vietnamese", "Helsinki-NLP/opus-mt-vi-en", "Apache-2.0"),
    "th": LocalModelSpec("th", "Thai", "Helsinki-NLP/opus-mt-th-en", "Apache-2.0"),
    "id": LocalModelSpec("id", "Indonesian", "Helsinki-NLP/opus-mt-id-en", "Apache-2.0"),
}

LOCAL_CPU_LANGUAGE_ORDER = tuple(LOCAL_MODEL_SPECS.keys())
DEFAULT_LOCAL_CPU_LANGUAGES = ("ja",)
DEFAULT_LOCAL_AUTO_SOURCE_LANGUAGE = "ja"


def normalize_local_languages(value):
    """Return a de-duplicated, registry-ordered list of supported language codes."""
    if isinstance(value, str):
        raw = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, (list, tuple, set)):
        raw = [str(part).strip() for part in value if str(part).strip()]
    else:
        raw = []
    selected = set(raw)
    return [code for code in LOCAL_CPU_LANGUAGE_ORDER if code in selected]
