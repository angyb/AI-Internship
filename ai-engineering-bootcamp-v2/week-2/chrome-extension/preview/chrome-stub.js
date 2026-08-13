/**
 * Chrome API stub for preview.html.
 *
 * Lets overlay.js run in a normal browser tab without Load unpacked.
 * Handles the same message types as background.js, with a delayed fake
 * /agent response so Ask → Stop → Ask can be exercised.
 *
 * Not packaged into the Web Store zip.
 */
(function () {
  const settings = {
    base: "http://127.0.0.1:8000",
    defaultBase: "http://127.0.0.1:8000",
    apiKey: "",
    telemetryOptIn: false,
    layoutMode: "panel",
    agentTimeoutMs: 120000,
    healthTimeoutMs: 60000,
    extensionVersion: "1.0.0",
  };

  // Mutable so preview.html can override via ?layout= before mount.
  window.__ZBOT_PREVIEW_SETTINGS = settings;

  let askPending = null;
  const ASK_DELAY_MS = 1800;

  function respond(cb, payload) {
    setTimeout(function () {
      if (typeof cb === "function") cb(payload);
    }, 40);
  }

  window.chrome = {
    runtime: {
      lastError: null,
      getURL: function (path) {
        // Load CSS / privacy from this origin instead of chrome-extension://.
        return path;
      },
      onMessage: {
        addListener: function () {},
      },
      sendMessage: function (msg, cb) {
        if (!msg || typeof msg.type !== "string") {
          respond(cb, {});
          return;
        }

        if (msg.type === "getSettings") {
          respond(cb, Object.assign({}, settings));
          return;
        }

        if (msg.type === "saveSettings") {
          if (Object.prototype.hasOwnProperty.call(msg, "base")) {
            settings.base = String(msg.base || settings.defaultBase).replace(
              /\/+$/,
              ""
            );
          }
          if (Object.prototype.hasOwnProperty.call(msg, "apiKey")) {
            settings.apiKey = String(msg.apiKey || "");
          }
          if (Object.prototype.hasOwnProperty.call(msg, "telemetryOptIn")) {
            settings.telemetryOptIn = Boolean(msg.telemetryOptIn);
          }
          if (Object.prototype.hasOwnProperty.call(msg, "layoutMode")) {
            if (msg.layoutMode === "overlay" || msg.layoutMode === "panel") {
              settings.layoutMode = msg.layoutMode;
            }
          }
          respond(cb, Object.assign({}, settings));
          return;
        }

        if (msg.type === "wake") {
          respond(cb, { ok: true, status: 200, base: settings.base });
          return;
        }

        if (msg.type === "cancelAsk") {
          if (askPending) {
            askPending.cancelled = true;
            clearTimeout(askPending.timer);
            askPending = null;
          }
          respond(cb, { cancelled: true });
          return;
        }

        if (msg.type === "ask") {
          askPending = { cancelled: false };
          askPending.timer = setTimeout(function () {
            const cancelled = askPending && askPending.cancelled;
            askPending = null;
            if (cancelled) {
              respond(cb, { cancelled: true });
              return;
            }
            respond(cb, {
              answer:
                "A **Tower Alert** appears when students struggle repeatedly on a Tower of Power.\n\n" +
                "Sources: [Tower Alerts](https://help.zearn.org)",
              steps: [
                {
                  phase: "Think",
                  text: "The user asks about Tower Alerts; search the docs.",
                },
                {
                  phase: "Act",
                  tool: "search_zearn_doc",
                  args: { query: "tower alert" },
                },
                {
                  phase: "Observe",
                  tool: "search_zearn_doc",
                  result: "3 chunks retrieved from Pinecone.",
                },
              ],
            });
          }, ASK_DELAY_MS);
          return;
        }

        if (msg.type === "reportError") {
          respond(cb, { status: "ok" });
          return;
        }

        if (msg.type === "evalAgent") {
          respond(cb, {
            traces_file: "traces/zearn_agent_traces.jsonl",
            trace_count: 18,
            summary: {
              trace_count: 18,
              all_checks_passed: 15,
              all_checks_pass_rate: 0.8333,
              checks: {
                used_tool: { passed: 18, failed: 0, pass_rate: 1.0 },
                citation_present: { passed: 18, failed: 0, pass_rate: 1.0 },
                fallback_banner: { passed: 18, failed: 0, pass_rate: 1.0 },
                outcome_appropriate: { passed: 15, failed: 3, pass_rate: 0.8333 },
                length_budget: { passed: 17, failed: 1, pass_rate: 0.9444 },
              },
            },
            rows: [
              {
                id: "q09",
                question: "How do I bake sourdough bread?",
                expected_outcome: "refuse",
                actual_outcome: "web",
                passed: false,
                checks: {
                  outcome_appropriate: {
                    passed: false,
                    reason: "Should refuse off-topic question but returned web.",
                  },
                },
              },
            ],
            before: {
              summary: {
                checks: {
                  citation_present: { pass_rate: 0.7778 },
                },
              },
            },
            after: {
              summary: {
                checks: {
                  citation_present: { pass_rate: 1.0 },
                },
              },
            },
          });
          return;
        }

        respond(cb, {});
      },
    },
  };
})();
