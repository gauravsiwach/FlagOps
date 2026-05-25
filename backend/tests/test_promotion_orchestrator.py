import pytest

from app.services.promotion_orchestrator import promote_flags


@pytest.mark.asyncio
async def test_promote_flags_applies_source_rules(monkeypatch):
    async def fake_update_flag(from_env, to_env, key, rules, enabled=False):
        return {"status": "ok", "from_env": from_env, "to_env": to_env, "key": key, "enabled": enabled}

    async def fake_create_flag(from_env, to_env, key, rules, enabled=False):
        return {"status": "ok", "from_env": from_env, "to_env": to_env, "key": key, "enabled": enabled}

    async def fake_snapshot(batch_id, flag_key, market_code, environment, rules):
        return None

    async def fake_audit_log(**kwargs):
        return None

    captured = {}

    async def fake_update_results(batch_id, results, final_status):
        captured["batch_id"] = batch_id
        captured["results"] = results
        captured["final_status"] = final_status

    monkeypatch.setattr("app.services.promotion_orchestrator.update_flag", fake_update_flag)
    monkeypatch.setattr("app.services.promotion_orchestrator.create_flag", fake_create_flag)
    monkeypatch.setattr("app.services.promotion_orchestrator.create_flag_snapshot", fake_snapshot)
    monkeypatch.setattr("app.services.promotion_orchestrator.create_audit_log", fake_audit_log)
    monkeypatch.setattr("app.services.promotion_orchestrator.update_promotion_batch_execution_results", fake_update_results)

    async def fake_fetch_flags(env):
        return [{"flag_key": "flagA", "rules": [{"r": 1}], "enabled": True}]

    monkeypatch.setattr("app.services.promotion_orchestrator.fetch_flags", fake_fetch_flags)

    batch_id = "b1"
    market_code = "MKT"
    from_env = "dev"
    to_env = "prod"
    resolutions = {"flagA": "use_source"}
    conflicts = [{"flag_key": "flagA", "source_rules": [{"r": 1}], "target_rules": [{"r": 2}], "source_enabled": True, "target_enabled": False, "status": "conflict"}]

    results = await promote_flags(batch_id, market_code, from_env, to_env, resolutions, conflicts, executed_by="tester")

    assert "flagA" in results
    assert results["flagA"]["applied"] is True
    assert captured["final_status"] == "executed"


@pytest.mark.asyncio
async def test_promote_flags_handles_update_error(monkeypatch):
    async def bad_update_flag(from_env, to_env, key, rules, enabled=False):
        raise RuntimeError("gb error")

    async def fake_create_flag(from_env, to_env, key, rules, enabled=False):
        raise RuntimeError("gb error")

    async def fake_snapshot(batch_id, flag_key, market_code, environment, rules):
        return None

    async def fake_audit_log(**kwargs):
        return None

    captured = {}

    async def fake_update_results(batch_id, results, final_status):
        captured["final_status"] = final_status
        captured["results"] = results

    monkeypatch.setattr("app.services.promotion_orchestrator.update_flag", bad_update_flag)
    monkeypatch.setattr("app.services.promotion_orchestrator.create_flag", fake_create_flag)
    monkeypatch.setattr("app.services.promotion_orchestrator.create_flag_snapshot", fake_snapshot)
    monkeypatch.setattr("app.services.promotion_orchestrator.create_audit_log", fake_audit_log)
    monkeypatch.setattr("app.services.promotion_orchestrator.update_promotion_batch_execution_results", fake_update_results)

    async def fake_fetch_flags_b(env):
        return [{"flag_key": "flagB", "rules": [{"r": 2}]}]

    monkeypatch.setattr("app.services.promotion_orchestrator.fetch_flags", fake_fetch_flags_b)

    batch_id = "b2"
    market_code = "MKT"
    from_env = "dev"
    to_env = "prod"
    resolutions = {"flagB": "use_source"}
    conflicts = [{"flag_key": "flagB", "source_rules": [{"r": 1}], "target_rules": [{"r": 2}], "source_enabled": True, "target_enabled": False, "status": "conflict"}]

    results = await promote_flags(batch_id, market_code, from_env, to_env, resolutions, conflicts, executed_by="tester")

    assert "flagB" in results
    assert results["flagB"]["error"] is not None
    assert captured["final_status"] == "rolled_back"
