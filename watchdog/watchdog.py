#!/usr/bin/env python3
"""
Hot Water External Watchdog
===========================

Polls HA + ETH01 directly. Pushes via ntfy.sh when:

  1. HA is unreachable AND tank temp is rising ≥3 °C from baseline at outage
     start → boiler firing without HA control (likely Tado schedule).
  2. HA is unreachable AND ETH01 is also unreachable → total blackout.

Notification path is fully outside HA, so it works when HA is exactly the
thing that's broken.

Can run as a standalone systemd service, a Flask background thread inside
another app you already have, or a simple cron-driven script.

CONFIGURE via environment:
  HA_URL, HA_TOKEN, ESPHOME_IP, NTFY_TOPIC, optional NTFY_URL
"""

import os
import threading
import time
from datetime import datetime

try:
    import requests
except ImportError:
    raise SystemExit("Install requests: pip install requests")

# ============================================================================
# CONFIGURATION
# ============================================================================
HA_URL     = os.environ.get("HA_URL",     "http://homeassistant.local:8123")
HA_TOKEN   = os.environ.get("HA_TOKEN",   "REPLACE_WITH_YOUR_LONG_LIVED_HA_TOKEN")
ESPHOME_IP = os.environ.get("ESPHOME_IP", "192.168.1.X")
ETH01_TEMP_URL = f"http://{ESPHOME_IP}/sensor/hotwatertemp32"

WATCHDOG_INTERVAL          = 60        # seconds between checks
WATCHDOG_HA_DOWN_GRACE     = 10 * 60   # 10 min before flagging HA "really down"
WATCHDOG_TEMP_RISE_THRESHOLD = 3.0     # °C rise => something is firing the boiler
WATCHDOG_ALERT_COOLDOWN    = 30 * 60   # don't repeat alerts more than every 30 min

# Make this UNGUESSABLE — anyone subscribed to it gets the alerts.
# Suggestion: yourname-hot-water-<random base32>
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")     # empty disables push
NTFY_URL   = os.environ.get("NTFY_URL", "https://ntfy.sh")

state = {
    "running": False,
    "last_check": None,
    "ha_ok": None,
    "eth01_ok": None,
    "tank_temp": None,
    "ha_down_since": None,
    "tank_temp_baseline": None,
    "alerts_sent": 0,
    "last_alert_at": None,
    "last_alert_reason": None,
    "ntfy_configured": bool(NTFY_TOPIC),
}
state_lock = threading.Lock()


def _check_ha():
    try:
        r = requests.get(f"{HA_URL}/api/",
                         headers={"Authorization": f"Bearer {HA_TOKEN}"},
                         timeout=5)
        return r.status_code == 200
    except requests.RequestException:
        return False


def _read_temp():
    try:
        r = requests.get(ETH01_TEMP_URL, timeout=5)
        if r.status_code == 200:
            d = r.json()
            return float(d.get("value", str(d.get("state", "")).split()[0]))
    except (requests.RequestException, ValueError, KeyError, IndexError):
        pass
    return None


def _push(reason: str):
    if not NTFY_TOPIC:
        return
    try:
        requests.post(
            f"{NTFY_URL}/{NTFY_TOPIC}",
            data=reason.encode("utf-8"),
            headers={
                "Title": "Hot Water Watchdog",
                "Priority": "urgent",
                "Tags": "warning,fire",
            },
            timeout=5,
        )
    except requests.RequestException as e:
        print(f"[watchdog] ntfy push failed: {e}", flush=True)


def _alert(now, reason):
    with state_lock:
        last = state["last_alert_at"]
        if last and (now - last) < WATCHDOG_ALERT_COOLDOWN:
            return
        state["last_alert_at"] = now
        state["last_alert_reason"] = reason
        state["alerts_sent"] += 1
    print(f"[watchdog] ALERT: {reason}", flush=True)
    _push(reason)


def tick():
    now = time.time()
    ha_ok = _check_ha()
    tank = _read_temp()

    with state_lock:
        state["last_check"] = datetime.now().isoformat()
        state["ha_ok"] = ha_ok
        state["eth01_ok"] = tank is not None
        state["tank_temp"] = tank

        if ha_ok:
            state["ha_down_since"] = None
            state["tank_temp_baseline"] = None
        else:
            if state["ha_down_since"] is None:
                state["ha_down_since"] = now
                state["tank_temp_baseline"] = tank

        ha_down_since = state["ha_down_since"]
        baseline = state["tank_temp_baseline"]

    if ha_ok or ha_down_since is None:
        return

    ha_down_for = now - ha_down_since
    if ha_down_for < WATCHDOG_HA_DOWN_GRACE:
        return

    mins = int(ha_down_for / 60)
    rise = (tank - baseline) if (tank is not None and baseline is not None) else None

    if rise is not None and rise >= WATCHDOG_TEMP_RISE_THRESHOLD:
        _alert(now,
            f"HA down {mins}min and tank rising ({baseline:.1f}→{tank:.1f}°C). "
            f"Boiler firing without HA control — investigate.")
    elif tank is None:
        _alert(now,
            f"HA down {mins}min and ETH01 unreachable. Total blackout.")
    else:
        # HA down, tank stable, ETH01 reachable — likely planned restart and
        # ETH01 survival is in control. Log only, don't page.
        print(f"[watchdog] HA down {mins}min, tank stable at {tank:.1f}°C — no page", flush=True)


def loop():
    while True:
        try:
            tick()
        except Exception as e:
            print(f"[watchdog] tick error: {e}", flush=True)
        time.sleep(WATCHDOG_INTERVAL)


def start():
    """Start the watchdog as a background thread (e.g. inside an existing Flask app)."""
    with state_lock:
        if state["running"]:
            return
        state["running"] = True
    threading.Thread(target=loop, name="hw-watchdog", daemon=True).start()
    print(f"[watchdog] started (ntfy={'on' if NTFY_TOPIC else 'off'})", flush=True)


if __name__ == "__main__":
    # Standalone foreground mode
    start()
    while True:
        time.sleep(3600)
