"""Offline regression tests for ComfyUI-FailSafe-Translate-Node."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
PKG = "failsafe_translate_testpkg"


def _install_deep_translator_stub():
    deep = types.ModuleType("deep_translator")

    class DummyTranslator:
        def __init__(self, *args, **kwargs):
            pass

        def translate(self, text):
            return text

    deep.GoogleTranslator = DummyTranslator
    exceptions = types.ModuleType("deep_translator.exceptions")
    for name in (
        "ElementNotFoundInGetRequest",
        "InvalidSourceOrTargetLanguage",
        "LanguageNotSupportedException",
        "NotValidLength",
        "NotValidPayload",
        "RequestError",
        "TooManyRequests",
        "TranslationNotFound",
    ):
        setattr(exceptions, name, type(name, (Exception,), {}))

    sys.modules["deep_translator"] = deep
    sys.modules["deep_translator.exceptions"] = exceptions


def _load_module(qualified_name, filename):
    spec = importlib.util.spec_from_file_location(qualified_name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_install_deep_translator_stub()
pkg = types.ModuleType(PKG)
pkg.__path__ = [str(ROOT)]
sys.modules[PKG] = pkg
language_models = _load_module(f"{PKG}.language_models", "language_models.py")
settings = _load_module(f"{PKG}.settings", "settings.py")
providers = _load_module(f"{PKG}.providers", "providers.py")
node = _load_module(f"{PKG}.failsafe_translate_node", "failsafe_translate_node.py")


class _Routes:
    def get(self, _path):
        return lambda fn: fn

    def post(self, _path):
        return lambda fn: fn


server_stub = types.ModuleType("server")
server_stub.PromptServer = type(
    "PromptServer", (), {"instance": type("Instance", (), {"routes": _Routes()})()}
)
sys.modules["server"] = server_stub
api = _load_module(f"{PKG}.api", "api.py")

BASE_CFG = dict(settings.DEFAULTS)
BASE_CFG["local_cpu_languages"] = list(settings.DEFAULTS["local_cpu_languages"])
BASE_CFG["retry_wait_seconds"] = 0.0


class FakeProvider:
    def __init__(self, name, responses, *, is_google=False):
        self.name = name
        self.is_google = is_google
        self.responses = list(responses)
        self.calls = 0

    def translate(self, _text):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class FailSafeTranslateTests(unittest.TestCase):
    def setUp(self):
        providers.google_breaker.clear()
        providers.cache.clear()
        providers.cache.update_limits(True, 256)
        providers.local_models.clear()

    def _run_with(self, cfg, provider_map, *args):
        def make_provider(name, src, dest, _cfg):
            return provider_map.get(name)

        with patch.object(node._settings, "all", return_value=cfg), patch.object(
            node, "_make_provider", side_effect=make_provider
        ):
            return node._run_translation(*args)

    def test_google_success(self):
        google = FakeProvider("Google", ["hello"], is_google=True)
        result = self._run_with(
            dict(BASE_CFG), {"Google": google},
            "こんにちは", "ja", "en", None, None, None,
        )
        self.assertEqual(result, ("hello",))
        self.assertEqual(google.calls, 1)

    def test_google_429_falls_back_to_local_cpu_and_cooldown_skips_google(self):
        google = FakeProvider(
            "Google", [providers.RateLimitedError("Google: rate limited (429)")], is_google=True
        )
        local = FakeProvider("LocalCPU", ["first", "second"])
        cfg = dict(BASE_CFG)

        first = self._run_with(
            cfg, {"Google": google, "LocalCPU": local},
            "一回目", "ja", "en", None, None, None,
        )
        self.assertEqual(first, ("first",))
        self.assertTrue(providers.google_breaker.in_cooldown())

        second = self._run_with(
            cfg, {"Google": google, "LocalCPU": local},
            "二回目", "ja", "en", None, None, None,
        )
        self.assertEqual(second, ("second",))
        self.assertEqual(google.calls, 1)

    def test_model_registry_covers_legacy_non_english_sources(self):
        expected = {
            "ja", "zh-CN", "zh-TW", "ko", "fr", "de", "es", "it", "ru", "pt",
            "nl", "pl", "tr", "ar", "hi", "bn", "pa", "jw", "ms", "vi", "th", "id",
        }
        self.assertEqual(set(language_models.LOCAL_MODEL_SPECS), expected)

    def test_shared_model_mappings(self):
        self.assertEqual(
            language_models.LOCAL_MODEL_SPECS["zh-CN"].model_id,
            language_models.LOCAL_MODEL_SPECS["zh-TW"].model_id,
        )
        self.assertEqual(
            language_models.LOCAL_MODEL_SPECS["jw"].model_id,
            "Helsinki-NLP/opus-mt-mul-en",
        )
        self.assertEqual(
            language_models.LOCAL_MODEL_SPECS["ms"].model_id,
            "Helsinki-NLP/opus-mt-mul-en",
        )

    def test_local_provider_only_for_enabled_source_to_english(self):
        cfg = dict(BASE_CFG)
        cfg["local_cpu_languages"] = ["ja", "fr"]
        self.assertIsNotNone(providers._make_provider("LocalCPU", "fr", "en", cfg))
        self.assertIsNone(providers._make_provider("LocalCPU", "de", "en", cfg))
        self.assertIsNone(providers._make_provider("LocalCPU", "fr", "ja", cfg))
        auto_provider = providers._make_provider("LocalCPU", "auto", "en", cfg)
        self.assertIsNotNone(auto_provider)
        self.assertEqual(auto_provider._src, "ja")
        self.assertEqual(auto_provider.cache_source, "auto:ja")

    def test_auto_uses_configured_local_source(self):
        cfg = dict(BASE_CFG)
        cfg["local_cpu_languages"] = ["ja"]
        cfg["local_auto_source_language"] = "fr"
        provider = providers._make_provider("LocalCPU", "auto", "en", cfg)
        self.assertIsNotNone(provider)
        self.assertEqual(provider._src, "fr")
        self.assertEqual(provider.cache_source, "auto:fr")

    def test_language_setting_is_filtered_and_ordered(self):
        manager = settings.SettingsManager()
        with tempfile.TemporaryDirectory() as tmp:
            manager._path = str(Path(tmp) / "settings.json")
            manager.update({"local_cpu_languages": ["fr", "bogus", "ja", "fr", "ko"]})
            self.assertEqual(manager.all()["local_cpu_languages"], ["ja", "ko", "fr"])

    def test_simple_src_combo_follows_local_language_setting(self):
        cfg = dict(BASE_CFG)
        cfg["local_cpu_languages"] = ["ja", "ko", "fr"]
        with patch.object(node._settings, "all", return_value=cfg):
            required = node.FailSafeTranslateSimple.INPUT_TYPES()["required"]
        options, metadata = required["src_lang"]
        self.assertEqual(options, ["auto", "ja", "ko", "fr", "[No Translation]"])
        self.assertEqual(metadata["default"], "auto")

    def test_empty_language_selection_leaves_no_translation_option(self):
        cfg = dict(BASE_CFG)
        cfg["local_cpu_languages"] = []
        with patch.object(node._settings, "all", return_value=cfg):
            options, metadata = node.FailSafeTranslateSimple.INPUT_TYPES()["required"]["src_lang"]
        self.assertEqual(options, ["auto", "[No Translation]"])
        self.assertEqual(metadata["default"], "auto")

    def test_advanced_keeps_legacy_language_list(self):
        required = node.FailSafeTranslateAdvanced.INPUT_TYPES()["required"]
        src_options = required["src_lang"][0]
        self.assertIn("en", src_options)
        self.assertIn("ja", src_options)
        self.assertIn("fr", src_options)
        self.assertNotIn("auto", src_options)

    def test_fallback_disabled_returns_input(self):
        google = FakeProvider(
            "Google", [providers.ProviderError("down", transient=False)], is_google=True
        )
        cfg = dict(BASE_CFG)
        cfg["fallback_enabled"] = False
        text = "そのまま"
        result = self._run_with(cfg, {"Google": google}, text, "ja", "en", None, None, None)
        self.assertEqual(result, (text,))

    def test_cache_enabled_boolean_coercion(self):
        manager = settings.SettingsManager()
        with tempfile.TemporaryDirectory() as tmp:
            manager._path = str(Path(tmp) / "settings.json")
            manager.update({"cache_enabled": False})
            self.assertIs(manager.all()["cache_enabled"], False)
            manager.update({"cache_enabled": "true"})
            self.assertIs(manager.all()["cache_enabled"], True)

    def test_node_input_contract_names_are_compatible(self):
        simple = node.FailSafeTranslateSimple.INPUT_TYPES()["required"]
        advanced = node.FailSafeTranslateAdvanced.INPUT_TYPES()["required"]
        self.assertEqual(list(simple), ["text", "src_lang"])
        self.assertEqual(
            list(advanced),
            ["text", "src_lang", "dest_lang", "fail_mode", "retries", "retry_wait_sec"],
        )

    def test_settings_get_endpoint_includes_local_languages(self):
        cfg = dict(BASE_CFG)
        cfg["local_cpu_languages"] = ["ja", "fr"]
        with patch.object(api._settings, "all", return_value=cfg):
            response = asyncio.run(api._get_settings(None))
        self.assertEqual(response.status, 200)
        self.assertIn(b'"local_cpu_languages": ["ja", "fr"]', response.body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
