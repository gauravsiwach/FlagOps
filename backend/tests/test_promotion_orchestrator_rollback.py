import pytest

from app.services import promotion_orchestrator as orchestrator


@pytest.mark.asyncio
async def test_promote_flags_rollback_on_mid_failure(monkeypatch):
    # prepare two flags
    resolutions = {"flag1": "use_source", "flag2": "use_source"}
    conflicts = [
        {"flag_key": "flag1", "source_rules": [{"r": 1}], "target_rules": [], "source_enabled": True, "target_enabled": False, "status": "conflict"},
        {"flag_key": "flag2", "source_rules": [{"r": 2}], "target_rules": [], "source_enabled": True, "target_enabled": False, "status": "conflict"},
    ]

    calls = {"update_calls": [], "rollback_called": False, "final_status": None}

    async def fake_create_flag_snapshot(batch_id, flag_key, market_code, environment, rules_before):
        return None

    async def fake_create_audit_log(**kwargs):
        return None

    # simulate update_flag: succeed for flag1, fail for flag2, succeed for rollback of flag1
    async def fake_update_flag(from_env, to_env, key, rules, enabled=False):
        calls["update_calls"].append((to_env, key, rules, enabled))
        if key == "flag2" and len(calls["update_calls"]) == 2:
            raise RuntimeError("simulated GB failure on flag2")
        # If rollback restore for flag1 (third call), mark rollback_called
        if key == "flag1" and len(calls["update_calls"]) >= 3:
            calls["rollback_called"] = True
        return {"status": "ok", "env": to_env, "key": key}

    async def fake_create_flag(from_env, to_env, key, rules, enabled=False):
        calls["update_calls"].append((to_env, key, rules, enabled))
        if key == "flag2" and len(calls["update_calls"]) == 2:
            raise RuntimeError("simulated GB failure on flag2")
        if key == "flag1" and len(calls["update_calls"]) >= 3:
            calls["rollback_called"] = True
        return {"status": "ok", "env": to_env, "key": key}

    # fake async_session to return a snapshot for flag1 during rollback
    class FakeResult:
        def __init__(self, snap):
            self._snap = snap

        def scalars(self):
            return self

        def first(self):
            return self._snap

    class FakeSnapshot:
        def __init__(self, rules_before):
            self.rules_before = rules_before

    class FakeSession:
        def __init__(self, snap_map):
            self._snap_map = snap_map

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, stmt):
            # stmt contains a where on FlagSnapshot.flag_key - we can't parse it here; return flag1 snapshot
            return FakeResult(FakeSnapshot([{"restored": True}]))

    monkeypatch.setattr(orchestrator, "create_flag_snapshot", fake_create_flag_snapshot)
    monkeypatch.setattr(orchestrator, "create_audit_log", fake_create_audit_log)
    monkeypatch.setattr(orchestrator, "update_flag", fake_update_flag)
    monkeypatch.setattr(orchestrator, "create_flag", fake_create_flag)
    fetch_calls = {"n": 0}

    async def fake_fetch_flags(env):
        fetch_calls["n"] += 1
        # first verification call returns flag1 with matching rules
        if fetch_calls["n"] == 1:
            return [{"flag_key": "flag1", "rules": [{"r": 1}], "enabled": True}]
        return []

    monkeypatch.setattr(orchestrator, "fetch_flags", fake_fetch_flags)
    monkeypatch.setattr(orchestrator, "async_session", lambda: FakeSession({"flag1": [{"restored": True}]}))

    # capture final status
    async def fake_update_results(batch_id, results, final_status):
        calls["final_status"] = final_status

    monkeypatch.setattr(orchestrator, "update_promotion_batch_execution_results", fake_update_results)

    res = await orchestrator.promote_flags("batch-x", "IN", "dev", "prod", resolutions, conflicts, executed_by="tester")

    # Expect that rollback was attempted and final status is rolled_back
    assert calls["rollback_called"] is True
    assert calls["final_status"] == "rolled_back"
    assert "flag2" in res and res["flag2"]["error"] is not None
