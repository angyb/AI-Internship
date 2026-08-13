/**
 * Ask Z-Bot background service worker (MV3).
 *
 * Proxies the Zearn Support Agent API (avoids CORS). Holds the shared
 * AGENT_API_KEY in chrome.storage.sync when the server requires it — this is
 * NOT an OpenAI/Google user secret; it is an optional gate for POST /agent.
 *
 * Messages:
 *   - { type: "wake" } -> GET /health
 *   - { type: "ask", question } -> POST /agent
 *   - { type: "cancelAsk" } -> abort in-flight /agent request
 *   - { type: "getSettings" } / { type: "saveSettings", ... }
 *   - { type: "reportError", message } -> optional POST /telemetry
 *   - chrome.commands "toggle-zbot" (Alt+Z)
 */

importScripts("config.js");

const CONFIG = self.ZBOT_CONFIG;

function normalizeBase(url) {
  return (url || CONFIG.DEFAULT_AGENT_API_URL).replace(/\/+$/, "");
}

function normalizeLayoutMode(mode) {
  return mode === "overlay" || mode === "panel"
    ? mode
    : CONFIG.DEFAULT_LAYOUT_MODE;
}

async function ensureInstallId() {
  const key = CONFIG.INSTALL_ID_STORAGE_KEY;
  try {
    const stored = await chrome.storage.local.get(key);
    if (stored[key]) return stored[key];
    const id =
      self.crypto && crypto.randomUUID
        ? crypto.randomUUID()
        : "install-" + Date.now() + "-" + Math.random().toString(16).slice(2);
    await chrome.storage.local.set({ [key]: id });
    return id;
  } catch (_e) {
    return "anonymous";
  }
}

async function loadSettings() {
  const sync = await chrome.storage.sync.get([
    CONFIG.STORAGE_KEY,
    CONFIG.API_KEY_STORAGE_KEY,
    CONFIG.TELEMETRY_STORAGE_KEY,
    CONFIG.LAYOUT_STORAGE_KEY,
  ]);
  return {
    base: normalizeBase(sync[CONFIG.STORAGE_KEY]),
    defaultBase: CONFIG.DEFAULT_AGENT_API_URL,
    apiKey: (sync[CONFIG.API_KEY_STORAGE_KEY] || "").trim(),
    telemetryOptIn: Boolean(sync[CONFIG.TELEMETRY_STORAGE_KEY]),
    layoutMode: normalizeLayoutMode(sync[CONFIG.LAYOUT_STORAGE_KEY]),
    agentTimeoutMs: CONFIG.AGENT_TIMEOUT_MS,
    healthTimeoutMs: CONFIG.HEALTH_TIMEOUT_MS,
    extensionVersion: CONFIG.EXTENSION_VERSION,
  };
}

async function saveSettings(partial) {
  const toSync = {};
  if (Object.prototype.hasOwnProperty.call(partial, "base")) {
    toSync[CONFIG.STORAGE_KEY] =
      normalizeBase(partial.base) || CONFIG.DEFAULT_AGENT_API_URL;
  }
  if (Object.prototype.hasOwnProperty.call(partial, "apiKey")) {
    toSync[CONFIG.API_KEY_STORAGE_KEY] = String(partial.apiKey || "").trim();
  }
  if (Object.prototype.hasOwnProperty.call(partial, "telemetryOptIn")) {
    toSync[CONFIG.TELEMETRY_STORAGE_KEY] = Boolean(partial.telemetryOptIn);
  }
  if (Object.prototype.hasOwnProperty.call(partial, "layoutMode")) {
    toSync[CONFIG.LAYOUT_STORAGE_KEY] = normalizeLayoutMode(partial.layoutMode);
  }
  if (Object.keys(toSync).length) {
    await chrome.storage.sync.set(toSync);
  }
  return loadSettings();
}

async function authHeaders() {
  const settings = await loadSettings();
  const installId = await ensureInstallId();
  const headers = {
    "Content-Type": "application/json",
    "X-Install-Id": installId,
  };
  if (settings.apiKey) {
    headers["X-API-Key"] = settings.apiKey;
  }
  return { headers, settings, installId };
}

async function fetchWithTimeout(url, options, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("timeout"), timeoutMs);
  const external = options && options.signal;
  function onExternalAbort() {
    controller.abort("cancelled");
  }
  if (external) {
    if (external.aborted) controller.abort("cancelled");
    else external.addEventListener("abort", onExternalAbort, { once: true });
  }
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
    if (external) external.removeEventListener("abort", onExternalAbort);
  }
}

let activeAsk = null;

function cancelAsk() {
  if (activeAsk) {
    activeAsk.cancelled = true;
    try {
      activeAsk.controller.abort();
    } catch (_e) {
      // ignore
    }
  }
  return { cancelled: true };
}

async function extractDetail(response) {
  try {
    const data = await response.json();
    if (data && typeof data.detail === "string") return data.detail;
    return JSON.stringify(data);
  } catch (_e) {
    try {
      return await response.text();
    } catch (_e2) {
      return "";
    }
  }
}

async function handleWake() {
  const { headers, settings } = await authHeaders();
  // Health is unauthenticated; still send install id for consistency.
  try {
    const resp = await fetchWithTimeout(
      settings.base + "/health",
      { method: "GET", headers: { "X-Install-Id": headers["X-Install-Id"] } },
      CONFIG.HEALTH_TIMEOUT_MS
    );
    return { ok: resp.ok, status: resp.status, base: settings.base };
  } catch (e) {
    const timedOut = e && e.name === "AbortError";
    return {
      ok: false,
      base: settings.base,
      error: timedOut ? "Health check timed out" : String(e),
    };
  }
}

async function handleAsk(question) {
  cancelAsk();
  const entry = { controller: new AbortController(), cancelled: false };
  activeAsk = entry;
  const { headers, settings } = await authHeaders();
  try {
    const resp = await fetchWithTimeout(
      settings.base + "/agent",
      {
        method: "POST",
        headers,
        body: JSON.stringify({ question }),
        signal: entry.controller.signal,
      },
      CONFIG.AGENT_TIMEOUT_MS
    );

    if (!resp.ok) {
      const detail = await extractDetail(resp);
      return { error: detail || "HTTP " + resp.status, status: resp.status };
    }

    const data = await resp.json();
    return {
      answer: typeof data.answer === "string" ? data.answer : "",
      steps: Array.isArray(data.steps) ? data.steps : [],
    };
  } catch (e) {
    if (e && e.name === "AbortError") {
      if (entry.cancelled) return { cancelled: true };
      const seconds = Math.round(CONFIG.AGENT_TIMEOUT_MS / 1000);
      return {
        error:
          "The agent request timed out after " +
          seconds +
          "s. The API may be waking up — try again.",
      };
    }
    return {
      error: "Could not reach the agent API at " + settings.base + ": " + String(e),
    };
  } finally {
    if (activeAsk === entry) activeAsk = null;
  }
}

async function reportError(message) {
  const { headers, settings, installId } = await authHeaders();
  if (!settings.telemetryOptIn) {
    return { status: "skipped" };
  }
  try {
    const resp = await fetchWithTimeout(
      settings.base + "/telemetry",
      {
        method: "POST",
        headers,
        body: JSON.stringify({
          event: "client_error",
          message: String(message || "").slice(0, 500),
          install_id: installId,
          extension_version: CONFIG.EXTENSION_VERSION,
        }),
      },
      15000
    );
    if (!resp.ok) return { status: "failed", code: resp.status };
    return await resp.json();
  } catch (e) {
    return { status: "failed", error: String(e) };
  }
}

async function handleEvalAgent() {
  const { headers, settings } = await authHeaders();
  try {
    const resp = await fetchWithTimeout(
      settings.base + "/eval-agent",
      {
        method: "POST",
        headers,
        body: JSON.stringify({ regenerate: false }),
      },
      CONFIG.HEALTH_TIMEOUT_MS
    );
    if (!resp.ok) {
      const detail = await extractDetail(resp);
      if (resp.status === 404) {
        return {
          error:
            "POST /eval-agent not found on " +
            settings.base +
            ". Deploy the latest week-2-rag-api to Render.",
          status: resp.status,
        };
      }
      return { error: detail || "HTTP " + resp.status, status: resp.status };
    }
    return await resp.json();
  } catch (e) {
    const timedOut = e && e.name === "AbortError";
    return {
      error: timedOut ? "Agent checks timed out" : String(e),
      base: settings.base,
    };
  }
}

async function toggleActiveTab() {
  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    const tab = tabs && tabs[0];
    if (!tab || tab.id == null) return;
    try {
      await chrome.tabs.sendMessage(tab.id, { type: "toggle" });
    } catch (_e) {
      // No content script on this tab — ignore.
    }
  } catch (_e) {
    // ignore
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || typeof msg.type !== "string") return undefined;

  if (msg.type === "ask") {
    handleAsk(String(msg.question || "")).then(sendResponse);
    return true;
  }
  if (msg.type === "cancelAsk") {
    sendResponse(cancelAsk());
    return false;
  }
  if (msg.type === "wake") {
    handleWake().then(sendResponse);
    return true;
  }
  if (msg.type === "evalAgent") {
    handleEvalAgent().then(sendResponse);
    return true;
  }
  if (msg.type === "getSettings" || msg.type === "getApiBase") {
    loadSettings().then(sendResponse);
    return true;
  }
  if (msg.type === "saveSettings") {
    saveSettings(msg).then(sendResponse);
    return true;
  }
  if (msg.type === "reportError") {
    reportError(msg.message).then(sendResponse);
    return true;
  }
  return undefined;
});

chrome.commands.onCommand.addListener((command) => {
  if (command === "toggle-zbot") {
    toggleActiveTab();
  }
});

// Ensure install id exists on worker start.
ensureInstallId();
