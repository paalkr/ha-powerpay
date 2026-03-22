"""Config flow for PowerPay integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import PowerPayApiClient, PowerPayAuthError, PowerPayConnectionError
from .const import (
    CONF_DEVICE_ID,
    CONF_EMAIL,
    CONF_OUTLETS,
    CONF_PASSWORD,
    CONF_SITE_ID,
    DOMAIN,
)

if TYPE_CHECKING:
    from homeassistant.data_entry_flow import FlowResult

_LOGGER = logging.getLogger(__name__)


def _build_device_selector(devices: list[dict]) -> SelectSelector:
    """Build a SelectSelector for devices."""
    options = [
        SelectOptionDict(
            value=dev["device_id"],
            label=f"{dev.get('name', '?')} - {dev.get('description', '?')}",
        )
        for dev in devices
        if isinstance(dev, dict) and "device_id" in dev
    ]
    return SelectSelector(SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN))


def _build_outlet_selector() -> SelectSelector:
    """Build a SelectSelector for outlets."""
    options = [SelectOptionDict(value=str(i), label=f"Outlet {i}") for i in range(1, 5)]
    return SelectSelector(
        SelectSelectorConfig(options=options, multiple=True, mode=SelectSelectorMode.LIST)
    )


class PowerPayConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PowerPay."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._client: PowerPayApiClient | None = None
        self._email: str = ""
        self._password: str = ""
        self._uid: str = ""
        self._sites: list[dict] = []
        self._devices: list[dict] = []
        self._selected_site_id: str = ""
        self._selected_site_name: str = ""

    async def _get_client(self) -> PowerPayApiClient:
        """Get an authenticated API client."""
        if self._client is None:
            self._client = PowerPayApiClient(email=self._email, password=self._password)
            await self._client.async_authenticate()
        return self._client

    async def _async_cleanup_client(self) -> None:
        """Close the API client if open."""
        if self._client:
            await self._client.async_close()
            self._client = None

    async def _async_fetch_sites(self) -> list[dict]:
        """Fetch available sites."""
        client = await self._get_client()
        sites = await client.async_get_sites()
        return sites if isinstance(sites, list) else []

    async def _async_fetch_devices(self, site_id: str) -> list[dict]:
        """Fetch devices for a site."""
        client = await self._get_client()
        devices = await client.async_server_action(
            api_name="python",
            endpoint="devices",
            method="GET",
            api_namespace_path="/enduser",
            query_params={
                "site_id": site_id,
                "product_category_code": "electricity",
            },
        )
        return devices if isinstance(devices, list) else []

    # ---- Initial setup flow ----

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Step 1: Enter credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._email = user_input[CONF_EMAIL]
            self._password = user_input[CONF_PASSWORD]
            try:
                client = await self._get_client()
                self._uid = client.firebase_uid or ""
                if not self._uid:
                    raise PowerPayAuthError("No user ID returned")
            except PowerPayAuthError:
                errors["base"] = "invalid_auth"
                self._client = None
            except PowerPayConnectionError:
                errors["base"] = "cannot_connect"
                self._client = None
            except Exception:
                _LOGGER.exception("Unexpected error during setup")
                errors["base"] = "unknown"
                self._client = None
            else:
                await self.async_set_unique_id(self._uid)
                self._abort_if_unique_id_configured()
                return await self.async_step_site()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_site(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Step 2: Select a site."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._selected_site_id = user_input[CONF_SITE_ID]
            for site in self._sites:
                if site.get("site_id") == self._selected_site_id:
                    self._selected_site_name = site.get("name", "Unknown")
                    break
            return await self.async_step_device()

        try:
            self._sites = await self._async_fetch_sites()
        except Exception:
            _LOGGER.exception("Failed to fetch sites")
            errors["base"] = "cannot_connect"
            return self.async_show_form(
                step_id="site",
                data_schema=vol.Schema({vol.Required(CONF_SITE_ID): str}),
                errors=errors,
            )

        if not self._sites:
            return self.async_abort(reason="no_sites")

        site_options = {
            site["site_id"]: f"{site.get('name', 'Unknown')} ({site.get('site_type_code', '')})"
            for site in self._sites
            if isinstance(site, dict) and "site_id" in site
        }

        return self.async_show_form(
            step_id="site",
            data_schema=vol.Schema({vol.Required(CONF_SITE_ID): vol.In(site_options)}),
            errors=errors,
        )

    async def async_step_device(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Step 3: Select a device and outlets."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected_device_id = user_input[CONF_DEVICE_ID]
            selected_outlets = [int(o) for o in user_input.get(CONF_OUTLETS, [])]

            device_name = "Unknown"
            for dev in self._devices:
                if dev.get("device_id") == selected_device_id:
                    device_name = dev.get("name", dev.get("description", "Unknown"))
                    break

            if not selected_outlets:
                errors["base"] = "no_outlets_selected"
            else:
                await self._async_cleanup_client()
                return self.async_create_entry(
                    title=f"{self._selected_site_name} - {device_name}",
                    data={
                        CONF_EMAIL: self._email,
                        CONF_PASSWORD: self._password,
                        CONF_SITE_ID: self._selected_site_id,
                        CONF_DEVICE_ID: selected_device_id,
                        CONF_OUTLETS: selected_outlets,
                    },
                )

        try:
            self._devices = await self._async_fetch_devices(self._selected_site_id)
        except Exception:
            _LOGGER.exception("Failed to fetch devices")
            errors["base"] = "cannot_connect"

        if not self._devices:
            return self.async_abort(reason="no_devices")

        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ID): _build_device_selector(self._devices),
                    vol.Required(
                        CONF_OUTLETS, default=["1", "2", "3", "4"]
                    ): _build_outlet_selector(),
                }
            ),
            errors=errors,
        )

    # ---- Reconfigure flow (change credentials, site, device, outlets) ----

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle reconfiguration - step 1: credentials."""
        reconfigure_entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            self._email = user_input[CONF_EMAIL]
            self._password = user_input[CONF_PASSWORD]
            try:
                client = await self._get_client()
                self._uid = client.firebase_uid or ""
                if not self._uid:
                    raise PowerPayAuthError("No user ID returned")
            except PowerPayAuthError:
                errors["base"] = "invalid_auth"
                self._client = None
            except PowerPayConnectionError:
                errors["base"] = "cannot_connect"
                self._client = None
            except Exception:
                _LOGGER.exception("Unexpected error during reconfigure")
                errors["base"] = "unknown"
                self._client = None
            else:
                return await self.async_step_reconfigure_site()

        current_email = reconfigure_entry.data.get(CONF_EMAIL, "")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL, default=current_email): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure_site(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Reconfigure step 2: select site."""
        reconfigure_entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            self._selected_site_id = user_input[CONF_SITE_ID]
            for site in self._sites:
                if site.get("site_id") == self._selected_site_id:
                    self._selected_site_name = site.get("name", "Unknown")
                    break
            return await self.async_step_reconfigure_device()

        try:
            self._sites = await self._async_fetch_sites()
        except Exception:
            _LOGGER.exception("Failed to fetch sites")
            errors["base"] = "cannot_connect"
            return self.async_show_form(
                step_id="reconfigure_site",
                data_schema=vol.Schema({vol.Required(CONF_SITE_ID): str}),
                errors=errors,
            )

        if not self._sites:
            return self.async_abort(reason="no_sites")

        site_options = {
            site["site_id"]: f"{site.get('name', 'Unknown')} ({site.get('site_type_code', '')})"
            for site in self._sites
            if isinstance(site, dict) and "site_id" in site
        }

        current_site = reconfigure_entry.data.get(CONF_SITE_ID, "")

        return self.async_show_form(
            step_id="reconfigure_site",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SITE_ID,
                        default=current_site if current_site in site_options else None,
                    ): vol.In(site_options)
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Reconfigure step 3: select device and outlets."""
        reconfigure_entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            selected_device_id = user_input[CONF_DEVICE_ID]
            selected_outlets = [int(o) for o in user_input.get(CONF_OUTLETS, [])]

            device_name = "Unknown"
            for dev in self._devices:
                if dev.get("device_id") == selected_device_id:
                    device_name = dev.get("name", dev.get("description", "Unknown"))
                    break

            if not selected_outlets:
                errors["base"] = "no_outlets_selected"
            else:
                await self._async_cleanup_client()
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    title=f"{self._selected_site_name} - {device_name}",
                    data={
                        CONF_EMAIL: self._email,
                        CONF_PASSWORD: self._password,
                        CONF_SITE_ID: self._selected_site_id,
                        CONF_DEVICE_ID: selected_device_id,
                        CONF_OUTLETS: selected_outlets,
                    },
                )

        try:
            self._devices = await self._async_fetch_devices(self._selected_site_id)
        except Exception:
            _LOGGER.exception("Failed to fetch devices")
            errors["base"] = "cannot_connect"

        if not self._devices:
            return self.async_abort(reason="no_devices")

        current_device = reconfigure_entry.data.get(CONF_DEVICE_ID, "")
        current_outlets = [str(o) for o in reconfigure_entry.data.get(CONF_OUTLETS, [1, 2, 3, 4])]

        return self.async_show_form(
            step_id="reconfigure_device",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ID, default=current_device): _build_device_selector(
                        self._devices
                    ),
                    vol.Required(CONF_OUTLETS, default=current_outlets): _build_outlet_selector(),
                }
            ),
            errors=errors,
        )

    # ---- Reauth flow ----

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        """Handle reauth when credentials expire."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reauth confirmation."""
        errors: dict[str, str] = {}

        if user_input is not None:
            reauth_entry = self._get_reauth_entry()
            email = reauth_entry.data[CONF_EMAIL]
            try:
                client = PowerPayApiClient(email=email, password=user_input[CONF_PASSWORD])
                await client.async_authenticate()
                await client.async_close()
            except PowerPayAuthError:
                errors["base"] = "invalid_auth"
            except PowerPayConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during reauth")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data={
                        **reauth_entry.data,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PowerPayOptionsFlow:
        """Get the options flow handler."""
        return PowerPayOptionsFlow(config_entry)


class PowerPayOptionsFlow(OptionsFlow):
    """Handle options for PowerPay."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "scan_interval",
                        default=self.config_entry.options.get("scan_interval", 60),
                    ): vol.All(int, vol.Range(min=30, max=600)),
                }
            ),
        )
