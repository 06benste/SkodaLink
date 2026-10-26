# SkodaLink – Škoda for Home Assistant (MyŠkoda Public API)

A Home Assistant custom integration for Škoda vehicles built on the **official
[MyŠkoda Public API](https://public.api.connect.skoda-auto.cz/docs)**. It replaces
integrations that used the unofficial MyŠkoda app API.

It authenticates with an API key that you create in the MyŠkoda app. You don't
enter your Škoda account password, and there is no OAuth login to break.

## Features

Entities are only created for what your vehicle actually reports and supports,
so a petrol mild hybrid, a plug-in hybrid and an Enyaq each get the right set.

| Platform | Entities |
| --- | --- |
| Sensor | Odometer, total range, fuel level, combustion range, AdBlue range, powertrain, battery level, electric range, charging state / type / power / rate, remaining charging time, fully charged at, target SoC, charge mode, max AC current, charging profile (with all saved profiles as attributes), air-conditioning state and ETA, auxiliary heating state / temperature / duration, active ventilation state, parking address, last data from car, API key expiry, API requests remaining |
| Binary sensor | Lock, doors, windows, trunk, bonnet, sunroof, lights, in motion, charging, charging cable connected / locked, at saved charging location, charging care mode, auto-unlock cable, front/rear window heating, climatisation without external power, climatisation at unlock |
| Climate | Remote air conditioning with target temperature |
| Switch | Charging, auxiliary heating, active ventilation |
| Number | Charge limit (50–100 %) |
| Select | Charge mode (only the modes the car offers) |
| Device tracker | Last parking position |
| Image | Vehicle render from the MyŠkoda app |
| Button | Refresh data |

### Actions (services)

- `skodalink.start_air_conditioning`: target temperature and "without external power".
- `skodalink.start_auxiliary_heating`: S-PIN, temperature, duration and heating/ventilation mode.
- `skodalink.update_charging_profile`: change the charge limit, max current,
  minimum battery level and auto-unlock of a saved charging location. It
  defaults to the location where the car is parked.
- `skodalink.refresh`: poll the vehicle now.

### Other features

- **Reauthentication.** API keys expire. A repair issue warns you 7 days before
  the key expires. When it expires, Home Assistant asks you for a new key, and
  no entities are lost.
- **Reconfigure.** You can swap the API key or add and remove vehicles without
  deleting the integration.
- **Options.** You can set the polling interval (default 10 min) and store your
  S-PIN for the auxiliary heating switch.
- **Partial data.** When the API can't fetch one part of the data, such as the
  parking position, the integration keeps the last known value instead of
  making those entities unavailable.
- **Diagnostics.** The download has the VIN, licence plate, location and keys
  redacted.

## Installation (HACS)

1. In HACS, open **⋮ → Custom repositories** and add
   `https://github.com/06benste/SkodaLink` with the category **Integration**.
2. Install **SkodaLink (MyŠkoda Public API)** and restart Home Assistant.

You can also install it manually by copying `custom_components/skodalink` into
your `config/custom_components` folder.

## Setup

1. In the **MyŠkoda app** (version 8.16 or newer), create an API key. Go to
   *Settings → API keys* or open <https://go.skoda.eu/api-keys>, and select the
   vehicles the key may access.
2. In Home Assistant, go to **Settings → Devices & services → Add integration →
   SkodaLink**.
3. Paste the API key and enter the **VIN** of each vehicle. The API cannot list
   vehicles, so you have to enter the VINs yourself. Separate several VINs with
   commas. The VIN is shown in the MyŠkoda app and on your V5C.

## Notes and limitations

- The public API doesn't offer **lock/unlock, honk/flash, or window heating
  control**. Those entities are read-only.
- Each API key has a **rate limit**. The *API requests remaining* diagnostic
  sensor shows the current quota. Don't set the polling interval too low.
- After a command, the integration reads the vehicle again after 20 s and
  after 90 s to pick up the new state.
- Mild-hybrid (MHEV) vehicles such as the 2024 Superb report themselves as
  petrol cars and have no high-voltage battery. Charging entities are not
  created for them.

## Development

```bash
pip install -r requirements_test.txt ruff
ruff check . && ruff format --check .
pytest
```

This project is not affiliated with or endorsed by Škoda Auto a.s.
