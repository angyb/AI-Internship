# Ask Z-Bot — Chrome Extension

A floating **Ask Z-Bot** overlay that appears on `zearn.org` / `help.zearn.org` and
answers Zearn support questions via the **Zearn Support Agent** (`POST /agent`).

MV3, vanilla JS, no build step. Fetches go through the background service worker
(so no CORS). Answers render markdown with a `Sources:` section on the **Ask** tab;
the agent's Think → Act → Observe steps live on the **TAO** tab.

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
| `overlay.js` / `overlay.css` | Shadow DOM UI — tabs, right-panel/overlay layouts, styling |
| `content.js` | Mount + toggle listener |
| `privacy-policy.html` | In-extension privacy policy (also host publicly for Web Store) |
| `store-listing.md` | Chrome Web Store listing draft |
| `PUBLISH_CHECKLIST.md` | Pre-submit checklist |
| `scripts/package.sh` | Zip for Web Store upload → `dist/ask-zbot-<version>.zip` |
| `scripts/preview.sh` | Local UI harness in a normal browser tab (stubbed agent) |
| `preview.html` / `preview/` | Preview host page + `chrome.*` stub (not packaged) |
| `vendor/marked.min.js` | Bundled markdown (MV3 forbids remote/CDN code) |
| `icons/` | Placeholder icons |

---

## Load unpacked (dev)

1. Open `chrome://extensions` → Developer mode → **Load unpacked** → this folder.
2. Visit `https://help.zearn.org`. Use the pill or **Alt+Z**.

Default API: `https://ai-internship-i3lw.onrender.com`.

### UI preview (no Load unpacked)

For overlay/CSS iteration without installing the extension:

```bash
./scripts/preview.sh          # http://127.0.0.1:8765/preview.html
./scripts/preview.sh 8766     # optional port
```

Opens a fake help.zearn.org page with the real `overlay.js` / `overlay.css` and a
stubbed `chrome.runtime` (`preview/chrome-stub.js`). Answers and TAO steps are
fake; Ask → Stop still works. Use `?layout=overlay` to start in floating mode.

The harness is excluded from `./scripts/package.sh`.

### Keyboard shortcut

**Alt+Z** toggles the overlay. If another extension owns it, assign at
`chrome://extensions/shortcuts`.

---

## UI layout

Expanding docks Ask Z-Bot as a **right panel** (full viewport height) by default. The
icon in the panel's upper-right corner switches between the docked panel and a
**floating overlay** card; the choice is saved to `chrome.storage.sync` (`layoutMode`)
and reused on the next page. Minimizing always returns to the bottom-right pill.

The docked panel sits **beside** the page rather than on top of it: when docked and
expanded, the overlay adds `ask-zbot-page-shift` on `<html>`, sets `--zbot-panel-width`,
and injects CSS to inset the page and shrink known **fixed headers** (e.g. Zearn
`.navigation_fixed`, help-center `.header`) so nav controls stay visible beside the
panel. Everything is removed when you undock or minimize. The panel narrows (to a 300px
floor) so the page keeps at least 320px, and on viewports too narrow for both it overlays
instead of squashing the page. Sites with other fixed-header patterns may need additional
selectors in `overlay.js`.

### Tabs

| Tab | Contents |
|-----|----------|
| Ask | Answer above the question box + disclaimer (default tab on every expand) |
| TAO | Think → Act → Observe steps for the last answer |
| Trace | Placeholder — coming soon |
| Health | API + Pinecone / embeddings / Gemini / BM25 / History DB, plus usage meters |

---

## Health

| Control | Purpose |
|---------|---------|
| Check now | `GET /health` — API liveness, dependency checks, and usage/quota meters |
| Privacy policy link | On the Ask tab — opens `privacy-policy.html` |

Usage meters come from the API (not the extension). Remaining prepaid credits are not exposed by most vendors:

| Vendor | What Health can show | Remaining $ / tokens |
|--------|----------------------|----------------------|
| Render | Workspace outbound bandwidth this month vs `RENDER_INCLUDED_BANDWIDTH_GB` (default 5 GB), Postgres disk vs disk size | Account credits: dashboard only. Set `RENDER_API_KEY` on the API service. |
| Pinecone | Vector count + estimated storage vs `PINECONE_PLAN` (starter 2 GB / builder 10 GB) | Monthly egress remaining is not in the API; Health already flags when the quota is exhausted. |
| OpenAI | Spend this month if `OPENAI_ADMIN_KEY` has `api.usage.read`. Optional cap via `OPENAI_MONTHLY_BUDGET_USD`. | Prepaid credit balance: dashboard only. |
| Gemini | Estimated Flash $ for Ask Z-Bot this month vs `GEMINI_MONTHLY_BUDGET_USD` (default $250 Tier 1 cap) | Project billed spend / prepaid credits: [AI Studio Usage](https://aistudio.google.com/usage) only. |

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
