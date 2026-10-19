package com.medicinled.controller

import android.content.Context
import org.json.JSONException
import org.json.JSONObject

/**
 * Which medicines light up for each command, read from `assets/configuration.json`
 * (a copy of the file written by medicine_led_configurator.py; re-copy it after reconfiguring).
 * Segments are matched to commands through the moment id, which equals [Command.ack].
 */
object MedicineCatalog {
    private var byMoment: Map<String, List<String>>? = null

    fun namesFor(context: Context, command: Command): List<String> {
        // Pens and Lokelma sit on their own strips, whose segment names are not medicine names.
        command.displayNames?.let { return it }
        val map = byMoment ?: load(context).also { byMoment = it }
        return map[command.ack].orEmpty()
    }

    private fun load(context: Context): Map<String, List<String>> {
        val result = mutableMapOf<String, MutableList<String>>()
        try {
            val json = context.assets.open("configuration.json").bufferedReader().use { JSONObject(it.readText()) }
            val strips = json.getJSONArray("strips")
            for (i in 0 until strips.length()) {
                val segments = strips.getJSONObject(i).getJSONArray("segments")
                for (j in 0 until segments.length()) {
                    val segment = segments.getJSONObject(j)
                    val moments = segment.getJSONArray("moments")
                    for (k in 0 until moments.length()) {
                        result.getOrPut(moments.getString(k)) { mutableListOf() }.add(segment.getString("name"))
                    }
                }
            }
        } catch (_: java.io.IOException) {
        } catch (_: JSONException) {
        }
        return result
    }
}
