"""The PowerPay integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, UnitOfPower
from homeassistant.helpers import entity_registry as er

from .api import PowerPayApiClient, PowerPayAuthError
from .const import CONF_DEVICE_ID, CONF_EMAIL, CONF_OUTLETS, CONF_PASSWORD, DOMAIN
from .coordinator import PowerPayCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH]

type PowerPayConfigEntry = ConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: PowerPayConfigEntry) -> bool:
    """Set up PowerPay from a config entry."""
    session = aiohttp.ClientSession(
        cookie_jar=aiohttp.CookieJar(),
    )

    client = PowerPayApiClient(
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        session=session,
    )

    try:
        await client.async_authenticate()
    except PowerPayAuthError as err:
        await session.close()
        _LOGGER.error("Failed to authenticate with PowerPay: %s", err)
        raise

    coordinator = PowerPayCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "client": client,
        "session": session,
        "device_id": entry.data.get(CONF_DEVICE_ID, ""),
        "outlets": entry.data.get(CONF_OUTLETS, []),
    }

    # Migrate power sensor unit from kW to W (v0.2.0 -> v0.3.0+)
    await _migrate_power_sensor_units(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_update_listener))

    return True


async def _migrate_power_sensor_units(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Fix power sensor unit_of_measurement from kW to W for existing installs."""
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.entity_id.endswith("_power") and entity.unit_of_measurement == "kW":
            _LOGGER.info("Migrating %s unit from kW to W", entity.entity_id)
            registry.async_update_entity_options(
                entity.entity_id, "sensor", {"unit_of_measurement": UnitOfPower.WATT}
            )


async def async_unload_entry(hass: HomeAssistant, entry: PowerPayConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data["client"].async_close()
        await data["session"].close()

    return unload_ok


async def async_update_listener(hass: HomeAssistant, entry: PowerPayConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
