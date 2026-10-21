package com.medicinled.controller

import android.graphics.Color

/**
 * Commands understood by the ESP32 firmware (led-farmaci.yaml).
 * Each one publishes its [payload] to the single command feed `<username>/feeds/led-farmaci-command`
 * (the moment id from configuration.json, or "off"); the device answers on the feedback feed with
 * "OK:<ack>" or "ERRORE:<reason>".
 */
enum class Command(
    val label: String,
    val subtitle: String?,
    val payload: String,
    val ack: String,
    val color: Int,
    val icon: Int,
    /** Fixed list shown while active; null = medicines from configuration.json (see [MedicineCatalog]). */
    val displayNames: List<String>? = null,
) {
    PRIMA_COLAZIONE("Colazione", "Prima", "before_breakfast", "before_breakfast", Color.rgb(255, 244, 179), R.drawable.ic_sun),
    DOPO_COLAZIONE("Colazione", "Dopo", "after_breakfast", "after_breakfast", Color.rgb(255, 225, 120), R.drawable.ic_sun),
    PRANZO("Pranzo", null, "lunch", "lunch", Color.rgb(255, 178, 122), R.drawable.ic_sun),
    LOKELMA("Lokelma", null, "non_dialysis_days_medicines", "non_dialysis_days_medicines", Color.rgb(176, 224, 230), R.drawable.ic_pill, listOf("Lokelma")),
    PRIMA_CENA("Cena", "Prima", "before_dinner", "before_dinner", Color.rgb(255, 190, 180), R.drawable.ic_sunset),
    DOPO_CENA("Cena", "Dopo", "after_dinner", "after_dinner", Color.rgb(255, 150, 140), R.drawable.ic_sunset),
    INSULINA_PASTI("Insulina pasti", "NovoRapid FlexPen®", "meals_insulin_pen", "meals_insulin_pen", Color.rgb(205, 230, 255), R.drawable.ic_pen_novorapid, listOf("NovoRapid FlexPen®")),
    INSULINA_NOTTE("Insulina notte", "Toujeo SoloStar®", "night_insulin_pen", "night_insulin_pen", Color.rgb(207, 243, 222), R.drawable.ic_pen_toujeo, listOf("Toujeo SoloStar®")),
    SPEGNI_TUTTO("Spegni", null, "off", "spento", Color.rgb(85, 92, 104), R.drawable.ic_power);
    // Payloads and acks match configuration.json: moments[].id, and "off" for everything off.

    companion object {
        const val COMMAND_FEED = "led-farmaci-command"
        const val FEEDBACK_FEED = "led-farmaci-feedback"

        /** Not a tile: asks the firmware to download and flash the latest build (settings screen only). */
        const val UPDATE_PAYLOAD = "update"
        const val UPDATE_ACK = "aggiornamento"

        fun fromAck(ack: String): Command? = entries.firstOrNull { it.ack == ack }
    }
}
