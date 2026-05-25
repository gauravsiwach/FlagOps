"""Routers for promotion validation and conflict resolution (A.02)."""
from fastapi import APIRouter, HTTPException
from typing import List
from sqlalchemy import select
import uuid

from app.adapters.growthbook import fetch_flags
from app.services.diff_engine import compute_diff
from app.repositories.db import create_promotion_batch, update_promotion_batch_resolutions, validate_market_and_environments
from app.schemas.promotion import (
    PromotionValidateRequest,
    PromotionValidateResponse,
    ConflictItem,
    ResolveConflictsRequest,
    ResolveConflictsResponse,
    ExecuteRequest,
    ExecuteResponse,
)
from app.services.promotion_orchestrator import promote_flags

router = APIRouter()


@router.post("/api/promotions/validate", response_model=PromotionValidateResponse)
async def validate_promotion(payload: PromotionValidateRequest):
    # Validate market and environments via repository
    await validate_market_and_environments(payload.market, payload.from_env, payload.to_env)

    # Fetch both environments
    try:
        source_flags, target_flags = await _fetch_both(payload.from_env, payload.to_env)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"GrowthBook API error: {e}")

    # Compute diff for given market
    diff = compute_diff(source_flags, target_flags, payload.market)

    # Filter conflicts/missing for requested flags (include both conflict and missing statuses)
    conflicts = [d for d in diff if d["flag_key"] in payload.flags_to_promote and d["status"] in ("conflict", "missing")]

    # Create pending promotion batch
    batch_id = str(uuid.uuid4())
    flags_data = {"flags_to_promote": payload.flags_to_promote, "conflicts": conflicts}
    try:
        await create_promotion_batch(batch_id, payload.market, payload.from_env, payload.to_env, flags_data, status="pending_validation")
    except Exception as e:
        # Log and return controlled 500 for DB errors
        raise HTTPException(status_code=500, detail=f"Database error creating promotion batch: {e}")

    conflict_items = [ConflictItem(flag_key=c["flag_key"], source_rules=c.get("source_rules"), target_rules=c.get("target_rules"), source_enabled=c.get("source_enabled", False), target_enabled=c.get("target_enabled", False)) for c in conflicts]

    return PromotionValidateResponse(batch_id=batch_id, conflicts=conflict_items)


@router.post("/api/promotions/resolve-conflicts", response_model=ResolveConflictsResponse)
async def resolve_conflicts(payload: ResolveConflictsRequest):
    # Persist resolutions and mark batch validated
    # Map resolutions to dict (preserve optional force flag)
    res_map = {r.flag_key: (r.decision if getattr(r, 'force', False) is False else {"decision": r.decision, "force": True}) for r in payload.resolutions}
    pb = await update_promotion_batch_resolutions(payload.batch_id, res_map)
    if pb is None:
        raise HTTPException(status_code=404, detail="Promotion batch not found")

    return ResolveConflictsResponse(batch_id=payload.batch_id, status="validated")


@router.post("/api/promotions/execute", response_model=ExecuteResponse)
async def execute_promotion(payload: ExecuteRequest):
    # Load batch
    from app.models.database import PromotionBatch
    from app.repositories.db import async_session, init_engine

    if async_session is None:
        init_engine()

    async with async_session() as session:
        result = await session.execute(select(PromotionBatch).where(PromotionBatch.id == payload.batch_id))
        pb = result.scalars().first()
        if not pb:
            raise HTTPException(status_code=404, detail="Promotion batch not found")
        if pb.status != "validated":
            raise HTTPException(status_code=409, detail="Promotion batch not validated for execution")

        flags_data = pb.flags_data or {}
        resolutions = flags_data.get("resolutions", {})
        conflicts = flags_data.get("conflicts", [])

    # Run orchestrator
    results = await promote_flags(payload.batch_id, pb.market_code, pb.from_environment, pb.to_environment, resolutions, conflicts, executed_by=payload.executed_by)

    # Build response items
    items = []
    for fk, r in results.items():
        items.append({"flag_key": fk, "applied": r.get("applied", False), "error": r.get("error"), "details": r.get("details")})

    final_status = "executed" if all(i.get("error") is None for i in results.values()) else "executed_with_errors"

    return ExecuteResponse(batch_id=payload.batch_id, status=final_status, results=items)


async def _fetch_both(from_env: str, to_env: str):
    import asyncio
    source_flags, target_flags = await asyncio.gather(
        fetch_flags(from_env),
        fetch_flags(to_env),
    )
    return source_flags, target_flags
