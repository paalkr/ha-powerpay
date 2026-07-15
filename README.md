# PowerPay Home Assistant Integration

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Tests](https://github.com/paalkr/ha-powerpay/actions/workflows/tests.yml/badge.svg)](https://github.com/paalkr/ha-powerpay/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Custom [Home Assistant](https://www.home-assistant.io/) integration for [PowerPay](https://app.powerpay.no/) — a power management service for harbours and camping sites across Scandinavia and Europe.

## Features

- Real-time power consumption monitoring
- Calculated and billed cost tracking with full transparency
- Monthly billing from PowerPay invoices
- Start and stop power sessions from Home Assistant
- Configurable polling interval
- 8 language translations

## Installation

### HACS (recommended)

1. Open HACS in your Home Assistant instance
2. Click the three dots menu (top right) → **Custom repositories**
3. Add `https://github.com/paalkr/ha-powerpay` with category **Integration**
4. Click **Download**
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/powerpay` folder to your Home Assistant `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **PowerPay**
3. Enter your PowerPay email and password
4. Select your location (harbour or campsite)
5. Select the power post (device) and which outlets to control

To change settings later, use the 3-dot menu → **Reconfigure** on the integration card.

### Polling interval

The integration polls PowerPay every **60 seconds** when a session is active, and every **5 minutes** when idle. You can adjust this in the integration's options (3-dot menu → **Configure**), with a range of 30–600 seconds.

## Sensors

### Per outlet (on the device)

| Sensor | Unit | Source | Description |
|--------|------|--------|-------------|
| **Current power** | W | API: `session.power` | Real-time power draw from the device's meter. Updates every poll cycle. Shows `unknown` when no session is active. |
| **Session energy** | kWh | API: `(end_energy - start_energy) / 1000` | Total energy consumed in the current session, calculated from the device's Wh meter readings. This is a real-time value not easily visible in the PowerPay app. Resets when a new session starts. |
| **Session cost** | NOK* | Calculated: `energy × price` | Estimated cost based on actual energy consumption multiplied by the price per kWh. Updates every poll cycle. This is typically **higher** than the billed cost because PowerPay bills per whole kWh (see billing below). |
| **Session billed cost** | NOK* | API: `price_basis.amount.value` (øre→NOK) | What PowerPay currently considers the billable amount. Increases in steps of `price_per_kwh` each time a full kWh is consumed. Matches "Totalt skyldig beløp" in the app. |
| **Price per kWh** | NOK/kWh* | API: `price_set.model_string` | The electricity price for this outlet's subscription plan. |
| **Session duration** | hours | API: `duration` (ms→hours) | How long the current session has been running. |
| **Outlet active** | on/off | API: session exists | Binary sensor indicating whether the outlet has an active session. |
| **Outlet** | on/off | Switch | Turn the outlet on (start a new session) or off (end the active session). |

*\* Currency depends on the location — NOK for Norway, SEK for Sweden, etc.*

### Account level (on PowerPay Account device)

| Sensor | Unit | Source | Description |
|--------|------|--------|-------------|
| **Monthly billing** | NOK* | API: `purchases` endpoint | Total amount billed by PowerPay in the current calendar month. Sums all Stripe invoices by their billing date, plus the billed cost of any active session. See billing section below. |
| **Unbilled consumption** | NOK* | Calculated: sum of session costs | Running total of energy costs from active sessions that haven't been invoiced yet. Shows what the next bill will include at minimum. Drops to 0 after billing. |
| **Active sessions** | count | API: session count | Number of currently active sessions across all configured outlets. |

## How PowerPay billing works

PowerPay uses a **subscription-based billing model** with per-kWh pricing, processed through Stripe:

### Per-session billing

- Energy is billed in **whole kWh increments**. At 2.99 kWh consumed, you're billed for 2 kWh. When consumption reaches 3.00 kWh, the bill jumps to 3 kWh.
- The **session billed cost** sensor reflects this stepped billing (matches "Totalt skyldig beløp" in the app).
- The **session cost** sensor shows `energy × price` which is the true cost based on actual decimal consumption — useful for your own tracking and automations.

### Monthly invoicing

- PowerPay generates invoices monthly, typically on the **20th of each month**.
- For long-running sessions (e.g. a boat plugged in all season), each invoice covers one billing period.
- The **monthly billing** sensor sums all invoices whose billing date falls in the current calendar month.
- When a session ends, any remaining unbilled energy is included in the final invoice.

### Why two cost sensors?

| Scenario | Session cost (calculated) | Session billed cost (PowerPay) |
|----------|--------------------------|-------------------------------|
| 2.99 kWh at 1.86 NOK/kWh | 5.56 NOK | 3.72 NOK (2 × 1.86) |
| 3.00 kWh at 1.86 NOK/kWh | 5.58 NOK | 5.58 NOK (3 × 1.86) |
| 3.50 kWh at 1.86 NOK/kWh | 6.51 NOK | 5.58 NOK (3 × 1.86) |

The calculated cost is always ≥ the billed cost. The difference shrinks as you approach the next whole kWh.

## Technical details

PowerPay has no documented public API. This integration uses the same private REST API the web app talks to:

1. **Firebase Authentication** — Signs in with your email/password to get an ID token
2. **Data fetching** — Calls the PowerPay REST API (`api.powerpay.no`) directly with the Firebase token to fetch session, device, and billing data

The Firebase token is refreshed automatically before it expires.

### API data units

| Field | Unit | Conversion |
|-------|------|------------|
| Energy meter readings | Wh | ÷ 1000 → kWh |
| Power | W | displayed as-is |
| `price_basis.amount.value` | øre | ÷ 100 → NOK |
| `captured_amount_value` | øre | ÷ 100 → NOK |
| Stripe invoice totals | øre | ÷ 100 → NOK |
| Duration | ms | ÷ 3600000 → hours |
| Timestamps | ms epoch | standard Unix ms |

## Known limitations

- **Session start may not work for all outlets** — Starting a session requires a valid subscription and payment method. Some outlets may reject sessions due to hardware or configuration issues.
- **No historical data import** — Only the current session and monthly billing are tracked. Past session details are not imported.
- **Unofficial API** — This relies on PowerPay's private API, which can change without notice. A major backend change may require an integration update.
- **Billing rounds to whole kWh** — The session billed cost lags behind actual consumption until the next full kWh is reached.

## Development

### Dev container

Open this repo in VS Code with the Dev Containers extension. The container includes Python 3.13, Home Assistant, and test dependencies. Port 8123 is forwarded for the HA UI.

### Running tests

```bash
pip install -r requirements_test.txt
pytest tests/ -v
```

### Linting

```bash
pip install ruff
ruff check custom_components/ tests/
```

## License

[MIT](LICENSE)
