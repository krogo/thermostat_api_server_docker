# Observer Thermostat Card

A Lovelace card for this server's climate entity. Emergency Heat is a fourth mode button (Off / Heat / E-Heat / Cool) instead of a separate Preset box. The card also shows equipment status, humidity, outdoor temperature and filter hours.

## Install

1. Copy `observer-thermostat-card.js` to `/config/www/` (it's `www` inside the `config` Samba share; create the folder if it doesn't exist).
2. **Settings → Dashboards → ⋮ → Resources → Add resource**: URL `/local/observer-thermostat-card.js?v=1`, type **JavaScript module**. If the Resources menu isn't there, turn on Advanced mode in your user profile.
3. Reload the browser, then add a card. It appears in the card picker as "Observer Thermostat Card", or you can use YAML:

```yaml
type: custom:observer-thermostat-card
entity: climate.house_main
```

After updating the JS file, bump `?v=` in the resource URL (or hard-refresh) so browsers don't keep the cached copy.

## Options

| Option | Default |
|---|---|
| `entity` (required) | — |
| `name` | entity's friendly name |
| `eheat_preset` | `Emergency Heat` |
| `humidity_entity` | `sensor.<base>_humidity` |
| `outdoor_entity` | `sensor.<base>_outdoor_ambient_temperature` |
| `filter_entity` | `sensor.<base>_filter_hours_remain` |
| `fan_status_entity` | `sensor.<base>_fan_status` |
| `outdoor_unit_entity` | `sensor.<base>_outdoor_unit` (server 1.0.3+) |
| `pending_entity` | `binary_sensor.<base>_changes_pending` |

`<base>` is the climate entity id without `climate.`. Override an option only if your sensor entity ids differ.

## Behaviour

- **+ / −** changes the setpoint locally. The change is sent 1.5 s after the last press, so tapping several times sends a single update.
- **"Sending to thermostat…"** is shown until the thermostat picks up the change. The thermostat polls the server, so this usually takes a few seconds.
- **E-Heat** sets the `Emergency Heat` preset. On this dual-fuel system that means furnace only, with the heat pump off. **Heat** while in E-Heat clears the preset.
- **Clicking the name** or an info value opens HA's standard dialog. That dialog still shows the Preset box, because a card can't change it.
- **Humidity** is shown in the warning color at 60 % or above.
