"""Process-wide settings for the FailSafe Translate node."""

import json
import logging
import os
import threading

from .language_models import (
    DEFAULT_LOCAL_AUTO_SOURCE_LANGUAGE,
    DEFAULT_LOCAL_CPU_LANGUAGES,
    LOCAL_MODEL_SPECS,
    normalize_local_languages,
)

logger = logging.getLogger("ComfyUI.FailsafeTranslate")

__all__ = ["DEFAULTS", "SECRET_KEYS", "SettingsManager", "all", "update", "reload", "mask"]

DEFAULTS = {
    "fallback_enabled": True,
    "local_cpu_languages": list(DEFAULT_LOCAL_CPU_LANGUAGES),
    "local_auto_source_language": DEFAULT_LOCAL_AUTO_SOURCE_LANGUAGE,
    "google_cooldown_minutes": 30,
    "google_retries": 0,
    "retry_wait_seconds": 3.0,
    "final_failure_behavior": "return_input",
    "cache_enabled": True,
    "cache_max_entries": 256,
}

# Kept for API compatibility with older revisions. There are no secrets now.
SECRET_KEYS = set()

_VALID_FINAL_BEHAVIORS = {"return_input", "return_error", "return_cached", "raise"}
_BOOL_KEYS = {"fallback_enabled", "cache_enabled"}


def _coerce_bool(value, default):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "on")


def _coerce(key, value):
    """Coerce an incoming value to the expected type for the given key."""
    if key in _BOOL_KEYS:
        return _coerce_bool(value, DEFAULTS[key])

    if key == "local_cpu_languages":
        return normalize_local_languages(value)

    if key == "local_auto_source_language":
        code = str(value).strip() if value is not None else DEFAULTS[key]
        return code if code in LOCAL_MODEL_SPECS else DEFAULTS[key]

    if key in ("google_cooldown_minutes", "google_retries", "cache_max_entries"):
        try:
            iv = int(float(value))
        except (TypeError, ValueError):
            return DEFAULTS[key]
        if key == "google_cooldown_minutes":
            return max(1, iv)
        if key == "cache_max_entries":
            return max(1, iv)
        return max(0, iv)

    if key == "retry_wait_seconds":
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return DEFAULTS[key]

    if key == "final_failure_behavior":
        s = str(value).strip() if value is not None else DEFAULTS[key]
        return s if s in _VALID_FINAL_BEHAVIORS else DEFAULTS[key]

    return DEFAULTS.get(key)


class SettingsManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "failsafe_translate_config.json",
        )
        self._data = dict(DEFAULTS)
        self._data["local_cpu_languages"] = list(DEFAULTS["local_cpu_languages"])
        self._load()

    def _load(self):
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[FailSafeTranslate] could not read settings file %s: %s",
                self._path,
                exc,
            )
            return
        if not isinstance(raw, dict):
            return
        with self._lock:
            for key, value in raw.items():
                if key in DEFAULTS:
                    self._data[key] = _coerce(key, value)

    def _save(self):
        try:
            with self._lock:
                data = dict(self._data)
                data["local_cpu_languages"] = list(self._data["local_cpu_languages"])
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[FailSafeTranslate] could not write settings file %s: %s",
                self._path,
                exc,
            )

    def all(self):
        with self._lock:
            out = dict(self._data)
            out["local_cpu_languages"] = list(self._data["local_cpu_languages"])
            return out

    def get(self, key):
        with self._lock:
            value = self._data.get(key, DEFAULTS.get(key))
            return list(value) if key == "local_cpu_languages" and value is not None else value

    def update(self, raw):
        """Merge known keys from ``raw`` into memory and persist them."""
        changed = {}
        if not isinstance(raw, dict):
            return changed
        with self._lock:
            for key, value in raw.items():
                if key not in DEFAULTS:
                    continue
                new_value = _coerce(key, value)
                if new_value != self._data[key]:
                    changed[key] = list(new_value) if key == "local_cpu_languages" else new_value
                    self._data[key] = new_value
        if changed:
            self._save()
        return changed

    def reload(self):
        with self._lock:
            self._data = dict(DEFAULTS)
            self._data["local_cpu_languages"] = list(DEFAULTS["local_cpu_languages"])
            self._load()
            return self.all()


_settings = SettingsManager()


def all():
    return _settings.all()


def update(raw):
    return _settings.update(raw)


def reload():
    return _settings.reload()


def mask(data):
    return dict(data) if isinstance(data, dict) else dict(DEFAULTS)
