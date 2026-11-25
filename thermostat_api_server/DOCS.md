# Observer Thermostat API Server

Runs a local replacement for the Observer cloud server, so a Heil/Carrier-family Observer communicating thermostat (TSTAT0201CW) can be controlled from Home Assistant over MQTT. Entities are created automatically through MQTT discovery: a climate entity, sensors (operating mode, outdoor unit, humidity, outdoor temperature, filter hours, equipment status) and configuration entities for the thermostat's own settings.

## Requirements

- An MQTT broker. The Mosquitto broker app is found automatically; any other broker can be set on the Configuration tab.
- The MQTT integration set up in Home Assistant, with discovery enabled (the default).
- The thermostat on the same network as Home Assistant, and a fixed (reserved) IP for the Home Assistant host.

## Setup

1. Fill in **Thermostat serial number** and **Server address** on the Configuration tab. The server address is your Home Assistant host's LAN IP.
2. Start the app and check the Log tab for `Connecting to MQTT`.
3. On the thermostat, set the Observer server address to the same IP (port 8080, unless you changed it on the Network tab).
4. Within a minute the thermostat should appear under **Settings → Devices & services → MQTT**.

Only run one copy of the server per thermostat. Two servers publishing the same discovery topics will fight over the entities.

## Options

- **Thermostat name** — device name in HA. It's also used in MQTT topics and entity IDs, so changing it later creates new entities.
- **Thermostat serial number** — from the thermostat's settings.
- **Server address** — the IP the thermostat uses to reach this app. It's echoed back in the server's replies.
- **MQTT host / port / username / password** — leave empty to use the Mosquitto broker app. Set them only for an external broker. TLS isn't supported.
- **Log level** — INFO for normal use. DEBUG logs every thermostat post (about one every few seconds), including the screen lockout code, router MAC and pairing PIN.
- **Emergency heat mode string** — the raw mode string for emergency heat. `eheat` is confirmed on firmware CESR131611-6.10. To check yours, put the thermostat in emergency heat at the wall and look at the *Operating Mode* sensor.
- **Status / outdoor unit check-in intervals** — the `pingRate` and `oduStatusPingRate` sent to the thermostat. `0` lets the thermostat pick its own interval (about 10 s for status), which is what you want in most cases.

## Features

- **Emergency heat** appears as the *Emergency Heat* preset on the climate entity (HVAC mode shows *heat*).
- **Device settings are learned, not overwritten.** Backlight, volume, sound type, time format, DST, screen lockout and humidify/dehumidify setpoints are read from the thermostat, saved in the app's data folder, and sent back unchanged. Each one (except the lockout code) is a configuration entity you can change from HA. Until the thermostat reports them once, upstream's defaults are used.
- **Observer Thermostat Card** — an optional Lovelace card with Off / Heat / E-Heat / Cool buttons. See `ha_card/` in the [repository](https://github.com/krogo/thermostat_api_server_docker/tree/master/ha_card).

## Troubleshooting

- **The app won't start and the log says no MQTT broker was found:** install the Mosquitto broker app, or set MQTT host.
- **Nothing appears in HA:** check that the thermostat's server address matches, and that the Log tab shows requests like `GET /Alive` and `POST /systems/...`. If there are no requests, the thermostat isn't reaching the app (wrong IP, port, or a firewall/VLAN in between).
- **Settings persistence:** after a restart the log should show `Loaded saved thermostat settings: {...}`.

## Endpoints the thermostat uses

On connect it sends `GET /Alive`, then POSTs to `/systems/<serial>` (its full config), `/dealer_config`, `/profile`, `/dealer`, `/idu_config`, `/odu_config`, and then repeats `/status` and `/odu_status`. It also POSTs `/equipment_events` and `/notifications`, and requests `GET /time/` and `GET /systems/<serial>/config` (the config push). The server reads `/status`, `/odu_status`, `/equipment_events`, `/profile` and `/systems/<serial>`, and answers everything else with an empty 200.

## Tested on

Heil-branded TSTAT0201CW, firmware CESR131611-6.10, protocol 1.7, dual fuel (two-stage furnace + two-stage heat pump). Other firmware may differ; reports and issues are welcome on [GitHub](https://github.com/krogo/thermostat_api_server_docker/issues).

Based on [aneisch/thermostat_api_server_docker](https://github.com/aneisch/thermostat_api_server_docker).
