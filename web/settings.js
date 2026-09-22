import { app } from "../../scripts/app.js";

/** FailSafe Translate - ComfyUI Settings integration. */
const ENDPOINT = "/failsafe_translate/settings";
const CATEGORY_ROOT = "FailSafe Translate";
const PREFIX = "FailSafeTranslate.";

const LOCAL_LANGUAGES = [
  { code: "ja", label: "Japanese" },
  { code: "zh-CN", label: "Chinese (Simplified)", note: "shared zh→en model" },
  { code: "zh-TW", label: "Chinese (Traditional)", note: "shared zh→en model" },
  { code: "ko", label: "Korean" },
  { code: "fr", label: "French" },
  { code: "de", label: "German" },
  { code: "es", label: "Spanish" },
  { code: "it", label: "Italian" },
  { code: "ru", label: "Russian" },
  { code: "pt", label: "Portuguese", note: "shared Romance→en model" },
  { code: "nl", label: "Dutch" },
  { code: "pl", label: "Polish" },
  { code: "tr", label: "Turkish" },
  { code: "ar", label: "Arabic" },
  { code: "hi", label: "Hindi" },
  { code: "bn", label: "Bengali" },
  { code: "pa", label: "Punjabi" },
  { code: "jw", label: "Javanese", note: "shared multilingual→en model" },
  { code: "ms", label: "Malay", note: "shared multilingual→en model" },
  { code: "vi", label: "Vietnamese" },
  { code: "th", label: "Thai" },
  { code: "id", label: "Indonesian" },
];

function categoryFor(id, group = "General") {
  return [CATEGORY_ROOT, group, id];
}

async function postSetting(key, value) {
  const res = await fetch(ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ [key]: value }),
  });
  if (!res.ok) throw new Error(`settings POST failed: ${res.status}`);
  return await res.json();
}

async function loadBackendSettings() {
  const res = await fetch(ENDPOINT, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`settings GET failed: ${res.status}`);
  const data = await res.json();
  return data && typeof data === "object" ? data : {};
}

async function refreshSourceCombos() {
  try {
    if (typeof app.refreshComboInNodes === "function") {
      await app.refreshComboInNodes();
    }
  } catch (error) {
    console.warn("[FailSafeTranslate] failed to refresh node definitions", error);
  }
}

function languageRenderer(_name, setter, value) {
  const root = document.createElement("div");
  root.style.width = "100%";

  const selected = new Set(Array.isArray(value) ? value : ["ja"]);
  const grid = document.createElement("div");
  grid.style.display = "grid";
  grid.style.gridTemplateColumns = "repeat(auto-fit, minmax(190px, 1fr))";
  grid.style.gap = "8px 16px";
  grid.style.marginBottom = "10px";

  for (const lang of LOCAL_LANGUAGES) {
    const label = document.createElement("label");
    label.style.display = "flex";
    label.style.alignItems = "center";
    label.style.gap = "7px";
    label.style.cursor = "pointer";

    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = selected.has(lang.code);
    box.addEventListener("change", () => {
      if (box.checked) selected.add(lang.code);
      else selected.delete(lang.code);
      const ordered = LOCAL_LANGUAGES.filter((x) => selected.has(x.code)).map((x) => x.code);
      setter(ordered);
    });

    const text = document.createElement("span");
    text.textContent = lang.note
      ? `${lang.code} — ${lang.label} (${lang.note})`
      : `${lang.code} — ${lang.label}`;
    label.append(box, text);
    grid.append(label);
  }

  const note = document.createElement("div");
  note.style.opacity = "0.78";
  note.style.fontSize = "0.9em";
  note.style.lineHeight = "1.45";
  note.textContent =
    "Only checked languages appear as explicit source choices in the Simple node. auto and [No Translation] are always available. " +
    "When src_lang=auto, Google still receives auto; if Local CPU fallback is needed, Local CPU Auto Source Language is used instead. " +
    "Models download on first fallback use and are cached on disk; only one model is kept in RAM at a time.";

  root.append(grid, note);
  return root;
}

function setting(id, name, type, defaultValue, extra = {}) {
  return {
    id: PREFIX + id,
    category: categoryFor(id),
    name,
    type,
    defaultValue,
    ...extra,
    async onChange(newValue, oldValue) {
      if (oldValue === undefined) return;
      try {
        await postSetting(id, newValue);
        if (id === "local_cpu_languages") {
          await refreshSourceCombos();
        }
      } catch (error) {
        console.warn(`[FailSafeTranslate] failed to update ${id}`, error);
      }
    },
  };
}

const SETTINGS = [
  setting("fallback_enabled", "Local CPU Fallback Enabled", "boolean", true, {
    tooltip: "When Google fails or is in 429 cooldown, use a selected local Marian/OPUS model on CPU. No CUDA VRAM is used.",
  }),
  setting("local_cpu_languages", "Local CPU Languages", languageRenderer, ["ja"]),
  setting("local_auto_source_language", "Local CPU Auto Source Language", "combo", "ja", {
    options: LOCAL_LANGUAGES.map((x) => x.code),
    tooltip: "Used only when the node src_lang is auto and Google cannot translate. Google itself still receives auto. This setting is independent of the explicit Local CPU Languages filter.",
  }),
  setting("google_cooldown_minutes", "Google Cooldown Minutes", "number", 30, {
    attrs: { min: 1, step: 1 },
  }),
  setting("google_retries", "Google Retries", "number", 0, {
    attrs: { min: 0, step: 1 },
  }),
  setting("retry_wait_seconds", "Retry Wait Seconds", "number", 3, {
    attrs: { min: 0, step: 0.1 },
  }),
  setting("final_failure_behavior", "Final Failure Behavior", "combo", "return_input", {
    options: ["return_input", "return_error", "raise"],
  }),
  setting("cache_enabled", "Cache Enabled", "boolean", true),
  setting("cache_max_entries", "Cache Max Entries", "number", 256, {
    attrs: { min: 1, step: 1 },
  }),
];

function sameValue(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

app.registerExtension({
  name: "FailSafeTranslate.Settings",
  settings: SETTINGS,

  async init() {
    try {
      const remote = await loadBackendSettings();
      for (const def of SETTINGS) {
        const key = def.id.slice(PREFIX.length);
        if (!(key in remote)) continue;
        const current = app.extensionManager.setting.get(def.id);
        if (!sameValue(current, remote[key])) {
          await app.extensionManager.setting.set(def.id, remote[key]);
        }
      }
    } catch (error) {
      console.warn("[FailSafeTranslate] settings initialization failed", error);
    }
  },
});
