import pytest

from app.adapters.growthbook import enable_feature


class FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


class FakeAsyncClient:
    def __init__(self, behavior):
        # behavior: dict mapping url substring -> (status_code, payload)
        self.behavior = behavior

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):
        for key, resp in self.behavior.items():
            if key in url:
                return FakeResponse(resp[0], resp[1])
        # default: 404
        return FakeResponse(404, {"error": "not found"})


@pytest.mark.asyncio
async def test_enable_feature_uses_v2_toggle(monkeypatch):
    # Simulate v2 toggle returning 200
    behavior = {"/api/v2/features/": (200, {"environments": {"qa": {"enabled": True}}})}
    monkeypatch.setattr("app.adapters.growthbook.httpx.AsyncClient", lambda timeout: FakeAsyncClient(behavior))

    resp = await enable_feature("test-flag", "qa", True)
    assert resp.get("environments", {}).get("qa", {}).get("enabled") is True


@pytest.mark.asyncio
async def test_enable_feature_falls_back_to_v2_post(monkeypatch):
    # Simulate toggle failing (404) and v2 POST succeeding
    behavior = {
        "/api/v2/features/test-flag/toggle": (404, {"error": "no toggle"}),
        "/api/v2/features/test-flag": (200, {"environments": {"qa": {"enabled": True}}}),
    }
    monkeypatch.setattr("app.adapters.growthbook.httpx.AsyncClient", lambda timeout: FakeAsyncClient(behavior))

    resp = await enable_feature("test-flag", "qa", True)
    assert resp.get("environments", {}).get("qa", {}).get("enabled") is True


@pytest.mark.asyncio
async def test_enable_feature_falls_back_to_v1_post(monkeypatch):
    # Simulate toggle and v2 POST failing, v1 POST succeeds
    behavior = {
        "/api/v2/features/test-flag/toggle": (404, {"error": "no toggle"}),
        "/api/v2/features/test-flag": (500, {"error": "server"}),
        "/api/v1/features/test-flag": (200, {"environments": {"qa": {"enabled": True}}}),
    }
    monkeypatch.setattr("app.adapters.growthbook.httpx.AsyncClient", lambda timeout: FakeAsyncClient(behavior))

    resp = await enable_feature("test-flag", "qa", True)
    assert resp.get("environments", {}).get("qa", {}).get("enabled") is True
