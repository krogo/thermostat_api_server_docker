#!/usr/bin/env python3
"""Home Assistant app entry point.

Reads the app options from /data/options.json, fills in MQTT details from the
Supervisor's MQTT service (the Mosquitto broker app) when they aren't set by
hand, exports everything as the environment variables thermostat_api_server.py
expects, and replaces itself with the server process.
"""

import json
import os
import sys
import urllib.request

OPTIONS_FILE = "/data/options.json"
SERVER = "/usr/bin/thermostat_api_server.py"


def log(msg):
    print(f"[run] {msg}", flush=True)


def supervisor_mqtt():
    """Return the MQTT service details from the Supervisor, or None."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None
    req = urllib.request.Request(
        "http://supervisor/services/mqtt",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.load(resp)
    except Exception as err:  # 400 when no MQTT broker app is installed
        log(f"No MQTT service from the Supervisor ({err})")
        return None
    if body.get("result") != "ok":
        return None
    return body.get("data") or None


def main():
    try:
        with open(OPTIONS_FILE) as f:
            opts = json.load(f)
    except FileNotFoundError:
        log(f"{OPTIONS_FILE} not found; using the environment as-is")
        os.execv(sys.executable, [sys.executable, "-u", SERVER])

    env = os.environ
    env["THERMOSTAT_NAME"] = opts["thermostat_name"]
    env["THERMOSTAT_SERIAL"] = opts["thermostat_serial"]
    env["API_SERVER_ADDRESS"] = opts["api_server_address"]
    env["LOG_LEVEL"] = opts.get("log_level", "INFO")
    env["EMERGENCY_HEAT_MODE"] = opts.get("emergency_heat_mode", "eheat")
    env["STATUS_PING_RATE"] = str(opts.get("status_ping_rate", 0))
    env["ODU_STATUS_PING_RATE"] = str(opts.get("odu_status_ping_rate", 0))

    if opts.get("mqtt_host"):
        log(f"Using MQTT broker from options: {opts['mqtt_host']}")
        env["MQTT_SERVER"] = opts["mqtt_host"]
        env["MQTT_PORT"] = str(opts.get("mqtt_port", 1883))
        user, password = opts.get("mqtt_username"), opts.get("mqtt_password", "")
    else:
        svc = supervisor_mqtt()
        if not svc:
            log("No MQTT broker found. Install the Mosquitto broker app, "
                "or set mqtt_host on the Configuration tab.")
            sys.exit(1)
        if svc.get("ssl"):
            log("Warning: the MQTT service reports SSL, which this server "
                "doesn't support. Set mqtt_host/mqtt_port by hand if it fails.")
        log(f"Using MQTT broker from the Supervisor: {svc['host']}:{svc['port']}")
        env["MQTT_SERVER"] = svc["host"]
        env["MQTT_PORT"] = str(svc["port"])
        user, password = svc.get("username"), svc.get("password", "")

    # The server only logs in when MQTT_USERNAME is present
    env.pop("MQTT_USERNAME", None)
    env.pop("MQTT_PASSWORD", None)
    if user:
        env["MQTT_USERNAME"] = user
        env["MQTT_PASSWORD"] = password or ""

    os.execv(sys.executable, [sys.executable, "-u", SERVER])


if __name__ == "__main__":
    main()
