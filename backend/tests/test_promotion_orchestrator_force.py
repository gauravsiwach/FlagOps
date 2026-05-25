import pytest

from app.services import promotion_orchestrator as orchestrator


@pytest.mark.asyncio
async def test_promote_flags_force_applies_empty_rules(monkeypatch):
    batch_id = "batch-force"
    resolutions = {"test-feature": {"decision": "use_source", "force": True}}
    conflicts = [{"flag_key": "test-feature", "source_rules": [], "target_rules": [], "source_enabled": False, "target_enabled": False, "status": "conflict"}]

    calls = {"update": None, "final_status": None}

    async def fake_create_flag_snapshot(batch_id_, flag_key, market_code, environment, rules_before):
        return None

    async def fake_create_audit_log(**kwargs):
        return None

    async def fake_update_flag(from_env, to_env, key, rules, enabled=False):
        calls["update"] = (to_env, key, rules, enabled)
        return {"status": "ok", "env": to_env, "key": key, "rules": rules}

    async def fake_create_flag(from_env, to_env, key, rules, enabled=False):
        calls["update"] = (to_env, key, rules, enabled)
        return {"status": "ok", "env": to_env, "key": key, "rules": rules}

    async def fake_fetch_flags(env):
            # return the flag with empty rules as expected post-apply
            return [{"flag_key": "test-feature", "rules": [], "enabled": False}]

    async def fake_update_results(batch_id_, results, final_status):
        calls["final_status"] = final_status

    monkeypatch.setattr(orchestrator, "create_flag_snapshot", fake_create_flag_snapshot)
    monkeypatch.setattr(orchestrator, "create_audit_log", fake_create_audit_log)
    monkeypatch.setattr(orchestrator, "update_flag", fake_update_flag)
    monkeypatch.setattr(orchestrator, "create_flag", fake_create_flag)
    monkeypatch.setattr(orchestrator, "fetch_flags", fake_fetch_flags)
    monkeypatch.setattr(orchestrator, "update_promotion_batch_execution_results", fake_update_results)

    res = await orchestrator.promote_flags(batch_id, "IN", "dev", "qa", resolutions, conflicts, executed_by="tester")

    assert calls["update"] == ("qa", "test-feature", [], False)
    assert calls["final_status"] == "executed"
    assert res["test-feature"]["applied"] is True
