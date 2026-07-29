#!/usr/bin/env python3
"""Push local .env variables to a Render web service.

Credentials (local only — never synced to Render):
  RENDER_API_KEY=rnd_...      # https://dashboard.render.com/u/settings#api-keys
  RENDER_SERVICE_ID=srv_...   # Service → Settings → Service ID

Add both to your local `.env`, or export them in the shell.

Usage:
  python sync_render_env.py
  python sync_render_env.py --dry-run
  python sync_render_env.py --deploy   # sync + trigger Render redeploy

Alternatively, in Render Dashboard → Environment → "Add from .env", paste the
output of:  python sync_render_env.py --print-bulk
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values

THIS_DIR = Path(__file__).resolve().parent
DEFAULT_ENV = THIS_DIR / ".env"

# Local-only keys — never push to the Render service
SKIP_KEYS = frozenset(
    {
        "RAG_API_URL",
        "RENDER_API_KEY",
        "RENDER_SERVICE_ID",
    }
)


def load_env_pairs(path: Path) -> list[dict[str, str]]:
    raw = dotenv_values(path)
    pairs: list[dict[str, str]] = []
    for key, value in raw.items():
        if not key or value is None or key in SKIP_KEYS:
            continue
        pairs.append({"key": key, "value": str(value)})
    pairs.sort(key=lambda item: item["key"])
    return pairs


def print_bulk_env(pairs: list[dict[str, str]]) -> None:
    for item in pairs:
        print(f"{item['key']}={item['value']}")


def sync_to_render(
    service_id: str,
    api_key: str,
    pairs: list[dict[str, str]],
    *,
    dry_run: bool = False,
) -> None:
    url = f"https://api.render.com/v1/services/{service_id}/env-vars"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    if dry_run:
        print(f"Would PUT {len(pairs)} env vars to {url}")
        for item in pairs:
            masked = item["value"]
            if re.search(r"(KEY|SECRET|TOKEN|PASSWORD)", item["key"], re.I):
                masked = item["value"][:4] + "…" if item["value"] else ""
            print(f"  {item['key']}={masked}")
        return

    response = httpx.put(url, headers=headers, json=pairs, timeout=60.0)
    if response.status_code >= 400:
        print(f"Render API error {response.status_code}: {response.text}", file=sys.stderr)
        sys.exit(1)
    print(f"Synced {len(pairs)} environment variables to Render service {service_id}.")


def trigger_deploy(service_id: str, api_key: str) -> None:
    url = f"https://api.render.com/v1/services/{service_id}/deploys"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    response = httpx.post(
        url,
        headers=headers,
        json={"clearCache": "do_not_clear"},
        timeout=60.0,
    )
    if response.status_code >= 400:
        print(f"Deploy trigger failed {response.status_code}: {response.text}", file=sys.stderr)
        sys.exit(1)

    if not response.content.strip():
        if response.status_code == 202:
            print(
                "Deploy queued (202) — another deploy may already be in progress. "
                "Check Render Dashboard → Events."
            )
        else:
            print(f"Deploy triggered (HTTP {response.status_code}). Check Render Dashboard → Events.")
        return

    try:
        payload = response.json()
    except ValueError:
        print(f"Deploy triggered (HTTP {response.status_code}). Check Render Dashboard → Events.")
        return

    deploy = payload.get("deploy") if isinstance(payload.get("deploy"), dict) else payload
    deploy_id = deploy.get("id", "unknown") if isinstance(deploy, dict) else "unknown"
    print(f"Triggered deploy: {deploy_id}")


def resolve_service_id(api_key: str, slug_hint: str | None) -> str | None:
    """Best-effort lookup when RENDER_SERVICE_ID is unset."""
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    cursor: str | None = None
    while True:
        params = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        response = httpx.get(
            "https://api.render.com/v1/services",
            headers=headers,
            params=params,
            timeout=60.0,
        )
        response.raise_for_status()
        payload = response.json()
        for wrapper in payload:
            service = wrapper.get("service") or wrapper
            name = str(service.get("name", ""))
            service_id = str(service.get("id", ""))
            if slug_hint and slug_hint.lower() in name.lower():
                return service_id
            if name == "week-2-rag-api":
                return service_id
        cursor = payload[-1].get("cursor") if payload else None
        if not cursor:
            break
    return None


def load_local_credentials(env_file: Path) -> tuple[str, str]:
    """Read Render API credentials from the shell env or local .env file."""
    from dotenv import load_dotenv

    load_dotenv(env_file)
    api_key = os.getenv("RENDER_API_KEY", "").strip()
    service_id = os.getenv("RENDER_SERVICE_ID", "").strip()
    return api_key, service_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync local .env to Render.")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--print-bulk", action="store_true", help="Print .env bulk paste for Dashboard")
    parser.add_argument("--deploy", action="store_true", help="Trigger deploy after sync")
    parser.add_argument("--service-id", default="")
    parser.add_argument("--api-key", default="")
    args = parser.parse_args()

    if not args.env_file.is_file():
        print(f"Missing env file: {args.env_file}", file=sys.stderr)
        sys.exit(1)

    pairs = load_env_pairs(args.env_file)
    if not pairs:
        print("No env vars to sync.", file=sys.stderr)
        sys.exit(1)

    if args.print_bulk:
        print_bulk_env(pairs)
        return

    file_api_key, file_service_id = load_local_credentials(args.env_file)
    api_key = (args.api_key or file_api_key).strip()
    if not api_key:
        print(
            "Set RENDER_API_KEY in .env or the shell "
            "(https://dashboard.render.com/u/settings#api-keys)",
            file=sys.stderr,
        )
        sys.exit(1)

    service_id = (args.service_id or file_service_id).strip()
    if not service_id:
        service_id = resolve_service_id(api_key, "rag") or resolve_service_id(api_key, "internship")
    if not service_id:
        print(
            "Set RENDER_SERVICE_ID (Render → your service → Settings → Service ID).",
            file=sys.stderr,
        )
        sys.exit(1)

    sync_to_render(service_id, api_key, pairs, dry_run=args.dry_run)
    if args.deploy and not args.dry_run:
        trigger_deploy(service_id, api_key)


if __name__ == "__main__":
    main()
