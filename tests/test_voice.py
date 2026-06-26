"""
Unit tests for the Voice API router.
Tests token generation and error states.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_livekit_token_failure_when_unset(client: AsyncClient, auth_headers: dict, monkeypatch):
    """Test token generator returns 500 error when credentials are not configured."""
    from jan_sahayak.config import Settings

    # Mock settings to clear LiveKit credentials
    def mock_settings(*args, **kwargs):
        return Settings(
            livekit_url="",
            livekit_api_key="",
            livekit_api_secret="",
        )

    import jan_sahayak.routers.voice as voice_router

    monkeypatch.setattr(voice_router, "get_settings", mock_settings)

    response = await client.post(
        "/api/voice/token",
        json={"room_name": "test-room", "identity": "test-user"},
        headers=auth_headers,
    )
    assert response.status_code == 503
    assert "not configured" in response.json()["message"]


@pytest.mark.asyncio
async def test_get_livekit_token_success(client: AsyncClient, auth_headers: dict, monkeypatch):
    """Test token generator returns a signed token when credentials are set."""
    from jan_sahayak.config import Settings

    # Mock settings with dummy credentials
    def mock_settings(*args, **kwargs):
        return Settings(
            livekit_url="wss://test.livekit.cloud",
            livekit_api_key="dummy_key",
            livekit_api_secret="dummy_secret",
        )

    import jan_sahayak.routers.voice as voice_router

    monkeypatch.setattr(voice_router, "get_settings", mock_settings)

    response = await client.post(
        "/api/voice/token",
        json={"room_name": "test-room", "identity": "test-user"},
        headers=auth_headers,
    )
    assert response.status_code == 200

    data = response.json()
    assert "token" in data
    assert data["server_url"] == "wss://test.livekit.cloud"
    assert len(data["token"]) > 20  # JWT tokens are long strings

