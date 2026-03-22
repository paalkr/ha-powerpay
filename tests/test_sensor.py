"""Tests for PowerPay sensor entities."""

from __future__ import annotations

import pytest

from custom_components.powerpay.data import PowerPayData
from custom_components.powerpay.sensor import (
    PowerPayActiveSessionsSensor,
    PowerPayBilledCostSensor,
    PowerPayCalculatedEnergySensor,
    PowerPayCostSensor,
    PowerPayDurationSensor,
    PowerPayEnergySensor,
    PowerPayMonthlyBillingSensor,
    PowerPayPowerSensor,
    PowerPayPriceSensor,
)

from .conftest import MOCK_DEVICE_ID


class MockCoordinator:
    """Minimal coordinator mock for sensor tests."""

    def __init__(self, data: PowerPayData):
        self.data = data
        self.last_update_success = True

    def async_add_listener(self, callback):
        return lambda: None


@pytest.fixture
def coordinator_with_session(mock_powerpay_data):
    return MockCoordinator(mock_powerpay_data)


@pytest.fixture
def coordinator_empty():
    return MockCoordinator(PowerPayData())


class TestPowerSensor:
    def test_value_with_session(self, coordinator_with_session):
        sensor = PowerPayPowerSensor(coordinator_with_session, MOCK_DEVICE_ID, 3)
        assert sensor.native_value == 1060

    def test_value_no_session(self, coordinator_empty):
        sensor = PowerPayPowerSensor(coordinator_empty, MOCK_DEVICE_ID, 3)
        assert sensor.native_value is None

    def test_available(self, coordinator_with_session):
        sensor = PowerPayPowerSensor(coordinator_with_session, MOCK_DEVICE_ID, 3)
        assert sensor.available is True

    def test_available_no_session(self, coordinator_empty):
        """Sensor is available but returns None when no session active."""
        sensor = PowerPayPowerSensor(coordinator_empty, MOCK_DEVICE_ID, 3)
        assert sensor.available is True
        assert sensor.native_value is None


class TestEnergySensor:
    def test_value(self, coordinator_with_session):
        sensor = PowerPayEnergySensor(coordinator_with_session, MOCK_DEVICE_ID, 3)
        assert sensor.native_value == 29.68


class TestCalculatedEnergySensor:
    def test_value(self, coordinator_with_session):
        sensor = PowerPayCalculatedEnergySensor(coordinator_with_session, MOCK_DEVICE_ID, 3)
        assert sensor.native_value == 30.12

    def test_value_no_session(self, coordinator_empty):
        sensor = PowerPayCalculatedEnergySensor(coordinator_empty, MOCK_DEVICE_ID, 3)
        assert sensor.native_value is None


class TestCostSensor:
    def test_value(self, coordinator_with_session):
        sensor = PowerPayCostSensor(coordinator_with_session, MOCK_DEVICE_ID, 3)
        assert sensor.native_value == pytest.approx(56.02, rel=0.01)

    def test_currency(self, coordinator_with_session):
        sensor = PowerPayCostSensor(coordinator_with_session, MOCK_DEVICE_ID, 3)
        assert sensor.native_unit_of_measurement == "NOK"


class TestBilledCostSensor:
    def test_value(self, coordinator_with_session):
        sensor = PowerPayBilledCostSensor(coordinator_with_session, MOCK_DEVICE_ID, 3)
        assert sensor.native_value == 53.94

    def test_value_no_session(self, coordinator_empty):
        sensor = PowerPayBilledCostSensor(coordinator_empty, MOCK_DEVICE_ID, 3)
        assert sensor.native_value is None


class TestDurationSensor:
    def test_value_hours(self, coordinator_with_session):
        sensor = PowerPayDurationSensor(coordinator_with_session, MOCK_DEVICE_ID, 3)
        # 16550269.984 seconds / 3600 = ~4597.3 hours
        assert sensor.native_value == pytest.approx(4597.3, rel=0.01)


class TestPriceSensor:
    def test_value(self, coordinator_with_session):
        sensor = PowerPayPriceSensor(coordinator_with_session, MOCK_DEVICE_ID, 3)
        assert sensor.native_value == 1.86

    def test_unit(self, coordinator_with_session):
        sensor = PowerPayPriceSensor(coordinator_with_session, MOCK_DEVICE_ID, 3)
        assert sensor.native_unit_of_measurement == "NOK/kWh"


class TestMonthlyBillingSensor:
    def test_value(self, coordinator_with_session):
        coordinator_with_session.data.monthly_billing = 1679.58
        coordinator_with_session.data.monthly_currency = "NOK"
        sensor = PowerPayMonthlyBillingSensor(coordinator_with_session, "test_entry")
        assert sensor.native_value == 1679.58
        assert sensor.native_unit_of_measurement == "NOK"

    def test_value_empty(self, coordinator_empty):
        sensor = PowerPayMonthlyBillingSensor(coordinator_empty, "test_entry")
        assert sensor.native_value == 0


class TestActiveSessionsSensor:
    def test_value(self, coordinator_with_session):
        sensor = PowerPayActiveSessionsSensor(coordinator_with_session, "test_entry")
        assert sensor.native_value == 1

    def test_value_empty(self, coordinator_empty):
        sensor = PowerPayActiveSessionsSensor(coordinator_empty, "test_entry")
        assert sensor.native_value == 0
