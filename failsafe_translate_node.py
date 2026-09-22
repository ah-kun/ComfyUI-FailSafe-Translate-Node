"""Fail-safe translation nodes.

Simple keeps the compact text + src_lang UI and always translates to English.
Its src_lang combo is dynamically limited by the Local CPU Languages setting.
Advanced keeps the legacy full language list for compatibility.
"""

import logging
import time
from typing import Any, List

from . import settings as _settings
from .language_models import LOCAL_CPU_LANGUAGE_ORDER, normalize_local_languages
from .providers import ProviderError, RateLimitedError, _make_provider, cache, google_breaker

logger = logging.getLogger("ComfyUI.FailsafeTranslate")

LEGACY_LANGUAGES = [
    "auto", "en", "ja", "zh-CN", "zh-TW", "ko", "fr", "de", "es", "it", "ru",
    "pt", "nl", "pl", "tr", "ar", "hi", "bn", "pa", "jw", "ms", "vi", "th", "id",
    "[No Translation]",
]

ADVANCED_FAIL_MODES = ["return_input", "return_cached", "return_error", "raise"]
_VALID_FINAL_BEHAVIORS = {"return_input", "return_error", "return_cached", "raise"}


def _simple_source_options():
    cfg = _settings.all()
    selected = set(normalize_local_languages(cfg.get("local_cpu_languages", [])))
    options = ["auto"]
    options.extend(code for code in LOCAL_CPU_LANGUAGE_ORDER if code in selected)
    options.append("[No Translation]")
    return options


def _coerce_retries(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return default


def _coerce_wait(value: Any, default: float = 1.0) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


def _coerce_behavior(value: Any, fallback: str) -> str:
    v = str(value).strip() if value is not None else ""
    return v if v in _VALID_FINAL_BEHAVIORS else fallback


def _provider_message(name: str, message: Any) -> str:
    msg = str(message or "provider error")
    prefix = f"{name}:"
    if msg.lower().startswith(prefix.lower()):
        return msg[len(prefix):].lstrip()
    return msg


def _attempt_provider(provider, text: str, retries: int, wait_sec: float) -> str:
    for attempt in range(retries + 1):
        try:
            return provider.translate(text)
        except RateLimitedError:
            raise
        except ProviderError as exc:
            if exc.transient and attempt < retries:
                time.sleep(wait_sec)
                continue
            raise exc
        except Exception:  # noqa: BLE001
            exc = ProviderError("unexpected provider error", transient=True)
            if attempt < retries:
                time.sleep(wait_sec)
                continue
            raise exc


def _handle_final_failure(text, src_lang, dest_lang, behavior, errors):
    if behavior == "return_input":
        return (text,)
    if behavior == "return_cached":
        cached = cache.find_by_request(text, src_lang, dest_lang)
        return (cached if cached is not None else text,)
    if behavior == "return_error":
        detail = "; ".join(f"{name}: {msg}" for name, msg, _ in errors) or "all providers unavailable"
        return (f"[ERROR] Translation failed: {detail}",)
    if errors:
        name, msg, transient = errors[-1]
        raise ProviderError(f"{name}: {msg}", transient=transient)
    raise ProviderError("all providers unavailable", transient=False)


def _run_translation(text, src_lang, dest_lang, fail_mode, retries, retry_wait_sec):
    if text is None:
        text = ""
    if src_lang == "[No Translation]" or not text.strip():
        return (text,)

    cfg = _settings.all()
    fallback_enabled = bool(cfg["fallback_enabled"])
    cooldown_minutes = cfg["google_cooldown_minutes"]
    behavior = _coerce_behavior(fail_mode, cfg["final_failure_behavior"])

    if retries is None:
        retries = cfg["google_retries"]
    if retry_wait_sec is None:
        retry_wait_sec = cfg["retry_wait_seconds"]
    retries = _coerce_retries(retries, cfg["google_retries"])
    wait_sec = _coerce_wait(retry_wait_sec, cfg["retry_wait_seconds"])

    cache.update_limits(cfg["cache_enabled"], cfg["cache_max_entries"])

    providers: List[str] = ["Google"]
    if fallback_enabled:
        providers.append("LocalCPU")

    errors: List[tuple] = []
    for index, name in enumerate(providers):
        if index > 0:
            logger.info("[FailSafeTranslate] Using fallback: %s", name)

        provider = _make_provider(name, src_lang, dest_lang, cfg)
        if provider is None:
            msg = "provider not available for this language pair/settings"
            logger.warning("[FailSafeTranslate] %s: %s", name, msg)
            errors.append((name, msg, False))
            continue

        if provider.is_google and google_breaker.in_cooldown():
            msg = "in cooldown, skipped"
            logger.warning(
                "[FailSafeTranslate] Google: in cooldown (%.0f s remaining), skipping",
                google_breaker.remaining_seconds(),
            )
            errors.append((name, msg, False))
            continue

        cache_source = getattr(provider, "cache_source", src_lang)
        key = (text, cache_source, dest_lang, name)
        cached = cache.get(key)
        if cached is not None:
            return (cached,)

        try:
            provider_retries = retries if provider.is_google else 0
            result = _attempt_provider(provider, text, provider_retries, wait_sec)
            cache.set(key, result)
            logger.info("[FailSafeTranslate] %s: success", name)
            return (result,)
        except RateLimitedError as exc:
            msg = _provider_message(name, exc.message)
            if provider.is_google:
                google_breaker.enter_cooldown(cooldown_minutes)
                logger.warning(
                    "[FailSafeTranslate] Google: rate limited, cooldown %d min",
                    cooldown_minutes,
                )
            errors.append((name, msg, False))
        except ProviderError as exc:
            msg = _provider_message(name, exc.message)
            logger.warning("[FailSafeTranslate] %s: %s", name, msg)
            errors.append((name, msg, exc.transient))
        except Exception:  # noqa: BLE001
            logger.warning("[FailSafeTranslate] %s: unexpected error", name, exc_info=True)
            errors.append((name, "unexpected error", False))

    return _handle_final_failure(text, src_lang, dest_lang, behavior, errors)


class FailSafeTranslateSimple:
    @classmethod
    def INPUT_TYPES(cls):
        options = _simple_source_options()
        default = "auto"
        return {
            "required": {
                "text": ("STRING", {"multiline": True}),
                "src_lang": (options, {"default": default}),
            },
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "translate"
    CATEGORY = "utils/text"

    def translate(self, text: str, src_lang: str) -> tuple:
        return _run_translation(text, src_lang, "en", None, None, None)


class FailSafeTranslateAdvanced:
    @classmethod
    def INPUT_TYPES(cls):
        # Advanced intentionally retains the legacy full list. Local CPU
        # fallback still only runs for enabled source languages -> English.
        return {
            "required": {
                "text": ("STRING", {"multiline": True}),
                "src_lang": ([l for l in LEGACY_LANGUAGES if l != "auto"], {"default": "en"}),
                "dest_lang": (LEGACY_LANGUAGES,),
                "fail_mode": (ADVANCED_FAIL_MODES,),
                "retries": ("INT", {"default": 3, "min": 0, "max": 10}),
                "retry_wait_sec": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 30.0}),
            },
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "translate"
    CATEGORY = "utils/text"

    def translate(self, text, src_lang, dest_lang, fail_mode, retries, retry_wait_sec):
        return _run_translation(text, src_lang, dest_lang, fail_mode, retries, retry_wait_sec)
