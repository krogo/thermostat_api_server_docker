#!/usr/bin/env python3

from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs
from urllib.parse import unquote
import xml.etree.ElementTree as ET
import paho.mqtt.client as mqttClient
import datetime
import os
import socketserver
import time
import json
import logging
import signal
import sys

logging.basicConfig(
    level=os.environ['LOG_LEVEL'], format="%(asctime)s -- %(levelname)s -- %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# Allow faster script restart
socketserver.TCPServer.allow_reuse_address = True

candidate_configuration = {"hold": "on", "fan": "auto"}
current_configuration = {"changes_pending": "OFF"}
changes_pending = False
first_start = True
# Last real non-off mode the device reported, used to restore mode on power-on
# instead of relying on Home Assistant's default turn_on behavior (which always
# picks heat over cool when both are available).
last_active_mode = "cool"

api_server_address = os.environ['API_SERVER_ADDRESS']
mqtt_address = os.environ['MQTT_SERVER']
mqtt_port = int(os.environ['MQTT_PORT'])
if 'MQTT_USERNAME' in os.environ:
  mqtt_username = os.environ['MQTT_USERNAME']
  mqtt_password = os.environ['MQTT_PASSWORD']
thermostat_name = os.environ['THERMOSTAT_NAME']
thermostat_command_topic = f"homeassistant/climate/{thermostat_name}/cmnd"
thermostat_state_topic = f"homeassistant/climate/{thermostat_name}/state"
thermostat_serial = os.environ['THERMOSTAT_SERIAL']

# Raw mode string the thermostat uses for emergency heat. Confirm yours by putting the
# thermostat in emergency heat and checking the "<name> Operating Mode" sensor in HA.
eheat_mode = os.environ.get('EMERGENCY_HEAT_MODE', 'eheat')
heat_modes = ("heat", eheat_mode)
active_modes = ("cool", "heat", eheat_mode)
EHEAT_PRESET = "Emergency Heat"

# Device settings that used to be hardcoded in every config push. They are now learned
# from what the thermostat reports, persisted to disk, and sent back unchanged unless
# changed from Home Assistant. Defaults are the old hardcoded values and are only used
# until the thermostat has reported its own.
SETTING_DEFAULTS = {
    "blight": "10",
    "timeFormat": "12",
    "dst": "on",
    "volume": "high",
    "soundType": "click",
    "scrLockout": "off",
    "scrLockoutCode": "0000",
    "humSetpoint": "45",
    "dehumSetpoint": "45",
}
settings_file = os.environ.get('SETTINGS_FILE', '/data/thermostat_settings.json')

def load_settings():
    try:
        with open(settings_file) as f:
            saved = json.load(f)
        return {k: str(v) for k, v in saved.items() if k in SETTING_DEFAULTS}
    except FileNotFoundError:
        return {}
    except Exception as e:
        logging.warning(f"Could not read {settings_file}: {e}")
        return {}

def save_settings():
    try:
        tmp = settings_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(device_settings, f, indent=2)
        os.replace(tmp, settings_file)
    except Exception as e:
        logging.warning(f"Could not save settings to {settings_file} (they will not survive a restart): {e}")

device_settings = load_settings()   # last values known to be on the thermostat
pending_settings = {}               # changes requested from HA, not yet sent

def effective_settings():
    return {**SETTING_DEFAULTS, **device_settings, **pending_settings}

current_configuration.update(effective_settings())
if device_settings:
    logging.info(f"Loaded saved thermostat settings: {device_settings}")
else:
    logging.info("No saved thermostat settings yet; using defaults until the thermostat reports its own")

device = {"mdl": "TSTAT0201CW", "sw": "Unknown", "mf": "Observer", "ids": thermostat_serial, "name": thermostat_name}

climate_configuration_payload = {
    "act_t": thermostat_state_topic,
    "act_tpl": "{% if value_json.coolicon == 'on' %}cooling{% elif value_json.heaticon == 'on' %}heating{% elif value_json.coolicon == 'off' and value_json.heaticon == 'off' %}idle{% endif %}",
    "curr_temp_t": thermostat_state_topic,
    "curr_temp_tpl": "{{ value_json.rt }}",
    "device": device,
    "fan_modes": ["auto","low","med","high"],
    "fan_mode_cmd_t": thermostat_command_topic + "/fan_mode",
    "fan_mode_stat_t": thermostat_state_topic,
    "fan_mode_stat_tpl": "{{ value_json.fan }}",
    "max_temp": 85,
    "min_temp": 55,
    "mode_cmd_t": thermostat_command_topic + "/operating_mode",
    "mode_stat_t": thermostat_state_topic,
    # Emergency heat is reported to HA as hvac mode "heat" plus the "Emergency Heat" preset
    "mode_stat_tpl": "{% if value_json.mode == '" + eheat_mode + "' %}heat{% else %}{{ value_json.mode }}{% endif %}",
    "modes": ["off", "cool", "heat"],
    "preset_modes": [EHEAT_PRESET],
    "preset_mode_command_topic": thermostat_command_topic + "/preset_mode",
    "preset_mode_state_topic": thermostat_state_topic,
    "preset_mode_value_template": "{% if value_json.mode == '" + eheat_mode + "' %}" + EHEAT_PRESET + "{% else %}none{% endif %}",
    "name": thermostat_name,
    "power_command_topic": thermostat_command_topic + "/power",
    "temp_cmd_t": thermostat_command_topic + "/temperature",
    "temp_stat_t": thermostat_state_topic,
    "temp_stat_tpl": "{% if value_json.mode == 'cool' %}{{ value_json.clsp }}{% elif value_json.mode in ['heat', '" + eheat_mode + "'] %}{{ value_json.htsp }}{% endif %}",
    "temp_step":"1",
    "temperature_unit": "F",
    "uniq_id": thermostat_serial
}

# HA controls for the device settings. Option lists and ranges are best guesses; a value
# the thermostat reports that isn't in a select's list gets added automatically.
SETTING_ENTITIES = {
    "blight":        {"platform": "number", "name": "Backlight", "ic": "mdi:brightness-6", "min": 0, "max": 100},
    "volume":        {"platform": "select", "name": "Volume", "ic": "mdi:volume-high", "options": ["high", "medium", "low", "off"]},
    "soundType":     {"platform": "select", "name": "Sound Type", "ic": "mdi:music-note", "options": ["click", "beep"]},
    "timeFormat":    {"platform": "select", "name": "Time Format", "ic": "mdi:clock-outline", "options": ["12", "24"]},
    "dst":           {"platform": "switch", "name": "Daylight Saving Time", "ic": "mdi:clock-time-four"},
    "scrLockout":    {"platform": "switch", "name": "Screen Lockout", "ic": "mdi:lock"},
    "humSetpoint":   {"platform": "number", "name": "Humidify Setpoint", "ic": "mdi:water-plus", "min": 0, "max": 100, "unit_of_meas": "%"},
    "dehumSetpoint": {"platform": "number", "name": "Dehumidify Setpoint", "ic": "mdi:water-minus", "min": 0, "max": 100, "unit_of_meas": "%"},
}
NUMERIC_SETTINGS = ("blight", "humSetpoint", "dehumSetpoint")

def publish_setting_entity(client, key):
    spec = SETTING_ENTITIES[key]
    payload = {
        "device": device,
        "name": f"{thermostat_name} {spec['name']}",
        "ic": spec["ic"],
        "uniq_id": f"{thermostat_serial}-setting-{key}",
        "entity_category": "config",
        "stat_t": thermostat_state_topic,
        "val_tpl": "{{ value_json." + key + " }}",
        "cmd_t": f"{thermostat_command_topic}/setting/{key}",
    }
    if spec["platform"] == "number":
        payload.update({"min": spec["min"], "max": spec["max"], "step": 1, "mode": "box"})
        if "unit_of_meas" in spec:
            payload["unit_of_meas"] = spec["unit_of_meas"]
    elif spec["platform"] == "select":
        payload["options"] = spec["options"]
    elif spec["platform"] == "switch":
        payload.update({"pl_on": "on", "pl_off": "off", "stat_on": "on", "stat_off": "off"})
    client.publish(f'homeassistant/{spec["platform"]}/{thermostat_serial}-setting-{key}/config', json.dumps(payload), retain=True)

def learn_settings(reported):
    """Record settings the thermostat reported. Returns True if anything changed."""
    changed = False
    for key, value in reported.items():
        if key in pending_settings:
            continue  # an HA change is queued for this key; don't let a stale report undo it
        if device_settings.get(key) != value:
            logging.info(f"Thermostat reported {key} = {value} (was {device_settings.get(key, 'unknown')})")
            device_settings[key] = value
            changed = True
            spec = SETTING_ENTITIES.get(key)
            if spec and spec["platform"] == "select" and value not in spec["options"]:
                spec["options"].append(value)
                publish_setting_entity(client, key)
    if changed:
        save_settings()
        current_configuration.update(effective_settings())
    return changed

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        logging.info("Connected to MQTT")
    else:
        return 

    client.subscribe(f"{thermostat_command_topic}/#")
    logging.info(f'''Subscribed to {thermostat_command_topic}/#''')

    client.publish(f'homeassistant/climate/{thermostat_serial}-climate/config', json.dumps(climate_configuration_payload), retain=True)

    changes_pending_sensor_payload = {
        "device": device,
        "stat_t": thermostat_state_topic,
        "name": f"{thermostat_name} Changes Pending",
        "ic": "mdi:sync",
        "val_tpl": "{{ value_json.changes_pending }}",
        "uniq_id": f"{thermostat_serial}-changes-pending",
        "device_class": "update"
    }
    client.publish(f'homeassistant/binary_sensor/{thermostat_serial}-changes-pending/config', json.dumps(changes_pending_sensor_payload), retain=True)

    latest_equipment_event_payload = {
        "device": device,
        "stat_t": thermostat_state_topic,
        "name": f"{thermostat_name} Active Equipment Event",
        "ic": "mdi:alert",
        "val_tpl": "{{ value_json.latest_equip }}",
        "uniq_id": f"{thermostat_serial}-latest-equip"
    }
    client.publish(f'homeassistant/sensor/{thermostat_serial}-latest-equip/config', json.dumps(latest_equipment_event_payload), retain=True)

    temperature_sensor_configuration_payload = {
        "device": device,
        "stat_t": thermostat_state_topic,
        "name": f"{thermostat_name} Temperature",
        "unit_of_meas": "°F",
        "device_class": "temperature",
        "ic": "mdi:thermometer",
        "val_tpl": "{{ value_json.rt }}",
        "uniq_id": f"{thermostat_serial}-temp"
    }
    client.publish(f'homeassistant/sensor/{thermostat_serial}-temp/config', json.dumps(temperature_sensor_configuration_payload), retain=True)

    humidity_sensor_configuration_payload = {
        "device": device,
        "stat_t": thermostat_state_topic,
        "name": f"{thermostat_name} Humidity",
        "unit_of_meas": "%",
        "device_class": "humidity",
        "ic": "mdi:water-percent",
        "val_tpl": "{{ value_json.rh }}",
        "uniq_id": f"{thermostat_serial}-humidity"
    }
    client.publish(f'homeassistant/sensor/{thermostat_serial}-humidity/config', json.dumps(humidity_sensor_configuration_payload), retain=True)

    for key in SETTING_ENTITIES:
        publish_setting_entity(client, key)

    mode_sensor_configuration_payload = {
        "device": device,
        "stat_t": thermostat_state_topic,
        "name": f"{thermostat_name} Operating Mode",
        "ic": "mdi:home-thermometer",
        "val_tpl": "{{ value_json.mode }}",
        "uniq_id": f"{thermostat_serial}-mode"
    }
    client.publish(f'homeassistant/sensor/{thermostat_serial}-mode/config', json.dumps(mode_sensor_configuration_payload), retain=True)

    fan_mode_sensor_configuration_payload = {
        "device": device,
        "stat_t": thermostat_state_topic,
        "name": f"{thermostat_name} Fan Mode",
        "val_tpl": "{{ value_json.fan }}",
        "ic": "mdi:fan",
        "uniq_id": f"{thermostat_serial}-fan-mode"
    }
    client.publish(f'homeassistant/sensor/{thermostat_serial}-fan-mode/config', json.dumps(fan_mode_sensor_configuration_payload), retain=True)

    state_sensor_configuration_payload = {
        "device": device,
        "stat_t": thermostat_state_topic,
        "name": f"{thermostat_name} State",
        "ic": "mdi:home-thermometer",
        "val_tpl": "{% if value_json.coolicon == 'on' %}Cooling{% elif value_json.heaticon == 'on' %}Heating{% elif value_json.fanicon == 'on' %}Idle Fan{% elif value_json.coolicon == 'off' and value_json.heaticon == 'off' and value_json.fanicon == 'off' %}Idle{% else %}Unknown{% endif %}",
        "uniq_id": f"{thermostat_serial}-state"
    }
    client.publish(f'homeassistant/sensor/{thermostat_serial}-state/config', json.dumps(state_sensor_configuration_payload), retain=True)

    setpoint_sensor_configuration_payload = {
        "device": device,
        "stat_t": thermostat_state_topic,
        "name": f"{thermostat_name} Setpoint",
        "ic": "mdi:thermometer",
        "val_tpl": "{% if value_json.mode == 'cool' %}{{ value_json.clsp }}{% elif value_json.mode == 'heat' %}{{ value_json.htsp }}{% endif %}",
        "uniq_id": f"{thermostat_serial}-setpoint",
        "unit_of_meas": "°F",
        "device_class": "temperature"
    }
    client.publish(f'homeassistant/sensor/{thermostat_serial}-setpoint/config', json.dumps(setpoint_sensor_configuration_payload), retain=True)

    fanicon_sensor_configuration_payload = {
        "device": device,
        "stat_t": thermostat_state_topic,
        "name": f"{thermostat_name} Fan Status",
        "val_tpl": "{{ value_json.fanicon }}",
        "ic": "mdi:fan",
        "uniq_id": f"{thermostat_serial}-fanicon"
    }
    client.publish(f'homeassistant/sensor/{thermostat_serial}-fan-status/config', json.dumps(fanicon_sensor_configuration_payload), retain=True)

    hold_sensor_configuration_payload = {
        "device": device,
        "stat_t": thermostat_state_topic,
        "name": f"{thermostat_name} Hold",
        "val_tpl": "{{ value_json.hold }}",
        "ic": "mdi:gesture-tap-hold",
        "uniq_id": f"{thermostat_serial}-hold"
    }
    client.publish(f'homeassistant/sensor/{thermostat_serial}-hold/config', json.dumps(hold_sensor_configuration_payload), retain=True)

    filtrlvl_sensor_configuration_payload = {
        "device": device,
        "stat_t": thermostat_state_topic,
        "name": f"{thermostat_name} Filter Hours Remain",
        "ic": "mdi:clock",
        "val_tpl": "{{ value_json.filtrlvl }}",
        "uniq_id": f"{thermostat_serial}-filtrlvl",
        "unit_of_meas": "h",
        "device_class": "duration"
    }
    client.publish(f'homeassistant/sensor/{thermostat_serial}-filtrlvl/config', json.dumps(filtrlvl_sensor_configuration_payload), retain=True)

    oducoiltmp_sensor_configuration_payload = {
        "device": device,
        "stat_t": thermostat_state_topic,
        "name": f"{thermostat_name} Outdoor Coil Temperature",
        "ic": "mdi:hvac",
        "val_tpl": "{{ value_json.oducoiltmp }}",
        "uniq_id": f"{thermostat_serial}-oducoiltmp",
        "unit_of_meas": "°F",
        "device_class": "temperature"
    }
    client.publish(f'homeassistant/sensor/{thermostat_serial}-oducoiltmp/config', json.dumps(oducoiltmp_sensor_configuration_payload), retain=True)

    oat_sensor_configuration_payload = {
        "device": device,
        "stat_t": thermostat_state_topic,
        "name": f"{thermostat_name} Outdoor Ambient Temperature",
        "ic": "mdi:thermometer",
        "val_tpl": "{{ value_json.oat }}",
        "uniq_id": f"{thermostat_serial}-oat",
        "unit_of_meas": "°F",
        "device_class": "temperature"
    }
    client.publish(f'homeassistant/sensor/{thermostat_serial}-oat/config', json.dumps(oat_sensor_configuration_payload), retain=True)

    iducfm_sensor_configuration_payload = {
        "device": device,
        "stat_t": thermostat_state_topic,
        "name": f"{thermostat_name} Indoor CFM",
        "ic": "mdi:fan",
        "val_tpl": "{{ value_json.iducfm }}",
        "uniq_id": f"{thermostat_serial}-iducfm",
        "unit_of_meas": "cfm"
    }
    client.publish(f'homeassistant/sensor/{thermostat_serial}-iducfm/config', json.dumps(iducfm_sensor_configuration_payload), retain=True)

    last_time_sensor_configuration_payload = {
        "device": device,
        "stat_t": thermostat_state_topic,
        "val_tpl": "{{ value_json.last_communication }}",
        "name": f"{thermostat_name} Last Communication",
        "ic": "mdi:clock",
        "uniq_id": f"{thermostat_serial}-last-time",
        "device_class": "timestamp"
    }
    client.publish(f'homeassistant/sensor/{thermostat_serial}-last-time/config', json.dumps(last_time_sensor_configuration_payload), retain=True)

    logging.info('Published Config Entries')

def on_message(client, userdata, message):
    global changes_pending
    global candidate_configuration
    global current_configuration
    global last_active_mode
    message.payload = message.payload.decode("utf-8")
    logging.info(f'''New message: {message.topic} {message.payload}''')

    if message.topic == f"{thermostat_command_topic}/operating_mode":
        new_operating_mode = message.payload
        changes_pending = True
        candidate_configuration["mode"] = new_operating_mode
        if new_operating_mode in active_modes:
            last_active_mode = new_operating_mode

    elif message.topic == f"{thermostat_command_topic}/preset_mode":
        if message.payload == EHEAT_PRESET:
            changes_pending = True
            candidate_configuration["mode"] = eheat_mode
            last_active_mode = eheat_mode
            logging.info("Emergency heat ON")
        elif message.payload == "none":
            mode_now = candidate_configuration.get("mode", current_configuration.get("mode"))
            if mode_now == eheat_mode:
                changes_pending = True
                candidate_configuration["mode"] = "heat"
                last_active_mode = "heat"
                logging.info("Emergency heat OFF -- back to normal heat")

    elif message.topic.startswith(f"{thermostat_command_topic}/setting/"):
        key = message.topic.rsplit("/", 1)[-1]
        if key not in SETTING_ENTITIES:
            logging.warning(f"Ignoring unknown setting {key}")
            return
        value = message.payload.strip()
        if key in NUMERIC_SETTINGS:
            try:
                value = str(int(float(value)))
            except ValueError:
                logging.warning(f"Ignoring non-numeric value for {key}: {value}")
                return
        changes_pending = True
        pending_settings[key] = value
        current_configuration.update(effective_settings())
        logging.info(f"Queued setting change {key} = {value}")

    elif message.topic == f"{thermostat_command_topic}/power":
        # Separate power on/off command (pow_cmd_t) so Home Assistant's turn_on
        # doesn't have to guess a mode. HA's default ClimateEntity turn_on always
        # picks heat before cool when both are supported, ignoring what mode the
        # thermostat was actually last running -- this restores the real one.
        changes_pending = True
        if message.payload == "ON":
            candidate_configuration["mode"] = last_active_mode
            logging.info(f"Power ON -- restoring last active mode: {last_active_mode}")
        elif message.payload == "OFF":
            candidate_configuration["mode"] = "off"

    elif message.topic == f"{thermostat_command_topic}/fan_mode":
        new_fan_mode = message.payload
        changes_pending = True
        candidate_configuration["fan"] = new_fan_mode

    elif message.topic == f"{thermostat_command_topic}/hold":
        new_hold_mode = message.payload
        changes_pending = True
        candidate_configuration["hold"] = new_hold_mode

    elif message.topic == f"{thermostat_command_topic}/temperature":
        new_temperature = message.payload.split(".")[0]
        
        # Determine active mode (fall back to current_configuration if not set in candidate)
        active_mode = candidate_configuration.get('mode', current_configuration.get('mode'))

        if active_mode == "cool":
            if candidate_configuration.get("clsp") != new_temperature:
                changes_pending = True
                candidate_configuration["clsp"] = new_temperature
                logging.info(f"Updated cooling setpoint (clsp) to {new_temperature}°F")
                
                # Ensure htsp is at least 2 degrees below clsp
                htsp_val = int(candidate_configuration.get("htsp", current_configuration.get("htsp", 0)))
                max_allowed_htsp = int(new_temperature) - 2
                
                if htsp_val > max_allowed_htsp:
                    candidate_configuration["htsp"] = str(max_allowed_htsp)
                    logging.info(f"Clamped heating setpoint (htsp) down to {max_allowed_htsp}°F to maintain 2°F deadband gap")

        elif active_mode in heat_modes:
            if candidate_configuration.get("htsp") != new_temperature:
                changes_pending = True
                candidate_configuration["htsp"] = new_temperature
                logging.info(f"Updated heating setpoint (htsp) to {new_temperature}°F")
                
                # Ensure clsp is at least 2 degrees above htsp
                clsp_val = int(candidate_configuration.get("clsp", current_configuration.get("clsp", 100)))
                min_required_clsp = int(new_temperature) + 2
                
                if clsp_val < min_required_clsp:
                    candidate_configuration["clsp"] = str(min_required_clsp)
                    logging.info(f"Adjusted cooling setpoint (clsp) up to {min_required_clsp}°F to maintain 2°F deadband gap")

    if changes_pending:
        current_configuration["changes_pending"] = "ON"
        client.publish(thermostat_state_topic, str(current_configuration).replace("'", '"').replace("None", '""'), retain=True)

class MyHttpRequestHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, format, *args):
        # Malformed requests fail before command/path are set; don't crash the logger
        if hasattr(self, 'path'):
            logging.info(f"{self.address_string()} -- {self.command} -- {self.path}")
        else:
            logging.info(f"{self.address_string()} -- malformed request -- {format % args}")

    def send_no_changes(self):
        html = f'''<status version="1.9" xmlns:atom="http://www.w3.org/2005/Atom"><atom:link rel="self" href="http://{api_server_address}/systems/{thermostat_serial}/status"/><atom:link rel="http://{api_server_address}/rels/system" href="http://{api_server_address}/systems/{thermostat_serial}"/><timestamp>{datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}</timestamp><pingRate>0</pingRate><dealerConfigPingRate>0</dealerConfigPingRate><weatherPingRate>14400</weatherPingRate><equipEventsPingRate>60</equipEventsPingRate><historyPingRate>86400</historyPingRate><iduFaultsPingRate>86400</iduFaultsPingRate><iduStatusPingRate>86400</iduStatusPingRate><oduFaultsPingRate>86400</oduFaultsPingRate><oduStatusPingRate>0</oduStatusPingRate><configHasChanges>off</configHasChanges><dealerConfigHasChanges>off</dealerHasChanges><dealerHasChanges>off</dealerHasChanges><oduConfigHasChanges>off</oduConfigHasChanges><iduConfigHasChanges>off</iduConfigHasChanges><utilityEventsHasChanges>off</utilityEventsHasChanges></status>'''
        self.send_response(200)
        self.send_header("Content-Length", str(len(html)))
        self.send_header("Connection", "keep-alive")
        self.send_header("Content-Type", "application/xml; charset=utf-8")
        self.end_headers()
        try:
            self.wfile.write(bytes(html, "utf8"))
            self.wfile.flush()
        except BrokenPipeError:
            self.log_error("Client closed connection before response was sent")

    def send_empty_200(self):
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

    def do_GET(self):
        if "/Alive" in self.path:
            html = "alive"
            self.send_response(200)
            self.send_header("Content-Length", "5")
            self.send_header("Connection", "keep-alive")
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(bytes(html, "utf8"))

        elif "/time" in self.path:
            time = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            html = f'''<time version="1.9" xmlns:atom="http://www.w3.org/2005/Atom"><atom:link rel="self" href="http://{api_server_address}/time/"/><utc>{time}</utc></time>'''
            self.send_response(200)
            self.send_header("Content-Length", len(html))
            self.send_header("Connection", "keep-alive")
            self.send_header("Content-Type", "application/xml; charset=utf-8")
            self.end_headers()
            self.wfile.write(bytes(html, "utf8"))

        elif "/config" in self.path:
            global changes_pending
            global current_configuration
            changes_pending = False
            current_configuration["changes_pending"] = "OFF"
            settings = effective_settings()
            logging.info(f'''New configuration: {candidate_configuration} settings: {settings}''')
            html = f'''<config version="1.9" xmlns:atom="http://www.w3.org/2005/Atom"><atom:link rel="self" href="http://{api_server_address}/systems/{thermostat_serial}/config"/><atom:link rel="http://{api_server_address}/rels/system" href="http://{api_server_address}/systems/{thermostat_serial}"/><atom:link rel="http://{api_server_address}/rels/dealer_config" href="http://{api_server_address}/systems/{thermostat_serial}/dealer_config"/><timestamp>{datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}</timestamp><mode>{candidate_configuration["mode"]}</mode><fan>{candidate_configuration["fan"]}</fan><blight>{settings["blight"]}</blight><timeFormat>{settings["timeFormat"]}</timeFormat><dst>{settings["dst"]}</dst><volume>{settings["volume"]}</volume><soundType>{settings["soundType"]}</soundType><scrLockout>{settings["scrLockout"]}</scrLockout><scrLockoutCode>{settings["scrLockoutCode"]}</scrLockoutCode><humSetpoint>{settings["humSetpoint"]}</humSetpoint><dehumSetpoint>{settings["dehumSetpoint"]}</dehumSetpoint><utilityEvent/><zones><zone id="1"><name>Zone 1</name><hold>{candidate_configuration["hold"]}</hold><otmr/><htsp>{candidate_configuration["htsp"]}</htsp><clsp>{candidate_configuration["clsp"]}</clsp><program></program></zone></zones></config>'''
            self.send_response(200)
            self.send_header("Content-Length", len(html))
            self.send_header("Connection", "keep-alive")
            self.send_header("Content-Type", "application/xml; charset=utf-8")
            self.end_headers()
            self.wfile.write(bytes(html, "utf8"))
            # The thermostat now has whatever we just sent; treat queued HA changes as applied
            if pending_settings:
                device_settings.update(pending_settings)
                pending_settings.clear()
                save_settings()
            current_configuration.update(effective_settings())
            client.publish(thermostat_state_topic, str(current_configuration).replace("'", '"').replace("None", '""'), retain=True)

        else:
            # Send 0 length 200 response
            self.send_empty_200()

    def do_POST(self):
        data = self.rfile.read(int(self.headers.get('Content-length'))).decode("utf-8")
        data = unquote(data).strip("data=")
        global current_configuration
        global candidate_configuration
        global first_start
        global last_active_mode

        html = ""
        match = False
        monitored = ["rt","rh","mode","fan","coolicon","heaticon","fanicon","hold","filtrlvl","clsp","htsp","opstat","iducfm","oat","oducoiltmp"]
        # The thermostat reports its own config (on local changes) to /systems/<serial>
        config_paths = ["/config", f"/{thermostat_serial}"]
        paths = ["/status", "/odu_status","/equipment_events", "/profile"] + config_paths # we only need data from these paths
        received_message = {}
        final_locator = f'/{self.path.split("/")[-1:][0]}' # eg /status
        logging.debug(f"{final_locator} -- {data}")

        if len(data) >= 45 and final_locator in paths:
            try: 
                # Parse and create dict of received message
                root = ET.fromstring(data)
                children = list(root)
                if final_locator in config_paths:
                    # Thermostat reporting its own config, as <system><config>...</config></system>.
                    # Only read the top-level device settings; zones/programs repeat tags like
                    # htsp/clsp, so don't flatten this into current_configuration.
                    cfg = root if root.tag == "config" else root.find("config")
                    if cfg is None:
                        self.send_empty_200()
                        return
                    reported = {}
                    for key in SETTING_DEFAULTS:
                        el = cfg.find(key)
                        if el is not None and el.text is not None:
                            reported[key] = el.text.strip()
                    mode_el = cfg.find("mode")
                    logging.debug(f"Thermostat config report: mode={mode_el.text if mode_el is not None else None} settings={reported}")
                    if learn_settings(reported):
                        client.publish(thermostat_state_topic, str(current_configuration).replace("'",'"').replace("None",'""'), retain=True)
                    self.send_empty_200()
                    return
                if "/equipment_events" in final_locator:
                    for child in root.iter():
                        # Only get latest equipment event
                        if child.tag in received_message:
                            continue
                        else:
                            received_message[child.tag] = child.text
                else:
                    for child in root.iter():
                        received_message[child.tag] = child.text
            except:
                if "/status" in self.path:
                    self.send_no_changes()
                else:
                    self.send_empty_200()
                return

            # Build current_configuration with monitored variables
            for option in monitored:
                if option in received_message:
                    current_configuration[option] = received_message[option]

            if current_configuration.get("mode") in active_modes:
                last_active_mode = current_configuration["mode"]

            # We don't need any kind of response for this path
            if "/odu_status" in final_locator:
                self.send_empty_200()

            elif "/equipment_events" in final_locator:
                # Fix for some newer firmware versions
                if "active" in received_message and received_message['active'] == "on":
                    state = f"{received_message['localtime'][1:]}: {received_message['description']}"
                else:
                    state = "No Active Event"
                current_configuration["latest_equip"] = state
                self.send_empty_200()

            elif "/profile" in final_locator:
                # Attempt to grab FW version and update climate device
                try:
                    if climate_configuration_payload["device"]["sw"] != received_message['firmware']:
                        climate_configuration_payload["device"]["sw"] = f"{received_message['firmware']}"
                        client.publish(f'homeassistant/climate/{thermostat_serial}-climate/config', json.dumps(climate_configuration_payload), retain=True)
                except:
                    pass
                self.send_empty_200()

            elif "/status" in final_locator:
                logging.debug(f"Current Configuration: {current_configuration}")
                current_configuration["last_communication"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

                # Initialize candidate_configuration as current_configuration at first start.
                # Use setdefault, not a blind overwrite: a command (e.g. a power on/off) can
                # arrive after container start but before the device's first status check-in,
                # and would otherwise be silently clobbered here once that first status lands.
                if first_start == True:
                    candidate_configuration.setdefault('clsp', current_configuration['clsp'])
                    candidate_configuration.setdefault('htsp', current_configuration['htsp'])
                    candidate_configuration.setdefault('mode', current_configuration['mode'])
                    if current_configuration['mode'] in active_modes:
                        last_active_mode = current_configuration['mode']

                    # Update climate device with client IP
                    climate_configuration_payload["device"]["cns"] = [["ip", self.client_address[0]]]
                    client.publish(f'homeassistant/climate/{thermostat_serial}-climate/config', json.dumps(climate_configuration_payload), retain=True)
                
                    first_start = False
                    self.send_no_changes()

                elif changes_pending == True:
                    logging.info("Responding with change notice...")
                    html = f'''<status version="1.9" xmlns:atom="http://www.w3.org/2005/Atom"><atom:link rel="self" href="http://{api_server_address}/systems/{thermostat_serial}/status"/><atom:link rel="http://{api_server_address}/rels/system" href="http://{api_server_address}/systems/{thermostat_serial}"/><timestamp>{datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}</timestamp><pingRate>0</pingRate><dealerConfigPingRate>0</dealerConfigPingRate><weatherPingRate>14400</weatherPingRate><equipEventsPingRate>60</equipEventsPingRate><historyPingRate>86400</historyPingRate><iduFaultsPingRate>86400</iduFaultsPingRate><iduStatusPingRate>86400</iduStatusPingRate><oduFaultsPingRate>86400</oduFaultsPingRate><oduStatusPingRate>0</oduStatusPingRate><configHasChanges>on</configHasChanges><dealerConfigHasChanges>off</dealerConfigHasChanges><dealerHasChanges>off</dealerHasChanges><oduConfigHasChanges>off</oduConfigHasChanges><iduConfigHasChanges>off</iduConfigHasChanges><utilityEventsHasChanges>off</utilityEventsHasChanges></status>'''
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(html)))
                    self.send_header("Connection", "keep-alive")
                    self.send_header("Content-Type", "application/xml; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(bytes(html, "utf8"))

                else:
                    self.send_no_changes()

            # Update MQTT topic with current states
            client.publish(thermostat_state_topic, str(current_configuration).replace("'",'"').replace("None",'""'), retain=True)

        # Malformed message
        else:
            if "/status" in self.path:
                self.send_no_changes()

            else:
                # Send 0 length 200 response
                self.send_empty_200()

class ThreadingSimpleServer(ThreadingMixIn, HTTPServer):
    pass


client = mqttClient.Client(mqttClient.CallbackAPIVersion.VERSION2, f"thermostat_api_server_{thermostat_serial}")
if "mqtt_username" in locals():
    client.username_pw_set(username=mqtt_username,password=mqtt_password)
server = ThreadingSimpleServer(('0.0.0.0', 8080), MyHttpRequestHandler)

client.on_connect = on_connect
client.on_message = on_message
logging.info("Connecting to MQTT")
client.connect(mqtt_address, mqtt_port)

def handle_stop(signum, frame):
    # Docker/Supervisor stop sends SIGTERM; as PID 1 we must handle it ourselves or get SIGKILLed (exit 137)
    logging.info("Stop requested, shutting down")
    raise SystemExit(0)

signal.signal(signal.SIGTERM, handle_stop)

client.loop_start()
client.subscribe(thermostat_command_topic)
try:
    server.serve_forever()
finally:
    server.server_close()
    client.loop_stop()
    client.disconnect()
    logging.info("Stopped")