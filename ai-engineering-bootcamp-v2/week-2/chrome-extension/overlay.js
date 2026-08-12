/**
 * Ask Z-Bot overlay UI. Renders a Shadow DOM overlay (collapsed pill ->
 * expanded panel) and talks to the agent through the background service worker.
 *
 * Plain script (no ES modules): exposes `self.ZBotOverlay`, instantiated by
 * content.js. Depends on config.js (self.ZBOT_CONFIG) and vendor/marked.min.js
 * (self.marked) being loaded first via the manifest content_scripts order.
 */
(function () {
  const CONFIG = self.ZBOT_CONFIG;

  const PANEL_HTML = `
    <div class="zbot-root">
      <button class="zbot-pill" type="button" data-act="open" title="Ask Z-Bot (Alt+Z)">
        <span class="zbot-pill__mark" aria-hidden="true">Z</span>
        <span>Ask Z-Bot</span>
      </button>

      <div class="zbot-panel zbot-hidden" role="dialog" aria-label="Ask Z-Bot">
        <div class="zbot-header">
          <div class="zbot-header__brand">
            <span class="zbot-header__mark" aria-hidden="true">Z</span>
            <span class="zbot-header__title">Ask Z-Bot</span>
          </div>
          <div class="zbot-header__actions">
            <button class="zbot-iconbtn" type="button" data-act="settings" title="Settings" aria-label="Settings">&#9881;</button>
            <button class="zbot-iconbtn" type="button" data-act="close" title="Minimize (Alt+Z)" aria-label="Minimize">&#8211;</button>
          </div>
        </div>
        <div class="zbot-body">
          <form class="zbot-form" data-el="form">
            <input class="zbot-input" data-el="question" type="text"
                   placeholder="Ask a Zearn support question..." autocomplete="off" />
            <button class="zbot-btn" data-el="ask" type="submit">Ask</button>
          </form>
          <div class="zbot-status" data-el="status"></div>
          <div data-el="output"></div>

          <details class="zbot-settings" data-el="settings">
            <summary>Settings</summary>

            <div class="zbot-settings__section">
              <label class="zbot-settings__label" for="zbot-apiurl">Agent API URL</label>
              <div class="zbot-settings__row">
                <input class="zbot-input" id="zbot-apiurl" data-el="apiurl" type="text"
                       placeholder="https://...onrender.com" autocomplete="off" />
              </div>
              <label class="zbot-settings__label" for="zbot-apikey">API key (optional)</label>
              <div class="zbot-settings__row">
                <input class="zbot-input" id="zbot-apikey" data-el="apikey" type="password"
                       placeholder="Required only if AGENT_API_KEY is set on the server"
                       autocomplete="off" />
              </div>
              <div class="zbot-settings__row zbot-settings__row--actions">
                <button class="zbot-btn" data-el="save" type="button">Save</button>
                <button class="zbot-btn zbot-btn--ghost" data-el="reset" type="button">Reset to default</button>
              </div>
              <div class="zbot-settings__hint" data-el="default-hint"></div>
            </div>

            <div class="zbot-settings__section">
              <div class="zbot-settings__label">API health</div>
              <div class="zbot-settings__row zbot-settings__row--actions">
                <span class="zbot-health" data-el="health">Not checked yet</span>
                <button class="zbot-btn zbot-btn--ghost" data-el="health-check" type="button">Check now</button>
              </div>
            </div>

            <div class="zbot-settings__section">
              <div class="zbot-settings__label">Privacy</div>
              <label class="zbot-settings__check">
                <input type="checkbox" data-el="telemetry" />
                Send anonymous error reports (no questions)
              </label>
              <div class="zbot-settings__hint">
                See the <a data-el="privacy-link" href="#" target="_blank" rel="noopener noreferrer">privacy policy</a>.
                Opt-in only; requires TELEMETRY_ENABLED on the API.
              </div>
            </div>

            <div class="zbot-settings__section">
              <div class="zbot-settings__label">Shortcuts &amp; timeouts</div>
              <ul class="zbot-settings__meta">
                <li><kbd>Alt</kbd>+<kbd>Z</kbd> — toggle Ask Z-Bot</li>
                <li data-el="timeouts"></li>
                <li data-el="version"></li>
              </ul>
              <div class="zbot-settings__hint">
                If Alt+Z does nothing, open <code>chrome://extensions/shortcuts</code> and assign it.
              </div>
            </div>
          </details>
        </div>
      </div>
    </div>
  `;

  function sendMessage(message) {
    return new Promise((resolve) => {
      try {
        chrome.runtime.sendMessage(message, (resp) => {
          if (chrome.runtime.lastError) {
            resolve({ error: chrome.runtime.lastError.message });
            return;
          }
          resolve(resp || {});
        });
      } catch (e) {
        resolve({ error: String(e) });
      }
    });
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function renderMarkdownInto(element, text) {
    let html;
    try {
      html = self.marked.parse(String(text || ""));
    } catch (_e) {
      element.textContent = String(text || "");
      return;
    }
    element.innerHTML = html;
    element.querySelectorAll("a").forEach((a) => {
      a.setAttribute("target", "_blank");
      a.setAttribute("rel", "noopener noreferrer");
    });
  }

  function usedWebFallback(steps) {
    return (steps || []).some((step) => {
      const tool = (step && step.tool) || "";
      return tool === "google_search_agent" || tool === "google_search";
    });
  }

  class ZBotOverlay {
    constructor() {
      this.host = null;
      this.shadow = null;
      this.els = {};
      this.wakeTriggered = false;
      this.loading = false;
      this.expanded = false;
      this.defaultBase = CONFIG.DEFAULT_AGENT_API_URL;
    }

    mount() {
      this.host = document.createElement("div");
      this.host.id = "ask-zbot-overlay-host";
      this.host.style.cssText =
        "position:fixed;bottom:20px;right:20px;z-index:2147483647;";
      this.shadow = this.host.attachShadow({ mode: "open" });

      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = chrome.runtime.getURL("overlay.css");
      this.shadow.appendChild(link);

      const wrapper = document.createElement("div");
      wrapper.innerHTML = PANEL_HTML;
      this.shadow.appendChild(wrapper);

      this.pill = this.shadow.querySelector(".zbot-pill");
      this.panel = this.shadow.querySelector(".zbot-panel");
      this.els = {
        form: this.shadow.querySelector('[data-el="form"]'),
        question: this.shadow.querySelector('[data-el="question"]'),
        ask: this.shadow.querySelector('[data-el="ask"]'),
        status: this.shadow.querySelector('[data-el="status"]'),
        output: this.shadow.querySelector('[data-el="output"]'),
        settings: this.shadow.querySelector('[data-el="settings"]'),
        apiurl: this.shadow.querySelector('[data-el="apiurl"]'),
        apikey: this.shadow.querySelector('[data-el="apikey"]'),
        telemetry: this.shadow.querySelector('[data-el="telemetry"]'),
        save: this.shadow.querySelector('[data-el="save"]'),
        reset: this.shadow.querySelector('[data-el="reset"]'),
        health: this.shadow.querySelector('[data-el="health"]'),
        healthCheck: this.shadow.querySelector('[data-el="health-check"]'),
        defaultHint: this.shadow.querySelector('[data-el="default-hint"]'),
        timeouts: this.shadow.querySelector('[data-el="timeouts"]'),
        version: this.shadow.querySelector('[data-el="version"]'),
        privacyLink: this.shadow.querySelector('[data-el="privacy-link"]'),
      };

      this.els.privacyLink.href = chrome.runtime.getURL("privacy-policy.html");

      this.pill.addEventListener("click", () => this.expand());
      this.shadow
        .querySelector('[data-act="close"]')
        .addEventListener("click", () => this.collapse());
      this.shadow
        .querySelector('[data-act="settings"]')
        .addEventListener("click", () => this.openSettings());
      this.els.form.addEventListener("submit", (e) => {
        e.preventDefault();
        this.ask();
      });
      this.els.save.addEventListener("click", () => this.saveSettings());
      this.els.reset.addEventListener("click", () => this.resetSettings());
      this.els.healthCheck.addEventListener("click", () => this.checkHealth(true));
      this.els.telemetry.addEventListener("change", () => {
        sendMessage({
          type: "saveSettings",
          telemetryOptIn: this.els.telemetry.checked,
        });
      });

      document.documentElement.appendChild(this.host);
      this.loadSettings();
    }

    isExpanded() {
      return this.expanded;
    }

    toggle() {
      if (this.expanded) this.collapse();
      else this.expand();
    }

    expand() {
      this.pill.classList.add("zbot-hidden");
      this.panel.classList.remove("zbot-hidden");
      this.expanded = true;
      this.els.question.focus();
      if (!this.wakeTriggered) {
        this.wakeTriggered = true;
        this.wake();
      }
    }

    collapse() {
      this.panel.classList.add("zbot-hidden");
      this.pill.classList.remove("zbot-hidden");
      this.expanded = false;
    }

    openSettings() {
      if (!this.expanded) this.expand();
      this.els.settings.open = true;
      this.els.apiurl.focus();
      this.els.apiurl.select();
    }

    async wake() {
      this.setStatus("Waking up the API…", true);
      this.setHealthPending();
      const resp = await sendMessage({ type: "wake" });
      this.applyHealthResult(resp);
      if (this.loading) return;
      if (resp && resp.ok) this.setStatus("");
      else
        this.setStatus(
          "API is still waking up — your first question may take up to a minute."
        );
    }

    async checkHealth(fromSettings) {
      if (fromSettings) this.setHealthPending();
      const resp = await sendMessage({ type: "wake" });
      this.applyHealthResult(resp);
      if (fromSettings && !this.loading) {
        this.setStatus(resp && resp.ok ? "API is reachable." : "API health check failed.");
        setTimeout(() => {
          if (!this.loading) this.setStatus("");
        }, 1800);
      }
      return resp;
    }

    setHealthPending() {
      this.els.health.className = "zbot-health zbot-health--pending";
      this.els.health.textContent = "Checking…";
    }

    applyHealthResult(resp) {
      if (resp && resp.ok) {
        this.els.health.className = "zbot-health zbot-health--ok";
        this.els.health.textContent = "Reachable · " + (resp.base || "");
      } else {
        this.els.health.className = "zbot-health zbot-health--bad";
        const detail =
          (resp && (resp.error || "HTTP " + resp.status)) || "unreachable";
        this.els.health.textContent = "Unreachable · " + detail;
      }
    }

    async ask() {
      const question = this.els.question.value.trim();
      if (!question || this.loading) return;

      this.loading = true;
      this.els.ask.disabled = true;
      this.els.output.innerHTML = "";
      this.setStatus(
        "Running agent… first request may take up to a minute while the API wakes up.",
        true
      );

      const resp = await sendMessage({ type: "ask", question });

      this.loading = false;
      this.els.ask.disabled = false;
      this.setStatus("");

      if (!resp || resp.error) {
        const message = (resp && resp.error) || "Unknown error.";
        this.renderError(message);
        sendMessage({ type: "reportError", message: message });
        return;
      }
      this.renderResult(resp.answer || "", resp.steps || []);
    }

    setStatus(text, withSpinner) {
      const status = this.els.status;
      status.innerHTML = "";
      if (!text) return;
      if (withSpinner) {
        const spinner = document.createElement("span");
        spinner.className = "zbot-spinner";
        status.appendChild(spinner);
      }
      status.appendChild(document.createTextNode(text));
    }

    renderError(message) {
      const banner = document.createElement("div");
      banner.className = "zbot-banner zbot-banner--error";
      banner.textContent = "Error: " + message;
      this.els.output.appendChild(banner);
    }

    renderResult(answer, steps) {
      const output = this.els.output;
      output.innerHTML = "";

      if (steps && steps.length) {
        const title = document.createElement("div");
        title.className = "zbot-section-title";
        title.textContent = "Think → Act → Observe";
        output.appendChild(title);
        output.appendChild(this.buildSteps(steps));
      }

      const text = (answer || "").trim();
      const isWebFallback =
        text.indexOf(CONFIG.FALLBACK_PREFIX) !== -1 || usedWebFallback(steps);
      const isRefusal =
        !isWebFallback &&
        (!text ||
          text === CONFIG.REFUSAL_MESSAGE ||
          text
            .toLowerCase()
            .indexOf("couldn't find that in the zearn documentation corpus") !== -1);

      if (isWebFallback) {
        output.appendChild(
          this.buildBanner("web", "Not found in Zearn docs — sourced from the web")
        );
      } else if (isRefusal) {
        output.appendChild(this.buildBanner("refusal", "Not found in corpus"));
      }

      const answerTitle = document.createElement("div");
      answerTitle.className = "zbot-section-title";
      answerTitle.textContent = "Answer";
      output.appendChild(answerTitle);

      const answerEl = document.createElement("div");
      answerEl.className = "zbot-answer";
      renderMarkdownInto(answerEl, text || CONFIG.REFUSAL_MESSAGE);
      output.appendChild(answerEl);
    }

    buildBanner(kind, text) {
      const banner = document.createElement("div");
      banner.className = "zbot-banner zbot-banner--" + kind;
      banner.textContent = text;
      return banner;
    }

    buildSteps(steps) {
      const container = document.createElement("div");
      container.className = "zbot-steps";

      steps.forEach((step, index) => {
        const phase = (step && step.phase) || "";
        const el = document.createElement("div");
        const n = index + 1;

        if (phase === "Think") {
          el.className = "zbot-step zbot-step--think";
          const label = document.createElement("div");
          label.className = "zbot-step__label";
          label.textContent = "Step " + n + " — Think";
          el.appendChild(label);
          const body = document.createElement("div");
          renderMarkdownInto(body, step.text || "");
          el.appendChild(body);
        } else if (phase === "Act") {
          el.className = "zbot-step zbot-step--act";
          const args = step.args || {};
          const argStr = Object.keys(args)
            .map((key) => key + "=" + JSON.stringify(args[key]))
            .join(", ");
          el.innerHTML =
            '<div class="zbot-step__label">Step ' +
            n +
            " — Act</div><div><code>" +
            escapeHtml(step.tool || "") +
            "(" +
            escapeHtml(argStr) +
            ")</code></div>";
        } else if (phase === "Observe") {
          el.className = "zbot-step zbot-step--observe";
          const label = document.createElement("div");
          label.className = "zbot-step__label";
          label.textContent = "Step " + n + " — Observe";
          el.appendChild(label);
          const sub = document.createElement("div");
          sub.innerHTML =
            "result from <code>" + escapeHtml(step.tool || "") + "</code>";
          el.appendChild(sub);
          if (step.result) {
            const details = document.createElement("details");
            const summary = document.createElement("summary");
            summary.textContent = "view result";
            const pre = document.createElement("pre");
            pre.textContent = String(step.result);
            details.appendChild(summary);
            details.appendChild(pre);
            el.appendChild(details);
          }
        } else {
          el.className = "zbot-step";
          el.textContent = "Step " + n + " — " + (phase || "unknown");
        }

        container.appendChild(el);
      });

      return container;
    }

    async loadSettings() {
      const resp = await sendMessage({ type: "getSettings" });
      if (resp && resp.defaultBase) this.defaultBase = resp.defaultBase;
      if (resp && resp.base) this.els.apiurl.value = resp.base;
      if (resp) this.els.apikey.value = resp.apiKey || "";
      if (resp) this.els.telemetry.checked = Boolean(resp.telemetryOptIn);
      this.els.defaultHint.textContent =
        "Default: " +
        this.defaultBase +
        " · Local: http://127.0.0.1:8000 · API key only needed if the server sets AGENT_API_KEY";
      const agentSec = Math.round(
        (resp.agentTimeoutMs || CONFIG.AGENT_TIMEOUT_MS) / 1000
      );
      const healthSec = Math.round(
        (resp.healthTimeoutMs || CONFIG.HEALTH_TIMEOUT_MS) / 1000
      );
      this.els.timeouts.textContent =
        "Timeouts: agent " + agentSec + "s · health " + healthSec + "s";
      this.els.version.textContent =
        "Version " + (resp.extensionVersion || CONFIG.EXTENSION_VERSION);
    }

    async saveSettings() {
      const value = this.els.apiurl.value.trim().replace(/\/+$/, "");
      const resp = await sendMessage({
        type: "saveSettings",
        base: value || this.defaultBase,
        apiKey: this.els.apikey.value,
        telemetryOptIn: this.els.telemetry.checked,
      });
      if (resp && resp.base) this.els.apiurl.value = resp.base;
      this.setStatus("Settings saved.");
      this.wakeTriggered = false;
      this.checkHealth(true);
      setTimeout(() => {
        if (!this.loading) this.setStatus("");
      }, 1500);
    }

    async resetSettings() {
      this.els.apiurl.value = this.defaultBase;
      this.els.apikey.value = "";
      this.els.telemetry.checked = false;
      await sendMessage({
        type: "saveSettings",
        base: this.defaultBase,
        apiKey: "",
        telemetryOptIn: false,
      });
      this.setStatus("Reset to defaults.");
      this.wakeTriggered = false;
      this.checkHealth(true);
      setTimeout(() => {
        if (!this.loading) this.setStatus("");
      }, 1500);
    }
  }

  self.ZBotOverlay = ZBotOverlay;
})();
