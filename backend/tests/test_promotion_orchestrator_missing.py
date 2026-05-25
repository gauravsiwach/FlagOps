import pytest

from app.services import promotion_orchestrator as orchestrator


@pytest.mark.asyncio
async def test_promote_flags_creates_missing_flag(monkeypatch):
    """Test that missing flags (exist in source, not in target) are created in target."""
    batch_id = "batch-missing"
    resolutions = {"missing-flag": "use_source"}
    conflicts = [
        {
            "flag_key": "missing-flag",
            "source_rules": [{"type": "feature", "value": "test"}],
            "target_rules": None,  # None because flag doesn't exist in target
            "source_enabled": True,
            "target_enabled": False,
            "status": "missing"
        }
    ]

    calls = {"create": None, "update": None, "final_status": None}

    async def fake_create_flag_snapshot(batch_id_, flag_key, market_code, environment, rules_before):
        return None

    async def fake_create_audit_log(**kwargs):
        return None

    async def fake_create_flag(from_env, to_env, key, rules, enabled=False):
        """Mock for creating a missing flag"""
        calls["create"] = (from_env, to_env, key, rules, enabled)
        return {"status": "created", "env": to_env, "key": key, "rules": rules}

    async def fake_update_flag(from_env, to_env, key, rules, enabled=False):
        """This should NOT be called for missing flags"""
        calls["update"] = (from_env, to_env, key, rules, enabled)
        return {"status": "updated", "env": to_env, "key": key}

    async def fake_fetch_flags(env):
        # After creation, return the flag with matching rules and enabled state
        return [{"flag_key": "missing-flag", "rules": [{"type": "feature", "value": "test"}], "enabled": True}]

    async def fake_update_results(batch_id_, results, final_status):
        calls["final_status"] = final_status

    monkeypatch.setattr(orchestrator, "create_flag_snapshot", fake_create_flag_snapshot)
    monkeypatch.setattr(orchestrator, "create_audit_log", fake_create_audit_log)
    monkeypatch.setattr(orchestrator, "create_flag", fake_create_flag)
    monkeypatch.setattr(orchestrator, "update_flag", fake_update_flag)
    monkeypatch.setattr(orchestrator, "fetch_flags", fake_fetch_flags)
    monkeypatch.setattr(orchestrator, "update_promotion_batch_execution_results", fake_update_results)

    res = await orchestrator.promote_flags(batch_id, "US", "dev", "qa", resolutions, conflicts, executed_by="tester")

    # Verify that create_flag was called
    assert calls["create"] == ("dev", "qa", "missing-flag", [{"type": "feature", "value": "test"}], True)
    # Verify that update_flag was NOT called
    assert calls["update"] is None
    # Verify execution succeeded
    assert calls["final_status"] == "executed"
    assert res["missing-flag"]["applied"] is True
