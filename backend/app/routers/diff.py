"""Router for GET /api/diff — Story A.01."""
from enum import Enum
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from app.adapters.growthbook import fetch_flags
from app.services.diff_engine import compute_diff

logger = logging.getLogger(__name__)
router = APIRouter()


class MarketCode(str, Enum):
    IN = "IN"


class DiffEntry(BaseModel):
    flag_key: str
    source_rules: Optional[Dict[str, Any]] = None
    target_rules: Optional[Dict[str, Any]] = None
    status: str  # in_sync | missing | conflict | updated
    last_modified_source: Optional[str] = None


class DiffResponse(BaseModel):
    market: str
    from_env: str
    to_env: str
    diff: List[DiffEntry]


@router.get("/api/diff", response_model=DiffResponse)
async def get_diff(
    market: MarketCode = Query(MarketCode.IN, description="Market code e.g. IN"),
    from_env: str = Query(..., description="Source environment e.g. QA"),
    to_env: str = Query(..., description="Target environment e.g. pre-prod"),
):
    """Fetch flags from source and target environments and return a structured diff."""
    try:
        source_flags, target_flags = await _fetch_both(from_env, to_env)
    except Exception as e:
        logger.exception("GrowthBook API fetch failed", extra={
            "market": market.value, "from_env": from_env, "to_env": to_env
        })
        raise HTTPException(status_code=502, detail=f"GrowthBook API error: {str(e)}")

    try:
        diff = compute_diff(source_flags, target_flags, market_code=market.value)
    except Exception as e:
        logger.exception("Diff computation failed", extra={
            "market": market.value, "from_env": from_env, "to_env": to_env
        })
        raise HTTPException(status_code=500, detail="Internal error computing diff")

    return DiffResponse(market=market.value, from_env=from_env, to_env=to_env, diff=diff)


async def _fetch_both(from_env: str, to_env: str):
    """Fetch flags from both environments concurrently."""
    import asyncio
    source_flags, target_flags = await asyncio.gather(
        fetch_flags(from_env),
        fetch_flags(to_env),
    )
    return source_flags, target_flags
