"""Tests for the PowerPay API client."""

from __future__ import annotations

import re

import pytest
from aioresponses import aioresponses

from custom_components.powerpay.api import (
    PowerPayApiClient,
    PowerPayAuthError,
    PowerPayConnectionError,
)
from custom_components.powerpay.const import (
    FIREBASE_API_KEY,
    FIREBASE_AUTH_URL,
    FIREBASE_TOKEN_URL,
    POWERPAY_API_BASE,
    POWERPAY_FASTIFY_BASE,
)

from .conftest import (
    MOCK_EMAIL,
    MOCK_FIREBASE_REFRESH_RESPONSE,
    MOCK_FIREBASE_SIGN_IN_RESPONSE,
    MOCK_PASSWORD,
    MOCK_RAW_SESSION,
    MOCK_SESSION_ID,
    MOCK_UID,
)

FIREBASE_SIGN_IN_URL = f"{FIREBASE_AUTH_URL}/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
FIREBASE_REFRESH_URL = f"{FIREBASE_TOKEN_URL}?key={FIREBASE_API_KEY}"


def _endpoint(path: str) -> re.Pattern:
    """Path-anchored matcher that tolerates a trailing query string.

    aioresponses matches the exact registered URL (query included), so a bare
    URL won't match a request carrying ?expand=... — register a regex instead.
    """
    return re.compile(re.escape(path) + r"(\?.*)?$")


# REST endpoints matched by path, ignoring any query string.
SESSION_URL = _endpoint(f"{POWERPAY_API_BASE}/enduser/session")
SESSION_HISTORY_URL = _endpoint(f"{POWERPAY_API_BASE}/enduser/session/history")
SESSION_END_URL = _endpoint(f"{POWERPAY_API_BASE}/enduser/session/end")
SITES_URL = _endpoint(f"{POWERPAY_API_BASE}/enduser/sites")
PURCHASES_URL = _endpoint(f"{POWERPAY_API_BASE}/enduser/purchases")
USER_PRIVILEGES_URL = _endpoint(f"{POWERPAY_FASTIFY_BASE}/user-privileges/list")


@pytest.fixture
def api_client():
    """Create an API client for testing."""
    return PowerPayApiClient(email=MOCK_EMAIL, password=MOCK_PASSWORD)


@pytest.fixture
def authed_client():
    """A client with a valid, non-expiring token so no re-auth is triggered."""
    client = PowerPayApiClient(email=MOCK_EMAIL, password=MOCK_PASSWORD)
    client._firebase_id_token = "mock_token"
    client._firebase_uid = MOCK_UID
    client._firebase_token_expires = 9999999999
    return client


# aiohttp creates a cleanup thread on session close that the HA test framework
# flags as a lingering thread. This is harmless. Override the verify_cleanup
# fixture for this module to allow it.
@pytest.fixture(autouse=True)
def _skip_thread_check(monkeypatch):
    """Disable the HA thread check for API tests (aiohttp cleanup threads)."""
    import threading

    original_enumerate = threading.enumerate
    monkeypatch.setattr(
        threading,
        "enumerate",
        lambda: [
            t
            for t in original_enumerate()
            if not t.name.startswith("Thread-") or "_run_safe_shutdown_loop" not in t.name
        ],
    )


class TestFirebaseAuth:
    """Tests for Firebase authentication."""

    @pytest.mark.asyncio
    async def test_sign_in_success(self):
        """Test Firebase sign-in with a mock session (no real aiohttp session)."""
        from unittest.mock import AsyncMock, MagicMock

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=MOCK_FIREBASE_SIGN_IN_RESPONSE)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.closed = False

        client = PowerPayApiClient(email=MOCK_EMAIL, password=MOCK_PASSWORD, session=mock_session)
        await client._async_firebase_sign_in()

        assert client._firebase_id_token == "mock_id_token_12345"
        assert client._firebase_refresh_token == "mock_refresh_token_12345"
        assert client._firebase_uid == MOCK_UID

    @pytest.mark.asyncio
    async def test_sign_in_invalid_credentials(self, api_client: PowerPayApiClient):
        with aioresponses() as m:
            m.post(
                re.compile(r".*/accounts:signInWithPassword.*"),
                status=400,
                payload={"error": {"message": "INVALID_LOGIN_CREDENTIALS"}},
            )
            with pytest.raises(PowerPayAuthError, match="INVALID_LOGIN_CREDENTIALS"):
                await api_client._async_firebase_sign_in()

    @pytest.mark.asyncio
    async def test_token_refresh_success(self, api_client: PowerPayApiClient):
        api_client._firebase_refresh_token = "old_refresh_token"

        with aioresponses() as m:
            m.post(
                re.compile(r".*/token.*"),
                payload=MOCK_FIREBASE_REFRESH_RESPONSE,
            )
            await api_client._async_firebase_refresh()

            assert api_client._firebase_id_token == "mock_refreshed_id_token"
            assert api_client._firebase_refresh_token == "mock_refreshed_refresh_token"

    @pytest.mark.asyncio
    async def test_token_refresh_no_refresh_token(self, api_client: PowerPayApiClient):
        with pytest.raises(PowerPayAuthError, match="No refresh token"):
            await api_client._async_firebase_refresh()


class TestUnwrap:
    """Tests for the response unwrap helper."""

    def test_python_list_passthrough(self):
        data = [{"session_id": "1"}, {"session_id": "2"}]
        assert PowerPayApiClient._unwrap(data) == data

    def test_python_dict_passthrough(self):
        data = {"session_id": "abc", "energy": 100}
        assert PowerPayApiClient._unwrap(data) == data

    def test_fastify_ag_grid_unwrap(self):
        data = {
            "success": True,
            "rowIdKey": "id",
            "data": {"rowData": [{"id": 1}], "rowCount": 1},
        }
        assert PowerPayApiClient._unwrap(data) == [{"id": 1}]

    def test_fastify_empty_ag_grid(self):
        data = {"success": True, "data": {"rowData": [], "rowCount": 0}}
        assert PowerPayApiClient._unwrap(data) == []


class TestRestTransport:
    """Tests for the REST transport (async_server_action)."""

    @pytest.mark.asyncio
    async def test_python_get_returns_bare_json(self, authed_client: PowerPayApiClient):
        with aioresponses() as m:
            m.get(SESSION_URL, payload=[{"id": 1}])
            result = await authed_client.async_server_action(
                api_name="python", endpoint="session", method="GET"
            )
            assert result == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_python_uses_token_header(self, authed_client: PowerPayApiClient):
        captured = {}

        with aioresponses() as m:
            m.get(SESSION_URL, payload=[])
            await authed_client.async_server_action(
                api_name="python", endpoint="session", method="GET"
            )
            # aioresponses records the request; pull the headers it saw.
            (req_key, calls) = next(iter(m.requests.items()))
            captured = calls[0].kwargs["headers"]
        assert captured["token"] == "mock_token"
        assert "Authorization" not in captured

    @pytest.mark.asyncio
    async def test_fastify_uses_bearer_and_unwraps(self, authed_client: PowerPayApiClient):
        with aioresponses() as m:
            m.post(
                USER_PRIVILEGES_URL,
                payload={"success": True, "data": {"rowData": [{"id": 1}], "rowCount": 1}},
            )
            result = await authed_client.async_server_action(
                api_name="fastify",
                endpoint="list",
                method="POST",
                api_namespace_path="/user-privileges",
                body={"agGridRequest": {}},
            )
            assert result == [{"id": 1}]
            (_req_key, calls) = next(iter(m.requests.items()))
            headers = calls[0].kwargs["headers"]
        assert headers["Authorization"] == "Bearer mock_token"

    @pytest.mark.asyncio
    async def test_non_200_raises(self, authed_client: PowerPayApiClient):
        with aioresponses() as m:
            m.get(SESSION_URL, status=500, body="boom")
            with pytest.raises(PowerPayConnectionError):
                await authed_client.async_server_action(
                    api_name="python", endpoint="session", method="GET"
                )

    @pytest.mark.asyncio
    async def test_401_triggers_reauth_and_retry(self, authed_client: PowerPayApiClient):
        with aioresponses() as m:
            # First call rejected, re-auth via Firebase, retry succeeds.
            m.get(SESSION_URL, status=401)
            m.post(
                re.compile(r".*/accounts:signInWithPassword.*"),
                payload=MOCK_FIREBASE_SIGN_IN_RESPONSE,
            )
            m.get(SESSION_URL, payload=[{"id": 1}])
            result = await authed_client.async_server_action(
                api_name="python", endpoint="session", method="GET"
            )
            assert result == [{"id": 1}]


class TestHighLevelMethods:
    """Tests for the high-level API methods over the REST transport."""

    @pytest.mark.asyncio
    async def test_get_active_sessions(self, authed_client: PowerPayApiClient):
        with aioresponses() as m:
            m.get(SESSION_URL, payload=[MOCK_RAW_SESSION])
            result = await authed_client.async_get_active_sessions()
            assert len(result) == 1
            assert result[0]["session_id"] == MOCK_SESSION_ID

    @pytest.mark.asyncio
    async def test_get_active_sessions_empty(self, authed_client: PowerPayApiClient):
        with aioresponses() as m:
            m.get(SESSION_URL, payload=[])
            result = await authed_client.async_get_active_sessions()
            assert result == []

    @pytest.mark.asyncio
    async def test_get_sites(self, authed_client: PowerPayApiClient):
        with aioresponses() as m:
            m.get(SITES_URL, payload=[{"site_id": "a"}, {"site_id": "b"}])
            result = await authed_client.async_get_sites()
            assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_session_history(self, authed_client: PowerPayApiClient):
        with aioresponses() as m:
            m.get(SESSION_HISTORY_URL, payload=[MOCK_RAW_SESSION])
            result = await authed_client.async_get_session_history(limit=100)
            assert len(result) == 1
            assert result[0]["session_id"] == MOCK_SESSION_ID

    @pytest.mark.asyncio
    async def test_end_session(self, authed_client: PowerPayApiClient):
        with aioresponses() as m:
            m.put(SESSION_END_URL, payload={"success": True})
            result = await authed_client.async_end_session(MOCK_SESSION_ID)
            assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_purchases_via_server_action(self, authed_client: PowerPayApiClient):
        with aioresponses() as m:
            m.get(PURCHASES_URL, payload=[{"currency": "NOK"}])
            result = await authed_client.async_server_action(
                api_name="python",
                endpoint="purchases",
                method="GET",
                query_params={"limit": "20"},
            )
            assert result == [{"currency": "NOK"}]


class TestFullAuth:
    """Tests for the authentication flow."""

    @pytest.mark.asyncio
    async def test_authenticate_signs_in(self, api_client: PowerPayApiClient):
        with aioresponses() as m:
            m.post(
                re.compile(r".*/accounts:signInWithPassword.*"),
                payload=MOCK_FIREBASE_SIGN_IN_RESPONSE,
            )
            await api_client.async_authenticate()
            assert api_client._firebase_uid == MOCK_UID
            assert api_client._firebase_id_token == "mock_id_token_12345"
            await api_client.async_close()

    def test_owns_session_default(self):
        """Client without a provided session should own its created session."""
        client = PowerPayApiClient(email=MOCK_EMAIL, password=MOCK_PASSWORD)
        assert client._owns_session is True

    def test_does_not_own_provided_session(self):
        """Client with a provided session should not own it."""
        from unittest.mock import MagicMock

        mock_session = MagicMock()
        client = PowerPayApiClient(email=MOCK_EMAIL, password=MOCK_PASSWORD, session=mock_session)
        assert client._owns_session is False
