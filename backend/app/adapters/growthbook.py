"""GrowthBook REST API adapter (moved to adapters package)."""
import os
import httpx
from dotenv import load_dotenv
from typing import Any, Dict, List, Optional

# Ensure .env is loaded even when this module is imported before main.py runs
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))


def _headers() -> Dict[str, str]:
    key = os.getenv("GROWTHBOOK_API_KEY", "")
    if not key:
        raise ValueError("GROWTHBOOK_API_KEY is not set in environment.")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _api_url() -> str:
    return os.getenv("GROWTHBOOK_API_URL", "https://api.growthbook.io")


def _project_id() -> Optional[str]:
    return os.getenv("GROWTHBOOK_PROJECT_ID") or None


async def fetch_flags(environment: str) -> List[Dict[str, Any]]:
    url = f"{_api_url()}/api/v1/features"
    flags: List[Dict[str, Any]] = []
    offset = 0
    limit = 100

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            params: Dict[str, Any] = {"limit": limit, "offset": offset}
            project = _project_id()
            if project:
                params["projectId"] = project
            response = await client.get(url, headers=_headers(), params=params)
            response.raise_for_status()
            data = response.json()

            for feature in data.get("features", []):
                env_data = feature.get("environments", {}).get(environment, {})
                flags.append({
                    "flag_key": feature.get("id"),
                    "rules": env_data.get("rules", []),
                    "enabled": env_data.get("enabled", False),
                    "last_modified": feature.get("dateUpdated"),
                })

            if len(data.get("features", [])) < limit:
                break
            offset += limit

    return flags


async def update_flag(environment: str, flag_key: str, rules: List[Dict[str, Any]]) -> Dict[str, Any]:
    url = f"{_api_url()}/api/v1/features/{flag_key}"
    payload = {"environments": {environment: {"rules": rules}}}

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(url, headers=_headers(), json=payload)
        response.raise_for_status()

    return response.json()
