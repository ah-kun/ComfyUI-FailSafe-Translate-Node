from .failsafe_translate_node import FailSafeTranslateSimple, FailSafeTranslateAdvanced

NODE_CLASS_MAPPINGS = {
    "FailSafeTranslateSimple": FailSafeTranslateSimple,
    "FailSafeTranslateAdvanced": FailSafeTranslateAdvanced
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "FailSafeTranslateSimple": "Prompt Translate (Google, Fail-safe)",
    "FailSafeTranslateAdvanced": "Prompt Translate (Google, Fail-safe, Advanced)"
}
