import time
from deep_translator import GoogleTranslator

# Supported languages list
LANGUAGES = [
    "auto", "en", "ja", "zh-CN", "zh-TW", "ko", "fr", "de", "es", "it", "ru", 
    "pt", "nl", "pl", "tr", "ar", "hi", "bn", "pa", "jv", "ms", "vi", "th", "id"
]

class FailSafeTranslateNode:
    def __init__(self):
        self.last_request = None
        self.last_result = None

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "text": ("STRING", {"multiline": True}),
                "src_lang": (LANGUAGES,),
            },
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "translate"
    CATEGORY = "utils/text"

    def translate_logic(self, text, src_lang, dest_lang, retries, retry_wait_sec, fail_mode):
        # Cache check
        current_request = (text, src_lang, dest_lang)
        if self.last_request == current_request:
            print("Using cached translation result.")
            return (self.last_result,)

        for attempt in range(retries + 1):
            try:
                translator = GoogleTranslator(source=src_lang, target=dest_lang)
                result = translator.translate(text)
                
                self.last_request = current_request
                self.last_result = result
                return (result,)
            
            except Exception as e:
                print(f"Translation failed (attempt {attempt + 1}/{retries + 1}): {e}")
                if attempt < retries:
                    time.sleep(retry_wait_sec)
                else:
                    # All retries failed, handle based on fail_mode
                    if fail_mode == "return_input":
                        return (text,)
                    elif fail_mode == "return_cached":
                        if self.last_result is not None:
                            print("Returning cached result due to failure.")
                            return (self.last_result,)
                        else:
                            print("No cache available, returning input.")
                            return (text,)
                    elif fail_mode == "return_error":
                        return (f"[ERROR] Translation failed: {str(e)}",)
                    else: # raise
                        raise e

class FailSafeTranslateSimple(FailSafeTranslateNode):
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "text": ("STRING", {"multiline": True}),
                "src_lang": (LANGUAGES,),
            },
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "translate"
    CATEGORY = "utils/text"

    def translate(self, text, src_lang):
        # Simple mode defaults: dest="en", retries=3, wait=1.0, fail_mode="raise"
        # Wait, user asked for "fail-safe" so maybe simple mode should also be safe?
        # But user said "Simple = Prompt Translate (Google, Fail-safe)" and "Advanced ... set options".
        # Usually simple implies "just work or tell me".
        # User said "Simple dst_lang fixed to en".
        # I will assume defaults: retries=3, wait=1.0, fail_mode="raise" (standard behavior) or maybe "return_error"?
        # Let's stick to the plan: "Uses default fail-safe settings (3 retries, 1s wait, raise on fail)."
        return self.translate_logic(text, src_lang, "en", 3, 1.0, "raise")

class FailSafeTranslateAdvanced(FailSafeTranslateNode):
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "text": ("STRING", {"multiline": True}),
                "src_lang": (LANGUAGES,),
                "dest_lang": (LANGUAGES,),
                "fail_mode": (["return_input", "return_cached", "return_error", "raise"],),
                "retries": ("INT", {"default": 3, "min": 0, "max": 10}),
                "retry_wait_sec": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 30.0}),
            },
        }

    RETURN_TYPES = ("STRING",)
    FUNCTION = "translate"
    CATEGORY = "utils/text"

    def translate(self, text, src_lang, dest_lang, fail_mode, retries, retry_wait_sec):
        return self.translate_logic(text, src_lang, dest_lang, retries, retry_wait_sec, fail_mode)
