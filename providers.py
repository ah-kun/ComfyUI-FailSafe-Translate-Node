"""Google translation, local CPU fallback, 429 breaker, and LRU cache."""

from __future__ import annotations

import gc
import logging
import os
import threading
import time
from collections import OrderedDict

import requests

from deep_translator import GoogleTranslator
from deep_translator.exceptions import (
    ElementNotFoundInGetRequest,
    InvalidSourceOrTargetLanguage,
    LanguageNotSupportedException,
    NotValidLength,
    NotValidPayload,
    RequestError,
    TooManyRequests,
    TranslationNotFound,
)

from .language_models import LOCAL_MODEL_SPECS, normalize_local_languages

logger = logging.getLogger("ComfyUI.FailsafeTranslate")

LOCAL_CHUNK_CHARS = 350


class ProviderError(Exception):
    """A provider failed. transient=True means retrying may help."""

    def __init__(self, message, transient=True):
        self.message = message
        self.transient = transient
        super().__init__(message)


class RateLimitedError(ProviderError):
    """Provider returned HTTP 429 / rate limited. Never retried."""

    def __init__(self, message=None):
        super().__init__(message or "Provider rate limited (429)", transient=False)


class ProviderUnavailableError(ProviderError):
    """Provider cannot be used in the current configuration."""

    def __init__(self, message):
        super().__init__(message, transient=False)


def _require_non_empty(result, label):
    if result is None or (isinstance(result, str) and not result.strip()):
        raise ProviderError(f"{label}: empty result", transient=False)
    return result


class GoogleCircuitBreaker:
    def __init__(self):
        self._lock = threading.Lock()
        self._until = 0.0

    def in_cooldown(self):
        with self._lock:
            return time.time() < self._until

    def enter_cooldown(self, minutes):
        with self._lock:
            try:
                minutes = float(minutes)
            except (TypeError, ValueError):
                minutes = 30.0
            self._until = time.time() + minutes * 60.0

    def clear(self):
        with self._lock:
            self._until = 0.0

    def remaining_seconds(self):
        with self._lock:
            return max(0.0, self._until - time.time())


google_breaker = GoogleCircuitBreaker()


class TranslateCache:
    def __init__(self):
        self._lock = threading.RLock()
        self._enabled = True
        self._max = 256
        self._data = OrderedDict()

    def update_limits(self, enabled, max_entries):
        with self._lock:
            self._enabled = bool(enabled)
            try:
                max_entries = int(max_entries)
            except (TypeError, ValueError):
                max_entries = 256
            self._max = max(1, max_entries)
            if not self._enabled:
                self._data.clear()
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def get(self, key):
        with self._lock:
            if not self._enabled or key not in self._data:
                return None
            self._data.move_to_end(key)
            return self._data[key]

    def set(self, key, value):
        with self._lock:
            if not self._enabled:
                return
            if key in self._data:
                self._data.pop(key)
            self._data[key] = value
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def find_by_request(self, text, src, dest):
        with self._lock:
            if not self._enabled:
                return None
            for key, value in reversed(self._data.items()):
                if len(key) >= 3 and key[:3] == (text, src, dest):
                    return value
            return None

    def clear(self):
        with self._lock:
            self._data.clear()


cache = TranslateCache()


def _split_text(text, max_chars=LOCAL_CHUNK_CHARS):
    """Split long prompts without silently truncating the local model input."""
    text = str(text)
    if len(text) <= max_chars:
        return [text]

    chunks = []
    remaining = text
    separators = ("\n", "。", "！", "？", ". ", "! ", "? ", ", ", "、", " ")
    while len(remaining) > max_chars:
        window = remaining[: max_chars + 1]
        cut = -1
        for sep in separators:
            pos = window.rfind(sep)
            if pos >= max_chars // 2:
                cut = max(cut, pos + len(sep))
        if cut <= 0:
            cut = max_chars
        chunk = remaining[:cut].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[cut:].lstrip()
    if remaining.strip():
        chunks.append(remaining.strip())
    return chunks


def _model_cache_dir():
    """Return a cache path outside the custom-node source tree when possible."""
    override = os.environ.get("FAILSAFE_TRANSLATE_MODEL_DIR")
    if override:
        path = os.path.abspath(os.path.expanduser(override))
    else:
        try:
            import folder_paths  # ComfyUI runtime

            path = os.path.join(folder_paths.models_dir, "failsafe_translate")
        except Exception:  # noqa: BLE001
            path = os.path.join(os.path.expanduser("~"), ".cache", "failsafe_translate")
    os.makedirs(path, exist_ok=True)
    return path


class GoogleProvider:
    name = "Google"
    is_google = True

    def __init__(self, src, dest):
        self._src = src
        self._dest = dest

    def translate(self, text):
        try:
            translator = GoogleTranslator(source=self._src, target=self._dest)
            return _require_non_empty(translator.translate(text), self.name)
        except TooManyRequests:
            raise RateLimitedError("Google: rate limited (429)") from None
        except RequestError:
            raise ProviderError("Google: connection/request error", transient=True) from None
        except ElementNotFoundInGetRequest:
            raise ProviderError("Google: unexpected response", transient=True) from None
        except TranslationNotFound:
            raise ProviderError("Google: no translation found", transient=False) from None
        except LanguageNotSupportedException:
            raise ProviderError("Google: unsupported language", transient=False) from None
        except InvalidSourceOrTargetLanguage:
            raise ProviderError("Google: invalid source or target language", transient=False) from None
        except NotValidLength:
            raise ProviderError("Google: text length out of range", transient=False) from None
        except NotValidPayload:
            raise ProviderError("Google: invalid text payload", transient=False) from None
        except requests.ConnectionError:
            raise ProviderError("Google: connection error", transient=True) from None
        except requests.Timeout:
            raise ProviderError("Google: timeout", transient=True) from None
        except requests.RequestException:
            raise ProviderError("Google: network error", transient=True) from None
        except Exception:
            raise ProviderError("Google: unexpected error", transient=True) from None


class _LocalModelRegistry:
    """Lazy CPU-only model holder. Keeps only one model resident in RAM."""

    def __init__(self):
        self._lock = threading.RLock()
        self._active_model_id = None
        self._active = None

    def get(self, model_id):
        with self._lock:
            if self._active_model_id == model_id and self._active is not None:
                return self._active

            # Bound RAM use: downloaded files stay on disk, but only the most
            # recently used model remains instantiated in memory.
            self._active = None
            self._active_model_id = None
            gc.collect()

            logger.info(
                "[FailSafeTranslate] LocalCPU: loading %s on CPU (first use may download the model)",
                model_id,
            )
            try:
                from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
            except ModuleNotFoundError as exc:
                raise ProviderUnavailableError(
                    "LocalCPU: transformers/sentencepiece not installed; run pip install -r requirements.txt"
                ) from exc

            try:
                cache_dir = _model_cache_dir()
                tokenizer = AutoTokenizer.from_pretrained(model_id, cache_dir=cache_dir)
                model = AutoModelForSeq2SeqLM.from_pretrained(model_id, cache_dir=cache_dir)
                model.to("cpu")
                model.eval()
            except Exception as exc:  # noqa: BLE001
                logger.debug("[FailSafeTranslate] LocalCPU model load failed", exc_info=True)
                raise ProviderUnavailableError(
                    f"LocalCPU: model download/load failed ({model_id})"
                ) from exc

            self._active_model_id = model_id
            self._active = (tokenizer, model)
            return self._active

    def clear(self):
        with self._lock:
            self._active_model_id = None
            self._active = None
            gc.collect()


local_models = _LocalModelRegistry()


class LocalCPUProvider:
    name = "LocalCPU"
    is_google = False

    def __init__(self, src, dest, enabled_languages):
        self._src = str(src)
        self._dest = str(dest)
        self._enabled_languages = set(normalize_local_languages(enabled_languages))

    def _spec(self):
        if self._dest.lower() != "en":
            return None
        if self._src not in self._enabled_languages:
            return None
        return LOCAL_MODEL_SPECS.get(self._src)

    def translate(self, text):
        if self._src.lower() == self._dest.lower():
            return str(text)

        spec = self._spec()
        if spec is None:
            raise ProviderUnavailableError(
                f"LocalCPU: source '{self._src}' is disabled/unsupported or target is not English"
            )

        tokenizer, model = local_models.get(spec.model_id)
        outputs = []
        try:
            import torch

            with torch.inference_mode():
                for chunk in _split_text(text):
                    encoded = tokenizer(
                        chunk,
                        return_tensors="pt",
                        truncation=True,
                        max_length=512,
                    )
                    generated = model.generate(**encoded, max_new_tokens=512)
                    decoded = tokenizer.batch_decode(generated, skip_special_tokens=True)
                    outputs.append(_require_non_empty(decoded[0] if decoded else "", self.name))
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.debug("[FailSafeTranslate] LocalCPU inference error", exc_info=True)
            raise ProviderError("LocalCPU: inference failed", transient=False) from exc

        return _require_non_empty(" ".join(outputs), self.name)


def _make_provider(name, src, dest, settings):
    """Return a provider instance for ``name``, or None if unavailable."""
    src, dest = str(src), str(dest)
    if name == "Google":
        return GoogleProvider(src, dest)
    if name == "LocalCPU":
        if dest.lower() != "en":
            return None
        if src == "auto":
            resolved_src = str(settings.get("local_auto_source_language", "ja"))
            if resolved_src not in LOCAL_MODEL_SPECS:
                return None
            provider = LocalCPUProvider(resolved_src, dest, [resolved_src])
            provider.cache_source = f"auto:{resolved_src}"
            return provider
        enabled = settings.get("local_cpu_languages", [])
        if src not in normalize_local_languages(enabled):
            return None
        provider = LocalCPUProvider(src, dest, enabled)
        provider.cache_source = src
        return provider
    return None
