"""Switch platform for PowerPay integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity

from .api import PowerPayApiClient, PowerPayConnectionError
from .const import DOMAIN
from .entity import PowerPayEntity

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import PowerPayCoordinator
    from .data import PowerPaySessionData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PowerPay switch platform."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: PowerPayCoordinator = data["coordinator"]
    client: PowerPayApiClient = data["client"]
    device_id: str = data["device_id"]
    outlets: list[int] = data["outlets"]

    entities = [PowerPayOutletSwitch(coordinator, client, device_id, outlet) for outlet in outlets]

    async_add_entities(entities)


class PowerPayOutletSwitch(PowerPayEntity, SwitchEntity):
    """Switch to control a PowerPay outlet session."""

    _attr_device_class = SwitchDeviceClass.OUTLET
    _attr_translation_key = "outlet_switch"

    def __init__(
        self,
        coordinator: PowerPayCoordinator,
        client: PowerPayApiClient,
        device_id: str,
        outlet_index: int,
    ) -> None:
        super().__init__(coordinator, device_id, f"outlet_{outlet_index}_switch")
        self._client = client
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

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on the outlet (start a new session)."""
        existing = self._get_session()
        if existing and existing.is_active:
            _LOGGER.warning("Outlet %d already has an active session", self._outlet_index)
            return

        try:
            session_id = await self._client.async_start_session(
                device_id=self._device_id,
                outlet_index=self._outlet_index,
            )
            if session_id:
                _LOGGER.info(
                    "Started session %s on outlet %d",
                    session_id,
                    self._outlet_index,
                )
            else:
                _LOGGER.warning("Failed to start session on outlet %d", self._outlet_index)
            await self.coordinator.async_request_refresh()
        except PowerPayConnectionError as err:
            _LOGGER.error("Failed to start session: %s", err)
            raise

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off the outlet (end the active session)."""
        session = self._get_session()
        if not session:
            _LOGGER.warning("No active session found for outlet %d", self._outlet_index)
            return

        try:
            await self._client.async_end_session(session.session_id)
            _LOGGER.info("Ended session %s on outlet %d", session.session_id, self._outlet_index)
            await self.coordinator.async_request_refresh()
        except PowerPayConnectionError as err:
            _LOGGER.error("Failed to end session: %s", err)
            raise
