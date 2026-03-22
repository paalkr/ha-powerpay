"""Data models for the PowerPay integration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PowerPaySessionData:
    """Represents an active PowerPay session."""

    session_id: str
    device_id: str
    outlet_index: int
    site_name: str
    device_name: str
    device_description: str
    start_ts: int
    energy_kwh: float  # From API meter: (end_energy - start_energy) / 1000
    calculated_energy_kwh: float  # From power * duration (updates every poll)
    cost_nok: float  # Calculated: calculated_energy_kwh * price_per_kwh
    billed_cost_nok: float  # From PowerPay: price_basis.amount.value / 100 (øre→NOK)
    duration_seconds: float
    current_power_w: float
    price_per_kwh: float
    currency: str
    is_active: bool
    cost_limit_nok: float | None = None
    energy_limit_kwh: float | None = None
    site_id: str = ""
    latitude: float | None = None
    longitude: float | None = None


@dataclass
class PowerPayDeviceData:
    """Represents a PowerPay device (physical power post)."""

    device_id: str
    name: str
    description: str
    site_id: str
    site_name: str
    outlet_count: int
    latitude: float | None = None
    longitude: float | None = None
    max_power: int | None = None
    max_current: int | None = None
    voltage: int | None = None
    phases: int | None = None


@dataclass
class PowerPayData:
    """Container for all PowerPay data."""

    sessions: list[PowerPaySessionData] = field(default_factory=list)
    devices: dict[str, PowerPayDeviceData] = field(default_factory=dict)
    firebase_uid: str = ""
    monthly_billing: float = 0.0
    monthly_currency: str = "NOK"
