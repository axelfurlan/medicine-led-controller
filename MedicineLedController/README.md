# Medicine LED Controller

Android app (Kotlin) that controls the `led-farmaci` ESP32/ESPHome LED strip through Adafruit IO MQTT.

## Features
- **Floating button** drawn over other apps (e.g. during a video call). Drag it anywhere; it snaps to the nearest side.
- **Command panel** ("Farmaci"): Colazione (prima/dopo), Pranzo, Lokelma, Cena (prima/dopo), Insulina pasti, Insulina notte. "Spegni" appears only in the active view.
- **Active view**: once the device confirms a command, the grid is replaced by the blinking tile, the list of medicines that light up (from `app/src/main/assets/configuration.json`, a copy of the configurator's file) and a "Spegni" button. The grid returns when the lights are turned off.
- **Feedback**: the pressed tile pulses while waiting, then blinks green once the device confirms; a banner shows "Comando ricevuto" or an error/timeout.
- **Fail-safe**: the MQTT connection has a Last Will that publishes `off` to the command feed, so if the app crashes, is killed or loses the network, the broker turns the LEDs off. On a normal exit with a command active, the app sends the all-off command before disconnecting. After a reconnect with a command active, it sends all-off again and returns to the grid.
- **Settings screen**: Adafruit IO connection, MQTT/device status, start/stop the floating button.

## MQTT protocol (matches `led-farmaci.yaml`)
All commands go to one feed, `<user>/feeds/led-farmaci-command`; the payload says what to do:

| Button | Payload |
|---|---|
| Colazione prima / dopo | `before_breakfast` / `after_breakfast` |
| Pranzo | `lunch` |
| Lokelma | `non_dialysis_days_medicines` |
| Cena prima / dopo | `before_dinner` / `after_dinner` |
| Insulina pasti / notte | `meals_insulin_pen` / `night_insulin_pen` |
| Spegni | `off` |

The app subscribes to `<user>/feeds/led-farmaci-feedback` (`OK:<mode>`, `OK:spento`, `ERRORE:...`) and to `<user>/errors` and `<user>/throttle`.

## Run
1. Open the folder in Android Studio and run on a phone (Android 8+).
2. Enter your Adafruit IO username and AIO key, then tap **Salva e connetti**.
3. Tap **Mostra pulsante flottante** and allow "Display over other apps".
4. From then on, opening the app from the launcher shows only the floating button. The full screen opens from the ⚙ in the panel or from the notification.
5. Close the floating button from its notification ("Chiudi pulsante") or from the app.

Port 8883 uses TLS (default); 1883 is unencrypted. The AIO key is stored in plain app preferences.
A command acknowledgement is not proof that medication was taken.
