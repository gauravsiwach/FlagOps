#!/usr/bin/env python3
"""Seed GrowthBook with test feature flags covering all diff statuses.

Flags created (dev → qa diff):
  test-feature          already exists — dev=enabled/no-rules, qa=disabled  → missing
  au-pricing-v2         dev=enabled/AU-rule, qa=enabled/same-rule            → in_sync
  au-checkout-redesign  dev=enabled/AU-rule-true, qa=enabled/AU-rule-false   → conflict
  au-loyalty-program    dev=disabled, qa=enabled/AU-rule                     → updated
  au-express-shipping   dev=enabled/AU-rule, qa=disabled                     → missing
  au-new-homepage       dev=enabled/AU-rule, qa=enabled/same-rule            → in_sync

Run from backend/:
  python scripts/seed_growthbook.py
"""

import asyncio
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

API_URL = os.getenv("GROWTHBOOK_API_URL", "https://api.growthbook.io")
API_KEY = os.getenv("GROWTHBOOK_API_KEY", "")
PROJECT_ID = os.getenv("GROWTHBOOK_PROJECT_ID", "")

if not API_KEY:
    print("ERROR: GROWTHBOOK_API_KEY not set in .env")
    sys.exit(1)

if not PROJECT_ID:
    print("ERROR: GROWTHBOOK_PROJECT_ID not set in .env")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

AU_RULE_TRUE = {
    "type": "force",
    "value": "true",
    "condition": "{\"countryCode\": \"IN\"}",
    "enabled": True,
}

AU_RULE_FALSE = {
    "type": "force",
    "value": "false",
    "condition": "{\"countryCode\": \"IN\"}",
    "enabled": True,
}

FLAGS = [
    {
        "id": "pricing-v2",
        "description": "Pricing v2 rollout — expected diff: in_sync",
        "owner": "gauravsiwach2008@gmail.com",
        "project": PROJECT_ID,
        "valueType": "boolean",
        "defaultValue": "false",
        "environments": {
            "dev":        {"enabled": True,  "rules": [AU_RULE_TRUE]},
            "qa":         {"enabled": True,  "rules": [AU_RULE_TRUE]},  # same → in_sync
            "uat":        {"enabled": False, "rules": []},
            "pre-prod":   {"enabled": False, "rules": []},
            "production": {"enabled": False, "rules": []},
        },
    },
    {
        "id": "checkout-redesign",
        "description": "Checkout redesign — expected diff: conflict",
        "owner": "gauravsiwach2008@gmail.com",
        "project": PROJECT_ID,
        "valueType": "boolean",
        "defaultValue": "false",
        "environments": {
            "dev":        {"enabled": True,  "rules": [AU_RULE_TRUE]},   # true
            "qa":         {"enabled": True,  "rules": [AU_RULE_FALSE]},  # false → conflict
            "uat":        {"enabled": False, "rules": []},
            "pre-prod":   {"enabled": False, "rules": []},
            "production": {"enabled": False, "rules": []},
        },
    },
    {
        "id": "loyalty-program",
        "description": "Loyalty program — expected diff: updated (only in qa)",
        "owner": "gauravsiwach2008@gmail.com",
        "project": PROJECT_ID,
        "valueType": "boolean",
        "defaultValue": "false",
        "environments": {
            "dev":        {"enabled": False, "rules": []},               # not in dev
            "qa":         {"enabled": True,  "rules": [AU_RULE_TRUE]},  # in qa → updated
            "uat":        {"enabled": False, "rules": []},
            "pre-prod":   {"enabled": False, "rules": []},
            "production": {"enabled": False, "rules": []},
        },
    },
    {
        "id": "express-shipping",
        "description": "Express shipping toggle — expected diff: missing (only in dev)",
        "owner": "gauravsiwach2008@gmail.com",
        "project": PROJECT_ID,
        "valueType": "boolean",
        "defaultValue": "false",
        "environments": {
            "dev":        {"enabled": True,  "rules": [AU_RULE_TRUE]},  # in dev
            "qa":         {"enabled": False, "rules": []},               # not in qa → missing
            "uat":        {"enabled": False, "rules": []},
            "pre-prod":   {"enabled": False, "rules": []},
            "production": {"enabled": False, "rules": []},
        },
    },
    {
        "id": "new-homepage",
        "description": "New homepage layout — expected diff: in_sync",
        "owner": "gauravsiwach2008@gmail.com",
        "project": PROJECT_ID,
        "valueType": "boolean",
        "defaultValue": "false",
        "environments": {
            "dev":        {"enabled": True,  "rules": [AU_RULE_TRUE]},
            "qa":         {"enabled": True,  "rules": [AU_RULE_TRUE]},  # same → in_sync
            "uat":        {"enabled": False, "rules": []},
            "pre-prod":   {"enabled": False, "rules": []},
            "production": {"enabled": False, "rules": []},
        },
    },
]

# Old flags created with country prefix — delete them on re-seed
STALE_FLAG_IDS = [
    "au-pricing-v2",
    "au-checkout-redesign",
    "au-loyalty-program",
    "au-express-shipping",
    "au-new-homepage",
]


async def delete_flag(client: httpx.AsyncClient, flag_id: str) -> None:
    resp = await client.delete(f"{API_URL}/api/v1/features/{flag_id}", headers=HEADERS)
    if resp.status_code in (200, 204):
        print(f"  🗑  Deleted  : {flag_id}")
    elif resp.status_code == 404:
        pass  # already gone
    else:
        print(f"  ✗ Delete failed: {flag_id} [{resp.status_code}]")


async def create_or_update(client: httpx.AsyncClient, flag: dict) -> None:
    flag_id = flag["id"]

    resp = await client.post(f"{API_URL}/api/v1/features", headers=HEADERS, json=flag)
    if resp.status_code in (200, 201):
        print(f"  ✓ Created  : {flag_id}")
        return

    # GrowthBook returns 400 (not 409) when ID already exists
    already_exists = resp.status_code in (400, 409) and "already exists" in resp.text
    if already_exists:
        # Update payload excludes read-only fields (id, valueType)
        update_body = {k: v for k, v in flag.items() if k not in ("id", "valueType")}
        # GrowthBook update endpoint is POST /api/v1/features/{id} (not PUT)
        resp = await client.post(
            f"{API_URL}/api/v1/features/{flag_id}",
            headers=HEADERS,
            json=update_body,
        )
        if resp.status_code in (200, 201):
            print(f"  ↻ Updated  : {flag_id}")
            return

    print(f"  ✗ Failed   : {flag_id} [{resp.status_code}] {resp.text[:200]}")


async def main() -> None:
    print(f"Seeding GrowthBook at {API_URL}\n")
    async with httpx.AsyncClient(timeout=30.0) as client:
        print("Cleaning up stale country-prefixed flags...")
        for flag_id in STALE_FLAG_IDS:
            await delete_flag(client, flag_id)
        print("\nCreating flags (no country prefix)...")
        for flag in FLAGS:
            await create_or_update(client, flag)
    print("\nDone. Test with:")
    print('  curl -s "http://localhost:8000/api/diff?market=AU&from_env=dev&to_env=qa" | python3 -m json.tool')


if __name__ == "__main__":
    asyncio.run(main())
