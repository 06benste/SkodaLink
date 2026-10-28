# SkodaLink

A preview build of the upcoming **official Škoda integration** for Home Assistant, packaged as a
custom component so you can test it before it ships in Home Assistant core.

The base is the draft core pull request
[home-assistant/core#181591](https://github.com/home-assistant/core/pull/181591) (commit `e97d0a1`),
by Škoda Auto / Mobility Lab VŠB-TUO. It uses Škoda's official public Vehicle API through the
[`skoda-public-api`](https://pypi.org/project/skoda-public-api/) library.

## Additions on top of the upstream PR

The API already returns these fields on every poll, but the upstream integration doesn't use them.
They're exposed here without any extra API calls:

| Entity | Type | Shown when the car reports |
|---|---|---|
| Lock | binary sensor (on = unlocked) | vehicle status |
| Doors, Windows | binary sensor (on = open) | vehicle status |
| Boot, Bonnet | binary sensor (on = open) | vehicle status |
| Sunroof | binary sensor (on = open) | a sunroof |
| Lights | binary sensor | vehicle status |
| Moving | binary sensor | parking position |
| Location | device tracker (GPS, address attribute, car picture) | parking position |
| AdBlue range | sensor | AdBlue range |
| Last updated from car | diagnostic sensor | vehicle status |
| API key expiry | diagnostic sensor | always |
| API requests remaining | diagnostic sensor (disabled by default) | always |

Packaging changes for custom-component use:

- `strings.json` → `translations/en.json`, with the `[%key:common::…%]` references resolved
- `manifest.json` has a `version` field and points to this repo; `quality_scale` was removed

## Requirements

- Home Assistant **2026.9 or newer** (the config flow uses `probatio`, which ships with HA from 2026.9)
- A Škoda vehicle and its **VIN**
- An **API key** from the MyŠkoda app (*Profile → Smart Home*)

## Install

### HACS (custom repository)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/06benste/skodalink`, type **Integration**.
2. Search for **Škoda**, download it, and restart Home Assistant.

### Manual

Copy `custom_components/skoda` into `<config>/custom_components/skoda` and restart Home Assistant.

## Set up

**Settings → Devices & services → Add integration → Škoda**, then enter the VIN and API key.

The integration polls the API every 5 minutes. It creates sensors, binary sensors and a device
tracker, depending on what your car reports. It has no controls yet.

## Notes

- The domain is `skoda`, the same one the core integration will use. When the official integration
  ships (expected in 2026.11), **remove this custom component** so the built-in one takes over. Your
  config entry should carry over, since the domain is the same.
- It doesn't conflict with the old community `myskoda` integration (different domain).
- Report bugs in the integration itself on the upstream PR.
