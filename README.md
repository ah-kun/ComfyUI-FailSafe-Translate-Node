# ComfyUI-FailSafe-Translate-Node

A fail-safe Google Translate node for ComfyUI, designed to handle network flakiness and provide robust translation capabilities for your workflows.

## Features

- **Fail-Safe**: Built-in retry logic and configurable failure modes.
- **Caching**: Caches results to avoid redundant API calls.
- **Two Modes**:
    - **Simple**: Zero-config, translates to English (default).
    - **Advanced**: Full control over destination language, retries, and failure behavior.

## Installation

1. Clone this repository into your `ComfyUI/custom_nodes/` directory:
   ```bash
   cd ComfyUI/custom_nodes/
   git clone https://github.com/YourUsername/ComfyUI-FailSafe-Translate-Node.git
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Nodes

#### 1. Prompt Translate (Google, Fail-safe)
*Simple mode for quick translation to English.*
- **text**: Input text (multiline).
- **src_lang**: Source language (or 'auto').
- **Output**: English translation.

#### 2. Prompt Translate (Google, Fail-safe, Advanced)
*Advanced mode with full configuration.*
- **text**: Input text.
- **src_lang**: Source language.
- **dest_lang**: Target language.
- **fail_mode**: Behavior when translation fails after retries:
    - `return_input`: Returns the original text.
    - `return_cached`: Returns the last successful result (if any), otherwise input.
    - `return_error`: Returns an error message string (e.g., "[ERROR] ...").
    - `raise`: Stops the workflow with an error.
- **retries**: Number of retry attempts (default: 3).
- **retry_wait_sec**: Seconds to wait between retries (default: 1.0).

## Requirements

- `deep-translator`
