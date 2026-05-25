"""GrowthBook REST API adapter (moved to adapters package)."""
import os
import httpx
import logging
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


async def create_flag(from_env: str, to_env: str, flag_key: str, rules: List[Dict[str, Any]], enabled: bool = False) -> Dict[str, Any]:
    """Ensure flag exists in target environment with the given rules and enabled state.

    GrowthBook features are global — a "missing" flag in our context means the feature
    exists in the source environment but has no rules/config in the target environment.
    Two cases:
      1. Feature exists globally → just update the target env (POST /api/v1/features/{id})
      2. Feature truly doesn't exist → create it globally (POST /api/v1/features)
    """
    feature_url = f"{_api_url()}/api/v1/features/{flag_key}"
    create_url = f"{_api_url()}/api/v1/features"

    logger = logging.getLogger(__name__)
    logger.info("CREATE_FLAG CALLED: flag=%s, from_env=%s, to_env=%s, rules=%s, enabled=%s", flag_key, from_env, to_env, rules, enabled)

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Check if feature already exists globally in GrowthBook
        resp_check = await client.get(feature_url, headers=_headers())

        if resp_check.status_code == 200:
            # Feature exists globally — just configure the target environment
            logger.info("Feature %s exists globally, updating %s env instead of creating", flag_key, to_env)
            payload = {"environments": {to_env: {"rules": rules, "enabled": enabled}}}
            logger.info("GrowthBook UPDATE (via create path) payload for %s -> %s: %s", flag_key, to_env, payload)
            response = await client.post(feature_url, headers=_headers(), json=payload)
        else:
            # Feature truly doesn't exist — fetch source metadata and create globally
            resp_source = await client.get(feature_url, headers=_headers())
            if resp_source.status_code >= 400:
                raise ValueError(f"Source feature '{flag_key}' not found in GrowthBook — cannot promote.")
            source_feature = resp_source.json().get("feature") or resp_source.json()

            payload = {
                "id": flag_key,
                "valueType": source_feature.get("valueType", "boolean"),
                "defaultValue": source_feature.get("defaultValue", "false"),
                "owner": source_feature.get("owner", ""),
                "project": _project_id(),
                "environments": {
                    to_env: {"enabled": enabled, "rules": rules}
                }
            }
            logger.info("GrowthBook CREATE payload for %s -> %s: %s", flag_key, to_env, payload)
            response = await client.post(create_url, headers=_headers(), json=payload)

        response.raise_for_status()

        try:
            logger.info("GrowthBook CREATE/UPDATE response for %s: %s", flag_key, response.json())
        except Exception:
            logger.debug("GrowthBook response non-json or missing")

    return response.json()


async def update_flag(from_env: str, to_env: str, flag_key: str, rules: List[Dict[str, Any]], enabled: bool = False) -> Dict[str, Any]:
    """Update an existing flag in target environment with new rules and enabled state.
    
    Used for conflicting or updated flags that already exist in target.
    GrowthBook API: POST /api/v1/features/{id} accepts ONLY {"environments": {...}}
    """
    update_url = f"{_api_url()}/api/v1/features/{flag_key}"
    
    logger = logging.getLogger(__name__)
    logger.info("UPDATE_FLAG CALLED: flag=%s, from_env=%s, to_env=%s, rules=%s, enabled=%s", flag_key, from_env, to_env, rules, enabled)
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        # Send only the target environment update — keep payload minimal
        payload = {"environments": {to_env: {"rules": rules, "enabled": enabled}}}
        logger.info("GrowthBook UPDATE payload for %s -> %s: %s", flag_key, to_env, payload)
        response = await client.post(update_url, headers=_headers(), json=payload)
        response.raise_for_status()
        
        try:
            logger.info("GrowthBook UPDATE response for %s: %s", flag_key, response.json())
        except Exception:
            logger.debug("GrowthBook response non-json or missing")

    return response.json()


async def enable_feature(flag_key: str, environment: str, enabled: bool) -> Dict[str, Any]:
    """Enable or disable a feature in a specific environment.

    Prefer v2 toggle endpoint `/api/v2/features/:id/toggle`. If unavailable,
    fall back to v2 `POST /features/:id` with an `environments` map. Last
    fallback is v1 `POST /api/v1/features/:id`.
    """
    logger = logging.getLogger(__name__)
    v2_toggle = f"{_api_url()}/api/v2/features/{flag_key}/toggle"
    v2_feature = f"{_api_url()}/api/v2/features/{flag_key}"
    v1_feature = f"{_api_url()}/api/v1/features/{flag_key}"

    payload_toggle = {"environments": {environment: bool(enabled)}}

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Try v2 toggle
        try:
            logger.info("Attempting v2 toggle for %s env=%s enabled=%s", flag_key, environment, enabled)
            resp = await client.post(v2_toggle, headers=_headers(), json={**payload_toggle, "reason": "Promote flow"})
            if resp.status_code == 200:
                return resp.json()
        except httpx.HTTPStatusError:
            logger.debug("v2 toggle returned HTTP error, will try fallback", exc_info=True)
        except Exception:
            logger.debug("v2 toggle failed, will try fallback", exc_info=True)

        # Fallback: v2 feature patch
        try:
            logger.info("Falling back to v2 feature POST for %s", flag_key)
            resp = await client.post(v2_feature, headers=_headers(), json={"environments": {environment: {"enabled": bool(enabled), "rules": []}}})
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            logger.debug("v2 POST fallback failed, trying v1", exc_info=True)

        # Last resort: v1 feature POST
        try:
            logger.info("Falling back to v1 feature POST for %s", flag_key)
            resp = await client.post(v1_feature, headers=_headers(), json={"environments": {environment: {"enabled": bool(enabled), "rules": []}}})
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.exception("Failed to enable feature %s in env %s", flag_key, environment)
            raise
