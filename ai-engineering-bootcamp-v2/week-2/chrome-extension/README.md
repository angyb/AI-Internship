# Ask Z-Bot — Chrome Extension

A floating **Ask Z-Bot** overlay that appears on `zearn.org` / `help.zearn.org` and
answers Zearn support questions via the **Zearn Support Agent** (`POST /agent`).

MV3, vanilla JS, no build step. Fetches go through the background service worker
(so no CORS). Answers render markdown with a `Sources:` section; Think → Act →
Observe steps show above the answer.

**Version:** 1.0.0 (Phase 1–2 UX + Phase 3 hardening + Phase 4 packaging + Phase 5 publish prep)

See the build plan in
[`../rag-vector-databases/chrome-extension-plan.md`](../rag-vector-databases/chrome-extension-plan.md).

**Cloud / production handoff for a future session:**
[`ask-zbot-cloud-handoff.md`](ask-zbot-cloud-handoff.md) — what is already on Render,
what “work in the cloud” usually means, and a starter prompt.

---

## Files

| File | Role |
|------|------|
| `manifest.json` | MV3 — content scripts, host permissions, `Alt+Z`, web-accessible CSS/privacy page |
| `config.js` | Shared constants on `self.ZBOT_CONFIG` |
| `background.js` | Proxies `/agent` + `/health` + optional `/telemetry`; API key + install ID headers |
| `overlay.js` / `overlay.css` | Shadow DOM UI + Zearn-adjacent styling + settings |
| `content.js` | Mount + toggle listener |
| `privacy-policy.html` | In-extension privacy policy (also host publicly for Web Store) |
| `store-listing.md` | Chrome Web Store listing draft |
| `PUBLISH_CHECKLIST.md` | Pre-submit checklist |
| `scripts/package.sh` | Zip for Web Store upload → `dist/ask-zbot-<version>.zip` |
| `vendor/marked.min.js` | Bundled markdown (MV3 forbids remote/CDN code) |
| `icons/` | Placeholder icons |

---

## Load unpacked (dev)

1. Open `chrome://extensions` → Developer mode → **Load unpacked** → this folder.
2. Visit `https://help.zearn.org`. Use the pill or **Alt+Z**.

Default API: `https://ai-internship-i3lw.onrender.com`.

### Keyboard shortcut

**Alt+Z** toggles the overlay. If another extension owns it, assign at
`chrome://extensions/shortcuts`.

---

## Settings

| Control | Purpose |
|---------|---------|
| Agent API URL | Override Render vs local `http://127.0.0.1:8000` |
| API key | Sent as `X-API-Key` when the server has `AGENT_API_KEY` set |
| Check now | `GET /health` |
| Send anonymous error reports | Opt-in `POST /telemetry` (no question text) |
| Privacy policy link | Opens `privacy-policy.html` |

---

## Security (Phase 3)

Server (`../rag-vector-databases/`):

| Env | Effect |
|-----|--------|
| `AGENT_API_KEY` | When set, `/agent` requires matching `X-API-Key` or Bearer token |
| `AGENT_RATE_LIMIT_ENABLED` | Default `true` |
| `AGENT_RATE_LIMIT_PER_MINUTE` | Default `20` (keyed by `X-Install-Id` or IP) |
| `TELEMETRY_ENABLED` | Default `false` — enables `POST /telemetry` |

Auth is **off** when `AGENT_API_KEY` is empty (local/dev and current public Render stay usable).
The extension API key is a **shared gate**, not an OpenAI/Google user secret.

Remote Streamlit: set the same `AGENT_API_KEY` in the environment when calling the API.

---

## Package for Chrome Web Store

```bash
./scripts/package.sh
# → dist/ask-zbot-1.0.0.zip
```

Follow [`PUBLISH_CHECKLIST.md`](PUBLISH_CHECKLIST.md) and [`store-listing.md`](store-listing.md).
You still need a **public https** privacy-policy URL for the Store (GitHub Pages, etc.).

---

## Manual test matrix

| Question | Expected |
|----------|----------|
| Tower Alert purpose | `search_zearn_doc`; Sources; no fallback banner |
| Weather in New York | `google_search_agent`; amber web-fallback banner |
| How many students can I add? | Sources links; one source list in the answer |

---

## Adding a new agent capability

Canonical guide:
[`../rag-vector-databases/zearn_faq_bot/ADDING_A_TOOL.md`](../rag-vector-databases/zearn_faq_bot/ADDING_A_TOOL.md)

1. Add `../rag-vector-databases/zearn_faq_bot/tools/<snake_name>.py`
2. Register in `agent.py`
3. Redeploy Render API — no extension code changes
