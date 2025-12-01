from failsafe_translate_node import FailSafeTranslateSimple, FailSafeTranslateAdvanced
import time

def test_node():
    print("=== Testing FailSafeTranslateSimple ===")
    simple_node = FailSafeTranslateSimple()
    
    print("Test 1: Basic Translation (en -> ja -> en)")
    try:
        # Simple node is fixed to EN destination
        # So we translate JA to EN
        result = simple_node.translate("こんにちは世界", "ja")
        print(f"Result (JA->EN): {result[0]}")
    except Exception as e:
        print(f"Test 1 failed: {e}")

    print("\n=== Testing FailSafeTranslateAdvanced ===")
    adv_node = FailSafeTranslateAdvanced()

    print("Test 2: Custom Destination (en -> fr)")
    try:
        result = adv_node.translate("Hello world", "en", "fr", "raise", 3, 1.0)
        print(f"Result: {result[0]}")
    except Exception as e:
        print(f"Test 2 failed: {e}")

    print("\nTest 3: Failure Mode 'return_input'")
    try:
        # Force failure by using invalid language code if possible, or just rely on logic check
        # deep-translator might raise error on invalid code immediately
        # Let's try a non-existent language code to trigger error
        result = adv_node.translate("Hello", "en", "xx_INVALID", "return_input", 1, 0.1)
        print(f"Result (should be input 'Hello'): {result[0]}")
    except Exception as e:
        print(f"Test 3 failed (unexpected exception): {e}")

    print("\nTest 4: Failure Mode 'return_error'")
    try:
        result = adv_node.translate("Hello", "en", "xx_INVALID", "return_error", 1, 0.1)
        print(f"Result (should start with [ERROR]): {result[0]}")
    except Exception as e:
        print(f"Test 4 failed (unexpected exception): {e}")

    print("\nTest 5: Caching (Advanced)")
    try:
        start = time.time()
        adv_node.translate("Cache Test", "en", "es", "raise", 3, 1.0)
        print(f"First call: {time.time() - start:.4f}s")
        
        start = time.time()
        adv_node.translate("Cache Test", "en", "es", "raise", 3, 1.0)
        print(f"Second call (cached): {time.time() - start:.4f}s")
    except Exception as e:
        print(f"Test 5 failed: {e}")

if __name__ == "__main__":
    test_node()
