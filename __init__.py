from .failsafe_translate_node import (
    FailSafeTranslateAdvanced,
    FailSafeTranslateSimple,
)

NODE_CLASS_MAPPINGS = {
    "FailSafeTranslateSimple": FailSafeTranslateSimple,
    "FailSafeTranslateAdvanced": FailSafeTranslateAdvanced,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "FailSafeTranslateSimple": "Prompt Translate (Google, Fail-safe)",
    "FailSafeTranslateAdvanced": "Prompt Translate (Google, Fail-safe, Advanced)",
}

WEB_DIRECTORY = "./web"

# Register the /failsafe_translate/settings endpoints (used by web/settings.js).
try:
    from .api import register_routes as _register_failsafe_routes  # noqa: F401

    _register_failsafe_routes()
except Exception as exc:  # noqa: BLE001
    import logging

    logging.warning("[FailSafeTranslate] could not register settings routes: %s", exc)
