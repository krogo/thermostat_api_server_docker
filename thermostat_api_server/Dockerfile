FROM python:3.13-alpine

RUN pip install --no-cache-dir "paho-mqtt>=2.0,<3"

COPY thermostat_api_server.py run.py /usr/bin/

# Learned thermostat settings persist in the app's /data folder
ENV SETTINGS_FILE=/data/thermostat_settings.json

EXPOSE 8080

# run.py reads /data/options.json, finds MQTT, then execs the server
ENTRYPOINT ["python", "-u", "/usr/bin/run.py"]
