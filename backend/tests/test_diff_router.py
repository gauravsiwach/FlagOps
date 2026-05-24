import pytest
from httpx import AsyncClient, ASGITransport

from main import app


async def _fake_fetch_flags_dev(env):
    # dev has one flag enabled with IN rule
    return [
        {
            "flag_key": "pricing-v2",
            "rules": [{"type": "force", "value": "true", "condition": {"countryCode": "IN"}}],
            "enabled": True,
            "last_modified": "2026-05-24T12:00:00.000Z",
        }
    ]


async def _fake_fetch_flags_qa(env):
    # qa has the same flag — in_sync
    return [
        {
            "flag_key": "pricing-v2",
            "rules": [{"type": "force", "value": "true", "condition": {"countryCode": "IN"}}],
            "enabled": True,
            "last_modified": "2026-05-24T12:00:00.000Z",
        }
    ]


@pytest.mark.asyncio
async def test_diff_happy_path(monkeypatch):
    async def fake_fetch(env):
        return await (_fake_fetch_flags_dev(env) if env == "dev" else _fake_fetch_flags_qa(env))

    monkeypatch.setattr("app.routers.diff.fetch_flags", fake_fetch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/diff?market=IN&from_env=dev&to_env=qa")
    assert r.status_code == 200
    payload = r.json()
    assert payload["market"] == "IN"
    assert isinstance(payload["diff"], list)
    assert payload["diff"][0]["flag_key"] == "pricing-v2"
    assert payload["diff"][0]["status"] == "in_sync"


@pytest.mark.asyncio
async def test_diff_growthbook_error(monkeypatch):
    async def failing_fetch(env):
        raise RuntimeError("GB down")

    monkeypatch.setattr("app.routers.diff.fetch_flags", failing_fetch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/diff?market=IN&from_env=dev&to_env=qa")

    assert r.status_code == 502


@pytest.mark.asyncio
async def test_diff_market_validation():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/diff?market=ZZ&from_env=dev&to_env=qa")
    # ZZ is not a valid MarketCode — FastAPI should return 422
    assert r.status_code == 422
