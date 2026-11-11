FROM ghcr.io/aneisch/thermostat_api_server:latest

# Run this fork's server instead of the stock one (copy thermostat_api_server.py into this folder)
COPY thermostat_api_server.py /usr/bin/thermostat_api_server.py

# Root so the server can write learned settings to the app's /data folder
USER root

# Exec form so Python (not /bin/sh) receives the stop signal
ENTRYPOINT ["python", "-u", "/usr/bin/thermostat_api_server.py"]

ENV THERMOSTAT_NAME="House Main" \
    THERMOSTAT_SERIAL="your_serial" \
    MQTT_SERVER="core-mosquitto" \
    MQTT_PORT="1883" \
    MQTT_USERNAME="your_mqtt_user" \
    MQTT_PASSWORD="your_mqtt_pass" \
    API_SERVER_ADDRESS="HA_LAN_IP" \
    LOG_LEVEL="INFO" \
    EMERGENCY_HEAT_MODE="eheat" \
    SETTINGS_FILE="/data/thermostat_settings.json"
