package com.medicinled.controller

import android.content.Context
import java.util.UUID

object AppSettings {
    private const val PREFS = "settings"
    const val DEFAULT_HOST = "io.adafruit.com"
    const val DEFAULT_PORT = 8883

    data class Connection(val host: String, val port: Int, val username: String, val key: String) {
        val isComplete get() = host.isNotBlank() && port in 1..65535 && username.isNotBlank() && key.isNotBlank()

        /** Adafruit IO uses TLS on 8883 and plain MQTT on 1883. */
        val serverUri get() = "${if (port == 8883 || port == 443) "ssl" else "tcp"}://$host:$port"
    }

    private fun prefs(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun load(context: Context): Connection {
        val p = prefs(context)
        return Connection(
            p.getString("host", DEFAULT_HOST) ?: DEFAULT_HOST,
            p.getInt("port", DEFAULT_PORT),
            p.getString("username", "") ?: "",
            p.getString("key", "") ?: "",
        )
    }

    fun save(context: Context, c: Connection) {
        prefs(context).edit()
            .putString("host", c.host)
            .putInt("port", c.port)
            .putString("username", c.username)
            .putString("key", c.key)
            .apply()
    }

    /** Adafruit IO drops older sessions with the same client id, so keep one stable id per install. */
    fun clientId(context: Context): String {
        val p = prefs(context)
        p.getString("client_id", null)?.let { return it }
        val id = "medled-android-" + UUID.randomUUID().toString().take(8)
        p.edit().putString("client_id", id).apply()
        return id
    }

    fun bubblePosition(context: Context): Pair<Int, Int>? {
        val p = prefs(context)
        if (!p.contains("bubble_x")) return null
        return p.getInt("bubble_x", 0) to p.getInt("bubble_y", 0)
    }

    fun saveBubblePosition(context: Context, x: Int, y: Int) {
        prefs(context).edit().putInt("bubble_x", x).putInt("bubble_y", y).apply()
    }
}
