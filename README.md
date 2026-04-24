# tadoLocalHotWater (v1.0)
## Local Hot Water Independence + Resilience for Tado-Controlled Hot Water

[![ESPHome](https://img.shields.io/badge/ESPHome-2025-blue?logo=esphome)](https://esphome.io/)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Integration-41BDF5?logo=home-assistant)](https://www.home-assistant.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-ffdd00?logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/ay129)
[![Donate](https://img.shields.io/badge/Donate-PayPal-blue.svg)](https://www.paypal.com/donate?business=nyashachipanga%40yahoo.com&currency_code=GBP)

A small, low-cost project that gives a Tado-controlled hot water system three layers of fallback so the tank doesn't go cold when **Tado's BU01**, **Tado's cloud**, **Home Assistant**, or **the network** drops. Companion project to [tadoHotWaterKnob](https://github.com/ay129-35MR/tadoHotWaterKnob) — same household, complementary problem.

<p align="center">
  <em>(images placeholder — to be added by author)</em>
</p>

---

## Why this exists — the cloud-independence manifesto

Smart-home hardware has a habit of dying long before the appliances it controls. **Google killed Works With Nest in 2019**, stranding entire ecosystems. **Revolv hubs were bricked by a deliberate cloud shutdown in 2016**. Insteon vanished overnight in 2022. Even when the cloud stays up, vendors quietly drop API support for older device generations, leaving working hardware as expensive paperweights — Logitech Harmony, Wink, Iris, Lowe's Iris again, the list keeps growing.

Tado is a healthy company today. The BU01 in your airing cupboard talks to your boiler via short-range radio to a wireless internet bridge that talks to Tado's cloud servers. **Three things have to keep working forever** for that hot tap to deliver: the BU01's radio link, your internet, and Tado's servers. Lose any one of them and you're cold-showering until it comes back.

This project is a small bet against that. It puts a **wired, local, vendor-neutral** parallel path next to the Tado control plane:

- The boiler's HW-call terminals get a second pair of wires from a cheap ESP32 relay running [ESPHome](https://esphome.io/) — open source firmware, no cloud, no account required.
- Decisions are made by [Home Assistant](https://www.home-assistant.io/) — open source, runs on your hardware, no cloud dependency.
- If even Home Assistant goes dark, the ESP32 itself takes over with a tiny survival thermostat — keeping the water usable until you get back to fix things.

Tado keeps doing what it does well — comfort, scheduling, schedules, app polish, schedules again. We just refuse to let it be the *only* path. If Tado vanishes tomorrow the way Nest did in 2019, the boiler still fires, the water still heats, and the only thing you lose is the app.

This is **cable-cutting for your boiler**: not a replacement for the cloud product you've already paid for, but a guarantee that your hot water survives its disappearance.

---

## The problem in concrete terms

The hot water side of a Tado X system has a single point of failure: the **BU01** wireless extension kit on the boiler. It's the only thing that closes the burner contacts for hot water. If it drops off the radio link, or Tado's cloud has a wobble, or Home Assistant decides to die during an upgrade, no hot water — and the Tado app shows everything in red, with nothing the homeowner can do remotely.

Three things were needed without ripping out Tado:

1. **Independence** — a parallel actuator that can fire the boiler without Tado being involved.
2. **Backup brain** — Home Assistant can drive either path; if Tado integration fails, HA still has hands.
3. **Survival** — if HA itself dies, *something* keeps the tank warm enough to use.

…all without ever creating two writers fighting over the same boiler call.

---

## TL;DR — three operating modes

> The whole project is essentially a state machine with three states. Read this table and you understand 80% of what's going on.

| Mode | When | Brain | Actuator | What ETH01 is doing |
|------|------|-------|----------|---------------------|
| **🟢 1 — Normal** | HA alive AND Tado alive AND `actuator = tado` | HA automations | **Tado BU01** (`switch.t_hot_water_boiler`) | sensing tank temp + hard safety only |
| **🟡 2 — Relay** | HA alive but `actuator = relay` (you flipped it) | HA automations | **ETH01 relay** (`switch.hotwatertemp_hot_water_relay`) | sensing tank temp + hard safety only |
| **🔴 3 — Survival** | HA heartbeat to ETH01 stale ≥ 15 min | **ETH01 alone** | **ETH01 relay** | tiny local fallback thermostat |

**Hard safety on the ETH01** — over-temp ≥ 65 °C → OFF + lockout, max-on-time → OFF + lockout, sensor invalid → OFF — is **active in all three modes** regardless of who the brain is. The boiler can never be left on indefinitely or in a dangerous state purely because of a software fault.

**Mode switching:**

- 🟢 Mode 1 ⇄ 🟡 Mode 2 is a **manual flip** of `input_select.hot_water_actuator`. v1 is intentionally manual — automatic actuator failover is a debugging nightmare when it triggers unexpectedly. The `hot_water_tado_unavailable_advisory` automation suggests when to flip; you decide.
- 🟢 / 🟡 → 🔴 Mode 3 happens **automatically** — the ETH01 watches its own heartbeat freshness. No HA cooperation required.
- 🔴 → 🟢 / 🟡 happens **automatically** the moment the heartbeat returns.

---

## Hardware & Build Context

The actuation side is intentionally simple: a single relay wired in parallel with the BU01's hot water output. Either device closing fires the burner; both must be open for the boiler to stay off. The intelligence is all in software.

### Parts List

| Part | Cost | Notes |
|---|---:|---|
| **WT32-ETH01** ESP32 dev board with built-in 100 Mb Ethernet | ~£8 | Wired LAN — no Wi-Fi flake risk for the safety-critical role. |
| **3.3V relay module** (SSR or small mechanical — 2A is plenty for the BU01's dry contacts) | ~£3 | Active-LOW relays work — invert the GPIO if needed. |
| **DS18B20** in a stainless probe with the standard 4.7 kΩ pull-up | ~£2 | Dropped into the tank's existing temperature port (most cylinders have one). |
| **3-core cable** between the ETH01 and the boiler (relay sits at the boiler end) | <£1 | COM + NO + GND. |
| **Pluggable terminal blocks** for the BU01 dry contacts | <£1 | Avoids cutting into the BU01 itself. |
| **5 V USB power supply** for the ETH01 | ~£3 | Feed it from the same circuit as the BU01 if possible. |
| Total | **~£15** | Tado kit is unchanged. |

### Wiring — the parallel path

The relay's COM and NO contacts go in parallel with the BU01's HW-on output (the dry pair that goes to the boiler's HW call terminals). Either path closing fires the burner.

```
                  ┌───────────────────────┐
                  │  Boiler "HW call"     │
                  │   dry-contact pair    │
                  └─────────┬─────────────┘
                            │
              ┌─────────────┼──────────────┐
              │                            │
   ┌──────────┴──────────┐    ┌────────────┴───────────┐
   │ Tado BU01           │    │ Relay (COM ↔ NO)        │
   │ extension kit       │    │ driven by ETH01 GPIO14  │
   │ (cloud / radio path)│    │ (wired path)            │
   └─────────────────────┘    └─────────────────────────┘
```

There is **no software arbitration at the hardware layer** — that's deliberate. It's then the software's job to stay disciplined. See "How clashes are prevented" below.

### Wiring — the ETH01

- **DS18B20** sits in the tank's temperature pocket. Yellow → GPIO4, red → 3.3V, black → GND, with the standard 4.7 kΩ pull-up between data and 3.3 V.
- **Relay control input** wired to GPIO14 (avoids strapping pins).
- **Ethernet** uses the WT32-ETH01's onboard LAN8720 (GPIO0/16/18/23). No Wi-Fi configured.
- Power the ETH01 from the same circuit as the BU01 if practical — they share a failure mode either way.

### Pinout (WT32-ETH01)

| Function | GPIO | Notes |
|---|---:|---|
| DS18B20 (one-wire) | GPIO4 | Single sensor, 4.7 kΩ pull-up to 3.3 V. |
| Relay control | GPIO14 | Active-HIGH. `restore_mode: ALWAYS_OFF`. |
| Ethernet MDC | GPIO23 | LAN8720 reserved. |
| Ethernet MDIO | GPIO18 | LAN8720 reserved. |
| Ethernet CLK_EXT_IN | GPIO0 | LAN8720 reserved. |
| Ethernet PHY power | GPIO16 | LAN8720 reserved. |

### Why a wired ESP for the safety role?

Wi-Fi is the most common failure mode on hobbyist ESPHome devices. Putting the safety-critical relay on a wired Ethernet board costs about £3 more than a generic ESP32 dev board and removes an entire class of issue. The BU01 itself is wireless (Tado's 868 MHz mesh) so the relay is the wired, deterministic alternative — exactly what you want for a fallback.

---

## How clashes are prevented

**One actuator selector** + **two wrapper scripts**:

```yaml
hot_water_on:
  if actuator == relay: relay ON, force Tado switch OFF
  else:                 Tado ON, force relay OFF

hot_water_off:
  Tado switch OFF
  relay OFF        # always both, regardless of selector
```

Every existing HA automation (turn-on, turn-off fail-safe, trip-catch, schedule, derate-overnight, towel-rail handler, iOS critical-alert action) is **minimally refactored** to call these scripts instead of toggling `switch.t_hot_water_boiler` directly. Roughly 5 line edits, no actual logic redesign — the wrappers become the single mux point for the entire control surface.

**The trade-off**: anything that bypasses the wrapper (Tado's own schedule, the Tado app, a stray `switch.turn_on` somewhere) can briefly desynchronise the two paths. HA's fail-safe off-cycle and the ETH01's max-on-time ultimately bound the damage — but discipline matters.

---

## Survival mode (the interesting bit)

Home Assistant publishes a **heartbeat** to the ETH01 every 2 minutes via an ESPHome service:

```yaml
- service: ha_heartbeat
  then:
    - lambda: 'id(ha_heartbeat_ms) = millis();'
```

…and a small set of **broad fallback thresholds** via a second service, every hour and on change:

- `fallback_low_temp` (default 38 °C)
- `fallback_high_temp` (default 46 °C)
- `max_safe_temp` (default 65 °C — must be above any legionella target)
- `max_on_seconds` (default 90 min)

When the heartbeat goes stale (>15 min on the ETH01's own clock), the device's interval lambda kicks in:

- below `fallback_low` → relay ON (with 3-min anti-chatter)
- above `fallback_high` → relay OFF
- temp ≥ `max_safe_temp` → OFF + lockout (manual clear from HA)
- relay on > `max_on_seconds` → OFF + lockout
- sensor invalid → OFF (no lockout, auto-resumes)

It deliberately **does not try to be smart**. No occupancy, no schedules, no usage-rate logic. Just keep the water usable until HA comes back.

The thresholds get clamped defensively on the ESP — if HA pushes a config where `low > high`, the lambda coerces it to a sane band rather than rejecting outright. Survival logic always has *some* usable threshold pair.

---

## The "HA dead + Tado still firing" gap (optional watchdog)

> **You can completely skip this section and still have a perfectly resilient system.** The three operating modes above already cover Tado failure and HA failure. The watchdog only adds out-of-band notification for the rare combined scenario where **HA is down AND Tado is still firing the boiler from its own schedule**. That's a real risk (the tank could overheat before anything intervenes — the ETH01 can shut its own relay but has no wire to Tado), but it's also rare enough that some users will reasonably decide it's not worth the extra moving part.

If you do want it, `watchdog/` contains ~90 lines of Python that:

- polls HA's `/api/` and the ETH01's REST endpoint every 60 s, **completely independently of HA**, and
- pushes via [ntfy.sh](https://ntfy.sh) when HA has been unreachable for 10+ min AND the tank is rising ≥3 °C from baseline (or ETH01 is also unreachable — total blackout).

Notification path is **fully outside HA**, so it works when HA is exactly the thing that's broken. Pick an unguessable ntfy topic — anyone subscribed gets the alerts.

### Where to run it — pick whatever suits you

The watchdog is intentionally simple Python so you can host it on whatever you already have running. Some options, in roughly increasing isolation from HA:

| Option | Pros | Cons |
|---|---|---|
| **A separate Raspberry Pi Zero / Pi 4 / similar SBC** | Maximum independence — different machine, different SD card, different power supply. The "watchdog watches the watchdog" archetype. | One more box to maintain. ~£15–£35 for the Pi. |
| **An always-on Linux box / NAS / homelab server** | Zero new hardware if you already have one. Survives HA going down because it's a different machine. | Same room/circuit/UPS as HA — shared physical-failure modes. |
| **A Docker container on the same host as HA** *(this repo's reference setup)* | Easiest if you already run other Dockerised services. Trivial to update. | Same kernel and host as HA — won't help if the host itself dies. |
| **A cron job on a router with entware/openWRT** | Independent power domain, different uptime profile. | Limited Python availability, awkward to update. |
| **A free-tier VPS or a friend's home Pi over Tailscale** | True off-site independence — survives a power cut at your house. | Now you depend on internet round-trip and a third party for the safety alert. |

The reference deployment in this repo runs it as a background thread inside an existing Flask app on a Linux box — about a 5-line addition to `app.py`. But there's nothing magic about that — `python3 watchdog/watchdog.py` works as a standalone process, and `watchdog/` includes a `start()` entrypoint you can import into any existing always-on Python process.

The principle to optimise for: **the watchdog should fail in a different way than HA fails.** Different machine is good. Different power supply is better. Different physical location is best. But all of them are dramatically better than nothing.

---

## Detecting BU01 offline

Took some figuring out:

- The Tado switch in many HA installs goes through a **Homebridge plugin** (cloud API + HomeKit). When the BU01 dies, that plugin keeps reporting the cached `off` rather than `unavailable` — so it can't be used for failure detection.
- **Re-enable the native Tado HA integration** alongside Homebridge. Its `binary_sensor.hot_water_connectivity` is the real "Tado HW zone reachable end-to-end" sensor. When the BU01 dies, that flips to `off` within seconds.

Heads-up if you do this: the native Tado HA integration uses **OAuth 2.0 Device Authorization** since March 2025. The auth flow generates a fresh `user_code` every retry. Only approve the **currently visible** code — don't re-click Configure after approving, or you invalidate what you just approved.

Other useful native-integration signals:

| Entity | Use |
|---|---|
| `binary_sensor.hot_water_connectivity` | Primary advisory trigger — zone-scoped, stable across BU01 replacements |
| `binary_sensor.<IB-device>_connection_state` | Tado IB01 internet bridge online — distinguishes "BU01 only" from "all Tado dark" |
| `binary_sensor.<BU-device>_connection_state` | Per-device BU01 (use the zone one above instead) |
| `binary_sensor.hot_water_overlay` | Manual override active — informational, not actionable |

---

## Repository layout

```
tadoLocalHotWater/
├── README.md
├── LICENSE
├── esphome/
│   └── hotwatertemp.yaml              # WT32-ETH01 firmware (globals, services, safety+survival lambda)
├── homeassistant/
│   ├── configuration.yaml.snippet     # input_select / boolean / number helpers
│   ├── scripts.yaml                   # hot_water_on / hot_water_off wrappers
│   └── automations.yaml               # heartbeat publisher, survival config publisher,
│                                      #   safe-default-on-restart, advisory, unmanaged warning,
│                                      #   refactoring template
├── observer/
│   ├── observer.py                    # Snapshot writer for a homepage widget — NO actuation
│   └── hot-water-observer.service     # systemd unit
├── watchdog/
│   └── watchdog.py                    # External HA-independent watchdog with ntfy.sh push
├── dashboard/
│   └── lovelace-hot-water-view.yaml   # Drop-in Lovelace view
├── docs/
│   └── (additional notes)
└── images/
    └── (placeholder — add your own photos and screenshots)
```

---

## Installation

1. **Flash the ETH01** with `esphome/hotwatertemp.yaml`. Edit the placeholders (`api.encryption.key`, `ota.password`, `static_ip`) for your install.
2. **Wire the relay** in parallel with the BU01's HW-on terminal. COM ↔ NO across the two terminals on the BU01 that already go to the boiler's HW call input.
3. **Add the helpers** from `homeassistant/configuration.yaml.snippet` to your HA config.
4. **Add the wrapper scripts** from `homeassistant/scripts.yaml`.
5. **Add the new automations** from `homeassistant/automations.yaml`.
6. **Refactor your existing hot water automations** to call `script.hot_water_on/off` instead of toggling `switch.t_hot_water_boiler` directly. Look at the "REFACTORING TEMPLATE" comment block at the bottom of `automations.yaml`.
7. **(Optional) Add the dashboard view** from `dashboard/lovelace-hot-water-view.yaml`.
8. **(Optional, and you can happily skip this entirely)** Run the **observer** (`observer/`) for a status snapshot, and/or the **external watchdog** (`watchdog/`) for HA-independent push alerts. The three operating modes already give you the resilience; the watchdog is purely about being *told* when the rare combined-failure scenario happens. See "The 'HA dead + Tado still firing' gap" above for a discussion of where to host it (Docker container / separate Pi / VPS / etc.).

Set up the native Tado HA integration alongside any existing Homebridge plugin — `binary_sensor.hot_water_connectivity` is required for the BU01-offline advisory.

---

## Lessons / things I'd do again

- **Don't mirror; mux.** An earlier draft had Tado → relay continuous mirroring. Two writers are always worse than one. An actuator selector + tiny wrapper scripts is much smaller code AND much more obvious during incidents.
- **Survival mode is a service-preservation tool, not a comfort controller.** Resisting the urge to put occupancy, schedules, and usage-rate logic on the ESP kept the survival code under 60 lines and easy to reason about.
- **Manual actuator selection beats auto-failover for v1.** You can always add the automation later; you can't undo a failover that flipped at the wrong moment.
- **Hardware safety on the ESP regardless of mode.** Over-temp, max-on-time, sensor-bad must trip on the device, never delegated to HA. Lockout requires manual clear so a transient sensor blip doesn't oscillate the boiler.
- **One external watchdog goes a long way.** ~90 lines of Python, slots into anything you already have running, gives you the only signal that survives HA dying.
- **Wired Ethernet for the safety-critical ESP.** A few extra pounds, removes Wi-Fi as a failure mode entirely.

---

## What's not in v1

- **Auto actuator-flip on Tado disconnect.** Manual selection only — auto-failover is a nightmare to debug when it fires unexpectedly. Will revisit after several weeks of stability data.
- **Rich HA scheduling on the ESP in survival mode.** Out of scope and will stay out — if HA is down for long enough that it matters, fix HA.
- **Survival thresholds slaved to live HA target.** Currently dedicated helpers; might revisit if it turns out the static band is too coarse in practice.

---

## Related projects

- [tadoHotWaterKnob](https://github.com/ay129-35MR/tadoHotWaterKnob) — the user-facing knob + display companion to this fallback layer. Same household, different layer.
- [esphome-display-screenshot](https://github.com/ay129-35MR/esphome-display-screenshot) — custom ESPHome component used on the knob.

---

## License

MIT — see [LICENSE](LICENSE). No warranty; this controls a boiler, please verify your wiring, your safety thresholds, and your insurance.

---

If this saved you a cold shower, [buy me a coffee](https://buymeacoffee.com/ay129) ☕ or [drop a tip](https://www.paypal.com/donate?business=nyashachipanga%40yahoo.com&currency_code=GBP) — thanks for reading.
