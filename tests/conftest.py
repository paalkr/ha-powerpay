"""Shared fixtures for PowerPay tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.powerpay.const import CONF_EMAIL, CONF_PASSWORD
from custom_components.powerpay.data import PowerPayData, PowerPayDeviceData, PowerPaySessionData

MOCK_EMAIL = "test@example.com"
MOCK_PASSWORD = "testpassword123"
MOCK_UID = "test_firebase_uid_12345"
MOCK_DEVICE_ID = "04bb17e6-1264-4c11-bace-547f6412ae9b"
MOCK_SESSION_ID = "44ffee54-c8e4-4c30-a7ed-fc0c94989cde"
MOCK_SITE_ID = "de9553a0-411e-4d0e-86fb-b7737562809b"


@pytest.fixture
def mock_config_entry_data() -> dict:
    """Return mock config entry data."""
    return {
        CONF_EMAIL: MOCK_EMAIL,
        CONF_PASSWORD: MOCK_PASSWORD,
    }


@pytest.fixture
def mock_session_data() -> PowerPaySessionData:
    """Return a mock PowerPay session."""
    return PowerPaySessionData(
        session_id=MOCK_SESSION_ID,
        device_id=MOCK_DEVICE_ID,
        outlet_index=3,
        site_name="Test Harbor",
        device_name="Test Post 001",
        device_description="Dock A Post 5",
        start_ts=1757618021694,
        energy_kwh=29.68,  # From API meter
        calculated_energy_kwh=30.12,  # power * duration
        cost_nok=56.02,  # 30.12 * 1.86 (based on calculated energy)
        billed_cost_nok=53.94,  # From PowerPay price_basis (per whole kWh)
        duration_seconds=16550269.984,
        current_power_w=1060,
        price_per_kwh=1.86,
        currency="NOK",
        is_active=True,
        cost_limit_nok=500.0,
        energy_limit_kwh=100000.0,
        site_id=MOCK_SITE_ID,
        latitude=59.835915,
        longitude=10.47653,
    )


@pytest.fixture
def mock_device_data() -> PowerPayDeviceData:
    """Return a mock PowerPay device."""
    return PowerPayDeviceData(
        device_id=MOCK_DEVICE_ID,
        name="Test Post 001",
        description="Dock A Post 5",
        site_id=MOCK_SITE_ID,
        site_name="Test Harbor",
        outlet_count=4,
        latitude=59.835915,
        longitude=10.47653,
        max_power=3680,
        max_current=16,
        voltage=230,
        phases=1,
    )


@pytest.fixture
def mock_powerpay_data(
    mock_session_data: PowerPaySessionData,
    mock_device_data: PowerPayDeviceData,
) -> PowerPayData:
    """Return mock PowerPay data."""
    return PowerPayData(
        sessions=[mock_session_data],
        devices={mock_device_data.device_id: mock_device_data},
        firebase_uid=MOCK_UID,
    )


@pytest.fixture
def mock_api_client():
    """Return a mocked PowerPay API client."""
    with patch("custom_components.powerpay.api.PowerPayApiClient", autospec=True) as mock_cls:
        client = mock_cls.return_value
        client.async_authenticate = AsyncMock()
        client.async_close = AsyncMock()
        client.firebase_uid = MOCK_UID
        client.async_get_active_sessions = AsyncMock(return_value=[])
        client.async_get_session_detail = AsyncMock(return_value=None)
        client.async_get_session_consumption = AsyncMock(return_value=[])
        client.async_get_sites = AsyncMock(return_value=[])
        client.async_get_user_privileges = AsyncMock(return_value=None)
        client.async_end_session = AsyncMock(return_value=None)
        client.async_server_action = AsyncMock(return_value=None)
        yield client


MOCK_FIREBASE_SIGN_IN_RESPONSE = {
    "idToken": "mock_id_token_12345",
    "refreshToken": "mock_refresh_token_12345",
    "localId": MOCK_UID,
    "expiresIn": "3600",
    "email": MOCK_EMAIL,
}

MOCK_FIREBASE_REFRESH_RESPONSE = {
    "id_token": "mock_refreshed_id_token",
    "refresh_token": "mock_refreshed_refresh_token",
    "user_id": MOCK_UID,
    "expires_in": "3600",
}

MOCK_LOGIN_RESPONSE = {"success": True}

MOCK_RAW_SESSION = {
    "session_id": MOCK_SESSION_ID,
    "start_ts": 1757618021694,
    "end_ts": 2073150807000,
    "duration": 16550269984,
    "user_id": MOCK_UID,
    "device_id": MOCK_DEVICE_ID,
    "outlet_index": 3,
    "start_energy": 560648.99,
    "end_energy": 4418751.95,
    "captured_amount_value": 0,
    "power": 1043,
    "average_power": 804,
    "archived": False,
    "price_basis": {
        "amount": {"value": 630847, "currency": "NOK"},
    },
    "cost_limit": 50000,
    "energy_limit": 100000000,
    "device_details": {
        "name": "Test Post 001",
        "device_id": MOCK_DEVICE_ID,
        "site_id": MOCK_SITE_ID,
        "description": "Dock A Post 5",
        "outlet_count": 4,
        "device_properties": {
            "phases": 1,
            "voltage": 230,
            "latitude": 59.835915,
            "longitude": 10.47653,
            "max_power": 3680,
            "max_current": 16,
        },
        "outlet_properties_effective": {
            "3": {"label": "Outlet 3"},
        },
    },
    "price_set": {
        "currency": "NOK",
        "model_string": "Sesongkunde:\nPris per kWh: 1,86 kr",
        "price_structure_parameters": {},
    },
}

MOCK_CONSUMPTION_DATA = [
    {
        "ts": 1774033200000,
        "energy": 782.71,
        "ts_iso": "2026-03-20T19:00:00+00:00",
        "total_energy": 979012.43,
        "max_power_avg_5m": 1060.55,
        "max_power_avg_10m": 996.09,
        "max_power_avg_15m": 949.22,
    }
]

# Mock HTML with embedded action ID for discovery tests.
# The __next_f.push format wraps the hex ID as a quoted string inside JSON data.
MOCK_ACTION_ID = "7f4f716aab1d9072cac29ef3d3aa492b918c8d4aa3"
MOCK_HOME_HTML = (
    "<!DOCTYPE html><html><head><title>PowerPay</title></head><body>"
    '<script>self.__next_f.push([1,"' + MOCK_ACTION_ID + '"])</script>'
    "</body></html>"
)
