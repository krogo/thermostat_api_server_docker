# Thermostat MQTT container
<a href="https://www.buymeacoffee.com/aneisch" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/default-black.png" width="150px" height="35px" alt="Buy Me A Coffee" style="height: 35px !important;width: 150px !important;" ></a><br>

Acts as API server for Observer Communicating HVAC controller (TSTAT0201CW). Bridges MQTT and thermostat for control through applications such as Home Assistant. You'll need to point your thermostat at this application by modifying the observer server address on the thermostat. Depending on your thermostat's firmware version, certain functionaly may or may not be supported. 

## Usage


### Example docker-compose

```yaml
version: '3.2'
services:
    thermostat_api_server:
        container_name: thermostat_api_server
        image: ghcr.io/aneisch/thermostat_api_server:latest # amd64, or latest-arm64 for ARM devices
        ports:
            - '8080:8080'
        environment:
            # Name for Device in HA
            - THERMOSTAT_NAME=Upstairs
            - THERMOSTAT_SERIAL=5687J272316
            - MQTT_SERVER=10.0.1.22 # This can be an internal docker IP or an IP on your "real" network that exposes the MQTT service
            # Optional MQTT_PORT - defaults to 1883
            #- MQTT_PORT=1883
            # Optional username/password
            #- MQTT_USERNAME=username
            #- MQTT_PASSWORD=password
            # Used in reply to thermostat
            - API_SERVER_ADDRESS=10.0.1.22 # This should be the IP where a wifi client can access this container port 8080, NOT an internal docker IP
            - LOG_LEVEL=DEBUG # DEBUG INFO
            # Optional: raw mode string your thermostat uses for emergency heat (default eheat)
            #- EMERGENCY_HEAT_MODE=eheat
        volumes:
            # Learned device settings (backlight, volume, humidity setpoints...) persist here
            - ./thermostat_data:/data
        restart: always
```
### Home Assistant Configuration

Uses [MQTT Discovery](https://www.home-assistant.io/docs/mqtt/discovery/) to add climate device and associated sensors. If MQTT discovery is enabled, no configuration should be necessary aside from setting container environment variables.  

![Home Assistant Entities](entities.png)

### Emergency heat and device settings (krogo fork)

- Emergency heat appears in Home Assistant as the **Emergency Heat** preset on the climate entity (HVAC mode shows *heat*). Selecting the preset sends the `EMERGENCY_HEAT_MODE` mode string to the thermostat; clearing it returns to normal heat. To confirm the right string for your firmware, put the thermostat in emergency heat at the wall and look at the *Operating Mode* sensor.
- Backlight, volume, sound type, time format, DST, screen lockout and humidify/dehumidify setpoints are no longer forced to fixed values on every config push. They are learned from the configuration the thermostat reports, saved to `SETTINGS_FILE`, and sent back unchanged. Each one (except the lockout code) is exposed as a configuration entity on the device so it can be changed from Home Assistant. Until the thermostat reports its config, the previous hardcoded values are used.
