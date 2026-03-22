"""Base entity for PowerPay integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PowerPayCoordinator


class PowerPayEntity(CoordinatorEntity[PowerPayCoordinator]):
    """Base class for PowerPay entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PowerPayCoordinator,
        device_id: str,
        entity_key: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._entity_key = entity_key
        self._attr_unique_id = f"{device_id}_{entity_key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        device = self.coordinator.data.devices.get(self._device_id)
        if device:
            return DeviceInfo(
                identifiers={(DOMAIN, device.device_id)},
                name=device.name or device.description,
                manufacturer="PowerPay",
                model=f"{device.outlet_count}-outlet power post",
                configuration_url="https://app.powerpay.no",
            )
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name="PowerPay Device",
            manufacturer="PowerPay",
            configuration_url="https://app.powerpay.no",
        )


class PowerPayAccountEntity(CoordinatorEntity[PowerPayCoordinator]):
    """Base class for account-level PowerPay entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PowerPayCoordinator,
        entry_id: str,
        entity_key: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._entity_key = entity_key
        self._attr_unique_id = f"{entry_id}_{entity_key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the account."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name="PowerPay Account",
            manufacturer="PowerPay",
            model="Account",
            configuration_url="https://app.powerpay.no",
        )
