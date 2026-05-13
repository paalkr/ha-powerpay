"""Tests for the PowerPay API client."""

from __future__ import annotations

import json
import re

import pytest
from aioresponses import aioresponses

from custom_components.powerpay.api import (
    PowerPayActionIdError,
    PowerPayApiClient,
    PowerPayAuthError,
)
from custom_components.powerpay.const import (
    FIREBASE_API_KEY,
    FIREBASE_AUTH_URL,
    FIREBASE_TOKEN_URL,
    POWERPAY_HOME_URL,
    POWERPAY_LOGIN_URL,
)

from .conftest import (
    MOCK_ACTION_ID,
    MOCK_EMAIL,
    MOCK_FIREBASE_REFRESH_RESPONSE,
    MOCK_FIREBASE_SIGN_IN_RESPONSE,
    MOCK_HOME_HTML,
    MOCK_LOGIN_RESPONSE,
    MOCK_PASSWORD,
    MOCK_RAW_SESSION,
    MOCK_SESSION_ID,
    MOCK_UID,
)

FIREBASE_SIGN_IN_URL = f"{FIREBASE_AUTH_URL}/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
FIREBASE_REFRESH_URL = f"{FIREBASE_TOKEN_URL}?key={FIREBASE_API_KEY}"


@pytest.fixture
def api_client():
    """Create an API client for testing."""
    return PowerPayApiClient(email=MOCK_EMAIL, password=MOCK_PASSWORD)


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


class TestCookieLogin:
    """Tests for cookie-based login."""

    @pytest.mark.asyncio
    async def test_login_success(self, api_client: PowerPayApiClient):
        api_client._firebase_id_token = "mock_token"

        with aioresponses() as m:
            m.get(POWERPAY_LOGIN_URL, payload=MOCK_LOGIN_RESPONSE)
            await api_client._async_login_cookies()

    @pytest.mark.asyncio
    async def test_login_failure(self, api_client: PowerPayApiClient):
        api_client._firebase_id_token = "mock_token"

        with aioresponses() as m:
            m.get(
                POWERPAY_LOGIN_URL,
                status=400,
                payload={"success": False, "message": "Missing token"},
            )
            with pytest.raises(PowerPayAuthError):
                await api_client._async_login_cookies()

    @pytest.mark.asyncio
    async def test_login_no_token(self, api_client: PowerPayApiClient):
        with pytest.raises(PowerPayAuthError, match="No Firebase ID token"):
            await api_client._async_login_cookies()


class TestActionIdDiscovery:
    """Tests for Server Action ID discovery."""

    @pytest.mark.asyncio
    async def test_discover_from_html(self, api_client: PowerPayApiClient):
        api_client._firebase_id_token = "mock_token"

        with aioresponses() as m:
            m.get(POWERPAY_HOME_URL, body=MOCK_HOME_HTML)
            await api_client._async_discover_action_id()

            assert api_client._action_id == MOCK_ACTION_ID

    @pytest.mark.asyncio
    async def test_discover_failure(self, api_client: PowerPayApiClient):
        api_client._firebase_id_token = "mock_token"

        with aioresponses() as m:
            m.get(POWERPAY_HOME_URL, body="<html><body>No actions here</body></html>")
            with pytest.raises(PowerPayActionIdError):
                await api_client._async_discover_action_id()

    def test_extract_action_ids_from_html(self, api_client: PowerPayApiClient):
        ids = api_client._extract_action_ids_from_html(MOCK_HOME_HTML)
        assert MOCK_ACTION_ID in ids

    def test_extract_action_ids_no_match(self, api_client: PowerPayApiClient):
        ids = api_client._extract_action_ids_from_html("<html>nothing</html>")
        assert ids == []

    def test_extract_named_action_refs(self, api_client: PowerPayApiClient):
        js = (
            'createServerReference)("40c329e4bb98cf12969ba03c3c2384a5e0c4caff04",'
            'o.callServer,void 0,o.findSourceMapURL,"serverEncryptData");'
            'createServerReference)("7fb4cdad5a87183902e0c34fc7dd364fce3d0690a3",'
            'o.callServer,void 0,o.findSourceMapURL,"default");'
        )
        refs = api_client._extract_named_action_refs(js)
        assert (
            "40c329e4bb98cf12969ba03c3c2384a5e0c4caff04",
            "serverEncryptData",
        ) in refs
        assert (
            "7fb4cdad5a87183902e0c34fc7dd364fce3d0690a3",
            "default",
        ) in refs

    def test_pick_gateway_prefers_default(self, api_client: PowerPayApiClient):
        refs = [
            ("40c329e4bb98cf12969ba03c3c2384a5e0c4caff04", "serverEncryptData"),
            ("7fb4cdad5a87183902e0c34fc7dd364fce3d0690a3", "default"),
            ("60f6f8cca252a02a722d3635e5246589838af09c49", "serverCreateEncryptedPayload"),
        ]
        assert (
            api_client._pick_gateway_action_id(refs)
            == "7fb4cdad5a87183902e0c34fc7dd364fce3d0690a3"
        )

    def test_pick_gateway_skips_encryption_helpers(self, api_client: PowerPayApiClient):
        refs = [
            ("40c329e4bb98cf12969ba03c3c2384a5e0c4caff04", "serverEncryptData"),
            ("40d2d22a7c5e37e3f2d2106d70669c314c7c7d3b12", "serverDecryptData"),
            ("60f6f8cca252a02a722d3635e5246589838af09c49", "serverCreateEncryptedPayload"),
            ("40997055632faa222d49a94892a23de7d5ba7e5532", "serverDecryptPayload"),
        ]
        assert api_client._pick_gateway_action_id(refs) is None

    def test_pick_gateway_falls_back_to_non_helper_name(
        self, api_client: PowerPayApiClient
    ):
        refs = [
            ("40c329e4bb98cf12969ba03c3c2384a5e0c4caff04", "serverEncryptData"),
            ("aabbccddeeff00112233445566778899aabbccddee", "someOtherAction"),
        ]
        assert (
            api_client._pick_gateway_action_id(refs)
            == "aabbccddeeff00112233445566778899aabbccddee"
        )

    @pytest.mark.asyncio
    async def test_discover_from_chunk_picks_default(self, api_client: PowerPayApiClient):
        """Primary path: chunk-based discovery picks the action named "default"."""
        api_client._firebase_id_token = "mock_token"

        gateway_id = "7fb4cdad5a87183902e0c34fc7dd364fce3d0690a3"
        encrypt_id = "40c329e4bb98cf12969ba03c3c2384a5e0c4caff04"
        chunk_url = "static/chunks/0001-deadbeef.js"
        home_with_chunk = (
            "<!DOCTYPE html><html><body>"
            f'<script src="/_next/{chunk_url}"></script>'
            f'<script>self.__next_f.push([1,"{encrypt_id}"])</script>'
            "</body></html>"
        )
        chunk_body = (
            f'createServerReference)("{encrypt_id}",'
            'o.callServer,void 0,o.findSourceMapURL,"serverEncryptData");'
            f'createServerReference)("{gateway_id}",'
            'o.callServer,void 0,o.findSourceMapURL,"default");'
        )

        with aioresponses() as m:
            m.get(POWERPAY_HOME_URL, body=home_with_chunk)
            m.get(f"https://app.powerpay.no/_next/{chunk_url}", body=chunk_body)
            await api_client._async_discover_action_id()

            assert api_client._action_id == gateway_id

    @pytest.mark.asyncio
    async def test_discover_excludes_helper_ids_from_html_fallback(
        self, api_client: PowerPayApiClient
    ):
        """Fallback path: HTML hex scan must not pick helper IDs found in chunks."""
        api_client._firebase_id_token = "mock_token"

        encrypt_id = "40c329e4bb98cf12969ba03c3c2384a5e0c4caff04"
        chunk_url = "static/chunks/0002-deadbeef.js"
        home_with_chunk = (
            "<!DOCTYPE html><html><body>"
            f'<script src="/_next/{chunk_url}"></script>'
            f'<script>self.__next_f.push([1,"{encrypt_id}"])</script>'
            "</body></html>"
        )
        chunk_body = (
            f'createServerReference)("{encrypt_id}",'
            'o.callServer,void 0,o.findSourceMapURL,"serverEncryptData");'
        )

        with aioresponses() as m:
            m.get(POWERPAY_HOME_URL, body=home_with_chunk)
            m.get(f"https://app.powerpay.no/_next/{chunk_url}", body=chunk_body)
            with pytest.raises(PowerPayActionIdError):
                await api_client._async_discover_action_id()


class TestRscParsing:
    """Tests for RSC flight stream response parsing."""

    def test_parse_real_rsc_format(self, api_client: PowerPayApiClient):
        """Test the real PowerPay RSC format with metadata line + data line."""
        rsc = '0:{"a":"$@1","f":"","b":"abc123"}\n1:{"status":200,"message":"Success","data":[{"session_id":"123"}]}\n'
        result = api_client._parse_rsc_response(rsc)
        assert result == [{"session_id": "123"}]

    def test_parse_list_response(self, api_client: PowerPayApiClient):
        rsc = '0:{"a":"$@1","f":"","b":"x"}\n1:{"status":200,"data":[{"session_id":"123","energy":100}]}\n'
        result = api_client._parse_rsc_response(rsc)
        assert result == [{"session_id": "123", "energy": 100}]

    def test_parse_ag_grid_response(self, api_client: PowerPayApiClient):
        rsc = '0:{"a":"$@1","f":"","b":"x"}\n1:{"status":200,"data":{"rowData":[{"id":1}],"rowCount":1}}\n'
        result = api_client._parse_rsc_response(rsc)
        assert result == [{"id": 1}]

    def test_parse_empty_response(self, api_client: PowerPayApiClient):
        result = api_client._parse_rsc_response("")
        assert result is None

    def test_parse_multiline_rsc(self, api_client: PowerPayApiClient):
        rsc = '0:"$Sreact.fragment"\n1:{"session_id":"abc"}\n2:null\n'
        result = api_client._parse_rsc_response(rsc)
        assert result == {"session_id": "abc"}


class TestServerAction:
    """Tests for Server Action calls."""

    @pytest.mark.asyncio
    async def test_server_action_success(self, api_client: PowerPayApiClient):
        api_client._firebase_id_token = "mock_token"
        api_client._firebase_token_expires = 9999999999
        api_client._action_id = "test_action_id_1234567890abcdef12345678"

        rsc_body = '0:{"a":"$@1","f":"","b":"x"}\n1:{"status":200,"data":[{"id":1}]}\n'
        with aioresponses() as m:
            m.post(
                POWERPAY_HOME_URL,
                body=rsc_body,
                content_type="text/x-component",
            )
            result = await api_client.async_server_action(
                api_name="python",
                endpoint="session",
                method="GET",
            )
            assert result == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_get_active_sessions(self, api_client: PowerPayApiClient):
        api_client._firebase_id_token = "mock_token"
        api_client._firebase_uid = MOCK_UID
        api_client._firebase_token_expires = 9999999999
        api_client._action_id = "test_action_id_1234567890abcdef12345678"

        sessions = [MOCK_RAW_SESSION]
        rsc_body = (
            f'0:{{"a":"$@1","f":"","b":"x"}}\n1:{{"status":200,"data":{json.dumps(sessions)}}}\n'
        )
        with aioresponses() as m:
            m.post(
                POWERPAY_HOME_URL,
                body=rsc_body,
                content_type="text/x-component",
            )
            result = await api_client.async_get_active_sessions()
            assert len(result) == 1
            assert result[0]["session_id"] == MOCK_SESSION_ID

    @pytest.mark.asyncio
    async def test_end_session(self, api_client: PowerPayApiClient):
        api_client._firebase_id_token = "mock_token"
        api_client._firebase_uid = MOCK_UID
        api_client._firebase_token_expires = 9999999999
        api_client._action_id = "test_action_id_1234567890abcdef12345678"

        rsc_body = '0:{"a":"$@1","f":"","b":"x"}\n1:{"status":200,"data":{"success":true}}\n'
        with aioresponses() as m:
            m.post(
                POWERPAY_HOME_URL,
                body=rsc_body,
                content_type="text/x-component",
            )
            result = await api_client.async_end_session(MOCK_SESSION_ID)
            assert result == {"success": True}


class TestFullAuth:
    """Tests for full authentication flow."""

    @pytest.mark.asyncio
    async def test_full_authenticate(self, api_client: PowerPayApiClient):
        with aioresponses() as m:
            m.post(
                re.compile(r".*/accounts:signInWithPassword.*"),
                payload=MOCK_FIREBASE_SIGN_IN_RESPONSE,
            )
            m.get(POWERPAY_LOGIN_URL, payload=MOCK_LOGIN_RESPONSE)
            m.get(POWERPAY_HOME_URL, body=MOCK_HOME_HTML)

            await api_client.async_authenticate()

            assert api_client._firebase_uid == MOCK_UID
            assert api_client._action_id is not None

            await api_client.async_close()
            import asyncio

            await asyncio.sleep(0.1)

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
