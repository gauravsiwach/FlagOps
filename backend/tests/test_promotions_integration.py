import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from app.repositories import db as repo_db
from sqlalchemy import select
from app.models.database import PromotionBatch


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
async def test_integration_validate_then_resolve(monkeypatch):
    # Ensure engine/session initialized (app startup should have done this)
    if repo_db.async_session is None:
        repo_db.init_engine()

    # Patch fetch_flags to controlled source/target
    async def fake_fetch(env):
        return await (_fake_fetch_flags_dev(env) if env == "dev" else _fake_fetch_flags_qa(env))

    monkeypatch.setattr("app.routers.promotions.fetch_flags", fake_fetch)

    # Step 1: call validate
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
        batch_id = body["batch_id"]

        # Step 2: resolve conflicts using real DB update path
        r2 = await ac.post("/api/promotions/resolve-conflicts", json={
            "batch_id": batch_id,
            "resolutions": [{"flag_key": "promo-flag", "decision": "use_source"}],
        })
        assert r2.status_code == 200

    # Verify DB state
    async with repo_db.async_session() as session:
        result = await session.execute(select(PromotionBatch).where(PromotionBatch.id == batch_id))
        pb = result.scalars().first()
        assert pb is not None
        assert pb.status == "validated"
        # resolutions stored as dict mapping flag_key->decision
        assert pb.flags_data is not None
        assert pb.flags_data.get("resolutions") is not None
        assert pb.flags_data.get("resolutions").get("promo-flag") == "use_source"
