"""Tests for PowerPay switch entities."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from custom_components.powerpay.api import PowerPayConnectionError
from custom_components.powerpay.data import PowerPayData
from custom_components.powerpay.switch import PowerPayOutletSwitch

from .conftest import MOCK_DEVICE_ID, MOCK_SESSION_ID


class MockCoordinator:
    """Minimal coordinator mock for switch tests."""

    def __init__(self, data: PowerPayData):
        self.data = data
        self.last_update_success = True
        self.async_request_refresh = AsyncMock()

    def async_add_listener(self, callback):
        return lambda: None


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.async_end_session = AsyncMock(return_value={"success": True})
    client.async_start_session = AsyncMock(return_value="new-session-id-1234")
    return client


class TestOutletSwitch:
    def test_is_on_with_active_session(self, mock_powerpay_data, mock_client):
        coordinator = MockCoordinator(mock_powerpay_data)
        switch = PowerPayOutletSwitch(coordinator, mock_client, MOCK_DEVICE_ID, 3)
        assert switch.is_on is True

    def test_is_off_no_session(self, mock_client):
        coordinator = MockCoordinator(PowerPayData())
        switch = PowerPayOutletSwitch(coordinator, mock_client, MOCK_DEVICE_ID, 3)
        assert switch.is_on is False

    @pytest.mark.asyncio
    async def test_turn_off(self, mock_powerpay_data, mock_client):
        coordinator = MockCoordinator(mock_powerpay_data)
        switch = PowerPayOutletSwitch(coordinator, mock_client, MOCK_DEVICE_ID, 3)

        await switch.async_turn_off()

        mock_client.async_end_session.assert_called_once_with(MOCK_SESSION_ID)
        coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_turn_off_no_session(self, mock_client):
        coordinator = MockCoordinator(PowerPayData())
        switch = PowerPayOutletSwitch(coordinator, mock_client, MOCK_DEVICE_ID, 3)

        await switch.async_turn_off()
        mock_client.async_end_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_turn_on(self, mock_client):
        coordinator = MockCoordinator(PowerPayData())
        switch = PowerPayOutletSwitch(coordinator, mock_client, MOCK_DEVICE_ID, 3)

        await switch.async_turn_on()

        mock_client.async_start_session.assert_called_once_with(
            device_id=MOCK_DEVICE_ID, outlet_index=3
        )
        coordinator.async_request_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_turn_on_already_active(self, mock_powerpay_data, mock_client):
        coordinator = MockCoordinator(mock_powerpay_data)
        switch = PowerPayOutletSwitch(coordinator, mock_client, MOCK_DEVICE_ID, 3)

        await switch.async_turn_on()
        mock_client.async_start_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_turn_off_error(self, mock_powerpay_data, mock_client):
        mock_client.async_end_session = AsyncMock(side_effect=PowerPayConnectionError("Timeout"))
        coordinator = MockCoordinator(mock_powerpay_data)
        switch = PowerPayOutletSwitch(coordinator, mock_client, MOCK_DEVICE_ID, 3)

        with pytest.raises(PowerPayConnectionError):
            await switch.async_turn_off()
