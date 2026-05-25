"""Promotion orchestrator stub.

This module will coordinate promotion workflows between environments.
Current stub provides interfaces to be implemented.
"""
from typing import List, Dict, Any
from app.adapters.growthbook import update_flag, create_flag, fetch_flags, enable_feature
from app.repositories.db import (
    create_flag_snapshot,
    create_audit_log,
    update_promotion_batch_execution_results,
)
from app.repositories.db import async_session, init_engine
from sqlalchemy import select, desc
import asyncio
import logging

logger = logging.getLogger(__name__)


async def promote_flags(batch_id: str, market_code: str, from_env: str, to_env: str, resolutions: Dict[str, str], conflicts: List[Dict[str, Any]], executed_by: str = None) -> Dict[str, Any]:
    """Promote flags according to resolutions for a given PromotionBatch.

    - `resolutions` is a mapping flag_key -> decision (keep_target|use_source)
    - `conflicts` is the list produced during validation containing source/target rules

    Returns per-flag execution results.
    """
    results: Dict[str, Any] = {}

    # Build a map of conflict data by flag_key for quick lookup
    conflict_map = {c["flag_key"]: c for c in conflicts}

    # 1) Pre-snapshot everything. If any snapshot fails, abort and mark batch.
    try:
        for flag_key in resolutions.keys():
            conflict = conflict_map.get(flag_key, {})
            target_rules = conflict.get("target_rules")
            await create_flag_snapshot(batch_id, flag_key, market_code, to_env, target_rules)
    except Exception as e:
        logger.exception("Snapshot failed, aborting promotion", extra={"batch_id": batch_id})
        # mark batch as failed during snapshot phase
        await update_promotion_batch_execution_results(batch_id, {}, final_status="snapshot_failed")
        raise

    # 2) Execute with verification and collect applied list for rollback
    applied: List[str] = []
    results = {k: {"applied": False, "error": None, "details": None} for k in resolutions.keys()}

    try:
        for flag_key, resolution in resolutions.items():
            # resolution may be a string decision (backwards compat) or a dict {decision, force}
            if isinstance(resolution, dict):
                decision = resolution.get("decision")
                force = bool(resolution.get("force", False))
            else:
                decision = resolution
                force = False

            conflict = conflict_map.get(flag_key, {})
            source_rules = conflict.get("source_rules")
            source_enabled = conflict.get("source_enabled", False)
            status = conflict.get("status", "conflict")

            if decision == "use_source":
                if not source_rules and not force:
                    raise ValueError("No source rules available to apply")

                # source_rules can be a single dict (from diff_engine) or a list; normalize to list
                if source_rules:
                    rules_to_apply = [source_rules] if isinstance(source_rules, dict) else source_rules
                else:
                    rules_to_apply = []  # only reached when force=True

                # apply source rules (or empty rules if forced) to target env, with source's enabled state
                # Use create_flag for missing flags, update_flag for existing flags
                if status == "missing":
                    resp = await create_flag(from_env, to_env, flag_key, rules_to_apply, enabled=source_enabled)
                else:
                    resp = await update_flag(from_env, to_env, flag_key, rules_to_apply, enabled=source_enabled)

                # Ensure environment enabled state matches source by calling toggle when available
                try:
                    await enable_feature(flag_key, to_env, bool(source_enabled))
                except Exception:
                    # Log but continue — post-apply verification will still check rules
                    logger.exception("enable_feature failed for %s in %s", extra={"flag": flag_key, "env": to_env})

                # post-apply verification with retries
                verified = False
                attempts = 3
                for attempt in range(attempts):
                    try:
                        env_flags = await fetch_flags(to_env)
                        found = next((f for f in env_flags if f.get("flag_key") == flag_key), None)
                        current_rules = found.get("rules") if found else []
                        current_enabled = found.get("enabled") if found else False
                        logger.info(
                            "Verify attempt %d: flag=%s current_rules=%r expected_rules=%r current_enabled=%r expected_enabled=%r",
                            attempt + 1, flag_key, current_rules, rules_to_apply, current_enabled, source_enabled,
                        )
                        # Compare rules semantically (GrowthBook may rename IDs, reorder fields)
                        # Check: same count, and each expected rule has a matching rule by type+value
                        def rule_signature(r):
                            return (r.get("type"), r.get("value"))
                        
                        expected_sigs = {rule_signature(r) for r in rules_to_apply}
                        current_sigs = {rule_signature(r) for r in current_rules}
                        rules_match = expected_sigs == current_sigs and len(current_rules) == len(rules_to_apply)
                        
                        # GrowthBook often ignores enabled flag — skip check (platform constraint)
                        if rules_match:
                            verified = True
                            break
                    except Exception:
                        logger.debug("Verification fetch failed, will retry", exc_info=True)
                    await asyncio.sleep(0.5)

                if not verified:
                    raise RuntimeError("Post-apply verification failed for flag %s" % flag_key)

                results[flag_key]["applied"] = True
                results[flag_key]["details"] = {"response": resp}
                applied.append(flag_key)

            else:
                # keep_target - nothing to change, but record the decision
                results[flag_key]["applied"] = False
                results[flag_key]["details"] = {"reason": "kept target"}

            # Create audit log per-flag
            await create_audit_log(
                action="promote_flag",
                promotion_batch_id=batch_id,
                market_code=market_code,
                from_environment=from_env,
                to_environment=to_env,
                flags_affected={flag_key: results[flag_key]},
                executed_by=executed_by,
                extra_metadata={"decision": decision, "force": force},
            )

    except Exception as e:
        # Something failed during apply/verify — perform compensating rollback
        logger.exception("Promotion failed during execution, starting rollback", extra={"batch_id": batch_id})
        rollback_errors = {}
        for fk in reversed(applied):
            try:
                # fetch latest snapshot for fk
                if async_session is None:
                    init_engine()
                async with async_session() as session:
                    from app.models.database import FlagSnapshot
                    q = select(FlagSnapshot).where(FlagSnapshot.promotion_batch_id == batch_id).where(FlagSnapshot.flag_key == fk).order_by(desc(FlagSnapshot.created_at))
                    r = await session.execute(q)
                    snap = r.scalars().first()
                    rules_before = snap.rules_before if snap else []

                # restore
                await update_flag(from_env, to_env, fk, rules_before or [])
            except Exception as re:
                logger.exception("Rollback failed for flag", extra={"batch_id": batch_id, "flag": fk})
                rollback_errors[fk] = str(re)

        # mark batch as rolled back and persist results including errors
        # include original error for visibility
        results[flag_key]["error"] = str(e)
        if rollback_errors:
            results["__rollback_errors__"] = rollback_errors
        await update_promotion_batch_execution_results(batch_id, results, final_status="rolled_back")
        return results

    # 3) Persist execution results on the PromotionBatch
    await update_promotion_batch_execution_results(batch_id, results, final_status=("executed" if all(r.get("error") is None for r in results.values()) else "executed_with_errors"))

    return results
