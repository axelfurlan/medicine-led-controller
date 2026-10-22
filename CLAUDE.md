# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A medicine-reminder system with three parts that share one MQTT protocol (Adafruit IO):

1. **`medicine_led_configurator.py`**: Tkinter GUI (stdlib only) that generates the firmware config.
2. **`led-farmaci.yaml`**: ESPHome config for an ESP32 (`esp32dev`, Arduino framework) driving 1–5 WS2812 LED strips. **Generated file**.
3. **`MedicineLedController/`**: Android app (Kotlin, Gradle) that publishes commands over MQTT from a floating overlay button.

There are no tests. `.esphome/` (ESPHome build output) is git-ignored; ignore it and do not search in it. Your own `configuration.json`, `led-farmaci.yaml` and `secrets.yaml` are git-ignored too; the repo ships `configuration.example.json` and `secrets.example.yaml` with dummy data, and `MedicineLedController/app/src/main/assets/configuration.json` is a dummy copy for the app.

## Generated files: edit the generator, not the output

`led-farmaci.yaml` and `configuration.json` are written by the configurator. The YAML header says "Automatically generated". Hand edits to the YAML are lost the next time the configurator saves. Change `generate_yaml` in `medicine_led_configurator.py` instead, then regenerate.

- The configurator's model functions are module-level and Tk-free, so they can be tested headless: `default_config`, `compute_layout`, `validate_config`, `generate_yaml`, `read_secrets`/`write_secrets`. The `Configurator` class is only the UI (dark ttk theme on `clam`).
- `configuration.json` (`"version": 3`; version 2 is migrated on load, anything older falls back to defaults) contains:
  - `moments`: each has `id` and `name`. The id is the command payload.
  - `strips`: up to 5. Each has `gpio`, `num_leds` and an ordered list of `segments`, each with `leds`, `gap_after` and the `moments` (ids) it belongs to.
  - `connections`: MQTT settings plus `command_feed` and `feedback_feed`.
  - `pulse`: `on_ms`, `off_ms` and `transition_ms`, used globally.
- Segment LED indices are not stored. They are computed in order: each segment starts after the previous one plus its `gap_after`. Insulin pens are just strips with one segment; there is no special case. The data is stored in shelf order (left to right), but the strip card lists the rows from the board (LED 0) to the far end, so with `right_to_left` the rows are shown reversed and the LED ranges always ascend down the table. The gaps (unlit LEDs) are positions on the shelf: `gap_before` on the strip (left end), `gap_after` on each segment (to its right; on the last segment it is the gap at the right end), and a gap keeps its position when segments are moved. A strip with `right_to_left: true` has LED 0 at the right end, so the numbering runs from the right (`compute_full_layout(segments, right_to_left, gap_before)`); the edge gaps count as used LEDs. Configs without `gap_before` are migrated on load: it is set to 0 and the old (ignored) last `gap_after` is zeroed.
- On startup the GUI auto-loads `configuration.json` and `secrets.yaml` from the script folder. If the JSON isn't version 3, it starts from `default_config()` instead. The suggested GPIOs (`SUGGESTED_GPIOS`: 16, 17, 18, 19, 21) are the ones wired on the current hardware.
- Credentials (`wifi_ssid`, `wifi_password`, `ota_password`, `adafruit_io_key`, `api_encryption_key`, `ap_password`, `github_token`) go only into `secrets.yaml` (gitignored). The YAML references them via `!secret`. Never embed them in the YAML or JSON.

## Firmware behaviour (`led-farmaci.yaml`)

- MQTT starts only once Wi-Fi is connected (`mqtt: enable_on_boot: false` + `wifi: on_connect: mqtt.enable`). Starting it at boot made the broker lookup fail instantly (no network yet) and ESPHome then waited a fixed 20 s before retrying.
- Boot and MQTT disconnect: all LEDs red with the `lampeggio_errore` blink script. MQTT `on_connect` clears this and shows steady red.
- Each moment `<id>` has an `on_message` handler on the single command topic (filtered with `payload: "<id>"`; `off` turns everything off) and a `lampeggio_<id>` script. The script blinks green the segments assigned to that moment, while all other segments stay red. `modalita_attiva` (global) holds the active moment ID.
- Entity IDs: `strip_<n>` is the physical strip (internal). `seg_<n>_<m>` is a partition named after the segment.
- `rmt_symbols` is 128 for up to 4 strips and 64 for 5, so the ESP32's 512 RMT symbols are not exceeded.
- The device publishes feedback to the feedback feed: `OK:<moment id>`, `OK:spento` (off) or `ERRORE:payload_non_valido`. The moment IDs `nessuna`, `spento`, `errore` and `off` are reserved. Unknown command payloads get `ERRORE:payload_non_valido` from a catch-all handler.

## Security: MQTT and API

- The device must use MQTT over TLS (port 8883, `TLS_MQTT_PORT`). On the ESP32, ESPHome encrypts MQTT **only when `certificate_authority` is set**, so `generate_yaml` embeds `ADAFRUIT_IO_CA` (DigiCert Global Root G2, the root of Adafruit IO's chain, valid to 2038) whenever the port is 8883; the hostname is verified. Port 1883 is plain text (the AIO key is sent in clear): the configurator asks for confirmation (`security_warnings`) and the app shows a warning. If Adafruit ever changes its root, update `ADAFRUIT_IO_CA` and re-flash over the LAN (USB/LAN OTA); the remote `update` command needs MQTT.
- The ESPHome native API is encrypted (`api: encryption: key: !secret api_encryption_key`); the configurator generates the key (`new_api_key`) when it is empty. `esphome logs --device <ip>` reads it from `secrets.yaml`.
- After switching a device from 1883 to 8883, rotate the AIO key (it was sent in clear text), update it in `secrets.yaml` and the app, and flash the device over USB/LAN right away. Wait 60 s after any update before power-cycling (OTA rollback).

## Wi-Fi fallback hotspot

The firmware has `wifi: ap:` + `captive_portal:`: if the device can't join its Wi-Fi it opens the protected hotspot "led-farmaci Fallback Hotspot" after about 90 s (password: `ap_password` in `secrets.yaml`, 8-63 characters, generated by the configurator and shown in its Connections page). Connect with a phone or laptop, open the portal page (192.168.4.1), choose the network and type its password; no cable or reflash is needed. While a hotspot is configured the device does not reboot-loop when Wi-Fi is missing.

**Caveat:** ESPHome stores the credentials entered in the portal under a key derived from the config hash and the ESPHome version. Any firmware whose generated config differs (different layout, different Wi-Fi in `secrets.yaml`, ...) ignores them and uses the *compiled* Wi-Fi again. Treat the portal as a bootstrap: after joining the site Wi-Fi through it, put that SSID/password in the configurator, **Publish firmware…** and tap the app's Update button (the device downloads the build over the site Wi-Fi); the new build has the site Wi-Fi compiled in.

## On-board status LED (optional)

Top-level `status_led_gpio` (null = off; the blue LED is GPIO 2 on typical ESP32 dev boards) adds a `switch` + `led_stato` script for diagnosing boots without USB: solid = firmware started; then N pulses = `esp_reset_reason()` (1 power-on, 2 reset button, 3 software, 4 crash, 5 interrupt watchdog, 6 task watchdog, 7 other watchdog, 9 brownout); then fast blink = no Wi-Fi, slow blink = Wi-Fi but no MQTT, short flash every 2 s = all connected. No LED at all means the firmware did not start (or ESPHome safe mode). It must not share a GPIO with a strip.

## Remote OTA (optional)

Set `connections.firmware_url` (HTTPS raw URL of `firmware.ota.bin` in a **private** repo; `<url>.md5` must sit beside it) and the `github_token` secret (read-only fine-grained token). The generator then adds `http_request`, `ota: http_request` and an `update` payload on the command feed: the device acks `OK:aggiornamento`, downloads with basic auth (`x-access-token` + token) and reboots. `update` is a reserved moment id. The LAN `ota: esphome` stays as fallback. Never publish the `.bin` in a public repo: it embeds Wi-Fi, AIO and OTA secrets.

Release: click **Publish firmware…** in the configurator (bottom bar). It regenerates `led-farmaci.yaml`/`configuration.json`/`secrets.yaml`, runs `esphome compile`, copies `firmware.ota.bin` + `.md5` into the local clone (`connections.firmware_repo`, default `../farmaci-firmware`, cloned if missing) and commits/pushes with the user's git credentials. Then tap "Aggiorna firmware ESP32" in the app settings (confirmation dialog; not in the overlay panel). The configurator runs ESPHome with the ESPHome Device Builder's `python.exe -m esphome` when that is installed, otherwise `esphome` from PATH. The first flash with this firmware still goes over the LAN with `esphome run led-farmaci.yaml --device <ip>`.

## MQTT protocol (shared contract)

There are only two feeds, so the free Adafruit IO plan (10 feeds) is never a limit. Commands go to `<user>/feeds/<command_feed>` (`led-farmaci-command`) with the moment id as payload, or `off` to turn everything off. The device answers on `<feedback_feed>`. The app also subscribes to `<user>/errors` and `<user>/throttle`.

**The app is not generated from the configuration.** `Command.kt` hardcodes each button's payload, which must equal a moment id in `configuration.json`, and the ack (`OK:<id>`). Keep `Command.kt` and the configured moment ids in sync by hand, and re-copy `configuration.json` into the app's assets. Adafruit IO throttles publishing, and the app's ACK timeout is 10 s.

## Commands

```
python medicine_led_configurator.py      # GUI; "Generate YAML…" also writes configuration.json + secrets.yaml
python -c "import medicine_led_configurator as m; c=m.default_config(); print(m.validate_config(c))"   # headless check
esphome config led-farmaci.yaml          # validate
esphome run led-farmaci.yaml             # compile + flash/OTA
esphome logs led-farmaci.yaml
cd MedicineLedController && ./gradlew assembleDebug    # Android build (gradlew.bat on Windows)
```

## Android app (`MedicineLedController/app/src/main/java/com/medicinled/controller/`)

- `MqttController`: singleton Paho `MqttAsyncClient` shared by the activity and the overlay. It is reference-counted via `acquire()`/`release()`, so the connection stays open while any screen uses it. `State` is pushed to listeners on the main thread. It handles the pending → active command lifecycle and the banner.
- `OverlayService`: foreground service that draws the draggable floating button and `CommandPanel` over other apps (needs the "Display over other apps" permission).
- `Command.kt`: the command list (UI tiles and topic mapping). `AppSettings`: SharedPreferences for the Adafruit IO username and key. `MainActivity`: settings screen.
- `MedicineCatalog` reads `app/src/main/assets/configuration.json` (a **copy** of the root file: re-copy it after reconfiguring) to list the medicines of the active command in `CommandPanel`'s active view. Moment ids are matched to `Command.ack`; `Command.displayNames` overrides this for Lokelma and the pens.
- Safety: `MqttController` sets an MQTT Last Will (`off` on the command feed) and sends all-off before a clean disconnect or after a reconnect while a command is active. Keep this when touching connection code.
- Port 8883 uses TLS, 1883 is plain. UI strings are in Italian.
- `MedicineLedController.zip` in the root is an archived copy of the app. Don't edit it.
