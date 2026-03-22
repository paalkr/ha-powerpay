"""Tests for PowerPay integration setup."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from custom_components.powerpay.const import CONF_EMAIL, CONF_PASSWORD, DOMAIN

from .conftest import MOCK_EMAIL, MOCK_PASSWORD


async def test_setup_entry(hass):
    """Test integration setup."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="PowerPay Test",
        data={CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: MOCK_PASSWORD},
        unique_id="test_uid",
    )
    entry.add_to_hass(hass)

    with (
        patch("custom_components.powerpay.PowerPayApiClient") as mock_client_cls,
        patch("custom_components.powerpay.PowerPayCoordinator") as mock_coord_cls,
        patch("aiohttp.ClientSession") as mock_session_cls,
    ):
        mock_client = AsyncMock()
        mock_client.async_authenticate = AsyncMock()
        mock_client.async_close = AsyncMock()
        mock_client_cls.return_value = mock_client

        mock_coord = AsyncMock()
        mock_coord.async_config_entry_first_refresh = AsyncMock()
        mock_coord_cls.return_value = mock_coord

        mock_session = AsyncMock()
        mock_session.close = AsyncMock()
        mock_session.closed = False
        mock_session_cls.return_value = mock_session

        with patch.object(
            hass.config_entries, "async_forward_entry_setups", new_callable=AsyncMock
        ):
            from custom_components.powerpay import async_setup_entry

            result = await async_setup_entry(hass, entry)
            assert result is True
            assert DOMAIN in hass.data
            assert entry.entry_id in hass.data[DOMAIN]
