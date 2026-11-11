/*
 * Observer Thermostat Card
 * Lovelace card for the thermostat_api_server climate entity (Observer / Heil TSTAT0201CW).
 * Shows Emergency Heat as a fourth mode button (it is a climate preset under the hood),
 * plus equipment status, humidity, outdoor temperature and filter hours.
 *
 * type: custom:observer-thermostat-card
 * entity: climate.house_main
 * # optional overrides (defaults are derived from the climate entity id):
 * name: House
 * eheat_preset: Emergency Heat
 * humidity_entity: sensor.house_main_humidity
 * outdoor_entity: sensor.house_main_outdoor_ambient_temperature
 * filter_entity: sensor.house_main_filter_hours_remain
 * fan_status_entity: sensor.house_main_fan_status
 * outdoor_unit_entity: sensor.house_main_outdoor_unit
 * pending_entity: binary_sensor.house_main_changes_pending
 */

const CARD_VERSION = "1.0.0";

const MODE_DEFS = {
  off:   { label: "Off",    icon: "mdi:power",            cls: "off" },
  heat:  { label: "Heat",   icon: "mdi:fire",             cls: "heat" },
  eheat: { label: "E-Heat", icon: "mdi:fire-alert",       cls: "eheat" },
  cool:  { label: "Cool",   icon: "mdi:snowflake",        cls: "cool" },
  heat_cool: { label: "Auto", icon: "mdi:sun-snowflake-variant", cls: "auto" },
  auto:  { label: "Auto",   icon: "mdi:thermostat-auto",  cls: "auto" },
  fan_only: { label: "Fan", icon: "mdi:fan",              cls: "off" },
  dry:   { label: "Dry",    icon: "mdi:water-percent",    cls: "off" },
};
const MODE_ORDER = ["off", "heat", "eheat", "cool", "heat_cool", "auto", "fan_only", "dry"];
const FAN_LABELS = { auto: "Auto", low: "Low", med: "Med", medium: "Med", high: "High", on: "On" };
const SETPOINT_DEBOUNCE_MS = 1500;

class ObserverThermostatCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.entity || !config.entity.startsWith("climate.")) {
      throw new Error("Set 'entity' to your thermostat's climate entity, e.g. climate.house_main");
    }
    const base = config.entity.split(".")[1];
    this._config = {
      eheat_preset: "Emergency Heat",
      humidity_entity: `sensor.${base}_humidity`,
      outdoor_entity: `sensor.${base}_outdoor_ambient_temperature`,
      filter_entity: `sensor.${base}_filter_hours_remain`,
      fan_status_entity: `sensor.${base}_fan_status`,
      outdoor_unit_entity: `sensor.${base}_outdoor_unit`,
      pending_entity: `binary_sensor.${base}_changes_pending`,
      ...config,
    };
    this._pendingTarget = null;
    if (this._root) this._update();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._root) this._build();
    this._update();
  }

  getCardSize() { return 6; }

  static getStubConfig(hass) {
    const climate = Object.keys(hass.states).find((e) => e.startsWith("climate."));
    return { entity: climate || "climate.house_main" };
  }

  // ---------- helpers ----------
  _state(id) { return id && this._hass ? this._hass.states[id] : undefined; }
  _val(id) {
    const s = this._state(id);
    if (!s || s.state === "unavailable" || s.state === "unknown" || s.state === "") return null;
    return s.state;
  }
  _call(service, data) {
    return this._hass.callService("climate", service, { entity_id: this._config.entity, ...data });
  }
  _currentMode(st) {
    if (st.attributes.preset_mode === this._config.eheat_preset) return "eheat";
    return st.state;
  }
  _hasEheat(st) {
    return (st.attributes.preset_modes || []).includes(this._config.eheat_preset);
  }

  // ---------- DOM ----------
  _build() {
    this._root = this.attachShadow({ mode: "open" });
    this._root.innerHTML = `
      <style>
        :host { --heat: var(--state-climate-heat-color, #ff8100); --cool: var(--state-climate-cool-color, #2b9af9);
                --eheat: var(--error-color, #db4437); --auto: var(--state-climate-heat_cool-color, #008000); }
        ha-card { padding: 16px; }
        .top { display: flex; justify-content: space-between; align-items: baseline; }
        .name { font-size: 1.2em; font-weight: 500; }
        .pending { font-size: 0.8em; color: var(--secondary-text-color); display: none; align-items: center; gap: 4px; }
        .pending.show { display: inline-flex; }
        .pending ha-icon { --mdc-icon-size: 16px; animation: spin 2s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }
        .main { display: flex; align-items: center; justify-content: space-between; margin: 12px 0 4px; }
        .current { color: var(--secondary-text-color); }
        .current .big { font-size: 2.2em; color: var(--primary-text-color); font-weight: 300; }
        .setpoint { display: flex; align-items: center; gap: 10px; }
        .target { font-size: 3em; font-weight: 400; min-width: 2.2em; text-align: center; line-height: 1; }
        .target.mode-heat { color: var(--heat); } .target.mode-eheat { color: var(--eheat); }
        .target.mode-cool { color: var(--cool); } .target.mode-off { color: var(--disabled-text-color, #888); font-size: 2em; }
        .target.dirty { opacity: 0.6; }
        .round { width: 44px; height: 44px; border-radius: 50%; border: 1px solid var(--divider-color);
                 background: none; color: var(--primary-text-color); cursor: pointer; display: grid; place-items: center; }
        .round:disabled { opacity: 0.3; cursor: default; }
        .status { display: flex; flex-wrap: wrap; gap: 6px 14px; color: var(--secondary-text-color); font-size: 0.9em; margin: 8px 0 14px; }
        .status span { display: inline-flex; align-items: center; gap: 4px; }
        .status ha-icon { --mdc-icon-size: 18px; }
        .status .act-heating ha-icon { color: var(--heat); } .status .act-cooling ha-icon { color: var(--cool); }
        .status .act-eheat ha-icon { color: var(--eheat); }
        .label { font-size: 0.75em; text-transform: uppercase; letter-spacing: 0.05em; color: var(--secondary-text-color); margin: 10px 0 6px; }
        .row { display: flex; gap: 6px; }
        .row button { flex: 1; border: 1px solid var(--divider-color); border-radius: 10px; background: none; color: var(--primary-text-color);
                      padding: 8px 4px; cursor: pointer; display: flex; flex-direction: column; align-items: center; gap: 2px; font: inherit; font-size: 0.85em; }
        .row button ha-icon { --mdc-icon-size: 20px; }
        .row button.active { color: var(--text-primary-color, #fff); border-color: transparent; }
        .row button.active.heat { background: var(--heat); } .row button.active.cool { background: var(--cool); }
        .row button.active.eheat { background: var(--eheat); } .row button.active.auto { background: var(--auto); }
        .row button.active.off, .row button.active.fan { background: var(--primary-color); }
        .info { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--divider-color); }
        .info div { display: flex; flex-direction: column; align-items: center; cursor: pointer; }
        .info .v { font-size: 1.1em; } .info .k { font-size: 0.75em; color: var(--secondary-text-color); }
        .info .k ha-icon { --mdc-icon-size: 14px; }
        .warn { color: var(--warning-color, #ffa600); }
        .missing { padding: 8px; color: var(--error-color); }
      </style>
      <ha-card>
        <div class="missing" hidden></div>
        <div class="body">
          <div class="top"><span class="name"></span><span class="pending"><ha-icon icon="mdi:sync"></ha-icon>Sending to thermostat…</span></div>
          <div class="main">
            <div class="current"><div class="big"><span class="cur"></span></div><div>Inside</div></div>
            <div class="setpoint">
              <button class="round minus" title="Lower"><ha-icon icon="mdi:minus"></ha-icon></button>
              <div class="target"></div>
              <button class="round plus" title="Raise"><ha-icon icon="mdi:plus"></ha-icon></button>
            </div>
          </div>
          <div class="status"></div>
          <div class="label">Mode</div><div class="row modes"></div>
          <div class="label">Fan</div><div class="row fans"></div>
          <div class="info">
            <div class="i-hum"><span class="v"></span><span class="k"><ha-icon icon="mdi:water-percent"></ha-icon> Humidity</span></div>
            <div class="i-out"><span class="v"></span><span class="k"><ha-icon icon="mdi:home-thermometer-outline"></ha-icon> Outside</span></div>
            <div class="i-filter"><span class="v"></span><span class="k"><ha-icon icon="mdi:air-filter"></ha-icon> Filter</span></div>
          </div>
        </div>
      </ha-card>`;
    const $ = (s) => this._root.querySelector(s);
    this._el = {
      missing: $(".missing"), body: $(".body"), name: $(".name"), pending: $(".pending"), cur: $(".cur"),
      target: $(".target"), minus: $(".minus"), plus: $(".plus"), status: $(".status"),
      modes: $(".modes"), fans: $(".fans"),
      hum: $(".i-hum .v"), out: $(".i-out .v"), filter: $(".i-filter .v"),
    };
    this._el.minus.addEventListener("click", () => this._step(-1));
    this._el.plus.addEventListener("click", () => this._step(1));
    $(".i-hum").addEventListener("click", () => this._moreInfo(this._config.humidity_entity));
    $(".i-out").addEventListener("click", () => this._moreInfo(this._config.outdoor_entity));
    $(".i-filter").addEventListener("click", () => this._moreInfo(this._config.filter_entity));
    $(".name").addEventListener("click", () => this._moreInfo(this._config.entity));
    this._modeKey = this._fanKey = null;
  }

  _moreInfo(entityId) {
    if (!this._state(entityId)) return;
    this.dispatchEvent(new CustomEvent("hass-more-info", { bubbles: true, composed: true, detail: { entityId } }));
  }

  _step(dir) {
    const st = this._state(this._config.entity);
    if (!st) return;
    const a = st.attributes;
    const step = a.target_temp_step || 1;
    const base = this._pendingTarget ?? a.temperature;
    if (base == null) return;
    const next = Math.min(a.max_temp ?? 95, Math.max(a.min_temp ?? 45, Math.round((base + dir * step) * 10) / 10));
    this._pendingTarget = next;
    this._update();
    clearTimeout(this._debounce);
    this._debounce = setTimeout(() => {
      const t = this._pendingTarget;
      this._call("set_temperature", { temperature: t }).finally(() => {
        // keep showing the local value until HA reports it (or give up after 20 s)
        this._sentAt = Date.now();
      });
    }, SETPOINT_DEBOUNCE_MS);
  }

  _setMode(mode, st) {
    if (mode === "eheat") return this._call("set_preset_mode", { preset_mode: this._config.eheat_preset });
    if (mode === "heat" && this._currentMode(st) === "eheat") return this._call("set_preset_mode", { preset_mode: "none" });
    return this._call("set_hvac_mode", { hvac_mode: mode });
  }

  _renderButtons(container, items, activeKey, onClick, keyName) {
    const sig = items.map((i) => i.key).join(",");
    if (this[keyName] !== sig) {
      container.innerHTML = "";
      for (const it of items) {
        const b = document.createElement("button");
        b.dataset.key = it.key;
        b.className = it.cls;
        if (it.icon) { const ic = document.createElement("ha-icon"); ic.setAttribute("icon", it.icon); b.appendChild(ic); }
        const sp = document.createElement("span"); sp.textContent = it.label; b.appendChild(sp);
        b.addEventListener("click", () => onClick(it.key));
        container.appendChild(b);
      }
      this[keyName] = sig;
    }
    for (const b of container.children) b.classList.toggle("active", b.dataset.key === activeKey);
  }

  _update() {
    if (!this._root || !this._hass || !this._config) return;
    const e = this._el;
    const st = this._state(this._config.entity);
    if (!st) {
      e.missing.hidden = false; e.body.hidden = true;
      e.missing.textContent = `Entity not found: ${this._config.entity}`;
      return;
    }
    e.missing.hidden = true; e.body.hidden = false;
    const a = st.attributes;
    const unit = this._hass.config?.unit_system?.temperature || "°F";
    const mode = this._currentMode(st);

    e.name.textContent = this._config.name || a.friendly_name || this._config.entity;
    e.cur.textContent = a.current_temperature != null ? `${a.current_temperature}${unit}` : "—";

    // Setpoint (local value wins while a change is in flight)
    if (this._pendingTarget != null && this._sentAt &&
        (a.temperature === this._pendingTarget || Date.now() - this._sentAt > 20000)) {
      this._pendingTarget = null; this._sentAt = null;
    }
    const target = this._pendingTarget ?? a.temperature;
    const off = st.state === "off";
    e.target.className = `target mode-${off ? "off" : mode}` + (this._pendingTarget != null ? " dirty" : "");
    e.target.textContent = off ? "Off" : (target != null ? `${target}°` : "—");
    e.minus.disabled = e.plus.disabled = off || target == null;

    // Waiting for the thermostat to pick up a change (it polls the server)
    e.pending.classList.toggle("show", this._val(this._config.pending_entity) === "on" || this._pendingTarget != null);

    // Status line
    const parts = [];
    const action = a.hvac_action;
    if (action === "heating") parts.push(["mdi:fire", mode === "eheat" ? "Heating — furnace (E-Heat)" : "Heating", mode === "eheat" ? "act-eheat" : "act-heating"]);
    else if (action === "cooling") parts.push(["mdi:snowflake", "Cooling", "act-cooling"]);
    else if (action) parts.push(["mdi:power-sleep", action === "off" ? "Off" : "Idle", ""]);
    else if (mode === "eheat") parts.push(["mdi:fire-alert", "E-Heat (furnace only)", "act-eheat"]);
    const fan = this._val(this._config.fan_status_entity);
    if (fan === "on") parts.push(["mdi:fan", "Fan running", ""]);
    const odu = this._val(this._config.outdoor_unit_entity);
    if (odu) parts.push(["mdi:heat-pump-outline", `Outdoor unit: ${odu}`, ""]);
    e.status.innerHTML = "";
    for (const [icon, text, cls] of parts) {
      const s = document.createElement("span"); if (cls) s.className = cls;
      const ic = document.createElement("ha-icon"); ic.setAttribute("icon", icon); s.appendChild(ic);
      s.appendChild(document.createTextNode(text)); e.status.appendChild(s);
    }

    // Mode buttons
    const modes = [...(a.hvac_modes || [])];
    if (this._hasEheat(st) && !modes.includes("eheat")) modes.push("eheat");
    const modeItems = MODE_ORDER.filter((m) => modes.includes(m)).map((m) => ({ key: m, ...MODE_DEFS[m] }));
    this._renderButtons(e.modes, modeItems, mode, (m) => this._setMode(m, this._state(this._config.entity)), "_modeKey");

    // Fan buttons
    const fanItems = (a.fan_modes || []).map((f) => ({ key: f, label: FAN_LABELS[f] || f, cls: "fan" }));
    this._renderButtons(e.fans, fanItems, a.fan_mode, (f) => this._call("set_fan_mode", { fan_mode: f }), "_fanKey");

    // Info row
    const hum = this._val(this._config.humidity_entity) ?? a.current_humidity;
    e.hum.textContent = hum != null ? `${Math.round(hum)}%` : "—";
    e.hum.classList.toggle("warn", hum != null && Number(hum) >= 60);
    const out = this._val(this._config.outdoor_entity);
    e.out.textContent = out != null ? `${out}${unit}` : "—";
    const filt = this._val(this._config.filter_entity);
    e.filter.textContent = filt != null ? `${Number(filt).toLocaleString()} h` : "—";
  }
}

customElements.define("observer-thermostat-card", ObserverThermostatCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "observer-thermostat-card",
  name: "Observer Thermostat Card",
  description: "Observer/Heil communicating thermostat with Emergency Heat mode button",
});
console.info(`%c OBSERVER-THERMOSTAT-CARD %c ${CARD_VERSION} `, "color:white;background:#db4437", "color:#db4437;background:white");
