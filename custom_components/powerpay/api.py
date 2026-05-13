"""PowerPay API client.

Handles Firebase authentication, Next.js Server Action discovery,
and data fetching through the PowerPay web application.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import time
from typing import Any

import aiohttp

from .const import (
    API_TIMEOUT,
    FIREBASE_API_KEY,
    FIREBASE_AUTH_URL,
    FIREBASE_TOKEN_URL,
    POWERPAY_BASE_URL,
    POWERPAY_HOME_URL,
    POWERPAY_LOGIN_URL,
    TOKEN_REFRESH_BUFFER,
)

_LOGGER = logging.getLogger(__name__)

# Regex to find Server Action IDs in Next.js flight data.
# Action IDs are 40-50 char hex strings used as server references.
ACTION_ID_PATTERN = re.compile(r'"([0-9a-f]{40,50})"')

# Named createServerReference calls expose both the action ID and the function
# name from the original module. The API gateway is exported as "default";
# the listed helper names belong to the client-side Stripe-session
# encryption helpers and must not be used as the gateway.
NAMED_ACTION_REF_PATTERN = re.compile(
    r'createServerReference\)\("([0-9a-f]{40,50})"[^)]*?,\s*"([A-Za-z_$][\w$]*)"\s*\)'
)
GATEWAY_ACTION_NAME = "default"
HELPER_ACTION_NAMES = frozenset(
    {
        "serverEncryptData",
        "serverDecryptData",
        "serverCreateEncryptedPayload",
        "serverDecryptPayload",
    }
)


class PowerPayAuthError(Exception):
    """Raised when authentication fails."""


class PowerPayConnectionError(Exception):
    """Raised when connection to PowerPay fails."""


class PowerPayActionIdError(Exception):
    """Raised when the Server Action ID cannot be discovered."""


class PowerPayApiClient:
    """Client for the PowerPay API.

    PowerPay has no public REST API. All data flows through Next.js Server Actions
    with deployment-specific action IDs. This client handles:
    1. Firebase authentication (sign-in + token refresh)
    2. Cookie-based session management
    3. Dynamic Server Action ID discovery
    4. RSC flight stream response parsing
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
        self._action_id: str | None = None

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
        """Perform full authentication: Firebase sign-in + cookie login + action ID discovery."""
        await self._async_firebase_sign_in()
        await self._async_login_cookies()
        await self._async_discover_action_id()

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

    async def _async_login_cookies(self) -> None:
        """Call /api/login to set server-side session cookies."""
        if not self._firebase_id_token:
            raise PowerPayAuthError("No Firebase ID token available")

        session = await self._ensure_session()
        headers = {"Authorization": f"Bearer {self._firebase_id_token}"}

        try:
            async with session.get(POWERPAY_LOGIN_URL, headers=headers) as resp:
                data = await resp.json()
                if resp.status != 200 or not data.get("success"):
                    _LOGGER.error("Cookie login failed: %s", data)
                    raise PowerPayAuthError(
                        f"Cookie login failed: {data.get('message', 'Unknown error')}"
                    )
                _LOGGER.debug("Cookie login successful, cookies set")
        except aiohttp.ClientError as err:
            raise PowerPayConnectionError(f"Cannot connect to PowerPay: {err}") from err

    async def _async_discover_action_id(self) -> None:
        # The bundle declares several named createServerReference calls. The
        # API gateway is exported as "default"; sibling refs named
        # serverEncryptData / serverDecryptData / serverCreateEncryptedPayload
        # / serverDecryptPayload wrap client-side Stripe-session encryption
        # helpers and must not be used. Read names alongside IDs to pick right.
        session = await self._ensure_session()

        try:
            async with session.get(POWERPAY_HOME_URL) as resp:
                if resp.status != 200:
                    _LOGGER.error("Failed to fetch home page: status=%d", resp.status)
                    raise PowerPayActionIdError(f"Failed to fetch home page: {resp.status}")
                html = await resp.text()
        except aiohttp.ClientError as err:
            raise PowerPayConnectionError(
                f"Cannot fetch home page for action ID discovery: {err}"
            ) from err

        js_urls = set(re.findall(r'static/chunks/[^\s"\\]+\.js', html))
        _LOGGER.debug("Found %d JS chunk URLs to search", len(js_urls))

        named_refs: list[tuple[str, str]] = []
        for js_url in sorted(js_urls):
            full_url = f"{POWERPAY_BASE_URL}/_next/{js_url.split('?')[0]}"
            try:
                async with session.get(full_url) as resp:
                    if resp.status != 200:
                        continue
                    js_content = await resp.text()
                    if "createServerReference" not in js_content:
                        continue
                    named_refs.extend(self._extract_named_action_refs(js_content))
            except aiohttp.ClientError:
                continue

        gateway_id = self._pick_gateway_action_id(named_refs)
        if gateway_id:
            self._action_id = gateway_id
            _LOGGER.debug(
                "Discovered API gateway action ID %s from %d named refs",
                self._action_id,
                len(named_refs),
            )
            return

        # Fallback: legacy HTML hex scan, filtering out known helper IDs we
        # collected from the chunks. Keeps discovery alive if PowerPay renames
        # the gateway export, but stops picking up the encryption helpers.
        helper_ids = {action_id for action_id, name in named_refs if name in HELPER_ACTION_NAMES}
        html_ids = [aid for aid in self._extract_action_ids_from_html(html) if aid not in helper_ids]
        if html_ids:
            self._action_id = html_ids[0]
            _LOGGER.debug(
                "Discovered action ID %s from HTML fallback (excluded %d helper IDs)",
                self._action_id,
                len(helper_ids),
            )
            return

        raise PowerPayActionIdError("Could not discover Server Action ID")

    @staticmethod
    def _extract_named_action_refs(js_content: str) -> list[tuple[str, str]]:
        return list(dict.fromkeys(NAMED_ACTION_REF_PATTERN.findall(js_content)))

    @staticmethod
    def _pick_gateway_action_id(refs: list[tuple[str, str]]) -> str | None:
        for action_id, name in refs:
            if name == GATEWAY_ACTION_NAME:
                return action_id
        for action_id, name in refs:
            if name not in HELPER_ACTION_NAMES:
                return action_id
        return None

    def _extract_action_ids_from_html(self, html: str) -> list[str]:
        """Extract Server Action IDs from inline Next.js flight data."""
        action_ids = []

        # Find all __next_f.push calls and extract string content
        push_pattern = re.compile(
            r'self\.__next_f\.push\(\[[\d]+,"([^"]*(?:\\.[^"]*)*)"\]', re.DOTALL
        )
        for match in push_pattern.finditer(html):
            chunk = match.group(1)
            # Unescape the string
            with contextlib.suppress(UnicodeDecodeError, ValueError):
                chunk = chunk.encode().decode("unicode_escape")

            # Check if the chunk itself is an action ID
            stripped = chunk.strip()
            if self._is_action_id(stripped):
                action_ids.append(stripped)
                continue

            # Look for quoted action IDs within the chunk
            candidates = ACTION_ID_PATTERN.findall(chunk)
            for candidate in candidates:
                if self._is_action_id(candidate):
                    action_ids.append(candidate)

        # Also search the raw HTML for hex strings that look like action IDs
        # (they may appear outside __next_f.push in inline scripts)
        if not action_ids:
            for candidate in ACTION_ID_PATTERN.findall(html):
                if self._is_action_id(candidate):
                    action_ids.append(candidate)

        return list(dict.fromkeys(action_ids))  # deduplicate preserving order

    @staticmethod
    def _is_action_id(s: str) -> bool:
        """Check if a string looks like a Server Action ID."""
        return 40 <= len(s) <= 50 and all(c in "0123456789abcdef" for c in s)

    async def _async_ensure_authenticated(self) -> None:
        """Ensure we have a valid authentication state."""
        if not self._firebase_id_token:
            await self.async_authenticate()
            return

        # Refresh Firebase token if approaching expiry
        if time.time() > self._firebase_token_expires - TOKEN_REFRESH_BUFFER:
            _LOGGER.debug("Firebase token approaching expiry, refreshing")
            await self._async_firebase_refresh()
            await self._async_login_cookies()

        # Ensure action ID is available
        if not self._action_id:
            await self._async_discover_action_id()

    async def async_server_action(
        self,
        api_name: str,
        endpoint: str,
        method: str = "GET",
        body: dict | None = None,
        api_namespace_path: str = "/enduser",
        query_params: dict[str, str] | None = None,
        other_options: dict | None = None,
    ) -> Any:
        """Execute a Next.js Server Action call."""
        await self._async_ensure_authenticated()
        session = await self._ensure_session()

        payload = [
            {
                "apiName": api_name,
                "endpoint": endpoint,
                "method": method,
                "body": body,
                "apiNamespacePath": api_namespace_path,
                "queryParams": query_params or {},
            }
        ]
        if other_options:
            payload[0]["otherOptions"] = other_options

        headers = {
            "Accept": "text/x-component",
            "Content-Type": "text/plain;charset=UTF-8",
            "next-action": self._action_id,
        }

        try:
            async with session.post(
                POWERPAY_HOME_URL, headers=headers, data=json.dumps(payload)
            ) as resp:
                if resp.status == 404:
                    # Likely a new deployment, re-discover action ID
                    _LOGGER.warning("Server Action returned 404, re-discovering action ID")
                    self._action_id = None
                    await self._async_discover_action_id()
                    return await self.async_server_action(
                        api_name,
                        endpoint,
                        method,
                        body,
                        api_namespace_path,
                        query_params,
                        other_options,
                    )

                if resp.status in (401, 403):
                    _LOGGER.warning("Server Action returned %d, re-authenticating", resp.status)
                    await self.async_authenticate()
                    return await self.async_server_action(
                        api_name,
                        endpoint,
                        method,
                        body,
                        api_namespace_path,
                        query_params,
                        other_options,
                    )

                response_text = await resp.text()

                if resp.status != 200:
                    _LOGGER.error(
                        "Server Action failed: status=%d, body=%s",
                        resp.status,
                        response_text[:500],
                    )
                    raise PowerPayConnectionError(f"Server Action failed with status {resp.status}")

                return self._parse_rsc_response(response_text)

        except aiohttp.ClientError as err:
            raise PowerPayConnectionError(f"Server Action request failed: {err}") from err

    def _parse_rsc_response(self, text: str) -> Any:
        """Parse an RSC flight stream response to extract the data payload.

        RSC flight format has lines like:
        0:{"a":"$@1","f":"","b":"..."}  (metadata, references line 1)
        1:{"status":200,"message":"Success","data":[...]}  (actual data)

        The actual API response is in the line referenced by the metadata's "$@N".
        """
        lines = text.strip().split("\n")

        # First pass: find the data line (usually line index 1)
        # The metadata line (index 0) contains "$@N" referencing the data line
        parsed_lines: dict[str, Any] = {}
        for line in lines:
            colon_idx = line.find(":")
            if colon_idx == -1:
                continue
            idx_str = line[:colon_idx]
            payload_str = line[colon_idx + 1 :]
            try:
                parsed_lines[idx_str] = json.loads(payload_str)
            except (json.JSONDecodeError, ValueError):
                continue

        # Strategy 1: Follow the metadata reference
        meta = parsed_lines.get("0")
        if isinstance(meta, dict) and "a" in meta:
            ref = meta["a"]
            if isinstance(ref, str) and ref.startswith("$@"):
                ref_idx = ref[2:]
                data_line = parsed_lines.get(ref_idx)
                if data_line is not None:
                    return self._unwrap_api_response(data_line)

        # Strategy 2: Find the line with actual data content
        for _idx, parsed in sorted(parsed_lines.items()):
            result = self._unwrap_api_response(parsed)
            if result is not None:
                return result

        _LOGGER.warning("Could not parse RSC response: %s", text[:500])
        return None

    def _unwrap_api_response(self, data: Any) -> Any:
        """Unwrap an API response, handling the status/data wrapper."""
        if isinstance(data, dict):
            # PowerPay wraps responses in {"status": 200, "data": ...}
            if "status" in data and "data" in data:
                inner = data["data"]
                # ag-Grid responses have nested data
                if isinstance(inner, dict) and "rowData" in inner:
                    return inner.get("rowData", [])
                return inner
            # Direct data objects
            if any(key in data for key in ("session_id", "site_id", "rowData", "rowCount")):
                return data

        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data

        return None

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
