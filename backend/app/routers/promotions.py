"""Routers for promotion validation and conflict resolution (A.02)."""
from fastapi import APIRouter, HTTPException
from typing import List
import uuid

from app.adapters.growthbook import fetch_flags
from app.services.diff_engine import compute_diff
from app.repositories.db import create_promotion_batch, update_promotion_batch_resolutions
from app.schemas.promotion import (
    PromotionValidateRequest,
    PromotionValidateResponse,
    ConflictItem,
    ResolveConflictsRequest,
    ResolveConflictsResponse,
)

router = APIRouter()


@router.post("/api/promotions/validate", response_model=PromotionValidateResponse)
async def validate_promotion(payload: PromotionValidateRequest):
    # Fetch both environments
    try:
        source_flags, target_flags = await _fetch_both(payload.from_env, payload.to_env)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"GrowthBook API error: {e}")

    # Compute diff for given market
    diff = compute_diff(source_flags, target_flags, payload.market)

    # Filter conflicts for requested flags
    conflicts = [d for d in diff if d["flag_key"] in payload.flags_to_promote and d["status"] == "conflict"]

    # Create pending promotion batch
    batch_id = str(uuid.uuid4())
    flags_data = {"flags_to_promote": payload.flags_to_promote, "conflicts": conflicts}
    try:
        await create_promotion_batch(batch_id, payload.market, payload.from_env, payload.to_env, flags_data, status="pending_validation")
    except Exception as e:
        # Log and return controlled 500 for DB errors
        raise HTTPException(status_code=500, detail=f"Database error creating promotion batch: {e}")

    conflict_items = [ConflictItem(flag_key=c["flag_key"], source_rules=c.get("source_rules"), target_rules=c.get("target_rules")) for c in conflicts]

    return PromotionValidateResponse(batch_id=batch_id, conflicts=conflict_items)


@router.post("/api/promotions/resolve-conflicts", response_model=ResolveConflictsResponse)
async def resolve_conflicts(payload: ResolveConflictsRequest):
    # Persist resolutions and mark batch validated
    # Map resolutions to dict
    res_map = {r.flag_key: r.decision for r in payload.resolutions}
    pb = await update_promotion_batch_resolutions(payload.batch_id, res_map)
    if pb is None:
        raise HTTPException(status_code=404, detail="Promotion batch not found")

    return ResolveConflictsResponse(batch_id=payload.batch_id, status="validated")


async def _fetch_both(from_env: str, to_env: str):
    import asyncio
    source_flags, target_flags = await asyncio.gather(
        fetch_flags(from_env),
        fetch_flags(to_env),
    )
    return source_flags, target_flags
