/**
 * Ask Z-Bot content-script entry. Mounts a single overlay instance per page.
 * Loaded after config.js, vendor/marked.min.js, and overlay.js (see manifest).
 *
 * Listens for { type: "toggle" } from the background (Alt+Z command).
 */
(function () {
  if (window.__askZbotMounted) return;
  window.__askZbotMounted = true;

  try {
    const overlay = new self.ZBotOverlay();
    overlay.mount();
    window.__askZbotOverlay = overlay;

    chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
      if (msg && msg.type === "toggle") {
        overlay.toggle();
        sendResponse({ ok: true });
        return true;
      }
      return undefined;
    });
  } catch (e) {
    console.error("[Ask Z-Bot] failed to mount overlay:", e);
  }
})();
