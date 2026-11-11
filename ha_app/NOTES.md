# Running as a Home Assistant OS local app — notes

## Install

1. Copy `config.yaml`, `Dockerfile` and the repo's `thermostat_api_server.py` into a folder named `thermostat_api_server` inside the local apps folder. On HA OS 2026.x that folder is `local_apps` in the Samba share, `/local_apps` in the SSH terminal. (It was called `addons` before add-ons were renamed to apps in 2026.2.)
   - The file names are case-sensitive: `config.yaml` and `Dockerfile` (capital D).
   - Check that the copy worked: `ls -l /local_apps/thermostat_api_server`. The `.py` file should be about 36 KB.
2. Fill in the `ENV` values in `Dockerfile`: serial, MQTT login and HA's LAN IP. Keep `THERMOSTAT_NAME` the same as before so the entity IDs and MQTT topics don't change. With the Mosquitto app, the MQTT server is `core-mosquitto`.
3. In HA, go to **Settings → Apps → Install app → ⋮ → Check for updates** (or run `ha store reload`) and install the app from **Local apps**.
4. Stop any other instance (for example the old NAS container) before starting this one. Two servers would publish the same discovery topics.
5. Point the thermostat's Observer server address at HA's LAN IP. Reserve that IP in the router.

## Updating

- Replace the files, then use **Rebuild** (⋮ menu on the app page) or `ha apps rebuild local_thermostat_api_server`.
- Bumping `version` in `config.yaml` isn't required for a rebuild. It does show which build is running.

## Troubleshooting

- **App doesn't appear under Local apps:** a file is missing or misnamed, or the folder is in the wrong place. A YAML error shows as a warning in the Supervisor log (**Settings → System → Logs → Supervisor**). If nothing about it appears at all, the Supervisor isn't finding the folder.
- **Logging:** use `LOG_LEVEL=INFO` normally. `DEBUG` logs every thermostat post (about one every 2 s), which pushes other entries out of the HA OS journal sooner. It also logs the lockout code, router MAC and pairing PIN.
- **Settings persistence:** after a restart the log should say `Loaded saved thermostat settings: {...}`. The data lives in the app's `/data` folder.

## Notes about this system (from the thermostat's own reports)

- Thermostat: Heil-branded TSTAT0201CW, firmware CESR131611-6.10, protocol version 1.7.
- Equipment: **dual fuel**. The indoor unit is a two-stage furnace (`furnace2stg`) and the outdoor unit is a two-stage heat pump (`hp2stgeverest`). Emergency heat (`eheat`) therefore means furnace only, heat pump off. The heat pump locks out below 30 °F outdoors (`heatlocktemp 30`).
- Programming is disabled (`cfgpgm off`). The thermostat holds its setpoints, and the stored weekly program isn't used, so the server sending `hold on` and an empty program doesn't override a schedule.
- Auto changeover is enabled at the dealer level (`cfgauto on`, deadband 2 °F). An auto/heat-cool mode could be added to the climate entity later.
- No humidifier is configured (`cfghumid off`), so the humidify setpoint probably does nothing.
- The zone sensor has a dealer-set temperature offset of −2 °F (`tempoffset -2`).
- Dealer limits: max heating setpoint 80 °F, min cooling setpoint 52 °F. The HA entity uses 55–85 °F.

## Endpoints the thermostat uses

On connect it sends `GET /Alive`, then POSTs to `/systems/<serial>` (its full config), `/dealer_config`, `/profile`, `/dealer`, `/idu_config`, `/odu_config`, and then repeats `/status` and `/odu_status` every few seconds. It also POSTs `/equipment_events` and `/notifications`, and requests `GET /time/` and `GET /systems/<serial>/config` (the config push). The server reads `/status`, `/odu_status`, `/equipment_events`, `/profile` and `/systems/<serial>`, and answers everything else with an empty 200.
