"""DataUpdateCoordinator for PowerPay."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PowerPayApiClient, PowerPayAuthError, PowerPayConnectionError
from .const import DOMAIN, SCAN_INTERVAL_ACTIVE, SCAN_INTERVAL_IDLE
from .data import PowerPayData, PowerPayDeviceData, PowerPaySessionData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class PowerPayCoordinator(DataUpdateCoordinator[PowerPayData]):
    """Coordinator to manage fetching PowerPay data."""

    def __init__(self, hass: HomeAssistant, client: PowerPayApiClient) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_IDLE),
        )
        self.client = client
        self._purchases_cache: list[dict] | None = None
        self._purchases_cache_ts: float = 0

    async def _async_update_data(self) -> PowerPayData:
        """Fetch data from PowerPay."""
        try:
            return await self._fetch_data()
        except PowerPayAuthError as err:
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except PowerPayConnectionError as err:
            raise UpdateFailed(f"Communication error: {err}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected error fetching PowerPay data")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def _fetch_data(self) -> PowerPayData:
        """Fetch and process all PowerPay data."""
        sessions_raw = await self.client.async_get_active_sessions()

        sessions: list[PowerPaySessionData] = []
        devices: dict[str, PowerPayDeviceData] = {}

        # Get previous data for accumulation
        prev_sessions: dict[str, PowerPaySessionData] = {}
        if self.data:
            prev_sessions = {s.session_id: s for s in self.data.sessions}

        for raw in sessions_raw:
            session = self._parse_session(raw)
            if session:
                # Accumulate calculated energy between polls (never decreases)
                prev = prev_sessions.get(session.session_id)
                if prev and prev.duration_seconds > 0:
                    time_delta_h = max(0, session.duration_seconds - prev.duration_seconds) / 3600
                    energy_delta_kwh = session.current_power_w * time_delta_h / 1000
                    session.calculated_energy_kwh = prev.calculated_energy_kwh + energy_delta_kwh
                else:
                    # First poll or new session: start from API meter reading
                    session.calculated_energy_kwh = session.energy_kwh

                # Recalculate cost from accumulated energy (also never decreases)
                session.cost_nok = session.calculated_energy_kwh * session.price_per_kwh

                sessions.append(session)

            # Extract device info from session data
            device_details = raw.get("device_details", {})
            if device_details:
                device = self._parse_device(device_details, raw)
                devices[device.device_id] = device

        # Fetch monthly billing from purchases
        monthly_billing, monthly_currency = await self._fetch_monthly_billing(sessions)

        # Adapt polling interval based on active sessions
        has_active = any(s.is_active for s in sessions)
        self.update_interval = timedelta(
            seconds=SCAN_INTERVAL_ACTIVE if has_active else SCAN_INTERVAL_IDLE
        )

        return PowerPayData(
            sessions=sessions,
            devices=devices,
            firebase_uid=self.client.firebase_uid or "",
            monthly_billing=monthly_billing,
            monthly_currency=monthly_currency,
            unbilled_consumption=sum(s.cost_nok for s in sessions),
        )

    async def _fetch_monthly_billing(
        self, active_sessions: list[PowerPaySessionData]
    ) -> tuple[float, str]:
        """Calculate monthly billing from invoices + active session billed cost.

        PowerPay bills monthly via Stripe on the 20th. We sum invoices whose
        billing date (event_ts) falls in the current calendar month, plus
        the billed cost of any active sessions (not yet invoiced).
        """
        import time as _time

        now = datetime.now(tz=UTC)
        month_start_ms = int(datetime(now.year, now.month, 1, tzinfo=UTC).timestamp() * 1000)

        total_billing = 0.0
        currency = "NOK"

        # Cache purchases for 5 minutes (they change at most monthly)
        cache_age = _time.time() - self._purchases_cache_ts
        if self._purchases_cache is None or cache_age > 300:
            try:
                result = await self.client.async_server_action(
                    api_name="python",
                    endpoint="purchases",
                    method="GET",
                    api_namespace_path="/enduser",
                    query_params={"limit": "20"},
                    other_options={"cache": "no-store"},
                )
                if isinstance(result, list):
                    self._purchases_cache = result
                    self._purchases_cache_ts = _time.time()
            except Exception:
                _LOGGER.debug("Failed to fetch purchases for monthly billing")

        # Sum invoices billed in the current calendar month (øre → NOK)
        if self._purchases_cache:
            for p in self._purchases_cache:
                pe = p.get("payment_event", {})
                event_ts = pe.get("event_ts", 0)
                if event_ts < month_start_ms:
                    continue
                meta = pe.get("metadata", {})
                stripe = meta.get("stripe_details", {})
                stripe_total = stripe.get("total", 0)  # øre
                if stripe_total > 0:
                    total_billing += stripe_total / 100  # øre → NOK
                cur = p.get("currency")
                if cur:
                    currency = cur

        # Add billed cost from active sessions (not yet invoiced)
        for session in active_sessions:
            total_billing += session.billed_cost_nok
            if session.currency:
                currency = session.currency

        return total_billing, currency

    def _parse_session(self, raw: dict[str, Any]) -> PowerPaySessionData | None:
        """Parse raw session data into a PowerPaySessionData."""
        try:
            device_details = raw.get("device_details", {})
            device_props = device_details.get("device_properties", {})
            price_set = raw.get("price_set", {})
            price_set.get("price_structure_parameters", {})

            start_energy = raw.get("start_energy", 0)
            end_energy = raw.get("end_energy", 0)
            energy_wh = end_energy - start_energy
            energy_kwh = energy_wh / 1000

            # Parse price from model_string or price_structure_parameters
            price_per_kwh = self._extract_price(price_set)

            # Initial values — overwritten by accumulator in _fetch_data
            calculated_energy_kwh = energy_kwh  # Start from API meter
            cost_nok = energy_kwh * price_per_kwh

            # Billed cost from PowerPay (bills per whole kWh, lags behind)
            # price_basis.amount.value is in øre
            price_basis = raw.get("price_basis", {})
            price_basis_amount = price_basis.get("amount", {}).get("value", 0)
            captured = raw.get("captured_amount_value", 0)  # øre, only set when session ends
            if price_basis_amount > 0:
                billed_cost_nok = price_basis_amount / 100  # øre → NOK
            elif captured > 0:
                billed_cost_nok = captured / 100  # øre → NOK
            else:
                billed_cost_nok = 0.0

            # A session returned by /enduser/session is active (not archived).
            # The end_ts is a scheduled end time, not the actual end.
            is_active = not raw.get("archived", False)

            # Duration in seconds
            duration_ms = raw.get("duration", 0)

            outlet_index = raw.get("outlet_index", 0)
            outlet_labels = device_details.get("outlet_properties_effective", {})
            outlet_labels.get(str(outlet_index), {})

            return PowerPaySessionData(
                session_id=raw["session_id"],
                device_id=raw.get("device_id", ""),
                outlet_index=outlet_index,
                site_name=device_details.get("site_name", raw.get("site_name", "")),
                device_name=device_details.get("name", ""),
                device_description=device_details.get("description", ""),
                start_ts=raw.get("start_ts", 0),
                energy_kwh=energy_kwh,
                calculated_energy_kwh=calculated_energy_kwh,
                cost_nok=cost_nok,
                billed_cost_nok=billed_cost_nok,
                duration_seconds=duration_ms / 1000,
                current_power_w=raw.get("power", 0),
                price_per_kwh=price_per_kwh,
                currency=price_set.get("currency", "NOK"),
                is_active=is_active,
                cost_limit_nok=(raw.get("cost_limit", 0) / 100 if raw.get("cost_limit") else None),
                energy_limit_kwh=(
                    raw.get("energy_limit", 0) / 1000000 if raw.get("energy_limit") else None
                ),
                site_id=device_details.get("site_id", ""),
                latitude=device_props.get("latitude"),
                longitude=device_props.get("longitude"),
            )
        except (KeyError, TypeError, ValueError) as err:
            _LOGGER.warning("Failed to parse session data: %s", err)
            return None

    def _parse_device(
        self, device_details: dict[str, Any], session_raw: dict[str, Any]
    ) -> PowerPayDeviceData:
        """Parse device details into a PowerPayDeviceData."""
        props = device_details.get("device_properties", {})
        return PowerPayDeviceData(
            device_id=device_details.get("device_id", ""),
            name=device_details.get("name", ""),
            description=device_details.get("description", ""),
            site_id=device_details.get("site_id", ""),
            site_name=device_details.get("site_name", session_raw.get("site_name", "")),
            outlet_count=device_details.get("outlet_count", 4),
            latitude=props.get("latitude"),
            longitude=props.get("longitude"),
            max_power=props.get("max_power"),
            max_current=props.get("max_current"),
            voltage=props.get("voltage"),
            phases=props.get("phases"),
        )

    def _extract_price(self, price_set: dict[str, Any]) -> float:
        """Extract price per kWh from price set data."""
        # Try to parse from model_string like "Sesongkunde:\nPris per kWh: 1,86 kr"
        model_string = price_set.get("model_string", "")
        import re

        match = re.search(r"(\d+[.,]\d+)\s*kr", model_string)
        if match:
            return float(match.group(1).replace(",", "."))

        # Fallback: check price structure parameters
        params = price_set.get("price_structure_parameters", {})
        if "energy_price_amount" in params:
            return float(params["energy_price_amount"])

        return 0.0
