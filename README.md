# Tallinna Vesi Water Integration (HACS)

Custom Home Assistant integration for monitoring cumulative and daily water consumption from Tallinna Vesi smart meters via their public self-service API.

## Features

- Secure authentication with Tallinna Vesi `X-API-Key`
- Automatic discovery of the account's smart meter supply point
- Validates that your account exposes at least one smart meter before completing setup
- Hourly polling of smart meter readings
- Exposes two sensors:
  - `Water consumption` (`total_increasing`, m³) – feeds Home Assistant's Energy / Water dashboard
  - `Daily water usage` (`measurement`, m³) – delta from midnight to the latest reading
- Diagnostics data for troubleshooting (recent readings, timestamps)

## Requirements

- Home Assistant 2024.6 or newer (tested with 2024.8), running with HACS
- Valid Tallinna Vesi self-service API key that has at least one smart meter linked

## Installation (HACS)

1. Copy or clone this repository into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. In *Settings → Devices & Services*, click **Add Integration** and look for "Tallinna Vesi Water".
4. Enter your Tallinna Vesi API key when prompted. If the account has multiple smart meters, choose the one you want to monitor.

After the first successful refresh, add the `Water consumption` sensor to the Home Assistant Energy dashboard under the Water section.

## Energy Dashboard Setup

1. Go to *Settings → Dashboards → Energy*.
2. Under **Water consumption**, pick the newly created `Water consumption` sensor.
3. Optionally add the `Daily water usage` sensor to standard HA statistics or charts.

## Troubleshooting

- **Invalid API key**: verify the key from the Tallinna Vesi self-service portal (generated from the "reading submission" page).
- **No smart meters found**: ensure your account shows a smart meter at the Tallinna Vesi self-service page.
- Check diagnostics (Device → Diagnostics) to view recent API responses and timestamps.
- Logs use the namespace `custom_components.tallinnavesi_water`.

## Development

- The integration polls hourly; adjust `DEFAULT_UPDATE_INTERVAL` in `const.py` for testing.
- Unit tests live under `tests/` and use pytest with Home Assistant test fixtures.

## Disclaimer

This project is unofficial and not affiliated with Tallinna Vesi.
