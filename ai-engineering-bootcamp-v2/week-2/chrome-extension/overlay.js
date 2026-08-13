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

  const TABS = [
    { id: "ask", label: "Ask" },
    { id: "tao", label: "TAO" },
    { id: "trace", label: "Trace" },
    { id: "memory", label: "Memory" },
    { id: "settings", label: "Settings" },
  ];

  const DEFAULT_TAB = "ask";

  // Layout toggle icons: a window frame holding either a small floating card
  // (overlay) or a filled right third (right panel). Each one shows the layout
  // the button switches *to*, and inherits the header's text color.
  const ICON_FRAME =
    '<rect x="1" y="1" width="20" height="14" rx="2.5" stroke="currentColor" stroke-width="2" fill="none"/>';

  const ICON_OVERLAY_SVG =
    '<svg viewBox="0 0 22 16" width="19" height="14" aria-hidden="true" focusable="false">' +
    ICON_FRAME +
    '<rect x="12.5" y="6.5" width="6" height="5.5" rx="0.8" fill="currentColor"/>' +
    "</svg>";

  const ICON_PANEL_SVG =
    '<svg viewBox="0 0 22 16" width="19" height="14" aria-hidden="true" focusable="false">' +
    ICON_FRAME +
    '<path d="M13.5 2H18.5A1.5 1.5 0 0 1 20 3.5V12.5A1.5 1.5 0 0 1 18.5 14H13.5Z" fill="currentColor"/>' +
    "</svg>";

  // Minimize collapses the panel back to the floating pill, so the button
  // shows the pill itself (resized 60×20 source → compact header glyph).
  const ICON_PILL_SVG =
    '<svg viewBox="0 0 30 10" width="12" height="4" aria-hidden="true" focusable="false">' +
    '<rect x="0" y="0" width="30" height="10" rx="5" fill="currentColor"/>' +
    "</svg>";

  const TABS_HTML = TABS.map(
    (tab) =>
      `<button class="zbot-tab" type="button" role="tab" data-tab="${tab.id}"` +
      ` id="zbot-tab-${tab.id}" aria-controls="zbot-panel-${tab.id}"` +
      ` aria-selected="false" tabindex="-1">${tab.label}</button>`
  ).join("");

  const PANEL_HTML = `
    <div class="zbot-root">
      <button class="zbot-pill" type="button" data-act="open" title="Ask Z-Bot (Alt+Z)">
        <img class="zbot-brand-mark zbot-pill__mark" data-el="brand-mark" alt="" width="22" height="22" aria-hidden="true" />
        <span>Ask Z-Bot</span>
      </button>

      <div class="zbot-panel zbot-hidden" role="dialog" aria-label="Ask Z-Bot">
        <div class="zbot-header">
          <div class="zbot-header__brand">
            <img class="zbot-brand-mark zbot-header__mark" data-el="brand-mark" alt="" width="24" height="24" aria-hidden="true" />
            <span class="zbot-header__title">Ask Z-Bot</span>
          </div>
          <div class="zbot-header__actions">
            <button class="zbot-iconbtn" type="button" data-act="layout" data-el="layout">
              <span class="zbot-icon" data-el="icon-overlay">${ICON_OVERLAY_SVG}</span>
              <span class="zbot-icon" data-el="icon-panel">${ICON_PANEL_SVG}</span>
            </button>
            <button class="zbot-iconbtn" type="button" data-act="close" title="Minimize to pill (Alt+Z)" aria-label="Minimize to pill">
              <span class="zbot-icon">${ICON_PILL_SVG}</span>
            </button>
          </div>
        </div>

        <div class="zbot-tabs" role="tablist" aria-label="Ask Z-Bot sections">${TABS_HTML}</div>

        <div class="zbot-body">
          <section class="zbot-tabpanel zbot-tabpanel--ask" role="tabpanel" data-tabpanel="ask"
                   id="zbot-panel-ask" aria-labelledby="zbot-tab-ask">
            <div class="zbot-ask-scroll">
              <div data-el="output"></div>
              <div class="zbot-status" data-el="status"></div>
            </div>
            <div class="zbot-ask-footer">
              <form class="zbot-form" data-el="form">
                <input class="zbot-input" data-el="question" type="text"
                       placeholder="Ask a Zearn support question..." autocomplete="off" />
                <button class="zbot-btn" data-el="ask" type="submit">Ask</button>
              </form>
              <p class="zbot-disclaimer">
                AI can make mistakes. See
                <a data-el="privacy-link" href="#" target="_blank" rel="noopener noreferrer">privacy policy</a>.
              </p>
            </div>
          </section>

          <section class="zbot-tabpanel zbot-hidden" role="tabpanel" data-tabpanel="tao"
                   id="zbot-panel-tao" aria-labelledby="zbot-tab-tao">
            <div class="zbot-section-title">Think &#8594; Act &#8594; Observe</div>
            <div data-el="tao"></div>
          </section>

          <section class="zbot-tabpanel zbot-hidden" role="tabpanel" data-tabpanel="trace"
                   id="zbot-panel-trace" aria-labelledby="zbot-tab-trace">
            <div class="zbot-section-title">Agent checks</div>
            <p class="zbot-trace-intro">
              Deterministic pass/fail checks on committed agent traces (Week 4 TRACE).
            </p>
            <div class="zbot-settings__row zbot-settings__row--actions">
              <button class="zbot-btn zbot-btn--ghost" data-el="trace-run" type="button">
                Run checks
              </button>
            </div>
            <div class="zbot-status" data-el="trace-status"></div>
            <div data-el="trace-output"></div>
          </section>

          <section class="zbot-tabpanel zbot-hidden" role="tabpanel" data-tabpanel="memory"
                   id="zbot-panel-memory" aria-labelledby="zbot-tab-memory">
            <div class="zbot-section-title">Memory</div>
            <div class="zbot-empty">Coming soon.</div>
          </section>

          <section class="zbot-tabpanel zbot-hidden" role="tabpanel" data-tabpanel="settings"
                   id="zbot-panel-settings" aria-labelledby="zbot-tab-settings">
            <div class="zbot-settings__section">
              <div class="zbot-settings__label">API health</div>
              <div class="zbot-settings__row zbot-settings__row--actions">
                <span class="zbot-health" data-el="health">Not checked yet</span>
                <button class="zbot-btn zbot-btn--ghost" data-el="health-check" type="button">Check now</button>
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
          </section>
        </div>
      </div>
    </div>
  `;

  const HOST_CSS_FLOATING =
    "position:fixed;bottom:20px;right:20px;z-index:2147483647;";
  const HOST_CSS_DOCKED =
    "position:fixed;top:0;right:0;bottom:0;z-index:2147483647;";

  const LAYOUT_LABELS = {
    // While docked, the button floats the panel as an overlay.
    panel: "Switch to floating overlay",
    // While floating, the button docks the panel to the right edge.
    overlay: "Expand into right panel",
  };

  // Docking reflows the host page instead of covering it. The panel gives up
  // width to keep the page usable, and only overlays when even a narrow panel
  // would leave no room. DOCKED_PANEL_WIDTH_PX matches .zbot-panel in the CSS.
  const DOCKED_PANEL_WIDTH_PX = 420;
  const MIN_DOCKED_PANEL_WIDTH_PX = 300;
  const MIN_PAGE_WIDTH_PX = 320;

  const PAGE_SHIFT_CLASS = "ask-zbot-page-shift";
  const PAGE_SHIFT_STYLE_ID = "ask-zbot-page-shift-style";
  const PAGE_SHIFT_CSS =
    "html." +
    PAGE_SHIFT_CLASS +
    "{margin-right:var(--zbot-panel-width)!important;width:auto!important;}" +
    "html." +
    PAGE_SHIFT_CLASS +
    " .navigation_fixed," +
    "html." +
    PAGE_SHIFT_CLASS +
    " .navigation_fixed.w-nav," +
    "html." +
    PAGE_SHIFT_CLASS +
    " .w-nav-overlay," +
    "html." +
    PAGE_SHIFT_CLASS +
    " .header," +
    "html." +
    PAGE_SHIFT_CLASS +
    " header.site-header{" +
    "width:calc(100% - var(--zbot-panel-width))!important;" +
    "max-width:calc(100% - var(--zbot-panel-width))!important;" +
    "}";

  function ensurePageShiftStyle() {
    if (document.getElementById(PAGE_SHIFT_STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = PAGE_SHIFT_STYLE_ID;
    style.textContent = PAGE_SHIFT_CSS;
    document.head.appendChild(style);
  }

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
      this.layoutMode = CONFIG.DEFAULT_LAYOUT_MODE;
      this.activeTab = DEFAULT_TAB;
      this.pageShiftActive = false;
      this.askGeneration = 0;
    }

    mount() {
      this.host = document.createElement("div");
      this.host.id = "ask-zbot-overlay-host";
      this.host.style.cssText = HOST_CSS_FLOATING;
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
      this.tabButtons = Array.from(this.shadow.querySelectorAll(".zbot-tab"));
      this.tabPanels = Array.from(this.shadow.querySelectorAll(".zbot-tabpanel"));
      this.els = {
        form: this.shadow.querySelector('[data-el="form"]'),
        question: this.shadow.querySelector('[data-el="question"]'),
        ask: this.shadow.querySelector('[data-el="ask"]'),
        status: this.shadow.querySelector('[data-el="status"]'),
        output: this.shadow.querySelector('[data-el="output"]'),
        tao: this.shadow.querySelector('[data-el="tao"]'),
        layout: this.shadow.querySelector('[data-el="layout"]'),
        iconOverlay: this.shadow.querySelector('[data-el="icon-overlay"]'),
        iconPanel: this.shadow.querySelector('[data-el="icon-panel"]'),
        health: this.shadow.querySelector('[data-el="health"]'),
        healthCheck: this.shadow.querySelector('[data-el="health-check"]'),
        traceRun: this.shadow.querySelector('[data-el="trace-run"]'),
        traceStatus: this.shadow.querySelector('[data-el="trace-status"]'),
        traceOutput: this.shadow.querySelector('[data-el="trace-output"]'),
        timeouts: this.shadow.querySelector('[data-el="timeouts"]'),
        version: this.shadow.querySelector('[data-el="version"]'),
        privacyLink: this.shadow.querySelector('[data-el="privacy-link"]'),
      };

      this.els.privacyLink.href = chrome.runtime.getURL("privacy-policy.html");
      const markUrl = chrome.runtime.getURL("icons/zbot-mark.png");
      this.shadow.querySelectorAll('[data-el="brand-mark"]').forEach((img) => {
        img.src = markUrl;
      });

      this.pill.addEventListener("click", () => this.expand());
      this.shadow
        .querySelector('[data-act="close"]')
        .addEventListener("click", () => this.collapse());
      this.els.layout.addEventListener("click", () => this.toggleLayout());
      this.tabButtons.forEach((button) => {
        button.addEventListener("click", () =>
          this.switchTab(button.dataset.tab)
        );
      });
      this.els.form.addEventListener("submit", (e) => {
        e.preventDefault();
        if (this.loading) this.stopAsk();
        else this.ask();
      });
      this.els.healthCheck.addEventListener("click", () => this.checkHealth(true));
      this.els.traceRun.addEventListener("click", () => this.runTraceChecks());

      window.addEventListener("resize", () => {
        if (this.layoutMode === "panel" && this.expanded) this.applyPageShift();
      });

      document.documentElement.appendChild(this.host);
      this.applyLayout();
      this.switchTab(DEFAULT_TAB);
      this.renderTaoEmpty();
      this.loadSettings();
    }

    applyLayout() {
      const docked = this.layoutMode === "panel";
      this.host.style.cssText =
        docked && this.expanded ? HOST_CSS_DOCKED : HOST_CSS_FLOATING;
      this.panel.classList.toggle("zbot-panel--docked", docked);
      this.panel.classList.toggle("zbot-panel--floating", !docked);

      const label = LAYOUT_LABELS[docked ? "panel" : "overlay"];
      this.els.layout.title = label;
      this.els.layout.setAttribute("aria-label", label);
      this.els.iconOverlay.classList.toggle("zbot-hidden", !docked);
      this.els.iconPanel.classList.toggle("zbot-hidden", docked);

      if (docked && this.expanded) {
        this.applyPageShift();
      } else {
        this.panel.style.removeProperty("width");
        this.clearPageShift();
      }
    }

    /**
     * Inset the host page so the docked panel sits beside the content rather
     * than on top of it. Also shrinks known fixed headers (e.g. Zearn
     * `.navigation_fixed`) so sign-in / search controls stay visible.
     */
    applyPageShift() {
      const available = window.innerWidth - MIN_PAGE_WIDTH_PX;
      if (available < MIN_DOCKED_PANEL_WIDTH_PX) {
        this.panel.style.removeProperty("width");
        this.clearPageShift();
        return;
      }

      const width = Math.min(DOCKED_PANEL_WIDTH_PX, available);
      this.panel.style.width = width + "px";

      ensurePageShiftStyle();
      const root = document.documentElement;
      root.style.setProperty("--zbot-panel-width", width + "px");
      root.classList.add(PAGE_SHIFT_CLASS);
      this.pageShiftActive = true;
    }

    clearPageShift() {
      if (!this.pageShiftActive) return;
      this.pageShiftActive = false;
      const root = document.documentElement;
      root.classList.remove(PAGE_SHIFT_CLASS);
      root.style.removeProperty("--zbot-panel-width");
    }

    toggleLayout() {
      this.layoutMode = this.layoutMode === "panel" ? "overlay" : "panel";
      this.applyLayout();
      sendMessage({ type: "saveSettings", layoutMode: this.layoutMode });
    }

    switchTab(tabId) {
      const id = TABS.some((tab) => tab.id === tabId) ? tabId : DEFAULT_TAB;
      this.activeTab = id;

      this.tabButtons.forEach((button) => {
        const selected = button.dataset.tab === id;
        button.classList.toggle("zbot-tab--active", selected);
        button.setAttribute("aria-selected", String(selected));
        button.tabIndex = selected ? 0 : -1;
      });
      this.tabPanels.forEach((panel) => {
        panel.classList.toggle(
          "zbot-hidden",
          panel.dataset.tabpanel !== id
        );
      });
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
      this.applyLayout();
      this.switchTab(DEFAULT_TAB);
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
      this.applyLayout();
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

    async runTraceChecks() {
      this.els.traceStatus.textContent = "Running agent checks…";
      this.els.traceOutput.innerHTML = "";
      const resp = await sendMessage({ type: "evalAgent" });
      if (!resp || resp.error) {
        this.els.traceStatus.textContent =
          "Checks failed: " + ((resp && resp.error) || "unknown error");
        return;
      }
      this.renderTraceResults(resp);
      const summary = resp.summary || {};
      this.els.traceStatus.textContent =
        summary.all_checks_passed +
        "/" +
        summary.trace_count +
        " traces passed all checks";
    }

    renderTraceResults(data) {
      const container = document.createElement("div");
      container.className = "zbot-trace-results";
      const summary = data.summary || {};
      const checks = summary.checks || {};

      const heading = document.createElement("div");
      heading.className = "zbot-section-title";
      heading.textContent = "Check pass rates";
      container.appendChild(heading);

      Object.keys(checks).forEach((name) => {
        const stats = checks[name] || {};
        const row = document.createElement("div");
        row.className = "zbot-trace-row";
        const rate =
          typeof stats.pass_rate === "number"
            ? Math.round(stats.pass_rate * 100) + "%"
            : "—";
        row.textContent =
          name + ": " + stats.passed + "/" + summary.trace_count + " (" + rate + ")";
        container.appendChild(row);
      });

      const before = data.before && data.before.summary && data.before.summary.checks;
      const after = data.after && data.after.summary && data.after.summary.checks;
      if (before && after && before.citation_present && after.citation_present) {
        const compare = document.createElement("div");
        compare.className = "zbot-trace-row zbot-trace-row--highlight";
        const bRate = Math.round((before.citation_present.pass_rate || 0) * 100);
        const aRate = Math.round((after.citation_present.pass_rate || 0) * 100);
        compare.textContent =
          "citation_present: " + bRate + "% → " + aRate + "% (before/after fix)";
        container.appendChild(compare);
      }

      const rows = data.rows || [];
      if (rows.length) {
        const failHeading = document.createElement("div");
        failHeading.className = "zbot-section-title";
        failHeading.textContent = "Failed traces";
        container.appendChild(failHeading);

        rows
          .filter((row) => !row.passed)
          .forEach((row) => {
            const item = document.createElement("div");
            item.className = "zbot-trace-row";
            const failed = Object.keys(row.checks || {}).filter(
              (name) => row.checks[name] && !row.checks[name].passed
            );
            item.textContent =
              row.id + " — " + failed.join(", ") + " — " + row.question;
            container.appendChild(item);
          });
      }

      this.els.traceOutput.appendChild(container);
    }

    async ask() {
      const question = this.els.question.value.trim();
      if (!question || this.loading) return;

      const generation = ++this.askGeneration;
      this.loading = true;
      this.setAskButtonMode("stop");
      this.els.output.innerHTML = "";
      this.els.tao.innerHTML = "";
      this.setStatus(
        "Running agent… first request may take up to a minute while the API wakes up.",
        true
      );

      const resp = await sendMessage({ type: "ask", question });
      if (generation !== this.askGeneration) return;

      this.loading = false;
      this.setAskButtonMode("ask");
      this.setStatus("");

      if (resp && resp.cancelled) {
        this.setStatus("Stopped.");
        return;
      }
      if (!resp || resp.error) {
        const message = (resp && resp.error) || "Unknown error.";
        this.renderError(message);
        sendMessage({ type: "reportError", message: message });
        return;
      }
      this.renderResult(resp.answer || "", resp.steps || []);
    }

    stopAsk() {
      if (!this.loading) return;
      this.askGeneration += 1;
      this.loading = false;
      this.setAskButtonMode("ask");
      this.setStatus("Stopping…");
      sendMessage({ type: "cancelAsk" }).then(() => {
        if (!this.loading) this.setStatus("Stopped.");
      });
    }

    setAskButtonMode(mode) {
      const stop = mode === "stop";
      this.els.ask.textContent = stop ? "Stop" : "Ask";
      this.els.ask.classList.toggle("zbot-btn--stop", stop);
      this.els.ask.setAttribute("aria-label", stop ? "Stop" : "Ask");
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
      this.renderTaoEmpty();
    }

    renderTaoEmpty() {
      this.els.tao.innerHTML = "";
      const empty = document.createElement("div");
      empty.className = "zbot-empty";
      empty.textContent =
        "Ask a question to see the agent's Think → Act → Observe steps.";
      this.els.tao.appendChild(empty);
    }

    renderResult(answer, steps) {
      const output = this.els.output;
      output.innerHTML = "";

      if (steps && steps.length) {
        this.els.tao.innerHTML = "";
        this.els.tao.appendChild(this.buildSteps(steps));
      } else {
        this.renderTaoEmpty();
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
      if (resp && resp.layoutMode && resp.layoutMode !== this.layoutMode) {
        this.layoutMode = resp.layoutMode;
        this.applyLayout();
      }
      const agentSec = Math.round(
        ((resp && resp.agentTimeoutMs) || CONFIG.AGENT_TIMEOUT_MS) / 1000
      );
      const healthSec = Math.round(
        ((resp && resp.healthTimeoutMs) || CONFIG.HEALTH_TIMEOUT_MS) / 1000
      );
      this.els.timeouts.textContent =
        "Timeouts: agent " + agentSec + "s · health " + healthSec + "s";
      this.els.version.textContent =
        "Version " +
        ((resp && resp.extensionVersion) || CONFIG.EXTENSION_VERSION);
    }
  }

  self.ZBotOverlay = ZBotOverlay;
})();
