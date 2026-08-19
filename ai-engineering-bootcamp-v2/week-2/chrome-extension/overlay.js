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
    { id: "history", label: "History" },
    { id: "tao", label: "TAO" },
    { id: "trace", label: "Trace" },
    { id: "health", label: "Health" },
  ];

  const DEFAULT_TAB = "ask";

  const HEALTH_CHECK_LABELS = {
    pinecone: "Pinecone (vector search)",
    embeddings: "OpenAI embeddings",
    gemini: "Gemini (agent)",
    bm25: "Keyword search (BM25)",
    database: "Chat history database",
  };

  const HEALTH_USAGE_LABELS = {
    render: "Render",
    pinecone: "Pinecone",
    openai: "OpenAI",
    gemini: "Gemini",
  };

  const HEALTH_USAGE_ORDER = ["render", "pinecone", "openai", "gemini"];

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
      <button class="zbot-pill" type="button" data-act="open"
              title="Ask Z-Bot (Alt+Z)" aria-label="Ask Z-Bot (Alt+Z)">
        <img class="zbot-brand-mark zbot-pill__mark" data-el="brand-mark" alt="" width="26" height="26" aria-hidden="true" />
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
              <div class="zbot-thread" data-el="output"></div>
              <div class="zbot-status" data-el="status"></div>
            </div>
            <div class="zbot-ask-footer">
              <span class="zbot-context-note" data-el="context-note"></span>
              <form class="zbot-form zbot-form--ask" data-el="form">
                <div class="zbot-composer" data-el="composer">
                  <textarea class="zbot-input zbot-input--question" data-el="question" rows="1"
                            placeholder="Ask a Zearn support question..." autocomplete="off"></textarea>
                  <div class="zbot-composer__interact">
                    <label class="zbot-retrieval-mode">
                      <span class="zbot-retrieval-mode__tooltip" role="tooltip">Answer retrieval</span>
                      <span class="zbot-retrieval-mode__face" aria-hidden="true">
                        <span class="zbot-retrieval-mode__label" data-el="retrieval-mode-label">Fast</span>
                        <svg class="zbot-retrieval-mode__chevron" viewBox="0 0 9 9"
                             aria-hidden="true" focusable="false">
                          <path d="M1.5 2.75 4.5 6.5 7.5 2.75" fill="none" stroke="currentColor"
                                stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                      </span>
                      <select class="zbot-retrieval-mode__select" data-el="retrieval-mode"
                              aria-label="Answer retrieval">
                        <option value="fast" selected>Fast</option>
                        <option value="slow">Slow</option>
                      </select>
                    </label>
                    <button class="zbot-btn zbot-btn--ask" data-el="ask" type="submit">Ask</button>
                  </div>
                </div>
              </form>
              <div class="zbot-ask-footer-bar">
                <p class="zbot-disclaimer">
                  AI can make mistakes. See
                  <a data-el="privacy-link" href="#" target="_blank" rel="noopener noreferrer">privacy policy</a>.
                </p>
                <button class="zbot-newchat-link" data-el="new-chat" type="button">
                  <svg class="zbot-newchat-link__icon" width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                    <path d="M18.375 2.625a1 1 0 0 1 1.414 0l2.586 2.586a1 1 0 0 1 0 1.414L12.5 16.5l-4 1 1-4Z"/>
                  </svg>
                  <span class="zbot-newchat-link__label">New chat</span>
                </button>
              </div>
            </div>
          </section>

          <section class="zbot-tabpanel zbot-hidden" role="tabpanel" data-tabpanel="history"
                   id="zbot-panel-history" aria-labelledby="zbot-tab-history">
            <div class="zbot-history-list-view" data-el="history-list-view">
              <div class="zbot-section-title">Saved chats</div>
              <div class="zbot-status" data-el="history-status"></div>
              <div class="zbot-history-list" data-el="history-list"></div>
            </div>
            <div class="zbot-history-detail-view zbot-hidden" data-el="history-detail-view">
              <div class="zbot-settings__row zbot-settings__row--actions">
                <button class="zbot-btn zbot-btn--ghost" data-el="history-back" type="button">&#8592; Back</button>
                <button class="zbot-btn" data-el="history-continue" type="button">Continue this chat</button>
              </div>
              <div class="zbot-history-detail-title" data-el="history-detail-title"></div>
              <div class="zbot-thread" data-el="history-detail"></div>
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

          <section class="zbot-tabpanel zbot-hidden" role="tabpanel" data-tabpanel="health"
                   id="zbot-panel-health" aria-labelledby="zbot-tab-health">
            <div class="zbot-settings__section">
              <div class="zbot-settings__label">API</div>
              <div class="zbot-settings__row zbot-settings__row--actions">
                <span class="zbot-health" data-el="health">Not checked yet</span>
                <button class="zbot-btn zbot-btn--ghost" data-el="health-check" type="button">Check now</button>
              </div>
            </div>
            <div class="zbot-settings__section">
              <div class="zbot-settings__label">Dependencies</div>
              <ul class="zbot-health-list" data-el="health-checks"></ul>
            </div>
            <div class="zbot-settings__section">
              <div class="zbot-settings__label">Usage &amp; quotas</div>
              <ul class="zbot-health-list" data-el="health-usage"></ul>
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
  const FIXED_HEADER_SELECTORS = [
    ".navigation_fixed",
    ".navigation_fixed.w-nav",
    ".w-nav-overlay",
    ".header",
    "header.site-header",
  ];

  /** Remove docked-panel inset styles from the host page (safe to call anytime). */
  function cleanupPageShiftStyles() {
    const root = document.documentElement;
    if (root) {
      root.classList.remove(PAGE_SHIFT_CLASS);
      root.style.removeProperty("--zbot-panel-width");
      root.style.removeProperty("margin-right");
      root.style.removeProperty("width");
    }
    FIXED_HEADER_SELECTORS.forEach((selector) => {
      document.querySelectorAll(selector).forEach((el) => {
        el.style.removeProperty("width");
        el.style.removeProperty("max-width");
      });
    });
  }

  if (!window.__zbotPageShiftCleanupRegistered) {
    window.__zbotPageShiftCleanupRegistered = true;
    window.addEventListener("pagehide", cleanupPageShiftStyles);
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

  function hasBulletedSourcesSection(text) {
    return /(?:\*\*Sources:\*\*|Sources:)\s*\n(?:(?:[-*]\s+|\d+\.\s+)\[[^\]]+\]\([^)]+\)\s*\n?)+/i.test(
      String(text || "")
    );
  }

  function stripDuplicateInlineSources(text) {
    let raw = String(text || "").trim();
    if (!hasBulletedSourcesSection(raw)) return raw;
    raw = raw.replace(/\n---\s*\n+Source:\s*[^\n]+\s*$/i, "");
    raw = raw.replace(/\n+Source:\s*[^\n]+\s*$/i, "");
    return raw.trim();
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

  function classifyAnswer(answer, steps) {
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
    return { isWebFallback, isRefusal, text };
  }

  const FONT_FAMILY = "Source Sans Pro";
  const FONT_DEFS = [
    { weight: "400", style: "normal", path: "fonts/source-sans-pro-regular.ttf" },
    { weight: "600", style: "normal", path: "fonts/source-sans-pro-semibold.ttf" },
    { weight: "700", style: "normal", path: "fonts/source-sans-pro-bold.ttf" },
    { weight: "400", style: "italic", path: "fonts/source-sans-pro-italic.ttf" },
  ];

  /** Register bundled Source Sans Pro for the shadow overlay (absolute extension URLs). */
  function injectBundledFonts(shadow) {
    const faces = FONT_DEFS.map((def) => ({
      ...def,
      url: chrome.runtime.getURL(def.path),
    }));

    const style = document.createElement("style");
    style.textContent = faces
      .map(
        (f) =>
          '@font-face{font-family:"' +
          FONT_FAMILY +
          '";font-style:' +
          f.style +
          ";font-weight:" +
          f.weight +
          ';font-display:swap;src:url("' +
          f.url +
          '") format("truetype");}'
      )
      .join("");
    shadow.appendChild(style);

    if (typeof FontFace !== "undefined" && document.fonts) {
      Promise.all(
        faces.map(function (f) {
          const face = new FontFace(FONT_FAMILY, 'url("' + f.url + '")', {
            weight: f.weight,
            style: f.style,
          });
          return face.load().then(function (loaded) {
            document.fonts.add(loaded);
          });
        })
      ).catch(function () {
        /* @font-face block above is the fallback */
      });
    }
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
      this._shiftedHeaders = [];
      this.thread = [];
      this.askGeneration = 0;
      this.sessionId = null;
      this.sessionTitle = "";
      this.tokenCount = 0;
      this.contextLimit = CONFIG.CONTEXT_TOKEN_LIMIT;
      this.contextWarn = CONFIG.CONTEXT_TOKEN_WARN;
      this.retrievalMode = "fast";
      this.activeHistoryMenu = null;
      this.openHistoryData = null;
    }

    genSessionId() {
      if (self.crypto && crypto.randomUUID) return crypto.randomUUID();
      return "sess-" + Date.now() + "-" + Math.random().toString(16).slice(2);
    }

    mount() {
      this.host = document.createElement("div");
      this.host.id = "ask-zbot-overlay-host";
      this.host.style.cssText = HOST_CSS_FLOATING;
      this.shadow = this.host.attachShadow({ mode: "open" });

      injectBundledFonts(this.shadow);

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
        composer: this.shadow.querySelector('[data-el="composer"]'),
        question: this.shadow.querySelector('[data-el="question"]'),
        retrievalMode: this.shadow.querySelector('[data-el="retrieval-mode"]'),
        retrievalModeLabel: this.shadow.querySelector('[data-el="retrieval-mode-label"]'),
        ask: this.shadow.querySelector('[data-el="ask"]'),
        status: this.shadow.querySelector('[data-el="status"]'),
        output: this.shadow.querySelector('[data-el="output"]'),
        tao: this.shadow.querySelector('[data-el="tao"]'),
        layout: this.shadow.querySelector('[data-el="layout"]'),
        iconOverlay: this.shadow.querySelector('[data-el="icon-overlay"]'),
        iconPanel: this.shadow.querySelector('[data-el="icon-panel"]'),
        health: this.shadow.querySelector('[data-el="health"]'),
        healthCheck: this.shadow.querySelector('[data-el="health-check"]'),
        healthChecks: this.shadow.querySelector('[data-el="health-checks"]'),
        healthUsage: this.shadow.querySelector('[data-el="health-usage"]'),
        traceRun: this.shadow.querySelector('[data-el="trace-run"]'),
        traceStatus: this.shadow.querySelector('[data-el="trace-status"]'),
        traceOutput: this.shadow.querySelector('[data-el="trace-output"]'),
        privacyLink: this.shadow.querySelector('[data-el="privacy-link"]'),
        newChat: this.shadow.querySelector('[data-el="new-chat"]'),
        contextNote: this.shadow.querySelector('[data-el="context-note"]'),
        historyListView: this.shadow.querySelector('[data-el="history-list-view"]'),
        historyDetailView: this.shadow.querySelector('[data-el="history-detail-view"]'),
        historyList: this.shadow.querySelector('[data-el="history-list"]'),
        historyStatus: this.shadow.querySelector('[data-el="history-status"]'),
        historyDetail: this.shadow.querySelector('[data-el="history-detail"]'),
        historyDetailTitle: this.shadow.querySelector('[data-el="history-detail-title"]'),
        historyBack: this.shadow.querySelector('[data-el="history-back"]'),
        historyContinue: this.shadow.querySelector('[data-el="history-continue"]'),
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
      this.els.question.addEventListener("input", () => this.resizeQuestionInput());
      if (this.els.retrievalMode) {
        this.els.retrievalMode.addEventListener("change", () =>
          this.saveRetrievalMode(this.els.retrievalMode.value)
        );
      }
      this.els.question.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          if (this.loading) this.stopAsk();
          else this.ask();
        }
      });
      this.els.healthCheck.addEventListener("click", () => this.checkHealth(true));
      this.els.traceRun.addEventListener("click", () => this.runTraceChecks());
      this.els.newChat.addEventListener("click", () => this.startNewChat());
      this.els.historyBack.addEventListener("click", () => this.showHistoryList());
      this.els.historyContinue.addEventListener("click", () =>
        this.continueHistorySession()
      );
      this.shadow.addEventListener("click", (e) => {
        if (!this.activeHistoryMenu) return;
        const path = typeof e.composedPath === "function" ? e.composedPath() : [e.target];
        const insideMenu = path.some(
          (node) =>
            node instanceof Element &&
            node.classList.contains("zbot-history-item__menu-wrap")
        );
        if (!insideMenu) this.closeHistoryMenu();
      });

      window.addEventListener("resize", () => {
        if (this.layoutMode === "panel" && this.expanded) this.applyPageShift();
        if (this.expanded) this.resizeQuestionInput();
      });

      // Best-effort: on refresh / tab close / navigation, mark the session
      // ended. Completed turns are already persisted server-side per turn, so
      // this only records why the session stopped.
      window.addEventListener("pagehide", () => {
        if (this.sessionId && this.thread.some((turn) => !turn.pending)) {
          sendMessage({
            type: "endSession",
            sessionId: this.sessionId,
            reason: "unload",
          });
        }
      });

      this.attachHostToPage();
      this.applyLayout();
      this.switchTab(DEFAULT_TAB);
      this.renderTaoEmpty();
      this.loadSettings();
      this.restoreCurrentSession();
    }

    attachHostToPage() {
      const pageRoot = document.documentElement || document.body;
      if (pageRoot) {
        pageRoot.appendChild(this.host);
        return;
      }
      const finish = () => {
        const root = document.documentElement || document.body;
        if (root) root.appendChild(this.host);
      };
      if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", finish, { once: true });
      } else {
        requestAnimationFrame(finish);
      }
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
      if (this.expanded) this.resizeQuestionInput();
    }

    /** Grow the question box with wrapped lines, capped at half the panel height. */
    resizeQuestionInput() {
      const el = this.els.question;
      if (!el || !this.panel) return;

      const minHeight = 24;
      const maxHeight = Math.floor(this.panel.clientHeight * 0.5);
      this.panel.style.setProperty("--zbot-question-max-height", maxHeight + "px");

      el.style.height = "auto";
      const scrollHeight = el.scrollHeight;
      const nextHeight = Math.max(minHeight, Math.min(scrollHeight, maxHeight - 12));
      el.style.height = nextHeight + "px";
      el.style.overflowY = scrollHeight > maxHeight ? "auto" : "hidden";

      if (this.els.composer) {
        this.els.composer.classList.toggle(
          "zbot-composer--multiline",
          nextHeight > minHeight + 2
        );
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

      const root = document.documentElement;
      if (!root) {
        this.pageShiftActive = false;
        return;
      }

      const staleStyle = document.getElementById(PAGE_SHIFT_STYLE_ID);
      if (staleStyle) staleStyle.remove();

      const inset = width + "px";
      root.style.setProperty("--zbot-panel-width", inset);
      root.style.setProperty("margin-right", inset, "important");
      root.style.setProperty("width", "auto", "important");
      root.classList.remove(PAGE_SHIFT_CLASS);

      this._shiftedHeaders = [];
      FIXED_HEADER_SELECTORS.forEach((selector) => {
        document.querySelectorAll(selector).forEach((el) => {
          this._shiftedHeaders.push(el);
          el.style.setProperty("width", "calc(100% - " + inset + ")", "important");
          el.style.setProperty("max-width", "calc(100% - " + inset + ")", "important");
        });
      });

      this.pageShiftActive = true;
    }

    clearPageShift() {
      if (!this.pageShiftActive) return;
      this.pageShiftActive = false;
      cleanupPageShiftStyles();
      this._shiftedHeaders = [];
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

      if (id === "history") {
        this.showHistoryList();
        this.loadHistory();
      } else {
        this.closeHistoryMenu();
      }
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
      this.resizeQuestionInput();
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
      if (resp && resp.ok) {
        const pinecone =
          resp.health && resp.health.checks && resp.health.checks.pinecone;
        if (pinecone && pinecone.ok === false) {
          this.setStatus("Vector search unavailable: " + (pinecone.detail || "Pinecone error"));
        } else {
          this.setStatus("");
        }
      } else
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
      this.renderHealthChecks(null, "Checking…");
      this.renderHealthUsage(null, "Checking…");
    }

    applyHealthResult(resp) {
      if (resp && resp.ok) {
        const health = (resp && resp.health) || {};
        const checks = health.checks || {};
        const usage = health.usage || {};
        const checkFail = Object.keys(checks).some(function (name) {
          return checks[name] && checks[name].ok === false;
        });
        const usageLevel = health.usage_level || "";
        let tone = "ok";
        let summary = "Reachable · ";
        if (checkFail) {
          tone = "warn";
          summary = "Reachable, but a dependency is failing · ";
        } else if (usageLevel === "over") {
          tone = "warn";
          summary = "Reachable, but a quota is exhausted · ";
        } else if (usageLevel === "warn") {
          tone = "warn";
          summary = "Reachable · approaching a quota · ";
        }
        this.els.health.className = "zbot-health zbot-health--" + tone;
        this.els.health.textContent = summary + (resp.base || "");
        this.renderHealthChecks(
          checks,
          "This API build does not report dependency checks yet. Redeploy week-2-rag-api."
        );
        this.renderHealthUsage(
          usage,
          "This API build does not report usage yet. Redeploy week-2-rag-api."
        );
      } else {
        this.els.health.className = "zbot-health zbot-health--bad";
        const detail =
          (resp && (resp.error || "HTTP " + resp.status)) || "unreachable";
        this.els.health.textContent = "Unreachable · " + detail;
        this.renderHealthChecks(null, "Skipped — API unreachable");
        this.renderHealthUsage(null, "Skipped — API unreachable");
      }
    }

    renderHealthChecks(checks, emptyMessage) {
      const list = this.els.healthChecks;
      if (!list) return;
      list.innerHTML = "";
      if (!checks || !Object.keys(checks).length) {
        const li = document.createElement("li");
        li.className = "zbot-health-list__empty";
        li.textContent = emptyMessage || "Not checked yet";
        list.appendChild(li);
        return;
      }
      const names = Object.keys(HEALTH_CHECK_LABELS).filter((name) =>
        Object.prototype.hasOwnProperty.call(checks, name)
      );
      Object.keys(checks).forEach((name) => {
        if (names.indexOf(name) === -1) names.push(name);
      });
      names.forEach((name) => {
        const check = checks[name] || {};
        const li = document.createElement("li");
        li.className =
          "zbot-health-item " +
          (check.ok ? "zbot-health-item--ok" : "zbot-health-item--bad");
        const label = document.createElement("span");
        label.className = "zbot-health-item__label";
        label.textContent = HEALTH_CHECK_LABELS[name] || name;
        const detail = document.createElement("span");
        detail.className = "zbot-health-item__detail";
        detail.textContent = check.detail || (check.ok ? "ok" : "failing");
        li.appendChild(label);
        li.appendChild(detail);
        list.appendChild(li);
      });
    }

    renderHealthUsage(usage, emptyMessage) {
      const list = this.els.healthUsage;
      if (!list) return;
      list.innerHTML = "";
      if (!usage || !Object.keys(usage).length) {
        const li = document.createElement("li");
        li.className = "zbot-health-list__empty";
        li.textContent = emptyMessage || "Not checked yet";
        list.appendChild(li);
        return;
      }
      const names = HEALTH_USAGE_ORDER.filter((name) =>
        Object.prototype.hasOwnProperty.call(usage, name)
      );
      Object.keys(usage).forEach((name) => {
        if (names.indexOf(name) === -1) names.push(name);
      });
      names.forEach((name) => {
        const item = usage[name] || {};
        const level = item.level || (item.ok ? "ok" : "info");
        const li = document.createElement("li");
        li.className =
          "zbot-health-item zbot-health-item--" +
          (level === "over"
            ? "bad"
            : level === "warn"
              ? "warn"
              : level === "info"
                ? "info"
                : "ok");
        const label = document.createElement("span");
        label.className = "zbot-health-item__label";
        label.textContent = HEALTH_USAGE_LABELS[name] || name;
        li.appendChild(label);
        const meters = Array.isArray(item.meters) ? item.meters : [];
        meters.forEach((meter) => {
          li.appendChild(this.buildUsageMeter(meter, level));
        });
        const detail = document.createElement("span");
        detail.className = "zbot-health-item__detail";
        detail.textContent = item.detail || "";
        li.appendChild(detail);
        if (item.dashboard) {
          const link = document.createElement("a");
          link.className = "zbot-health-item__link";
          link.href = item.dashboard;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.textContent = "Open dashboard";
          li.appendChild(link);
        }
        list.appendChild(li);
      });
    }

    buildUsageMeter(meter, level) {
      const wrap = document.createElement("div");
      wrap.className = "zbot-meter";
      const row = document.createElement("div");
      row.className = "zbot-meter__row";
      const name = document.createElement("span");
      name.className = "zbot-meter__name";
      name.textContent = meter.label || "";
      const value = document.createElement("span");
      value.className = "zbot-meter__value";
      const unit = meter.unit || "";
      const usedTxt = this.formatUsageQty(meter.used, unit);
      if (meter.limit == null) {
        value.textContent = usedTxt;
      } else {
        value.textContent =
          usedTxt + " / " + this.formatUsageQty(meter.limit, unit);
      }
      row.appendChild(name);
      row.appendChild(value);
      wrap.appendChild(row);
      if (meter.limit != null && Number(meter.limit) > 0) {
        const pct = Math.max(
          0,
          Math.min(100, Number(meter.pct != null ? meter.pct : 0))
        );
        const track = document.createElement("div");
        track.className = "zbot-meter__track";
        const fill = document.createElement("div");
        fill.className =
          "zbot-meter__fill zbot-meter__fill--" +
          (level === "over" ? "bad" : level === "warn" ? "warn" : "ok");
        fill.style.width = pct + "%";
        track.appendChild(fill);
        wrap.appendChild(track);
      }
      return wrap;
    }

    formatUsageQty(value, unit) {
      const n = Number(value);
      const u = String(unit || "");
      if (!isFinite(n)) return "—";
      if (u.toUpperCase() === "USD") {
        return "$" + n.toFixed(2);
      }
      const digits = Math.abs(n) >= 100 ? 0 : Math.abs(n) >= 10 ? 1 : 2;
      return n.toFixed(digits) + (u ? " " + u : "");
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

      if (this.tokenCount >= this.contextLimit) {
        this.updateContextNote();
        this.setStatus(
          "Context limit reached. Start a new chat to continue.",
          false
        );
        return;
      }

      if (!this.sessionId) this.sessionId = this.genSessionId();
      const history = this.buildHistory();

      const generation = ++this.askGeneration;
      this.loading = true;
      this.setAskButtonMode("stop");
      this.els.question.value = "";
      this.resizeQuestionInput();
      this.thread.push({ question: question, pending: true, generation: generation });
      this.renderThread();
      this.els.tao.innerHTML = "";
      this.setStatus("");

      const resp = await sendMessage({
        type: "ask",
        question,
        sessionId: this.sessionId,
        history,
        retrievalMode: this.getRetrievalMode(),
      });
      if (generation !== this.askGeneration) {
        this.removePendingTurn(generation);
        return;
      }

      this.loading = false;
      this.setAskButtonMode("ask");
      this.setStatus("");

      if (resp && resp.cancelled) {
        this.removePendingTurn(generation);
        this.setStatus("Stopped.");
        return;
      }
      if (!resp || resp.error) {
        const message = (resp && resp.error) || "Unknown error.";
        this.completePendingTurn({
          answer: "",
          steps: [],
          error: message,
        });
        this.saveCurrentSession();
        sendMessage({ type: "reportError", message: message });
        return;
      }
      if (resp.sessionId) this.sessionId = resp.sessionId;
      if (resp.title) this.sessionTitle = resp.title;
      if (typeof resp.tokenCount === "number") this.tokenCount = resp.tokenCount;
      if (typeof resp.contextTokenLimit === "number" && resp.contextTokenLimit > 0) {
        this.contextLimit = resp.contextTokenLimit;
      }
      this.completePendingTurn({
        answer: resp.answer || "",
        steps: resp.steps || [],
        timingsMs: resp.timingsMs || {},
        searchCallCount:
          typeof resp.searchCallCount === "number" ? resp.searchCallCount : 0,
      });
      this.saveCurrentSession();
      this.updateContextNote();
    }

    /** Prior completed, non-error turns as [{role, content}] for agent memory. */
    buildHistory() {
      const history = [];
      this.thread.forEach((turn) => {
        if (turn.pending || !turn.question) return;
        history.push({ role: "user", content: turn.question });
        if (turn.answer && !turn.error) {
          history.push({ role: "assistant", content: turn.answer });
        }
      });
      return history;
    }

    removePendingTurn(generation) {
      const index = this.thread.findIndex(
        (turn) => turn.pending && turn.generation === generation
      );
      if (index === -1) return;
      this.thread.splice(index, 1);
      this.renderThread();
    }

    completePendingTurn(result) {
      const turn = this.thread[this.thread.length - 1];
      if (!turn || !turn.pending) return;

      turn.pending = false;
      turn.answer = result.answer || "";
      turn.steps = result.steps || [];
      turn.timingsMs = result.timingsMs || {};
      turn.searchCallCount =
        typeof result.searchCallCount === "number" ? result.searchCallCount : 0;
      turn.error = result.error || "";

      const classified = classifyAnswer(turn.answer, turn.steps);
      if (turn.error) {
        turn.banner = "error";
        turn.bannerText = turn.error;
      } else if (classified.isWebFallback) {
        turn.banner = "web";
        turn.bannerText = "Not found in Zearn docs — sourced from the web";
      } else if (classified.isRefusal) {
        turn.banner = "refusal";
        turn.bannerText = "Not found in corpus";
      }

      if (turn.steps && turn.steps.length) {
        this.els.tao.innerHTML = "";
        this.els.tao.appendChild(this.buildSteps(turn.steps));
        const perf = this.buildPerformancePanel(
          turn.timingsMs,
          turn.searchCallCount
        );
        if (perf) this.els.tao.appendChild(perf);
      } else {
        this.renderTaoEmpty();
      }

      this.renderThread();
    }

    renderThread() {
      const container = this.els.output;
      container.innerHTML = "";

      this.thread.forEach((turn) => {
        container.appendChild(this.buildThreadAskBlock(turn.question));
        if (turn.pending) {
          container.appendChild(this.buildThreadPendingBlock());
        } else {
          container.appendChild(this.buildThreadAnswerBlock(turn));
        }
      });

      this.scrollThreadToBottom();
    }

    scrollThreadToBottom() {
      const scroll = this.shadow.querySelector(".zbot-ask-scroll");
      if (!scroll) return;
      requestAnimationFrame(() => {
        scroll.scrollTop = scroll.scrollHeight;
      });
    }

    buildThreadAskBlock(question) {
      const block = document.createElement("div");
      block.className = "zbot-thread-ask";

      const label = document.createElement("div");
      label.className = "zbot-thread-label";
      label.textContent = "Ask";

      const bubble = document.createElement("div");
      bubble.className = "zbot-thread-bubble";

      const body = document.createElement("div");
      body.className = "zbot-thread-bubble__body";
      body.textContent = question;

      bubble.appendChild(body);
      block.appendChild(label);
      block.appendChild(bubble);
      return block;
    }

    buildThreadPendingBlock() {
      const block = document.createElement("div");
      block.className = "zbot-thread-answer";

      const label = document.createElement("div");
      label.className = "zbot-thread-label";
      label.textContent = "Answer";

      const bubble = document.createElement("div");
      bubble.className = "zbot-thread-bubble zbot-thread-bubble--pending";

      const body = document.createElement("div");
      body.className = "zbot-thread-bubble__body zbot-thread-bubble__body--pending";
      const spinner = document.createElement("span");
      spinner.className = "zbot-spinner";
      body.appendChild(spinner);
      body.appendChild(document.createTextNode(" Thinking…"));

      bubble.appendChild(body);
      block.appendChild(label);
      block.appendChild(bubble);
      return block;
    }

    buildThreadAnswerBlock(turn) {
      const block = document.createElement("div");
      block.className = "zbot-thread-answer";

      const label = document.createElement("div");
      label.className = "zbot-thread-label";
      label.textContent = "Answer";

      const bubble = document.createElement("div");
      bubble.className = "zbot-thread-bubble";

      if (turn.banner) {
        bubble.appendChild(this.buildBanner(turn.banner, turn.bannerText));
      }

      const displayText = stripDuplicateInlineSources(
        (turn.answer || "").trim() ||
          (turn.banner === "refusal" ? CONFIG.REFUSAL_MESSAGE : "")
      );

      const body = document.createElement("div");
      body.className = "zbot-thread-bubble__body zbot-answer";
      if (turn.error && !displayText) {
        body.textContent = "Error: " + turn.error;
      } else {
        renderMarkdownInto(body, displayText || CONFIG.REFUSAL_MESSAGE);
      }
      bubble.appendChild(body);

      block.appendChild(label);
      block.appendChild(bubble);
      return block;
    }

    stopAsk() {
      if (!this.loading) return;
      const activeGeneration = this.askGeneration;
      this.askGeneration += 1;
      this.loading = false;
      this.setAskButtonMode("ask");
      this.setStatus("Stopping…");
      sendMessage({ type: "cancelAsk" }).then(() => {
        if (!this.loading) {
          this.removePendingTurn(activeGeneration);
          this.setStatus("Stopped.");
        }
      });
    }

    getRetrievalMode() {
      const select = this.els.retrievalMode;
      const value = select && select.value === "fast" ? "fast" : "slow";
      return value;
    }

    applyRetrievalMode(mode) {
      const normalized = mode === "fast" ? "fast" : "slow";
      this.retrievalMode = normalized;
      if (this.els.retrievalMode) {
        this.els.retrievalMode.value = normalized;
      }
      if (this.els.retrievalModeLabel) {
        this.els.retrievalModeLabel.textContent = normalized === "fast" ? "Fast" : "Slow";
      }
    }

    saveRetrievalMode(mode) {
      const normalized = mode === "fast" ? "fast" : "slow";
      this.applyRetrievalMode(normalized);
      sendMessage({ type: "saveSettings", retrievalMode: normalized });
    }

    setAskButtonMode(mode) {
      const stop = mode === "stop";
      this.els.ask.textContent = stop ? "Stop" : "Ask";
      this.els.ask.classList.toggle("zbot-btn--stop", stop);
      this.els.ask.setAttribute("aria-label", stop ? "Stop" : "Ask");
      if (this.els.retrievalMode) {
        this.els.retrievalMode.disabled = stop;
      }
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
      this.completePendingTurn({
        answer: "",
        steps: [],
        error: message,
      });
    }

    renderTaoEmpty() {
      this.els.tao.innerHTML = "";
      const empty = document.createElement("div");
      empty.className = "zbot-empty";
      empty.textContent =
        "Ask a question to see the agent's Think → Act → Observe steps.";
      this.els.tao.appendChild(empty);
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

    buildPerformancePanel(timingsMs, searchCallCount) {
      const timings = timingsMs && typeof timingsMs === "object" ? timingsMs : {};
      const keys = Object.keys(timings);
      if (!keys.length) return null;

      const sorted = keys
        .map((name) => ({ name, ms: Number(timings[name]) || 0 }))
        .sort((a, b) => b.ms - a.ms);

      const details = document.createElement("details");
      details.className = "zbot-perf";

      const summary = document.createElement("summary");
      const totalMs = Number(timings.agent_total) || sorted.reduce((s, r) => s + r.ms, 0);
      summary.textContent =
        "Performance — " +
        Math.round(totalMs) +
        " ms total" +
        (searchCallCount ? " · " + searchCallCount + " search" : "");
      details.appendChild(summary);

      const table = document.createElement("table");
      table.className = "zbot-perf__table";

      sorted.forEach((row) => {
        const tr = document.createElement("tr");
        const nameCell = document.createElement("td");
        nameCell.textContent = row.name;
        const msCell = document.createElement("td");
        msCell.textContent = Math.round(row.ms) + " ms";
        tr.appendChild(nameCell);
        tr.appendChild(msCell);
        table.appendChild(tr);
      });

      details.appendChild(table);
      return details;
    }

    startNewChat() {
      if (this.sessionId) {
        sendMessage({
          type: "endSession",
          sessionId: this.sessionId,
          reason: "new_chat",
        });
      }
      this.sessionId = null;
      this.sessionTitle = "";
      this.tokenCount = 0;
      this.thread = [];
      this.askGeneration += 1;
      this.loading = false;
      this.setAskButtonMode("ask");
      this.setStatus("");
      this.renderThread();
      this.renderTaoEmpty();
      this.clearCurrentSession();
      this.updateContextNote();
      this.switchTab("ask");
      this.els.question.focus();
    }

    updateContextNote() {
      const note = this.els.contextNote;
      const input = this.els.question;
      const askBtn = this.els.ask;
      if (!note) return;

      const limit = this.contextLimit || CONFIG.CONTEXT_TOKEN_LIMIT;
      const warn = this.contextWarn || CONFIG.CONTEXT_TOKEN_WARN;
      const used = this.tokenCount || 0;
      const kUsed = Math.round(used / 1000);
      const kLimit = Math.round(limit / 1000);

      note.classList.remove("zbot-context-note--warn", "zbot-context-note--block");

      if (used >= limit) {
        note.textContent =
          "Context limit reached (" + kUsed + "k / " + kLimit +
          "k). Start a new chat to continue.";
        note.classList.add("zbot-context-note--block");
        if (input) {
          input.disabled = true;
          input.placeholder = "Context limit reached — start a new chat.";
        }
        if (askBtn) askBtn.disabled = true;
        return;
      }

      if (input) {
        input.disabled = false;
        input.placeholder = "Ask a Zearn support question...";
      }
      if (askBtn) askBtn.disabled = false;

      if (used >= warn) {
        note.textContent =
          kUsed + "k / " + kLimit + "k tokens — consider a new chat";
        note.classList.add("zbot-context-note--warn");
        return;
      }

      note.textContent = kUsed + "k / " + kLimit + "k tokens";
    }

    currentSessionSnapshot() {
      return {
        sessionId: this.sessionId,
        title: this.sessionTitle,
        tokenCount: this.tokenCount,
        contextLimit: this.contextLimit,
        thread: this.thread
          .filter((turn) => !turn.pending)
          .map((turn) => ({
            question: turn.question,
            answer: turn.answer || "",
            steps: turn.steps || [],
            error: turn.error || "",
            banner: turn.banner || "",
            bannerText: turn.bannerText || "",
          })),
      };
    }

    saveCurrentSession() {
      if (!this.sessionId) return;
      try {
        chrome.storage.local.set({
          [CONFIG.CURRENT_SESSION_STORAGE_KEY]: this.currentSessionSnapshot(),
        });
      } catch (_e) {
        // best-effort cache
      }
    }

    clearCurrentSession() {
      try {
        chrome.storage.local.remove(CONFIG.CURRENT_SESSION_STORAGE_KEY);
      } catch (_e) {
        // ignore
      }
    }

    restoreCurrentSession() {
      let done = false;
      try {
        chrome.storage.local.get(CONFIG.CURRENT_SESSION_STORAGE_KEY, (stored) => {
          done = true;
          const data = stored && stored[CONFIG.CURRENT_SESSION_STORAGE_KEY];
          if (!data || !data.sessionId || !Array.isArray(data.thread)) {
            this.updateContextNote();
            return;
          }
          this.sessionId = data.sessionId;
          this.sessionTitle = data.title || "";
          this.tokenCount = data.tokenCount || 0;
          if (data.contextLimit) this.contextLimit = data.contextLimit;
          this.thread = data.thread.map((turn) => ({
            question: turn.question,
            answer: turn.answer || "",
            steps: turn.steps || [],
            error: turn.error || "",
            banner: turn.banner || "",
            bannerText: turn.bannerText || "",
            pending: false,
          }));
          this.renderThread();
          this.updateContextNote();
        });
      } catch (_e) {
        // ignore
      }
      if (!done) this.updateContextNote();
    }

    showHistoryList() {
      this.closeHistoryMenu();
      this.els.historyDetailView.classList.add("zbot-hidden");
      this.els.historyListView.classList.remove("zbot-hidden");
    }

    showHistoryDetail() {
      this.els.historyListView.classList.add("zbot-hidden");
      this.els.historyDetailView.classList.remove("zbot-hidden");
    }

    async loadHistory() {
      this.closeHistoryMenu();
      this.els.historyStatus.textContent = "";
      this.renderHistoryPlaceholder("Loading saved chats…");
      const resp = await sendMessage({ type: "getHistoryList" });
      if (!resp || resp.error) {
        this.renderHistoryPlaceholder(
          "Could not load history: " + ((resp && resp.error) || "unknown error")
        );
        return;
      }
      this.renderHistoryList(resp.sessions || []);
    }

    renderHistoryPlaceholder(message) {
      const list = this.els.historyList;
      list.innerHTML = "";
      const empty = document.createElement("div");
      empty.className = "zbot-empty";
      empty.textContent = message;
      list.appendChild(empty);
    }

    closeHistoryMenu() {
      if (!this.activeHistoryMenu) return;
      this.activeHistoryMenu
        .closest(".zbot-history-item")
        ?.classList.remove("zbot-history-item--menu-open");
      this.activeHistoryMenu.classList.add("zbot-hidden");
      const btn = this.activeHistoryMenu.parentElement?.querySelector(
        ".zbot-history-item__menu-btn"
      );
      if (btn) btn.setAttribute("aria-expanded", "false");
      this.activeHistoryMenu = null;
    }

    toggleHistoryMenu(menuEl, menuBtn) {
      if (this.activeHistoryMenu === menuEl) {
        this.closeHistoryMenu();
        return;
      }
      this.closeHistoryMenu();
      menuEl.classList.remove("zbot-hidden");
      menuBtn.setAttribute("aria-expanded", "true");
      menuEl.closest(".zbot-history-item")?.classList.add("zbot-history-item--menu-open");
      this.activeHistoryMenu = menuEl;
    }

    renderHistoryList(sessions) {
      const list = this.els.historyList;
      list.innerHTML = "";
      if (!sessions.length) {
        this.els.historyStatus.textContent = "";
        this.renderHistoryPlaceholder("No saved chats yet.");
        return;
      }
      this.els.historyStatus.textContent = "";

      sessions.forEach((session) => {
        const item = document.createElement("div");
        item.className = "zbot-history-item";

        const displayTitle = session.title || "Untitled chat";

        const main = document.createElement("button");
        main.type = "button";
        main.className = "zbot-history-item__main";
        main.title = displayTitle;
        const title = document.createElement("div");
        title.className = "zbot-history-item__title";
        title.textContent = displayTitle;
        title.title = displayTitle;
        const meta = document.createElement("div");
        meta.className = "zbot-history-item__meta";
        meta.textContent = this.formatHistoryMeta(session);
        main.appendChild(title);
        main.appendChild(meta);
        main.addEventListener("click", () => this.openHistorySession(session.id));

        const menuWrap = document.createElement("div");
        menuWrap.className = "zbot-history-item__menu-wrap";

        const menuBtn = document.createElement("button");
        menuBtn.type = "button";
        menuBtn.className = "zbot-history-item__menu-btn";
        menuBtn.setAttribute("aria-label", "Chat options");
        menuBtn.setAttribute("aria-haspopup", "menu");
        menuBtn.setAttribute("aria-expanded", "false");
        menuBtn.textContent = "\u22EE";

        const menu = document.createElement("div");
        menu.className = "zbot-history-item__menu zbot-hidden";
        menu.setAttribute("role", "menu");

        const renameBtn = document.createElement("button");
        renameBtn.type = "button";
        renameBtn.className = "zbot-history-item__menu-action";
        renameBtn.dataset.action = "rename";
        renameBtn.setAttribute("role", "menuitem");
        renameBtn.textContent = "Rename";
        renameBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          this.closeHistoryMenu();
          this.renameHistorySession(session.id, displayTitle);
        });

        const deleteBtn = document.createElement("button");
        deleteBtn.type = "button";
        deleteBtn.className = "zbot-history-item__menu-action";
        deleteBtn.dataset.action = "delete";
        deleteBtn.setAttribute("role", "menuitem");
        deleteBtn.textContent = "Delete";
        deleteBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          this.closeHistoryMenu();
          this.deleteHistorySession(session.id);
        });

        menu.appendChild(renameBtn);
        menu.appendChild(deleteBtn);
        menuBtn.addEventListener("click", (e) => {
          e.preventDefault();
          e.stopPropagation();
          this.toggleHistoryMenu(menu, menuBtn);
        });

        menuWrap.addEventListener("click", (e) => {
          e.stopPropagation();
        });

        menuWrap.appendChild(menuBtn);
        menuWrap.appendChild(menu);

        item.appendChild(main);
        item.appendChild(menuWrap);
        list.appendChild(item);
      });
    }

    formatHistoryMeta(session) {
      const parts = [];
      if (session.updated_at) {
        const date = new Date(session.updated_at);
        if (!isNaN(date.getTime())) parts.push(date.toLocaleString());
      }
      if (session.token_count) {
        parts.push(Math.round(session.token_count / 1000) + "k tokens");
      }
      if (session.ended_reason) parts.push(session.ended_reason);
      return parts.join(" · ");
    }

    async openHistorySession(sessionId) {
      this.showHistoryDetail();
      this.openHistoryData = null;
      this.els.historyContinue.disabled = true;
      this.els.historyDetailTitle.textContent = "Loading…";
      this.els.historyDetail.innerHTML = "";
      const resp = await sendMessage({ type: "getHistorySession", sessionId });
      if (!resp || resp.error) {
        this.els.historyDetailTitle.textContent =
          "Could not load chat: " + ((resp && resp.error) || "unknown error");
        return;
      }
      this.openHistoryData = resp;
      this.els.historyContinue.disabled = false;
      this.els.historyDetailTitle.textContent = resp.title || "Untitled chat";
      this.renderHistoryTranscript(resp.messages || []);
    }

    /** Rebuild Ask thread turns from a saved session's flat message list. */
    threadFromMessages(messages) {
      const turns = [];
      messages.forEach((message) => {
        const content = message.content || "";
        if (message.role === "user") {
          turns.push({
            question: content,
            answer: "",
            steps: [],
            error: "",
            banner: "",
            bannerText: "",
            pending: false,
          });
        } else {
          let turn = turns[turns.length - 1];
          if (!turn || turn.answer || turn.error) {
            turn = {
              question: "",
              answer: "",
              steps: [],
              error: "",
              banner: "",
              bannerText: "",
              pending: false,
            };
            turns.push(turn);
          }
          turn.answer = content;
          turn.steps = message.steps || [];
          turn.error = message.error || "";
          if (message.error) {
            turn.banner = "error";
            turn.bannerText = message.error;
          }
        }
      });
      return turns;
    }

    continueHistorySession() {
      const data = this.openHistoryData;
      if (!data || !data.id) return;

      this.sessionId = data.id;
      this.sessionTitle = data.title || "";
      this.tokenCount = data.token_count || 0;
      this.thread = this.threadFromMessages(data.messages || []);
      this.askGeneration += 1;
      this.loading = false;
      this.setAskButtonMode("ask");
      this.setStatus("");
      this.renderThread();
      this.renderTaoEmpty();
      this.saveCurrentSession();
      this.updateContextNote();
      this.switchTab("ask");
      if (this.els.question && !this.els.question.disabled) {
        this.els.question.focus();
      }
    }

    renderHistoryTranscript(messages) {
      const container = this.els.historyDetail;
      container.innerHTML = "";
      messages.forEach((message) => {
        if (message.role === "user") {
          container.appendChild(this.buildThreadAskBlock(message.content || ""));
        } else {
          container.appendChild(
            this.buildThreadAnswerBlock({
              answer: message.content || "",
              error: message.error || "",
              banner: message.error ? "error" : "",
              bannerText: message.error || "",
            })
          );
        }
      });
    }

    async renameHistorySession(sessionId, currentTitle) {
      const next = window.prompt("Rename chat", currentTitle || "Untitled chat");
      if (next === null) return;
      const title = next.trim();
      if (!title) {
        this.els.historyStatus.textContent = "Title cannot be empty.";
        return;
      }
      const resp = await sendMessage({
        type: "renameHistorySession",
        sessionId,
        title,
      });
      if (!resp || resp.error) {
        this.els.historyStatus.textContent =
          "Rename failed: " + ((resp && resp.error) || "unknown error");
        return;
      }
      if (sessionId === this.sessionId) {
        this.sessionTitle = title;
        this.saveCurrentSession();
      }
      if (this.openHistoryData && this.openHistoryData.id === sessionId) {
        this.openHistoryData.title = title;
        this.els.historyDetailTitle.textContent = title;
      }
      this.loadHistory();
    }

    async deleteHistorySession(sessionId) {
      const resp = await sendMessage({ type: "deleteHistorySession", sessionId });
      if (!resp || resp.error) {
        this.els.historyStatus.textContent =
          "Delete failed: " + ((resp && resp.error) || "unknown error");
        return;
      }
      if (sessionId === this.sessionId) {
        this.clearCurrentSession();
        this.sessionId = null;
        this.sessionTitle = "";
        this.tokenCount = 0;
        this.thread = [];
        this.renderThread();
        this.updateContextNote();
      }
      this.loadHistory();
    }

    async loadSettings() {
      const resp = await sendMessage({ type: "getSettings" });
      if (resp && resp.defaultBase) this.defaultBase = resp.defaultBase;
      if (resp && resp.layoutMode && resp.layoutMode !== this.layoutMode) {
        this.layoutMode = resp.layoutMode;
        this.applyLayout();
      }
      if (resp && resp.retrievalMode) {
        this.applyRetrievalMode(resp.retrievalMode);
      } else {
        this.applyRetrievalMode("fast");
      }
    }
  }

  self.ZBotOverlay = ZBotOverlay;
})();
