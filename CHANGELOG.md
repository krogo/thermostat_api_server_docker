# Changelog (krogo fork)

This fork tracks [aneisch/thermostat_api_server_docker](https://github.com/aneisch/thermostat_api_server_docker) and adds the changes below. Version numbers match the `version` in the Home Assistant local app's `config.yaml` (see `ha_app/`).

Base: upstream commit `b882915` ("Misc bug fixes, including unexpected flip to heat"), the latest upstream as of 2026-11-10.

## 1.0.6 — 2026-11-10

### Fixed
- **Slow pickup of HA changes.** This firmware sometimes sends empty or unparseable `/status` posts. Upstream answered those with "no changes" even when a change was queued, so the change waited for the next full status post. That added 17–30 s in testing. Every status reply now announces queued changes.

### Observed
- The 1.0.4 XML fix changed the thermostat's polling with no other change. With the well-formed reply and `pingRate`/`oduStatusPingRate` still `0`, it posts status about every 10 s and odu_status/equipment_events about once a minute: about 8 requests/min, down from about 33. With the malformed reply it was polling back-to-back every ~1.8 s, apparently because it couldn't parse the intervals. So `0` seems to mean "use the default". The `*_PING_RATE` options are probably unnecessary now.

## 1.0.5 — 2026-11-10

### Added
- `STATUS_PING_RATE` and `ODU_STATUS_PING_RATE` set the check-in intervals (`pingRate`, `oduStatusPingRate`) sent in every status reply. Both default to `0`, upstream's value, which makes the thermostat post back-to-back about every 2 s. The wall unit's keypad has been sluggish, possibly from that load. Higher values reduce traffic but delay how quickly HA changes are picked up.

## 1.0.4 — 2026-11-10

### Fixed
- **Fan mode reverting to auto** (upstream bug). The outgoing config started as `fan: auto, hold: on` and was never refreshed from what the thermostat reported. Any change from HA (mode, setpoint, a setting) also pushed fan `auto`. It also reverted anything changed at the wall since the server started: mode, fan, setpoints. The outgoing config is now synced from every status report while no HA change is pending. A setpoint change from HA still sets hold `on`, as upstream intended.
- The "no changes" reply, sent on every poll every few seconds, contained malformed XML (`<dealerConfigHasChanges>off</dealerHasChanges>`). The thermostat tolerated it; it's now well-formed.
- The MQTT state is published as real JSON. The old `str(dict)` plus quote-replacement broke on apostrophes, and on any value containing the text `None`.
- If the thermostat requests its config before its first status report, the server returns an empty reply instead of crashing.

### Card 1.1.0
- Mode and fan buttons show a pulsing dashed outline, and "Sending to thermostat…" appears until the thermostat reports the new value (or after 45 s).

## 1.0.3 — 2026-11-10

### Added
- `<name> Outdoor Unit` sensor, showing the outdoor unit's operating status (`opstat`) as reported in `/odu_status`. The card uses it to show whether the heat pump is running.
- **Observer Thermostat Card** (`ha_card/`, card version 1.0.0). It's a custom Lovelace card with Off / Heat / E-Heat / Cool buttons, so Emergency Heat appears as a mode instead of a separate Preset box. It also has a debounced setpoint, fan buttons, equipment status, humidity, outdoor temperature, filter hours and a "sending to thermostat" indicator.

## 1.0.2 — 2026-11-10 (commit `81a8c35`)

### Fixed
- **Clean shutdown.** Stopping the app used to take about 12 s and end with `exited with non-zero exit code 137` (SIGKILL). The script ran as PID 1 behind a shell-form `ENTRYPOINT`, so `/bin/sh` never passed SIGTERM on, and PID 1 ignores SIGTERM without a handler. The script now handles SIGTERM: it closes the HTTP server and disconnects from MQTT, then exits 0. The `ENTRYPOINT` is now exec form. Stop takes about 2 s.
  - The Supervisor may log `Container ... not found` / `App ... is not running` while cleaning up after a stop. That's harmless: the container exited before the cleanup step ran.

## 1.0.1 — 2026-11-10 (commit `a4a1d90`)

### Changed
- Request log lines are back to the original `IP -- METHOD -- path` format. The 1.0.0 logging fix had appended the raw HTTP request line to every entry.

## 1.0.0 — 2026-11-10 (commits `ac36cab`, `65df724`, `9beb0be`)

First version run as a Home Assistant OS local app, replacing the Docker container on the NAS.

### Added
- **Emergency heat.** The climate entity has an `Emergency Heat` preset. Selecting it sets the thermostat mode to `eheat`; selecting `none` returns to `heat`. While in emergency heat the HVAC mode shows `heat`, the target temperature follows the heating setpoint, and power on/off restores emergency heat if that was the last mode. The mode string can be changed with `EMERGENCY_HEAT_MODE` (default `eheat`, confirmed on firmware CESR131611-6.10).
- **Device settings are learned, not overwritten.** Upstream sends fixed values for backlight, time format, DST, volume, sound type, screen lockout, lockout code and humidify/dehumidify setpoints on every config push. That would have changed this thermostat's backlight from 85 to 10. Now:
  - The values come from the config the thermostat posts to `/systems/<serial>` (as `<system><config>…</config></system>`) at connect time and after any change at the wall.
  - They're saved to `SETTINGS_FILE` (default `/data/thermostat_settings.json`), so they survive restarts.
  - They're sent back unchanged on every config push.
  - Until the thermostat has reported its settings once, the old hardcoded values are used, the same as upstream.
- **Remote editing of those settings.** They appear as configuration entities on the thermostat device in HA: Backlight (0–100), Volume, Sound Type, Time Format, Daylight Saving Time, Screen Lockout, Humidify Setpoint and Dehumidify Setpoint. The lockout code is kept but not exposed. Changes are queued and sent on the next config push. If the thermostat reports a select value that isn't in the list, it's added to the options.
- New environment variables: `EMERGENCY_HEAT_MODE`, `SETTINGS_FILE`. The Dockerfile creates `/data` and declares it as a volume.

### Fixed
- A malformed HTTP request (seen from a LAN scanner) crashed the request logger with `AttributeError: 'MyHttpRequestHandler' object has no attribute 'path'`.

### Changed
- The GitHub Actions workflow pushes images to `ghcr.io/<repo owner>/` instead of hardcoding `aneisch`.
