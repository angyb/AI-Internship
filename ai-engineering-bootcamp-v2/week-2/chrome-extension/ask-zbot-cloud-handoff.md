# Ask Z-Bot Chrome Extension — Cloud Handoff Summary

**Purpose of this doc:** Brief a future Cursor session whose goal is to make Ask Z-Bot
**work in the cloud** (production / public / always-on backend + distributable extension).

**Status as of 2026-08-12:** Extension **v1.0.0** is complete as a load-unpacked demo with a
**tabbed UI**, **docked right-panel default**, **page reflow** (including Zearn fixed headers),
and a **local preview harness** for UI iteration. The **backend agent API is already
cloud-hosted** on Render. Remaining work is mostly production hardening, Store distribution,
and clarifying what “cloud” means for the client vs the API.

**Related docs:**
- [`README.md`](README.md) — load unpacked, settings, preview harness, package zip
- [`../rag-vector-databases/chrome-extension-plan.md`](../rag-vector-databases/chrome-extension-plan.md) — full build plan (Phases 1–5 done)
- [`PUBLISH_CHECKLIST.md`](PUBLISH_CHECKLIST.md) — Web Store / production checklist
- [`store-listing.md`](store-listing.md) — Store listing draft
- [`../rag-vector-databases/zearn-support-agent-summary.md`](../rag-vector-databases/zearn-support-agent-summary.md) — ADK agent
- [`../rag-vector-databases/how-it-works.md`](../rag-vector-databases/how-it-works.md) — RAG + agent internals

---

## One-sentence job

> On `zearn.org` / `help.zearn.org`, **Ask Z-Bot** (pill → tabbed panel) sends the user’s
> question to a cloud FastAPI **`POST /agent`** endpoint; the ADK agent searches Zearn
> docs (hybrid RAG) with Google Search fallback and returns a cited answer on the **Ask**
> tab plus Think/Act/Observe steps on the **TAO** tab.

---

## UI preview harness (use this when working on the extension)

**Prefer the preview harness for overlay/CSS/layout work** — no Load unpacked, no CORS,
no waiting on Render cold starts.

```bash
cd ai-engineering-bootcamp-v2/week-2/chrome-extension
./scripts/preview.sh          # → http://127.0.0.1:8765/preview.html
./scripts/preview.sh 8766     # optional port
```

| Piece | Role |
|-------|------|
| `preview.html` | Fake host page with a fixed Zearn-style header (`.navigation_fixed`) |
| `preview/chrome-stub.js` | Stubbed `chrome.runtime` — fake `/agent` answers, Stop, settings |
| `scripts/preview.sh` | Serves the extension folder on localhost |

The harness loads the **real** `overlay.js` / `overlay.css` / `config.js`. Answers and TAO
steps are fake. Ask → **Stop** still exercises abort wiring. Optional query:
`?layout=overlay` starts in floating mode instead of the default docked panel.

**When to use Load unpacked instead:** end-to-end agent calls on real `help.zearn.org` /
`zearn.org`, manifest/permissions changes, or anything the stub does not model.

Preview files are **excluded** from `./scripts/package.sh` (not shipped to the Web Store).

---

## What is already in the cloud vs local

| Piece | Where it runs today | Notes |
|-------|---------------------|--------|
| Agent API (`POST /agent`, `/health`, `/telemetry`) | **Render** `https://ai-internship-i3lw.onrender.com` | Default URL in `config.js` |
| Streamlit agent UI | **Render** `https://zearn-faq-bot.onrender.com` | Separate service; not required by the extension |
| Vector store | **Pinecone** (cloud) | Used inside `search_zearn_doc` on the API |
| Extension UI (pill, panel, settings) | **User’s Chrome** (load unpacked) | Not hosted; MV3 content script + service worker |
| UI preview harness | **Local** `http://127.0.0.1:8765/preview.html` | Stub agent only; for extension UI dev |
| Optional local API | `http://127.0.0.1:8000` | Override via `chrome.storage.sync` (`agentApiUrl`); no Settings UI field today |

**Important clarification for the next session:**  
“Make the extension work in the cloud” usually does **not** mean hosting the overlay as a website.
Chrome extensions always run in the browser. What people usually mean:

1. **Rely only on the cloud API** (already the default — Render), harden it for public use, and/or  
2. **Publish the extension** (Chrome Web Store) so others can install it without load-unpacked, and/or  
3. **Stop depending on free-tier cold starts** (upgrade Render, warmer service, or different host).

Ask the user which of those they want before changing architecture.

---

## Extension UI (current)

### Layout modes

- **Default:** docked **right panel** (full viewport height, ~420px wide).
- **Toggle:** header icon switches to a **floating overlay** card; choice persisted in
  `chrome.storage.sync` as `layoutMode` (`panel` | `overlay`).
- **Minimize:** returns to bottom-right **Ask Z-Bot** pill. **Alt+Z** toggles expand/collapse.

### Page reflow (docked mode)

When docked and expanded, the overlay **insets the host page** instead of covering it:

- Sets `ask-zbot-page-shift` on `<html>` and `--zbot-panel-width` to the panel width.
- Injects CSS to shrink `<html>` margin and **fixed site headers** (e.g. Zearn
  `.navigation_fixed`, `.w-nav-overlay`, help-center `.header`) so search / Sign up /
  Log in stay visible beside the panel.
- Panel narrows (300px floor) so the page keeps at least 320px; on very narrow viewports
  it overlays instead of squashing the page.
- Restored on minimize, floating mode, or layout toggle.

### Tabs

| Tab | Contents |
|-----|----------|
| **Ask** | Markdown answer above the question box; pinned disclaimer; **Ask** → **Stop** while agent runs |
| **TAO** | Think → Act → Observe steps for the last answer |
| **Trace** | Placeholder |
| **Health** | API liveness plus Pinecone / embeddings / Gemini / BM25 / History DB |

Privacy policy link lives on the **Ask** tab footer (`privacy-policy.html`).

### Styling & assets

- Accent/header/pill: **#1CC7E6** with black text; buttons/links: **#007694**
- Brand mark: `icons/zbot-mark.png` on pill and panel header
- Layout/minimize icons: inline SVGs in `overlay.js`

### Ask flow

- First expand triggers `GET /health` (wake Render).
- `POST /agent` via service worker; **Stop** sends `{ type: "cancelAsk" }` to abort in-flight request.
- Web-fallback answers show an amber banner when `google_search_agent` was used.

---

## Architecture (current)

```
zearn.org page
  └─ content.js + overlay.js (Shadow DOM UI, tabs, docked panel, page reflow)
        │  chrome.runtime.sendMessage
        ▼
  background.js (MV3 service worker)
        │  GET /health  (wake + health)
        │  POST /agent  (question → answer + steps; abortable)
        │  POST /telemetry  (opt-in errors only)
        ▼
  Render FastAPI  (week-2-rag-api)
        └─ zearn_support_agent (Gemini ADK)
              ├─ search_zearn_doc → retrieve_context() → Pinecone + BM25
              └─ google_search_agent (web fallback)
```

**Why the service worker?** Content scripts on zearn.org cannot freely call a third-party
API (CORS / privilege model). All fetches go through `background.js` with declared
`host_permissions`. No CORS middleware was added to FastAPI (proxy-only).

**API contract** (`POST /agent`):

```json
// Request
{ "question": "What causes a Tower Alert?" }

// Response
{ "answer": "...markdown with Sources: [Title](url)...", "steps": [ /* Think|Act|Observe */ ] }
```

Citations live **only in `answer`** — do not add a second source list from Observe JSON.

---

## Repo location & key files

```
ai-engineering-bootcamp-v2/week-2/chrome-extension/   ← extension root (load this folder)
  manifest.json          # MV3, v1.0.0, zearn.org matches
  background.js          # /agent proxy, cancelAsk, Alt+Z, storage, API key, install ID
  overlay.js / .css      # Tabbed UI, docked panel, page reflow, Ask/Stop
  content.js             # mount + toggle listener
  config.js              # DEFAULT_AGENT_API_URL, layoutMode key, timeouts
  privacy-policy.html
  icons/zbot-mark.png    # Pill + header brand mark
  preview.html           # Local UI harness host (not packaged)
  preview/chrome-stub.js # Stub chrome.runtime for preview
  scripts/preview.sh     # ./scripts/preview.sh → localhost preview
  scripts/package.sh     # → dist/ask-zbot-1.0.0.zip
  vendor/marked.min.js   # MV3 forbids remote CDN scripts

ai-engineering-bootcamp-v2/week-2/rag-vector-databases/
  main.py                # POST /agent, /telemetry
  agent_security.py      # optional AGENT_API_KEY + rate limit
  zearn_faq_bot/         # ADK agent package
  render.yaml            # week-2-rag-api + zearn-agent-ui
```

Vanilla JS, **no build step**. Package with `./scripts/package.sh`.

---

## Cloud API env (Render) — relevant to “go cloud”

| Variable | Role for public/cloud use |
|----------|---------------------------|
| `GOOGLE_API_KEY` | Required for `/agent` (Gemini + Google Search) |
| `OPENAI_API_KEY` / `PINECONE_*` | Retrieval inside `search_zearn_doc` |
| `AGENT_API_KEY` | **Optional gate.** Empty = open `/agent` (current demo). Set = require `X-API-Key` from extension (stored in sync; no Settings UI field today) |
| `AGENT_RATE_LIMIT_ENABLED` / `AGENT_RATE_LIMIT_PER_MINUTE` | Default on; 20/min per install ID or IP |
| `TELEMETRY_ENABLED` | Default `false` |
| Rerank / PyTorch | **Off on Render** (512MB) — hybrid BM25+dense only |

API URL override still works via `chrome.storage.sync` key `agentApiUrl` (background reads it);
there is no in-panel field — use devtools or restore a Settings control if needed.

Cold start: free Render can take ~30–60s; overlay calls `GET /health` on first expand
(`HEALTH_TIMEOUT_MS=60000`, `AGENT_TIMEOUT_MS=120000`).

---

## What “cloud” work likely involves (suggested scope)

Use this as a checklist for the future session — pick with the user:

### A. Production cloud API (backend)

- [ ] Confirm Render service is awake and `/agent` works from the extension (default URL)
- [ ] Decide whether to set `AGENT_API_KEY` on Render (recommended if Store / public traffic)
- [ ] Sync env (`sync_render_env.py` or Dashboard); redeploy `week-2-rag-api`
- [ ] Consider paid Render / always-on to reduce cold starts
- [ ] Optional: dedicated production API URL (custom domain) and update
      `DEFAULT_AGENT_API_URL` in `config.js` + `host_permissions` in `manifest.json`

### B. Distributable extension (Chrome Web Store)

- [ ] Follow [`PUBLISH_CHECKLIST.md`](PUBLISH_CHECKLIST.md)
- [ ] Host `privacy-policy.html` at a **public https** URL (Store rejects `chrome-extension://`)
- [ ] Real icons + screenshots (placeholders today)
- [ ] `./scripts/package.sh` → upload zip
- [ ] Paste [`store-listing.md`](store-listing.md); Zearn affiliation disclaimer

### C. Do **not** reinvent unless asked

- Do not move the overlay into Streamlit / a website (different product)
- Do not add FastAPI CORS unless dropping the service-worker proxy
- Do not put OpenAI/Google keys in the extension — only optional shared `AGENT_API_KEY`
- New agent tools: see `zearn_faq_bot/ADDING_A_TOOL.md` — redeploy API only; no extension changes
- For **UI-only** changes, use `./scripts/preview.sh` first; Load unpacked for real agent smoke tests

---

## Load & smoke test (before cloud changes)

### UI iteration (fast)

```bash
./scripts/preview.sh
# Open http://127.0.0.1:8765/preview.html — docked panel, fixed header reflow, Ask/Stop stub
```

### End-to-end (real agent)

1. Chrome → `chrome://extensions` → Developer mode → **Load unpacked** → this `chrome-extension/` folder  
2. **Reload** the extension after code changes  
3. Open `https://help.zearn.org` → **Ask Z-Bot** pill or **Alt+Z**  
4. Leave API URL as default Render (or set `agentApiUrl` in sync storage for local uvicorn)  
5. Manual matrix: Tower Alert (docs only) · weather (web fallback banner) · add students (Sources links)  
6. On `about.zearn.org` / marketing pages: confirm docked panel reflows `.navigation_fixed` header

---

## Known gaps / risks for cloud

| Gap | Impact |
|-----|--------|
| Render free cold start | First ask feels “broken” without wait copy / health wake (already implemented; still slow) |
| Open `/agent` when `AGENT_API_KEY` unset | Anyone with the URL can spend Gemini/OpenAI quota |
| Placeholder toolbar icons | Fine for demo; `zbot-mark.png` used in UI; Store may want polished set |
| Privacy policy only inside extension | Need public URL for Store |
| No Settings UI for API URL / API key | Still in `background.js` + sync storage; re-expose if public installs need self-serve config |
| Manual test matrix not marked done in plan | Re-run before claiming production-ready |
| `marked` without DOMPurify | Acceptable while answers come from own API; revisit if corpus/tools widen |
| Fixed headers on unknown sites | Zearn `.navigation_fixed` + common help-center selectors handled; other CMS themes may need new CSS selectors |

---

## Prompt starter for the next session

Paste something like:

> Read `ai-engineering-bootcamp-v2/week-2/chrome-extension/ask-zbot-cloud-handoff.md`
> and `chrome-extension-plan.md`. The Ask Z-Bot extension already defaults to the Render
> API and has a tabbed docked-panel UI. Use `./scripts/preview.sh` for UI work.
> I want it to **work in the cloud** meaning: [harden Render + turn on AGENT_API_KEY /
> publish to Chrome Web Store / reduce cold starts / custom domain — pick one].
> Do not rebuild the overlay from scratch; extend the existing MV3 extension and
> `week-2-rag-api` deploy.

---

## Success criteria (cloud session)

- Extension on a fresh Chrome install (or Store build) answers via the **cloud** `/agent` URL without a local uvicorn
- Cold start is handled or eliminated enough for a demo
- If public: `AGENT_API_KEY` (or equivalent) is on; rate limits verified
- If Store: privacy URL + listing assets + zip submitted or ready to submit
- No OpenAI/Google secrets in the extension bundle
