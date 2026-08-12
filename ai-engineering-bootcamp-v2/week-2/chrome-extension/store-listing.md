# Chrome Web Store listing — Ask Z-Bot

Draft copy for a future public listing. Do **not** submit until Phase 5 checklist items are complete and you have permission to use Zearn branding publicly.

## Listing fields

| Field | Suggested text |
|-------|----------------|
| **Name** | Ask Z-Bot — Zearn Support Agent |
| **Short description** (132 chars max) | Floating Ask Z-Bot on zearn.org — answers teacher/admin support questions from Zearn docs with cited sources. |
| **Category** | Productivity |
| **Language** | English |

## Detailed description

```
Ask Z-Bot adds a floating helper on zearn.org and help.zearn.org.

Ask a Zearn support question (Tower Alerts, rosters, accounts, and more). Z-Bot
calls a Zearn Support Agent that searches official Zearn documentation first and
falls back to the web only when docs do not answer — with a clear banner when
that happens.

Features:
• Shadow-DOM overlay — Ask Z-Bot pill, Alt+Z to toggle
• Think → Act → Observe step log (same idea as the Streamlit demo)
• Markdown answers with Sources links from Zearn docs / PDFs
• Optional API key + rate limiting (configured by the API operator)
• Settings: API URL, health check, privacy opt-in for anonymous error reports

This is an independent educational / internship project and is not affiliated
with or endorsed by Zearn unless stated otherwise.
```

## Permission justifications

| Permission / host | Justification |
|-------------------|---------------|
| `storage` | Save API URL, optional API key, telemetry preference, install ID |
| `host` Render API / localhost | Call `GET /health` and `POST /agent` via the service worker |
| Content script on `*.zearn.org` | Show the Ask Z-Bot overlay on Zearn pages |

## Assets needed before submit

- [ ] 128×128 store icon (replace placeholder)
- [ ] 440×280 small promo tile (optional)
- [ ] 1280×800 or 640×400 screenshots (at least 1; recommend 3): pill collapsed, panel with answer + Sources, Settings
- [ ] Privacy policy **public URL** (host `privacy-policy.html` on GitHub Pages / your site — Store rejects `chrome-extension://` URLs)

## Single purpose statement

```
The extension’s single purpose is to help users ask Zearn support questions and
receive grounded answers from a Zearn documentation agent while browsing Zearn sites.
```
