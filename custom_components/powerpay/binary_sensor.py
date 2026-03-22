"""Binary sensor platform for PowerPay integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .const import DOMAIN
from .entity import PowerPayEntity

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
    """Set up PowerPay binary sensor platform."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: PowerPayCoordinator = data["coordinator"]
    device_id: str = data["device_id"]
    outlets: list[int] = data["outlets"]

    entities = [PowerPayOutletActiveSensor(coordinator, device_id, outlet) for outlet in outlets]

    async_add_entities(entities)


class PowerPayOutletActiveSensor(PowerPayEntity, BinarySensorEntity):
    """Binary sensor indicating whether an outlet has an active session."""

    _attr_device_class = BinarySensorDeviceClass.POWER
    _attr_translation_key = "outlet_active"

    def __init__(
        self,
        coordinator: PowerPayCoordinator,
        device_id: str,
        outlet_index: int,
    ) -> None:
        super().__init__(coordinator, device_id, f"outlet_{outlet_index}_active")
        self._outlet_index = outlet_index

    def _get_session(self) -> PowerPaySessionData | None:
        for session in self.coordinator.data.sessions:
            if session.device_id == self._device_id and session.outlet_index == self._outlet_index:
                return session
        return None

    @property
    def is_on(self) -> bool:
        session = self._get_session()
        return session is not None and session.is_active
