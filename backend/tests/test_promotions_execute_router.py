import pytest

from app.routers import promotions as promotions_router
from app.schemas.promotion import ExecuteRequest


class FakePB:
    def __init__(self, id_):
        self.id = id_
        self.status = "validated"
        self.flags_data = {"resolutions": {"flagA": "keep_target"}, "conflicts": []}
        self.market_code = "MKT"
        self.from_environment = "dev"
        self.to_environment = "prod"


class FakeSession:
    def __init__(self, pb):
        self._pb = pb

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, stmt):
        class R:
            def __init__(self, pb):
                self._pb = pb

            def scalars(self):
                return self

            def first(self):
                return self._pb

        return R(self._pb)


@pytest.mark.asyncio
async def test_execute_promotion_calls_orchestrator(monkeypatch):
    pb = FakePB("batch-1")

    # monkeypatch the async_session that the router imports at call time
    import app.repositories.db as repo_db
    monkeypatch.setattr(repo_db, "async_session", lambda: FakeSession(pb))

    async def fake_promote_flags(batch_id, market_code, from_env, to_env, resolutions, conflicts, executed_by=None):
        return {"flagA": {"applied": False, "error": None, "details": {"reason": "kept target"}}}

    monkeypatch.setattr(promotions_router, "promote_flags", fake_promote_flags)

    req = ExecuteRequest(batch_id="batch-1", executed_by="tester")
    resp = await promotions_router.execute_promotion(req)

    assert resp.batch_id == "batch-1"
    assert resp.status == "executed"
    assert len(resp.results) == 1
