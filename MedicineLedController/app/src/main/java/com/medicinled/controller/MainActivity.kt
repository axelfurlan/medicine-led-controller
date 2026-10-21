package com.medicinled.controller

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.text.format.DateFormat
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

class MainActivity : Activity() {
    private companion object {
        const val REQUEST_NOTIFICATIONS = 1
    }

    private lateinit var host: EditText
    private lateinit var port: EditText
    private lateinit var username: EditText
    private lateinit var key: EditText
    private lateinit var status: TextView
    private lateinit var mqttStatus: TextView
    private lateinit var deviceStatus: TextView
    private lateinit var overlayButton: Button
    private lateinit var updateButton: Button
    private lateinit var panel: CommandPanel

    private val listener: (MqttController.State) -> Unit = { render(it) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (savedInstanceState == null && launchAsButton(intent)) return
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(20), dp(16), dp(24))
            setBackgroundColor(Color.rgb(247, 248, 250))
        }
        root.addView(TextView(this).apply { text = "Medicine LED"; textSize = 28f; setTextColor(Color.rgb(20, 33, 61)) })

        val statusCard = card(root)
        mqttStatus = TextView(this).apply { textSize = 16f }
        deviceStatus = TextView(this).apply { textSize = 15f; setPadding(0, dp(6), 0, 0) }
        statusCard.addView(mqttStatus)
        statusCard.addView(deviceStatus)

        section(root, "Comandi")
        panel = CommandPanel(this)
        root.addView(panel)

        section(root, "Pulsante flottante")
        root.addView(TextView(this).apply {
            text = "Mostra i comandi sopra le altre app, ad esempio durante una videochiamata."
            textSize = 14f; setTextColor(Color.DKGRAY)
        })
        overlayButton = Button(this).apply { setOnClickListener { toggleOverlay() } }
        root.addView(overlayButton)

        section(root, "Connessione Adafruit IO")
        host = addField(root, "Broker", AppSettings.DEFAULT_HOST)
        port = addField(root, "Porta (8883 = TLS, 1883 = non cifrata)", AppSettings.DEFAULT_PORT.toString())
        username = addField(root, "Adafruit IO username", "")
        key = addField(root, "AIO Key", "", true)
        root.addView(Button(this).apply { text = "Salva e connetti"; setOnClickListener { saveSettings() } })
        status = TextView(this).apply { textSize = 15f; setPadding(0, dp(8), 0, 0) }
        root.addView(status)

        section(root, "Firmware")
        root.addView(TextView(this).apply {
            text = "Scarica e installa l'ultima versione del firmware sul dispositivo, anche fuori casa."
            textSize = 14f; setTextColor(Color.DKGRAY)
        })
        updateButton = Button(this).apply { text = "Aggiorna firmware ESP32"; setOnClickListener { confirmFirmwareUpdate() } }
        root.addView(updateButton)

        val settings = AppSettings.load(this)
        host.setText(settings.host)
        port.setText(settings.port.toString())
        username.setText(settings.username)
        key.setText(settings.key)
        if (!settings.isComplete) status.text = "Inserisci i dati di connessione."

        setContentView(ScrollView(this).apply { addView(root) })
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        launchAsButton(intent)
    }

    /**
     * Opening the app from the launcher shows only the floating button once it is set up.
     * The gear in the panel and the notification open this screen without ACTION_MAIN.
     */
    private fun launchAsButton(intent: Intent): Boolean {
        if (intent.action != Intent.ACTION_MAIN || !Settings.canDrawOverlays(this) || !AppSettings.load(this).isComplete) return false
        startForegroundService(Intent(this, OverlayService::class.java))
        finish()
        return true
    }

    override fun onStart() {
        super.onStart()
        MqttController.acquire(this)
        MqttController.addListener(listener)
    }

    override fun onResume() {
        super.onResume()
        updateOverlayButton()
    }

    override fun onStop() {
        MqttController.removeListener(listener)
        MqttController.release()
        super.onStop()
    }

    private fun render(state: MqttController.State) {
        panel.render(state)
        updateButton.isEnabled = state.connection == MqttController.Connection.CONNECTED
        val (label, color) = CommandPanel.connectionLabel(state)
        mqttStatus.text = "MQTT / Adafruit IO: $label" + (state.connectionError?.let { "\n$it" } ?: "")
        mqttStatus.setTextColor(if (state.connection == MqttController.Connection.CONNECTED) Color.rgb(24, 121, 78) else color)
        deviceStatus.text = if (state.lastFeedbackAt == 0L) {
            "Dispositivo: nessuna risposta ricevuta finora"
        } else {
            "Dispositivo: ultima risposta alle ${DateFormat.getTimeFormat(this).format(state.lastFeedbackAt)} (${state.lastFeedback})"
        }
    }

    private fun confirmFirmwareUpdate() {
        AlertDialog.Builder(this)
            .setTitle("Aggiornare il firmware?")
            .setMessage("Il dispositivo scarica la nuova versione e si riavvia: i LED restano spenti per circa un minuto. Non togliere l'alimentazione durante l'aggiornamento.")
            .setNegativeButton("Annulla", null)
            .setPositiveButton("Aggiorna") { _, _ -> MqttController.requestFirmwareUpdate() }
            .show()
    }

    private fun toggleOverlay() {
        if (OverlayService.isRunning) {
            startService(Intent(this, OverlayService::class.java).setAction(OverlayService.ACTION_STOP))
            overlayButton.postDelayed({ updateOverlayButton() }, 300)
            return
        }
        if (!Settings.canDrawOverlays(this)) {
            status.text = "Consenti \"Mostra sopra altre app\" e poi torna qui."
            startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
            return
        }
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQUEST_NOTIFICATIONS)
            return
        }
        startOverlay()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        // The notification is only informative; start the overlay either way.
        if (requestCode == REQUEST_NOTIFICATIONS) startOverlay()
    }

    private fun startOverlay() {
        startForegroundService(Intent(this, OverlayService::class.java))
        overlayButton.postDelayed({ updateOverlayButton() }, 300)
    }

    private fun updateOverlayButton() {
        overlayButton.text = if (OverlayService.isRunning) "Nascondi pulsante flottante" else "Mostra pulsante flottante"
    }

    private fun card(parent: LinearLayout) = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        background = rounded(Color.WHITE, 16)
        setPadding(dp(16), dp(14), dp(16), dp(14))
        parent.addView(this, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply {
            topMargin = dp(16)
        })
    }

    private fun section(parent: LinearLayout, title: String) {
        parent.addView(TextView(this).apply {
            text = title; textSize = 18f; setTypeface(typeface, Typeface.BOLD)
            setTextColor(Color.rgb(20, 33, 61)); setPadding(0, dp(24), 0, dp(8))
        })
    }

    private fun addField(parent: LinearLayout, label: String, hintText: String, secret: Boolean = false): EditText {
        parent.addView(TextView(this).apply { text = label; setPadding(0, dp(8), 0, dp(2)) })
        val field = EditText(this).apply {
            hint = hintText; setSingleLine(true)
            if (secret) inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        parent.addView(field, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        return field
    }

    private fun saveSettings() {
        val p = port.text.toString().toIntOrNull()
        val connection = AppSettings.Connection(host.text.toString().trim(), p ?: -1, username.text.toString().trim(), key.text.toString().trim())
        if (!connection.isComplete) {
            status.text = "Controlla broker, porta, username e AIO Key."; return
        }
        AppSettings.save(this, connection)
        status.text = "Impostazioni salvate su questo telefono."
        MqttController.reconnect()
    }
}
