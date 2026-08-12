# Ask Z-Bot Chrome Extension — Cloud Handoff Summary

**Purpose of this doc:** Brief a future Cursor session whose goal is to make Ask Z-Bot
**work in the cloud** (production / public / always-on backend + distributable extension).

**Status as of 2026-08-12:** Extension **v1.0.0** is complete as a load-unpacked demo.
The **backend agent API is already cloud-hosted** on Render. Remaining work is mostly
production hardening, Store distribution, and clarifying what “cloud” means for the
client vs the API.

**Related docs:**
- [`README.md`](README.md) — load unpacked, settings, package zip
- [`../rag-vector-databases/chrome-extension-plan.md`](../rag-vector-databases/chrome-extension-plan.md) — full build plan (Phases 1–5 done)
- [`PUBLISH_CHECKLIST.md`](PUBLISH_CHECKLIST.md) — Web Store / production checklist
- [`store-listing.md`](store-listing.md) — Store listing draft
- [`../rag-vector-databases/zearn-support-agent-summary.md`](../rag-vector-databases/zearn-support-agent-summary.md) — ADK agent
- [`../rag-vector-databases/how-it-works.md`](../rag-vector-databases/how-it-works.md) — RAG + agent internals

---

## One-sentence job

> On `zearn.org` / `help.zearn.org`, a floating **Ask Z-Bot** overlay sends the user’s
> question to a cloud FastAPI **`POST /agent`** endpoint; the ADK agent searches Zearn
> docs (hybrid RAG) with Google Search fallback and returns a cited answer + Think/Act/Observe steps.

---

## What is already in the cloud vs local

| Piece | Where it runs today | Notes |
|-------|---------------------|--------|
| Agent API (`POST /agent`, `/health`, `/telemetry`) | **Render** `https://ai-internship-i3lw.onrender.com` | Default URL in `config.js` |
| Streamlit agent UI | **Render** `https://zearn-faq-bot.onrender.com` | Separate service; not required by the extension |
| Vector store | **Pinecone** (cloud) | Used inside `search_zearn_doc` on the API |
| Extension UI (pill, overlay, settings) | **User’s Chrome** (load unpacked) | Not hosted; MV3 content script + service worker |
| Optional local API | `http://127.0.0.1:8000` | Override in Settings for uvicorn |

**Important clarification for the next session:**  
“Make the extension work in the cloud” usually does **not** mean hosting the overlay as a website.
Chrome extensions always run in the browser. What people usually mean:

1. **Rely only on the cloud API** (already the default — Render), harden it for public use, and/or  
2. **Publish the extension** (Chrome Web Store) so others can install it without load-unpacked, and/or  
3. **Stop depending on free-tier cold starts** (upgrade Render, warmer service, or different host).

Ask the user which of those they want before changing architecture.

---

## Architecture (current)

```
zearn.org page
  └─ content.js + overlay.js (Shadow DOM UI)
        │  chrome.runtime.sendMessage
        ▼
  background.js (MV3 service worker)
        │  GET /health  (wake + health)
        │  POST /agent  (question → answer + steps)
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
  manifest.json          # MV3, v1.0.0
  background.js          # /agent proxy, Alt+Z, storage, API key, install ID
  overlay.js / .css      # UI
  content.js             # mount + toggle listener
  config.js              # DEFAULT_AGENT_API_URL = Render
  privacy-policy.html
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
| `AGENT_API_KEY` | **Optional gate.** Empty = open `/agent` (current demo). Set = require `X-API-Key` from extension Settings |
| `AGENT_RATE_LIMIT_ENABLED` / `AGENT_RATE_LIMIT_PER_MINUTE` | Default on; 20/min per install ID or IP |
| `TELEMETRY_ENABLED` | Default `false` |
| Rerank / PyTorch | **Off on Render** (512MB) — hybrid BM25+dense only |

Extension Settings already support API URL override + API key field (`chrome.storage.sync`).

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

---

## Load & smoke test (before cloud changes)

1. Chrome → `chrome://extensions` → Developer mode → **Load unpacked** → this `chrome-extension/` folder  
2. Open `https://help.zearn.org` → **Ask Z-Bot** pill or **Alt+Z**  
3. Leave API URL as default Render (or set local `http://127.0.0.1:8000` if uvicorn is running)  
4. Manual matrix: Tower Alert (docs only) · weather (web fallback banner) · add students (Sources links)

---

## Known gaps / risks for cloud

| Gap | Impact |
|-----|--------|
| Render free cold start | First ask feels “broken” without wait copy / health wake (already implemented; still slow) |
| Open `/agent` when `AGENT_API_KEY` unset | Anyone with the URL can spend Gemini/OpenAI quota |
| Placeholder icons | Fine for demo; not Store-ready |
| Privacy policy only inside extension | Need public URL for Store |
| Manual test matrix not marked done in plan | Re-run before claiming production-ready |
| `marked` without DOMPurify | Acceptable while answers come from own API; revisit if corpus/tools widen |

---

## Prompt starter for the next session

Paste something like:

> Read `ai-engineering-bootcamp-v2/week-2/chrome-extension/ask-zbot-cloud-handoff.md`
> and `chrome-extension-plan.md`. The Ask Z-Bot extension already defaults to the Render
> API. I want it to **work in the cloud** meaning: [harden Render + turn on AGENT_API_KEY /
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
