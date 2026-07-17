"""PowerPay API client.

Handles Firebase authentication and data fetching through PowerPay's REST API.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import aiohttp

from .const import (
    API_TIMEOUT,
    FIREBASE_API_KEY,
    FIREBASE_AUTH_URL,
    FIREBASE_TOKEN_URL,
    POWERPAY_API_BASE,
    POWERPAY_FASTIFY_BASE,
    TOKEN_REFRESH_BUFFER,
)

_LOGGER = logging.getLogger(__name__)


class PowerPayAuthError(Exception):
    """Raised when authentication fails."""


class PowerPayConnectionError(Exception):
    """Raised when connection to PowerPay fails."""


class PowerPayApiClient:
    """Client for the PowerPay API.

    PowerPay has no documented public API, but the web app talks to a REST API
    at api.powerpay.no, authenticated with the Firebase ID token. This client:
    1. Signs in with Firebase (email/password) and refreshes the token
    2. Calls the python API (api/v1, `token` header) and the fastify report API
       (report/api, Bearer auth) directly
    """

    def __init__(
        self,
        email: str,
        password: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """Initialize the API client."""
        self._email = email
        self._password = password
        self._session = session
        self._owns_session = session is None
        self._firebase_id_token: str | None = None
        self._firebase_refresh_token: str | None = None
        self._firebase_uid: str | None = None
        self._firebase_token_expires: float = 0

    @property
    def firebase_uid(self) -> str | None:
        """Return the Firebase user ID."""
        return self._firebase_uid

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar(),
                timeout=aiohttp.ClientTimeout(total=API_TIMEOUT),
            )
            self._owns_session = True
        return self._session

    async def async_authenticate(self) -> None:
        """Authenticate with Firebase (email/password sign-in).

        The REST API authenticates per-request with the Firebase ID token, so
        sign-in is all that's needed up front.
        """
        await self._async_firebase_sign_in()

    async def _async_firebase_sign_in(self) -> None:
        """Sign in with Firebase using email/password."""
        session = await self._ensure_session()
        url = f"{FIREBASE_AUTH_URL}/accounts:signInWithPassword"
        params = {"key": FIREBASE_API_KEY}
        payload = {
            "email": self._email,
            "password": self._password,
            "returnSecureToken": True,
        }

        try:
            async with session.post(url, params=params, json=payload) as resp:
                data = await resp.json()
                if resp.status != 200:
                    error_message = data.get("error", {}).get("message", "Unknown error")
                    _LOGGER.error("Firebase sign-in failed: %s", error_message)
                    raise PowerPayAuthError(f"Firebase sign-in failed: {error_message}")

                self._firebase_id_token = data["idToken"]
                self._firebase_refresh_token = data["refreshToken"]
                self._firebase_uid = data["localId"]
                self._firebase_token_expires = time.time() + int(data.get("expiresIn", 3600))
                _LOGGER.debug("Firebase sign-in successful for uid=%s", self._firebase_uid)
        except aiohttp.ClientError as err:
            raise PowerPayConnectionError(f"Cannot connect to Firebase: {err}") from err

    async def _async_firebase_refresh(self) -> None:
        """Refresh the Firebase ID token using the refresh token."""
        if not self._firebase_refresh_token:
            raise PowerPayAuthError("No refresh token available")

        session = await self._ensure_session()
        url = FIREBASE_TOKEN_URL
        params = {"key": FIREBASE_API_KEY}
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self._firebase_refresh_token,
        }

        try:
            async with session.post(url, params=params, data=payload) as resp:
                data = await resp.json()
                if resp.status != 200:
                    _LOGGER.error("Firebase token refresh failed: %s", data)
                    raise PowerPayAuthError("Firebase token refresh failed")

                self._firebase_id_token = data["id_token"]
                self._firebase_refresh_token = data["refresh_token"]
                self._firebase_uid = data["user_id"]
                self._firebase_token_expires = time.time() + int(data.get("expires_in", 3600))
                _LOGGER.debug("Firebase token refreshed successfully")
        except aiohttp.ClientError as err:
            raise PowerPayConnectionError(f"Cannot refresh Firebase token: {err}") from err

    async def _async_ensure_authenticated(self) -> None:
        """Ensure we have a valid Firebase token, refreshing if near expiry."""
        if not self._firebase_id_token:
            await self.async_authenticate()
            return

        if time.time() > self._firebase_token_expires - TOKEN_REFRESH_BUFFER:
            _LOGGER.debug("Firebase token approaching expiry, refreshing")
            await self._async_firebase_refresh()

    async def async_server_action(
        self,
        api_name: str,
        endpoint: str,
        method: str = "GET",
        body: dict | None = None,
        api_namespace_path: str = "/enduser",
        query_params: dict[str, str] | None = None,
        other_options: dict | None = None,
        _retry: bool = True,
    ) -> Any:
        """Call a PowerPay REST API endpoint.

        PowerPay's web app talks to two backends, authenticated with the
        Firebase ID token:
        - the "python" API at api/v1 (token in a `token` header)
        - the "fastify" report API at report/api (Bearer auth)

        The request URL is ``{base}{api_namespace_path}/{endpoint}`` plus query
        params. ``other_options`` is accepted for call-site compatibility but no
        longer maps to anything (it configured the old server-action proxy).
        """
        await self._async_ensure_authenticated()
        session = await self._ensure_session()

        if api_name == "fastify":
            base = POWERPAY_FASTIFY_BASE
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._firebase_id_token}",
            }
        else:
            base = POWERPAY_API_BASE
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "token": self._firebase_id_token or "",
            }

        url = f"{base}{api_namespace_path}"
        if endpoint:
            url += f"/{endpoint}"

        params = {k: str(v) for k, v in (query_params or {}).items() if v is not None}

        try:
            async with session.request(
                method,
                url,
                headers=headers,
                params=params,
                json=body if body is not None else None,
            ) as resp:
                if resp.status in (401, 403) and _retry:
                    _LOGGER.warning("API returned %d, re-authenticating", resp.status)
                    await self.async_authenticate()
                    return await self.async_server_action(
                        api_name,
                        endpoint,
                        method,
                        body,
                        api_namespace_path,
                        query_params,
                        other_options,
                        _retry=False,
                    )

                response_text = await resp.text()

                if resp.status != 200:
                    _LOGGER.error(
                        "API call failed: status=%d, url=%s, body=%s",
                        resp.status,
                        url,
                        response_text[:500],
                    )
                    raise PowerPayConnectionError(f"API call failed with status {resp.status}")

                if not response_text:
                    return None

                try:
                    data = json.loads(response_text)
                except (json.JSONDecodeError, ValueError) as err:
                    raise PowerPayConnectionError(f"Could not parse API response: {err}") from err

                return self._unwrap(data)

        except aiohttp.ClientError as err:
            raise PowerPayConnectionError(f"API request failed: {err}") from err

    @staticmethod
    def _unwrap(data: Any) -> Any:
        """Unwrap the fastify ag-Grid envelope; pass python responses through.

        The python API (api/v1) returns bare JSON (list or dict). The fastify
        report API wraps ag-Grid results as
        ``{"success": ..., "rowIdKey": ..., "data": {"rowData": [...], "rowCount": N}}``.
        """
        if isinstance(data, dict):
            inner = data.get("data")
            if isinstance(inner, dict) and "rowData" in inner:
                return inner.get("rowData", [])
        return data

    # ---- High-level API methods ----

    async def async_get_active_sessions(self) -> list[dict]:
        """Get current (non-archived) sessions for the user.

        The /enduser/session endpoint returns only current sessions.
        A session is considered active if it's not archived, regardless
        of end_ts (which is a scheduled end time, not the actual end).
        """
        result = await self.async_server_action(
            api_name="python",
            endpoint="session",
            method="GET",
            api_namespace_path="/enduser",
            query_params={"expand": "photo"},
            other_options={"cache": "no-store"},
        )

        if result is None:
            return []

        if isinstance(result, list):
            return [s for s in result if isinstance(s, dict)]
        if isinstance(result, dict) and "session_id" in result:
            return [result]
        return []

    async def async_get_session_detail(self, session_id: str) -> dict | None:
        """Get detailed session info including consumption data."""
        result = await self.async_server_action(
            api_name="python",
            endpoint="session",
            method="GET",
            api_namespace_path="/enduser",
            query_params={
                "session_id": session_id,
                "include_details": "true",
            },
        )

        if isinstance(result, dict):
            return result
        if isinstance(result, list) and result:
            return result[0]
        return None

    async def async_get_session_consumption(self, session_id: str) -> list[dict]:
        """Get hourly consumption data for a session."""
        result = await self.async_server_action(
            api_name="python",
            endpoint="session/consumption",
            method="GET",
            api_namespace_path="/enduser",
            query_params={"session_id": session_id},
        )

        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "data" in result:
            return result["data"]
        return []

    async def async_get_sites(self) -> list[dict]:
        """Get all available sites."""
        result = await self.async_server_action(
            api_name="python",
            endpoint="sites",
            method="GET",
            api_namespace_path="/enduser",
            other_options={
                "fetchCacheRevalidationTime": 300,
                "isPublicEndpoint": True,
            },
        )

        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "data" in result:
            return result["data"]
        return []

    async def async_get_session_history(self, limit: int = 100) -> list[dict]:
        """Get session history (completed sessions)."""
        result = await self.async_server_action(
            api_name="python",
            endpoint="session/history",
            method="GET",
            api_namespace_path="/enduser",
            query_params={"limit": str(limit)},
            other_options={"cache": "no-store"},
        )

        if isinstance(result, list):
            return [s for s in result if isinstance(s, dict)]
        return []

    async def async_get_user_privileges(self) -> dict | None:
        """Get user privileges from the fastify backend."""
        result = await self.async_server_action(
            api_name="fastify",
            endpoint="list",
            method="POST",
            body={
                "agGridRequest": {
                    "startRow": 0,
                    "endRow": 1000,
                    "rowGroupCols": [],
                    "valueCols": [],
                    "pivotCols": [],
                    "pivotMode": False,
                    "groupKeys": [],
                    "filterModel": {
                        "userPrivilege.userId": {
                            "filterType": "text",
                            "type": "equals",
                            "filter": self._firebase_uid,
                        }
                    },
                    "sortModel": [],
                }
            },
            api_namespace_path="/user-privileges",
        )

        return result

    async def async_start_session(
        self,
        device_id: str,
        outlet_index: int,
        cost_limit: int = 1000000000,
        energy_limit: int = 100000000,
        session_end: int | None = None,
    ) -> str | None:
        """Start a new session on a device outlet.

        Args:
            device_id: The device UUID.
            outlet_index: The outlet number (1-4).
            cost_limit: Max cost in øre (default ~unlimited).
            energy_limit: Max energy in Wh (default ~unlimited).
            session_end: End timestamp in ms (default 10 years from now).

        Returns:
            The new session ID if successful, None otherwise.
        """
        if session_end is None:
            session_end = int((time.time() + 10 * 365.25 * 24 * 3600) * 1000)

        result = await self.async_server_action(
            api_name="python",
            endpoint="session",
            method="POST",
            body={
                "device_id": device_id,
                "outlet_index": outlet_index,
                "session_end": session_end,
                "energy_limit": energy_limit,
                "cost_limit": cost_limit,
            },
            api_namespace_path="/enduser",
        )

        if isinstance(result, dict):
            session_id = result.get("session_id")
            if session_id:
                _LOGGER.info("Started session: %s", session_id)
                return session_id

        _LOGGER.warning("Session start did not return a session ID")
        return None

    async def async_end_session(self, session_id: str) -> dict | None:
        """End an active session (turns off the outlet)."""
        result = await self.async_server_action(
            api_name="python",
            endpoint=f"session/end?session_id={session_id}",
            method="PUT",
            api_namespace_path="/enduser",
        )
        return result

    async def async_close(self) -> None:
        """Close the API client session."""
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()
