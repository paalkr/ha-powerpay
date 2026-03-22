"""Tests for PowerPay config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.data_entry_flow import FlowResultType

from custom_components.powerpay.config_flow import PowerPayConfigFlow
from custom_components.powerpay.const import (
    CONF_DEVICE_ID,
    CONF_EMAIL,
    CONF_OUTLETS,
    CONF_PASSWORD,
    CONF_SITE_ID,
)

from .conftest import MOCK_DEVICE_ID, MOCK_EMAIL, MOCK_PASSWORD, MOCK_SITE_ID, MOCK_UID


def _mock_client():
    """Create a mock API client for config flow tests."""
    client = AsyncMock()
    client.firebase_uid = MOCK_UID
    client.async_authenticate = AsyncMock()
    client.async_close = AsyncMock()
    client.async_get_sites = AsyncMock(
        return_value=[
            {"site_id": MOCK_SITE_ID, "name": "Test Harbor", "site_type_code": "harbour"},
        ]
    )
    client.async_server_action = AsyncMock(
        return_value=[
            {
                "device_id": MOCK_DEVICE_ID,
                "name": "Test Post 001",
                "description": "Dock A Post 5",
                "outlet_count": 4,
            },
        ]
    )
    return client


async def test_full_flow_success(hass):
    """Test the complete 3-step config flow."""
    flow = PowerPayConfigFlow()
    flow.hass = hass
    flow.context = {"source": "user"}

    mock_client = _mock_client()

    with (
        patch.object(flow, "_get_client", return_value=mock_client),
        patch.object(flow, "_abort_if_unique_id_configured"),
    ):
        # Step 1: Credentials
        result = await flow.async_step_user(user_input=None)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"

        result = await flow.async_step_user(
            user_input={CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: MOCK_PASSWORD}
        )
        # Should advance to site selection
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "site"

        # Step 2: Site selection
        result = await flow.async_step_site(user_input={CONF_SITE_ID: MOCK_SITE_ID})
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "device"

        # Step 3: Device + outlet selection
        result = await flow.async_step_device(
            user_input={CONF_DEVICE_ID: MOCK_DEVICE_ID, CONF_OUTLETS: [1, 3]}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_EMAIL] == MOCK_EMAIL
        assert result["data"][CONF_SITE_ID] == MOCK_SITE_ID
        assert result["data"][CONF_DEVICE_ID] == MOCK_DEVICE_ID
        assert result["data"][CONF_OUTLETS] == [1, 3]


async def test_user_flow_invalid_auth(hass):
    """Test user flow with invalid credentials."""
    from custom_components.powerpay.api import PowerPayAuthError

    flow = PowerPayConfigFlow()
    flow.hass = hass
    flow.context = {"source": "user"}

    mock_client = AsyncMock()
    mock_client.firebase_uid = None
    mock_client.async_authenticate = AsyncMock(side_effect=PowerPayAuthError("Invalid"))

    with patch.object(flow, "_get_client", side_effect=PowerPayAuthError("Invalid")):
        result = await flow.async_step_user(
            user_input={CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: "wrong"}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"]["base"] == "invalid_auth"


async def test_user_flow_cannot_connect(hass):
    """Test user flow with connection error."""
    from custom_components.powerpay.api import PowerPayConnectionError

    flow = PowerPayConfigFlow()
    flow.hass = hass
    flow.context = {"source": "user"}

    with patch.object(flow, "_get_client", side_effect=PowerPayConnectionError("Timeout")):
        result = await flow.async_step_user(
            user_input={CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: MOCK_PASSWORD}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"]["base"] == "cannot_connect"


async def test_user_flow_unknown_error(hass):
    """Test user flow with unexpected error."""
    flow = PowerPayConfigFlow()
    flow.hass = hass
    flow.context = {"source": "user"}

    with patch.object(flow, "_get_client", side_effect=RuntimeError("Something broke")):
        result = await flow.async_step_user(
            user_input={CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: MOCK_PASSWORD}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"]["base"] == "unknown"


async def test_reconfigure_flow(hass):
    """Test the reconfigure flow."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain="powerpay",
        title="Test Harbor - Test Post 001",
        data={
            CONF_EMAIL: MOCK_EMAIL,
            CONF_PASSWORD: MOCK_PASSWORD,
            CONF_SITE_ID: MOCK_SITE_ID,
            CONF_DEVICE_ID: MOCK_DEVICE_ID,
            CONF_OUTLETS: [1, 3],
        },
        unique_id=MOCK_UID,
    )
    entry.add_to_hass(hass)

    flow = PowerPayConfigFlow()
    flow.hass = hass
    flow.context = {"source": "reconfigure", "entry_id": entry.entry_id}

    mock_client = _mock_client()

    with patch.object(flow, "_get_client", return_value=mock_client):
        # Step 1: Show credentials form with current email pre-filled
        result = await flow.async_step_reconfigure(user_input=None)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reconfigure"

        # Step 2: Submit new credentials
        result = await flow.async_step_reconfigure(
            user_input={CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: "newpassword"}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reconfigure_site"

        # Step 3: Select site
        result = await flow.async_step_reconfigure_site(user_input={CONF_SITE_ID: MOCK_SITE_ID})
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reconfigure_device"

        # Step 4: Select device and outlets
        result = await flow.async_step_reconfigure_device(
            user_input={CONF_DEVICE_ID: MOCK_DEVICE_ID, CONF_OUTLETS: ["2", "4"]}
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
