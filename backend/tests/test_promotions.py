import pytest
from httpx import AsyncClient, ASGITransport

from main import app


async def _fake_fetch_flags_dev(env):
    return [
        {
            "flag_key": "promo-flag",
            "rules": [{"type": "force", "value": "true", "condition": {"countryCode": "IN"}}],
            "enabled": True,
            "last_modified": "2026-05-24T12:00:00.000Z",
        }
    ]


async def _fake_fetch_flags_qa(env):
    # QA has a conflicting rule for same flag
    return [
        {
            "flag_key": "promo-flag",
            "rules": [{"type": "force", "value": "false", "condition": {"countryCode": "IN"}}],
            "enabled": True,
            "last_modified": "2026-05-24T12:00:00.000Z",
        }
    ]


@pytest.mark.asyncio
async def test_validate_no_conflicts(monkeypatch):
    # both envs have same rule -> no conflicts
    async def same_fetch(env):
        return [
            {
                "flag_key": "promo-flag",
                "rules": [{"type": "force", "value": "true", "condition": {"countryCode": "IN"}}],
                "enabled": True,
                "last_modified": "2026-05-24T12:00:00.000Z",
            }
        ]

    called = []

    async def fake_create(batch_id, market_code, from_environment, to_environment, flags_data, status="pending_validation"):
        called.append((batch_id, flags_data))

    # Mock both market validation and fetch
    async def fake_validate_market(*args, **kwargs):
        return True

    monkeypatch.setattr("app.routers.promotions.fetch_flags", same_fetch)
    monkeypatch.setattr("app.routers.promotions.create_promotion_batch", fake_create)
    monkeypatch.setattr("app.routers.promotions.validate_market_and_environments", fake_validate_market)

    payload = {"market": "IN", "from_env": "dev", "to_env": "qa", "flags_to_promote": ["promo-flag"]}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/promotions/validate", json=payload)

    assert r.status_code == 200
    body = r.json()
    assert body.get("conflicts") == []
    assert len(called) == 1


@pytest.mark.asyncio
async def test_resolve_invalid_decision():
    # invalid decision value -> Pydantic should reject with 422
    payload = {"batch_id": "b", "resolutions": [{"flag_key": "x", "decision": "invalid_choice"}]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/promotions/resolve-conflicts", json=payload)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_batch_db_error(monkeypatch):
    # simulate DB failure by raising from create_promotion_batch
    async def failing_create(*args, **kwargs):
        raise RuntimeError("db down")

    async def fake_validate_market(*args, **kwargs):
        return True

    monkeypatch.setattr("app.routers.promotions.create_promotion_batch", failing_create)
    monkeypatch.setattr("app.routers.promotions.validate_market_and_environments", fake_validate_market)
    payload = {"market": "IN", "from_env": "dev", "to_env": "qa", "flags_to_promote": ["promo-flag"]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/promotions/validate", json=payload)
    assert r.status_code == 500


@pytest.mark.asyncio
async def test_validate_creates_batch_and_returns_conflicts(monkeypatch):
    async def fake_fetch(env):
        return await (_fake_fetch_flags_dev(env) if env == "dev" else _fake_fetch_flags_qa(env))

    called = []

    async def fake_create(batch_id, market_code, from_environment, to_environment, flags_data, status="pending_validation"):
        called.append((batch_id, market_code, from_environment, to_environment, flags_data, status))

    async def fake_validate_market(*args, **kwargs):
        return True

    monkeypatch.setattr("app.routers.promotions.fetch_flags", fake_fetch)
    monkeypatch.setattr("app.routers.promotions.create_promotion_batch", fake_create)
    monkeypatch.setattr("app.routers.promotions.validate_market_and_environments", fake_validate_market)

    payload = {
        "market": "IN",
        "from_env": "dev",
        "to_env": "qa",
        "flags_to_promote": ["promo-flag"],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/promotions/validate", json=payload)

    assert r.status_code == 200
    body = r.json()
    assert "batch_id" in body
    assert isinstance(body.get("conflicts"), list)
    assert any(c["flag_key"] == "promo-flag" for c in body.get("conflicts"))
    assert len(called) == 1


@pytest.mark.asyncio
async def test_resolve_persists_and_returns_validated(monkeypatch):
    async def fake_update(batch_id, resolutions):
        return {"id": batch_id}

    monkeypatch.setattr("app.routers.promotions.update_promotion_batch_resolutions", fake_update)

    payload = {
        "batch_id": "test-batch",
        "resolutions": [{"flag_key": "promo-flag", "decision": "use_source"}],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/promotions/resolve-conflicts", json=payload)

    assert r.status_code == 200
    body = r.json()
    assert body["batch_id"] == "test-batch"
    assert body["status"] == "validated"


@pytest.mark.asyncio
async def test_resolve_not_found_returns_404(monkeypatch):
    async def fake_update_none(batch_id, resolutions):
        return None

    monkeypatch.setattr("app.routers.promotions.update_promotion_batch_resolutions", fake_update_none)

    payload = {
        "batch_id": "missing-batch",
        "resolutions": [{"flag_key": "promo-flag", "decision": "keep_target"}],
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/promotions/resolve-conflicts", json=payload)

    assert r.status_code == 404
