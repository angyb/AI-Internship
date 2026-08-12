# Publish checklist — Ask Z-Bot v1.0.0

Use this before any Chrome Web Store submission. Packaging and hardening are
implemented; **actual Store upload is a human step**.

## Pre-flight

- [ ] Reload unpacked extension after pulling v1.0.0
- [ ] Manual test matrix on `help.zearn.org` and `zearn.org` (Tower Alert / weather / add students)
- [ ] `Alt+Z` toggles; Settings Save / Reset / Check now work
- [ ] With `AGENT_API_KEY` unset: `/agent` works without key (dev)
- [ ] With `AGENT_API_KEY` set on API: extension Settings API key required; 401 without it
- [ ] Rapid asks eventually return 429 when over `AGENT_RATE_LIMIT_PER_MINUTE`
- [ ] Telemetry checkbox off by default; with server `TELEMETRY_ENABLED=true` + opt-in, errors POST `/telemetry`
- [ ] Privacy policy opens from Settings link (`privacy-policy.html`)

## Package

```bash
cd ai-engineering-bootcamp-v2/week-2/chrome-extension
./scripts/package.sh
# → dist/ask-zbot-<version>.zip
```

- [ ] Zip loads via “Load unpacked” after unzip (smoke)
- [ ] Zip uploaded to Chrome Web Store developer dashboard (when ready)

## Store assets

- [ ] Copy from [`store-listing.md`](store-listing.md) pasted into listing form
- [ ] Screenshots attached (see store-listing assets checklist)
- [ ] Privacy policy hosted at a **public https URL** and linked in the listing
- [ ] Confirm branding disclaimer (not affiliated with Zearn unless authorized)

## API / Render

- [ ] Set `AGENT_API_KEY` in Render Dashboard if public traffic is expected
- [ ] Confirm `AGENT_RATE_LIMIT_*` and `TELEMETRY_ENABLED` in `render.yaml` / sync
- [ ] Streamlit remote UI has matching `AGENT_API_KEY` if auth is on

## Done when

Store listing is draft-complete **or** you explicitly decide to keep the extension
load-unpacked only (bootcamp demo). Either outcome is fine for the internship.
