# Medicine LED Controller

A medicine reminder built from LED strips. An ESP32 lights up (blinks green) exactly the compartments of a
medicine shelf, or an insulin pen, that are due at a given moment of the day. You trigger a moment from an
Android app, which shows a floating button over other apps and then lists the medicines that are lit.

It has three parts that talk through one [Adafruit IO](https://io.adafruit.com) MQTT feed:

| Part | What it is |
|---|---|
| `medicine_led_configurator.py` | Desktop GUI (Python + Tkinter, standard library only). You describe your LED strips, the medicines on them and the moments of the day (breakfast, lunch, ...). It generates the ESPHome firmware config. |
| `led-farmaci.yaml` (generated) | [ESPHome](https://esphome.io) config for an ESP32 driving 1-5 WS2812 strips. Not stored in this repo: you generate it. |
| `MedicineLedController/` | Android app (Kotlin) with the command panel, the medicine list and a fail-safe that turns the LEDs off if the app dies. See its [README](MedicineLedController/README.md). |

> This is a personal reminder aid, not a medical device. A command being acknowledged does not prove that
> medication was taken.

## Setup

1. **Adafruit IO:** create an account and two feeds, `led-farmaci-command` and `led-farmaci-feedback`.
   The free plan is enough (10 feeds, 30 messages/minute).
2. **Configure:** run `python medicine_led_configurator.py` (Python 3 with Tkinter). Define your strips, medicines
   and moments, enter your Wi-Fi, OTA password, Adafruit IO username and key, then press **Generate YAML...**.
   This writes `led-farmaci.yaml`, `configuration.json` and `secrets.yaml` (all git-ignored).
   `configuration.example.json` and `secrets.example.yaml` show the format with dummy values.
3. **Flash:** `esphome run led-farmaci.yaml` (first time over USB, later over the air).
4. **App:** copy your `configuration.json` to `MedicineLedController/app/src/main/assets/configuration.json`
   (it supplies the medicine names), open `MedicineLedController` in Android Studio and run it on a phone
   (Android 8+). Enter your Adafruit IO username and key in the app.

## MQTT protocol

All commands go to `<user>/feeds/led-farmaci-command`; the payload is a moment id from `configuration.json`
(for example `lunch`) or `off`. The device answers on `<user>/feeds/led-farmaci-feedback` with `OK:<id>`,
`OK:spento` or `ERRORE:<reason>`. The app hardcodes its buttons in `Command.kt`, so keep those payloads in sync
with the moment ids you configure. The app also sets an MQTT Last Will (`off`), so the LEDs are switched off
if the app crashes or is killed.

The app's UI text is in Italian. `CLAUDE.md` contains notes for working on the code with Claude Code.

## License

MIT, see [LICENSE](LICENSE).
