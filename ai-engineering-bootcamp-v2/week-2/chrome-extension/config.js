/**
 * Shared config for Ask Z-Bot. Plain-script (no ES modules) so the same file
 * can be loaded by both content scripts and the MV3 service worker
 * (via importScripts). Everything is hung off `self` so it works in either
 * context (window in content scripts, worker global in the service worker).
 */
(function () {
  self.ZBOT_CONFIG = {
    // Default Render API. Override per-install via the overlay's API URL field
    // (persisted to chrome.storage.sync under STORAGE_KEY) for local uvicorn.
    DEFAULT_AGENT_API_URL: "https://ai-internship-i3lw.onrender.com",
    STORAGE_KEY: "agentApiUrl",
    API_KEY_STORAGE_KEY: "agentApiKey",
    TELEMETRY_STORAGE_KEY: "telemetryOptIn",
    INSTALL_ID_STORAGE_KEY: "installId",
    LAYOUT_STORAGE_KEY: "layoutMode",

    // "panel" docks the expanded UI to the right edge; "overlay" floats it.
    DEFAULT_LAYOUT_MODE: "panel",

    // First Render request after idle can take ~60s; the agent loop itself
    // (multi-step retrieval + optional Google fallback) can be slow.
    AGENT_TIMEOUT_MS: 120000,
    HEALTH_TIMEOUT_MS: 60000,

    // Extension version — keep in sync with manifest.json
    EXTENSION_VERSION: "1.0.0",

    // Mirror zearn_faq_bot/constants.py so banner detection matches the agent.
    FALLBACK_PREFIX: "This wasn't found in Zearn documentation; sourced from the web.",
    REFUSAL_MESSAGE:
      "I couldn't find that in the Zearn documentation corpus. " +
      "Try rephrasing your question, or contact Zearn support for help.",
  };
})();
