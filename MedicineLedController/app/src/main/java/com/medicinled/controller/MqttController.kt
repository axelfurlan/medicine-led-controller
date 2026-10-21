package com.medicinled.controller

import android.content.Context
import android.os.Handler
import android.os.Looper
import org.eclipse.paho.client.mqttv3.IMqttActionListener
import org.eclipse.paho.client.mqttv3.IMqttDeliveryToken
import org.eclipse.paho.client.mqttv3.IMqttToken
import org.eclipse.paho.client.mqttv3.MqttAsyncClient
import org.eclipse.paho.client.mqttv3.MqttCallbackExtended
import org.eclipse.paho.client.mqttv3.MqttConnectOptions
import org.eclipse.paho.client.mqttv3.MqttException
import org.eclipse.paho.client.mqttv3.MqttMessage
import org.eclipse.paho.client.mqttv3.persist.MemoryPersistence

/**
 * Single shared MQTT connection to Adafruit IO, used by both the activity and the overlay.
 * All state changes and listener calls happen on the main thread.
 */
object MqttController {
    enum class Connection { DISCONNECTED, CONNECTING, CONNECTED, FAILED }
    enum class BannerKind { SENDING, SUCCESS, ERROR }

    data class Banner(val kind: BannerKind, val title: String, val detail: String)

    data class State(
        val connection: Connection = Connection.DISCONNECTED,
        val connectionError: String? = null,
        /** Command published, waiting for "OK:..." from the device. */
        val pending: Command? = null,
        /** Last command confirmed by the device (its LEDs are blinking). */
        val active: Command? = null,
        val banner: Banner? = null,
        val lastFeedback: String? = null,
        val lastFeedbackAt: Long = 0L,
    )

    private const val ACK_TIMEOUT_MS = 10_000L
    private const val RETRY_DELAY_MS = 15_000L
    /** "Turn everything off": sent on the command feed, also as the MQTT Last Will. */
    private val OFF_PAYLOAD = Command.SPEGNI_TUTTO.payload.toByteArray()

    var state = State()
        private set

    private val main = Handler(Looper.getMainLooper())
    private val listeners = mutableListOf<(State) -> Unit>()
    private lateinit var appContext: Context
    private var client: MqttAsyncClient? = null
    private var username = ""
    private var users = 0

    private val ackTimeout = Runnable {
        if (state.pending != null) {
            update(state.copy(pending = null))
            showBanner(BannerKind.ERROR, "Nessuna risposta", "Il dispositivo potrebbe essere spento o non connesso.")
        }
    }
    private val hideBanner = Runnable { update(state.copy(banner = null)) }
    private val retry = Runnable { if (users > 0 && client == null) connect() }

    fun addListener(listener: (State) -> Unit) {
        listeners += listener
        listener(state)
    }

    fun removeListener(listener: (State) -> Unit) {
        listeners -= listener
    }

    /** Keeps the connection open while at least one screen (activity or overlay) uses it. */
    fun acquire(context: Context) {
        appContext = context.applicationContext
        users++
        if (client == null) connect()
    }

    fun release() {
        users = (users - 1).coerceAtLeast(0)
        if (users == 0) disconnect()
    }

    /** Call after the connection settings change. */
    fun reconnect() {
        disconnect()
        if (users > 0) connect()
    }

    fun send(command: Command) {
        val c = client
        if (c == null || !c.isConnected) {
            showBanner(BannerKind.ERROR, "Non connesso", "Controlla Internet e le impostazioni MQTT.")
            if (c == null && users > 0) connect()
            return
        }
        val topic = commandTopic()
        try {
            c.publish(topic, command.payload.toByteArray(), 1, false, null, object : IMqttActionListener {
                override fun onSuccess(token: IMqttToken?) {}
                override fun onFailure(token: IMqttToken?, e: Throwable?) {
                    main.post { failSend(e) }
                }
            })
        } catch (e: MqttException) {
            failSend(e)
            return
        }
        main.removeCallbacks(ackTimeout)
        main.postDelayed(ackTimeout, ACK_TIMEOUT_MS)
        update(state.copy(pending = command))
        showBanner(BannerKind.SENDING, "Comando inviato…", "In attesa di conferma dal dispositivo", autoHide = false)
    }

    /** Asks the device to flash the latest firmware; it answers "OK:aggiornamento" and then reboots. */
    fun requestFirmwareUpdate() {
        val c = client
        if (c == null || !c.isConnected) {
            showBanner(BannerKind.ERROR, "Non connesso", "Controlla Internet e le impostazioni MQTT.")
            return
        }
        try {
            c.publish(commandTopic(), Command.UPDATE_PAYLOAD.toByteArray(), 1, false, null, object : IMqttActionListener {
                override fun onSuccess(token: IMqttToken?) {}
                override fun onFailure(token: IMqttToken?, e: Throwable?) {
                    main.post { failSend(e) }
                }
            })
        } catch (e: MqttException) {
            failSend(e)
            return
        }
        main.removeCallbacks(ackTimeout)
        main.postDelayed(ackTimeout, ACK_TIMEOUT_MS)
        showBanner(BannerKind.SENDING, "Richiesta inviata…", "In attesa di conferma dal dispositivo", autoHide = false)
    }

    private fun failSend(e: Throwable?) {
        main.removeCallbacks(ackTimeout)
        update(state.copy(pending = null))
        showBanner(BannerKind.ERROR, "Invio non riuscito", e?.message ?: "Errore sconosciuto")
    }

    private fun connect() {
        val settings = AppSettings.load(appContext)
        if (!settings.isComplete) {
            update(state.copy(connection = Connection.FAILED, connectionError = "Inserisci username e AIO Key"))
            return
        }
        username = settings.username
        val c = try {
            MqttAsyncClient(settings.serverUri, AppSettings.clientId(appContext), MemoryPersistence())
        } catch (e: MqttException) {
            update(state.copy(connection = Connection.FAILED, connectionError = e.message))
            return
        }
        client = c
        c.setCallback(object : MqttCallbackExtended {
            override fun connectComplete(reconnect: Boolean, serverURI: String?) {
                subscribe(c)
                main.post {
                    if (client !== c) return@post
                    // After a dropped connection we cannot know whether the broker already sent our will, so
                    // end in the safe state: lights off, and the UI back to the grid.
                    val wasActive = reconnect && state.active != null
                    if (wasActive) publishOff(c)
                    update(state.copy(connection = Connection.CONNECTED, connectionError = null,
                        active = if (wasActive) null else state.active))
                }
            }

            override fun connectionLost(cause: Throwable?) {
                // Automatic reconnect is enabled; just reflect it in the UI.
                main.post { if (client === c) update(state.copy(connection = Connection.CONNECTING, connectionError = cause?.message)) }
            }

            override fun messageArrived(topic: String, message: MqttMessage) {
                val payload = String(message.payload).trim()
                main.post { if (client === c) onMessage(topic, payload) }
            }

            override fun deliveryComplete(token: IMqttDeliveryToken?) {}
        })
        val options = MqttConnectOptions().apply {
            userName = settings.username
            password = settings.key.toCharArray()
            isAutomaticReconnect = true
            // Safety net: if this app dies without a clean disconnect (crash, kill, lost network), the broker
            // publishes "turn everything off" on our behalf so the LEDs never keep blinking unattended.
            setWill(commandTopic(), OFF_PAYLOAD, 1, false)
            isCleanSession = true
            keepAliveInterval = 30
            connectionTimeout = 15
            maxReconnectDelay = 30_000
        }
        update(state.copy(connection = Connection.CONNECTING, connectionError = null))
        try {
            c.connect(options, null, object : IMqttActionListener {
                override fun onSuccess(token: IMqttToken?) {}
                override fun onFailure(token: IMqttToken?, e: Throwable?) {
                    main.post { if (client === c) onConnectFailed(c, e) }
                }
            })
        } catch (e: MqttException) {
            onConnectFailed(c, e)
        }
    }

    private fun onConnectFailed(c: MqttAsyncClient, e: Throwable?) {
        client = null
        closeQuietly(c)
        val code = (e as? MqttException)?.reasonCode
        val authProblem = code == MqttException.REASON_CODE_FAILED_AUTHENTICATION.toInt() ||
            code == MqttException.REASON_CODE_NOT_AUTHORIZED.toInt()
        val message = if (authProblem) "Username o AIO Key non validi" else (e?.message ?: "Connessione non riuscita")
        update(state.copy(connection = Connection.FAILED, connectionError = message))
        // Retrying bad credentials would only get the account temporarily blocked by Adafruit IO.
        if (!authProblem) main.postDelayed(retry, RETRY_DELAY_MS)
    }

    private fun subscribe(c: MqttAsyncClient) {
        val topics = arrayOf("$username/feeds/${Command.FEEDBACK_FEED}", "$username/errors", "$username/throttle")
        try {
            c.subscribe(topics, IntArray(topics.size) { 1 })
        } catch (_: MqttException) {
        }
    }

    private fun onMessage(topic: String, payload: String) {
        if (!topic.endsWith("/feeds/${Command.FEEDBACK_FEED}")) {
            // Adafruit IO error or rate-limit notice.
            showBanner(BannerKind.ERROR, "Adafruit IO", payload)
            return
        }
        val now = System.currentTimeMillis()
        when {
            payload == "OK:${Command.UPDATE_ACK}" -> {
                main.removeCallbacks(ackTimeout)
                update(state.copy(pending = null, active = null, lastFeedback = payload, lastFeedbackAt = now))
                showBanner(BannerKind.SUCCESS, "Aggiornamento avviato", "Il dispositivo si riavvia tra circa un minuto")
            }
            payload.startsWith("OK:") -> {
                val command = Command.fromAck(payload.removePrefix("OK:"))
                main.removeCallbacks(ackTimeout)
                update(
                    state.copy(
                        pending = null,
                        active = if (command == Command.SPEGNI_TUTTO) null else command ?: state.active,
                        lastFeedback = payload,
                        lastFeedbackAt = now,
                    )
                )
                if (command == Command.SPEGNI_TUTTO) {
                    showBanner(BannerKind.SUCCESS, "Comando ricevuto", "Promemoria spenti")
                } else {
                    showBanner(BannerKind.SUCCESS, "Comando ricevuto", "LED in corso di lampeggio")
                }
            }
            payload.startsWith("ERRORE") -> {
                main.removeCallbacks(ackTimeout)
                update(state.copy(pending = null, lastFeedback = payload, lastFeedbackAt = now))
                showBanner(BannerKind.ERROR, "Errore dal dispositivo", payload.substringAfter(':').replace('_', ' '))
            }
            else -> update(state.copy(lastFeedback = payload, lastFeedbackAt = now))
        }
    }

    private fun disconnect() {
        main.removeCallbacks(retry)
        main.removeCallbacks(ackTimeout)
        val c = client ?: return
        client = null
        // A clean disconnect does not trigger the will, so turn the lights off explicitly if they are blinking.
        closeQuietly(c, turnOff = state.active != null)
        update(state.copy(connection = Connection.DISCONNECTED, connectionError = null, pending = null, active = null))
    }

    private fun commandTopic() = "$username/feeds/${Command.COMMAND_FEED}"

    private fun publishOff(c: MqttAsyncClient) {
        try {
            c.publish(commandTopic(), OFF_PAYLOAD, 1, false)
        } catch (_: MqttException) {
        }
    }

    private fun closeQuietly(c: MqttAsyncClient, turnOff: Boolean = false) {
        val topic = commandTopic()
        Thread {
            try {
                if (turnOff && c.isConnected) {
                    c.publish(topic, OFF_PAYLOAD, 1, false).waitForCompletion(3000)
                }
            } catch (_: Exception) {
            }
            try {
                if (c.isConnected) c.disconnectForcibly(500, 1000)
            } catch (_: Exception) {
            }
            try {
                c.close()
            } catch (_: Exception) {
            }
        }.start()
    }

    private fun showBanner(kind: BannerKind, title: String, detail: String, autoHide: Boolean = true) {
        main.removeCallbacks(hideBanner)
        update(state.copy(banner = Banner(kind, title, detail)))
        if (autoHide) main.postDelayed(hideBanner, if (kind == BannerKind.ERROR) 8_000L else 6_000L)
    }

    private fun update(newState: State) {
        if (newState == state) return
        state = newState
        listeners.toList().forEach { it(newState) }
    }
}
