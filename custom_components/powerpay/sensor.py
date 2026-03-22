"""Sensor platform for PowerPay integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy, UnitOfPower, UnitOfTime

from .const import DOMAIN
from .entity import PowerPayAccountEntity, PowerPayEntity

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import PowerPayCoordinator
    from .data import PowerPaySessionData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PowerPay sensor platform."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: PowerPayCoordinator = data["coordinator"]
    device_id: str = data["device_id"]
    outlets: list[int] = data["outlets"]

    entities: list[SensorEntity] = []

    # Create static entities for each configured outlet
    for outlet in outlets:
        entities.extend(
            [
                PowerPayPowerSensor(coordinator, device_id, outlet),
                PowerPayEnergySensor(coordinator, device_id, outlet),
                PowerPayCostSensor(coordinator, device_id, outlet),
                PowerPayBilledCostSensor(coordinator, device_id, outlet),
                PowerPayCalculatedEnergySensor(coordinator, device_id, outlet),
                PowerPayDurationSensor(coordinator, device_id, outlet),
                PowerPayPriceSensor(coordinator, device_id, outlet),
            ]
        )

    # Account-level sensors
    entities.extend(
        [
            PowerPayMonthlyBillingSensor(coordinator, entry.entry_id),
            PowerPayUnbilledConsumptionSensor(coordinator, entry.entry_id),
            PowerPayActiveSessionsSensor(coordinator, entry.entry_id),
        ]
    )

    async_add_entities(entities)


class PowerPaySessionSensor(PowerPayEntity, SensorEntity):
    """Base class for session-based sensors."""

    def __init__(
        self,
        coordinator: PowerPayCoordinator,
        device_id: str,
        outlet_index: int,
        entity_key: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_id, f"outlet_{outlet_index}_{entity_key}")
        self._outlet_index = outlet_index

    def _get_session(self) -> PowerPaySessionData | None:
        """Get the session data for this outlet."""
        for session in self.coordinator.data.sessions:
            if session.device_id == self._device_id and session.outlet_index == self._outlet_index:
                return session
        return None


class PowerPayPowerSensor(PowerPaySessionSensor):
    """Current power consumption sensor."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_suggested_display_precision = 0
    _attr_translation_key = "current_power"

    def __init__(self, coordinator: PowerPayCoordinator, device_id: str, outlet_index: int) -> None:
        super().__init__(coordinator, device_id, outlet_index, "power")

    @property
    def native_value(self) -> float | None:
        session = self._get_session()
        return session.current_power_w if session else None


class PowerPayEnergySensor(PowerPaySessionSensor):
    """Session energy consumption sensor."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 2
    _attr_translation_key = "session_energy"

    def __init__(self, coordinator: PowerPayCoordinator, device_id: str, outlet_index: int) -> None:
        super().__init__(coordinator, device_id, outlet_index, "energy")

    @property
    def native_value(self) -> float | None:
        session = self._get_session()
        return session.energy_kwh if session else None


class PowerPayCostSensor(PowerPaySessionSensor):
    """Session cost sensor."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2
    _attr_translation_key = "session_cost"

    def __init__(self, coordinator: PowerPayCoordinator, device_id: str, outlet_index: int) -> None:
        super().__init__(coordinator, device_id, outlet_index, "cost")

    @property
    def native_value(self) -> float | None:
        session = self._get_session()
        return session.cost_nok if session else None

    @property
    def native_unit_of_measurement(self) -> str | None:
        session = self._get_session()
        return session.currency if session else "NOK"


class PowerPayBilledCostSensor(PowerPaySessionSensor):
    """Session billed cost from PowerPay (bills per whole kWh)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2
    _attr_translation_key = "session_billed_cost"

    def __init__(self, coordinator: PowerPayCoordinator, device_id: str, outlet_index: int) -> None:
        super().__init__(coordinator, device_id, outlet_index, "billed_cost")

    @property
    def native_value(self) -> float | None:
        session = self._get_session()
        return session.billed_cost_nok if session else None

    @property
    def native_unit_of_measurement(self) -> str | None:
        session = self._get_session()
        return session.currency if session else "NOK"


class PowerPayCalculatedEnergySensor(PowerPaySessionSensor):
    """Calculated energy from power * duration (updates every poll cycle).

    The API's session energy (end_energy - start_energy) only updates when the
    device reports meter readings (every 15-30 min). This sensor provides a
    continuous estimate using current power * session duration.
    """

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 2
    _attr_translation_key = "calculated_energy"

    def __init__(self, coordinator: PowerPayCoordinator, device_id: str, outlet_index: int) -> None:
        super().__init__(coordinator, device_id, outlet_index, "calculated_energy")

    @property
    def native_value(self) -> float | None:
        session = self._get_session()
        return session.calculated_energy_kwh if session else None


class PowerPayDurationSensor(PowerPaySessionSensor):
    """Session duration sensor."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_suggested_display_precision = 1
    _attr_translation_key = "session_duration"

    def __init__(self, coordinator: PowerPayCoordinator, device_id: str, outlet_index: int) -> None:
        super().__init__(coordinator, device_id, outlet_index, "duration")

    @property
    def native_value(self) -> float | None:
        session = self._get_session()
        return session.duration_seconds / 3600 if session else None


class PowerPayPriceSensor(PowerPaySessionSensor):
    """Price per kWh sensor."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_suggested_display_precision = 2
    _attr_translation_key = "price_per_kwh"

    def __init__(self, coordinator: PowerPayCoordinator, device_id: str, outlet_index: int) -> None:
        super().__init__(coordinator, device_id, outlet_index, "price")

    @property
    def native_value(self) -> float | None:
        session = self._get_session()
        return session.price_per_kwh if session else None

    @property
    def native_unit_of_measurement(self) -> str | None:
        session = self._get_session()
        currency = session.currency if session else "NOK"
        return f"{currency}/kWh"


class PowerPayMonthlyBillingSensor(PowerPayAccountEntity, SensorEntity):
    """Monthly billing from PowerPay invoices + active session billed cost."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2
    _attr_translation_key = "monthly_billing"

    def __init__(self, coordinator: PowerPayCoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "monthly_billing")

    @property
    def native_value(self) -> float:
        return self.coordinator.data.monthly_billing

    @property
    def native_unit_of_measurement(self) -> str:
        """Return currency from billing data."""
        return self.coordinator.data.monthly_currency


class PowerPayUnbilledConsumptionSensor(PowerPayAccountEntity, SensorEntity):
    """Cost of active sessions not yet invoiced by PowerPay."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2
    _attr_translation_key = "unbilled_consumption"

    def __init__(self, coordinator: PowerPayCoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "unbilled_consumption")

    @property
    def native_value(self) -> float:
        return self.coordinator.data.unbilled_consumption

    @property
    def native_unit_of_measurement(self) -> str:
        return self.coordinator.data.monthly_currency


class PowerPayActiveSessionsSensor(PowerPayAccountEntity, SensorEntity):
    """Number of active sessions sensor."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "active_sessions"

    def __init__(self, coordinator: PowerPayCoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "active_sessions")

    @property
    def native_value(self) -> int:
        return len([s for s in self.coordinator.data.sessions if s.is_active])
