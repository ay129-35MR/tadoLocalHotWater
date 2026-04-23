#!/usr/bin/env python3
"""
Hot Water Observer
==================

Observer-only. Polls HA + ETH01, writes a snapshot to status.json for a
homepage widget. Does NOT actuate anything — actuation lives in HA wrapper
scripts and ETH01 survival mode.

Run as a systemd service (see hot-water-observer.service) or any other
supervisor. Idempotent; safe to restart freely.

CONFIGURE:
  - ESPHOME_IP   : your ETH01's IP
  - HA_URL       : your HA's URL
  - HA_TOKEN     : long-lived access token (Settings → Profile → Security)
  - STATUS_FILE  : where to write the snapshot
"""

import json
import logging
import os
import sys
import time
from datetime import datetime

try:
    import requests
except ImportError:
    print("Please install requests: pip install requests")
    sys.exit(1)

# ============================================================================
# CONFIGURATION
# ============================================================================
ESPHOME_IP = os.environ.get("ESPHOME_IP", "192.168.1.X")
ESPHOME_SENSOR_ID = "hotwatertemp32"
ESPHOME_URL = f"http://{ESPHOME_IP}/sensor/{ESPHOME_SENSOR_ID}"

HA_URL = os.environ.get("HA_URL", "http://homeassistant.local:8123")
HA_TOKEN = os.environ.get("HA_TOKEN", "REPLACE_WITH_YOUR_LONG_LIVED_HA_TOKEN")

STATUS_FILE = os.environ.get(
    "STATUS_FILE", "/var/lib/hot-water-observer/status.json"
)
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "60"))

LOG_LEVEL = logging.INFO
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"

# Entities polled from HA. ETH01 entities are auto-prefixed `hotwatertemp_` by
# ESPHome's HA integration. Adapt the Tado-side entity IDs to your install:
#   - bu*_connection_state, ib*_connection_state are device-specific to your
#     hardware; use binary_sensor.hot_water_connectivity instead (zone-scoped,
#     stable across BU01 replacements).
ENTITIES = {
    "relay_state":        "switch.hotwatertemp_hot_water_relay",
    "tado_state":         "switch.t_hot_water_boiler",
    "actuator":           "input_select.hot_water_actuator",
    "survival_active":    "binary_sensor.hotwatertemp_hot_water_survival_active",
    "watchdog_lockout":   "binary_sensor.hotwatertemp_hot_water_watchdog_lockout",
    "heartbeat_healthy":  "binary_sensor.hotwatertemp_hot_water_ha_heartbeat_healthy",
    "tado_zone_online":   "binary_sensor.hot_water_connectivity",
    "tado_bridge_online": "binary_sensor.ib_internet_bridge_connection_state",  # ← rename to your IB device
    "tado_overlay":       "binary_sensor.hot_water_overlay",
}

logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT)
log = logging.getLogger("hw_observer")


def _ha_headers():
    return {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}


def ha_healthy() -> bool:
    try:
        r = requests.get(f"{HA_URL}/api/", headers=_ha_headers(), timeout=5)
        return r.status_code == 200
    except requests.exceptions.RequestException:
        return False


def get_temp_esphome() -> float | None:
    try:
        r = requests.get(ESPHOME_URL, timeout=5)
        r.raise_for_status()
        d = r.json()
        return float(d.get("value", str(d.get("state", "")).split()[0]))
    except Exception as e:
        log.debug(f"ESPHome temp read failed: {e}")
        return None


def get_temp_ha() -> float | None:
    try:
        r = requests.get(f"{HA_URL}/api/states/sensor.hotwatertemp32",
                         headers=_ha_headers(), timeout=5)
        r.raise_for_status()
        return float(r.json()["state"])
    except Exception as e:
        log.debug(f"HA temp read failed: {e}")
        return None


def get_temp() -> tuple[float | None, str]:
    t = get_temp_esphome()
    if t is not None:
        return t, "ESPHome"
    t = get_temp_ha()
    if t is not None:
        return t, "HA API"
    return None, "None"


def get_ha_entity(entity_id: str) -> str | None:
    try:
        r = requests.get(f"{HA_URL}/api/states/{entity_id}",
                         headers=_ha_headers(), timeout=5)
        r.raise_for_status()
        return r.json().get("state")
    except Exception as e:
        log.debug(f"HA entity {entity_id} read failed: {e}")
        return None


def write_status(temp, temp_source, ha_up, observed):
    data = {
        "mode": "HA Online (Observer)" if ha_up else "HA Down (Observer)",
        "last_check": datetime.now().strftime("%H:%M:%S"),
        "last_check_iso": datetime.now().isoformat(),
        "temp": f"{temp:.1f}" if temp is not None else "--",
        "temp_source": temp_source,
        "ha_healthy": ha_up,
        "relay_state":        observed.get("relay_state", "unknown"),
        "heater_state":       observed.get("tado_state", "unknown"),
        "actuator":           observed.get("actuator", "unknown"),
        "survival_active":    observed.get("survival_active", "unknown"),
        "watchdog_lockout":   observed.get("watchdog_lockout", "unknown"),
        "heartbeat_healthy":  observed.get("heartbeat_healthy", "unknown"),
        "tado_zone_online":   observed.get("tado_zone_online", "unknown"),
        "tado_bridge_online": observed.get("tado_bridge_online", "unknown"),
        "tado_overlay":       observed.get("tado_overlay", "unknown"),
        "status": _status_line(temp, ha_up, observed),
    }
    try:
        os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
        with open(STATUS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.error(f"Failed to write status.json: {e}")


def _status_line(temp, ha_up, observed):
    if not ha_up:
        return "HA unreachable — ETH01 survival mode may be active"
    if observed.get("watchdog_lockout") == "on":
        return "WATCHDOG LOCKOUT — clear from HA button"
    if observed.get("survival_active") == "on":
        return "Survival mode active (HA heartbeat stale on ETH01)"
    actuator = observed.get("actuator", "?")
    relay = observed.get("relay_state", "?")
    tado = observed.get("tado_state", "?")
    zone = observed.get("tado_zone_online", "?")
    bridge = observed.get("tado_bridge_online", "?")
    warn = ""
    if actuator == "tado":
        if bridge == "off":
            warn = " ⚠ TADO BRIDGE DOWN — switch actuator to relay"
        elif zone == "off":
            warn = " ⚠ TADO HW ZONE OFFLINE — switch actuator to relay"
    if temp is None:
        return f"Temp unavailable | actuator={actuator} tado={tado} relay={relay}{warn}"
    return f"OK {temp:.1f}°C | actuator={actuator} tado={tado} relay={relay}{warn}"


def main():
    log.info("Hot Water Observer starting — observer-only, no actuation")
    log.info(f"ESPHome: {ESPHOME_URL}")
    log.info(f"HA: {HA_URL}")
    log.info(f"Status file: {STATUS_FILE}")

    while True:
        try:
            ha_up = ha_healthy()
            temp, temp_src = get_temp()

            observed = {}
            if ha_up:
                for key, eid in ENTITIES.items():
                    observed[key] = get_ha_entity(eid) or "unknown"

            write_status(temp, temp_src, ha_up, observed)
        except Exception as e:
            log.error(f"Unexpected error in observer loop: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Stopped by user")
        sys.exit(0)
