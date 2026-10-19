package com.medicinled.controller

import android.app.ActivityManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.IBinder
import android.os.Process
import android.provider.Settings
import android.util.DisplayMetrics
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import kotlin.math.hypot

/**
 * Foreground service that draws a draggable pill button over other apps (e.g. a video call).
 * Tapping it opens the command panel; X collapses it back to the button.
 */
class OverlayService : Service() {
    companion object {
        const val ACTION_STOP = "com.medicinled.controller.STOP_OVERLAY"
        private const val CHANNEL_ID = "overlay"
        private const val NOTIFICATION_ID = 1

        var isRunning = false
            private set
    }

    private lateinit var wm: WindowManager
    private lateinit var bubble: FrameLayout
    private lateinit var bubbleRing: GradientDrawable
    private lateinit var bubbleParams: WindowManager.LayoutParams
    private lateinit var panel: CommandPanel
    private lateinit var panelRoot: ScrollView
    private lateinit var panelParams: WindowManager.LayoutParams
    private lateinit var closeTarget: LinearLayout
    private lateinit var closeCircle: GradientDrawable
    private lateinit var closeParams: WindowManager.LayoutParams
    private var closeTargetShown = false
    private var expanded = false
    private var quitting = false

    private val listener: (MqttController.State) -> Unit = { state ->
        if (expanded) panel.render(state)
        bubbleRing.setStroke(dp(4), CommandPanel.connectionLabel(state).second)
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        startInForeground()
        if (!Settings.canDrawOverlays(this)) {
            stopSelf()
            return
        }
        isRunning = true
        wm = getSystemService(WindowManager::class.java)
        createBubble()
        createPanel()
        createCloseTarget()
        wm.addView(bubble, bubbleParams)
        MqttController.acquire(this)
        MqttController.addListener(listener)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) stopSelf()
        return START_STICKY
    }

    override fun onDestroy() {
        if (isRunning) {
            isRunning = false
            MqttController.removeListener(listener)
            MqttController.release()
            removeQuietly(if (expanded) panelRoot else bubble)
            hideCloseTarget()
        }
        super.onDestroy()
        if (quitting) Process.killProcess(Process.myPid())
    }

    private fun startInForeground() {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL_ID, "Pulsante flottante", NotificationManager.IMPORTANCE_LOW))
        val flags = PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), flags)
        val stop = PendingIntent.getService(this, 1, Intent(this, OverlayService::class.java).setAction(ACTION_STOP), flags)
        val notification = Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_pill)
            .setContentTitle("Farmaci")
            .setContentText("Pulsante flottante attivo")
            .setContentIntent(open)
            .setOngoing(true)
            .addAction(Notification.Action.Builder(null, "Chiudi pulsante", stop).build())
            .build()
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun overlayParams(width: Int, height: Int, gravity: Int) = WindowManager.LayoutParams(
        width, height,
        WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
        PixelFormat.TRANSLUCENT,
    ).also { it.gravity = gravity }

    private fun createBubble() {
        val size = dp(68)
        val margin = dp(6) // room for the shadow
        bubbleRing = GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(Color.WHITE)
            setStroke(dp(4), Color.rgb(170, 176, 186))
        }
        val circle = FrameLayout(this).apply {
            background = bubbleRing
            elevation = dp(6).toFloat()
            contentDescription = "Apri comandi farmaci"
            addView(ImageView(context).apply { setImageResource(R.drawable.ic_pill) },
                FrameLayout.LayoutParams(dp(42), dp(42), Gravity.CENTER))
        }
        bubble = FrameLayout(this).apply {
            setPadding(margin, margin, margin, margin)
            addView(circle, FrameLayout.LayoutParams(size, size))
        }
        bubbleParams = overlayParams(
            WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT, Gravity.TOP or Gravity.START,
        )
        val (screenW, screenH) = screenSize()
        val saved = AppSettings.bubblePosition(this)
        bubbleParams.x = saved?.first ?: (screenW - size - 2 * margin)
        bubbleParams.y = saved?.second ?: (screenH * 0.45).toInt()
        clampBubble()
        bubble.setOnTouchListener(BubbleDragListener())
    }

    private fun createPanel() {
        panel = CommandPanel(this, onSettings = ::openSettings, onClose = ::collapse, onQuit = ::quitApp)
        panel.elevation = dp(8).toFloat()
        panelRoot = ScrollView(this).apply {
            val p = dp(8)
            setPadding(p, p, p, p)
            clipToPadding = false
            addView(panel)
        }
        panelParams = overlayParams(0, WindowManager.LayoutParams.WRAP_CONTENT, Gravity.CENTER)
    }

    /** "Drop here to close" target shown at the bottom of the screen while the bubble is dragged. */
    private fun createCloseTarget() {
        closeCircle = GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(Color.argb(220, 43, 47, 54))
            setStroke(dp(2), Color.WHITE)
        }
        val circle = FrameLayout(this).apply {
            background = closeCircle
            addView(ImageView(context).apply { setImageResource(R.drawable.ic_close) },
                FrameLayout.LayoutParams(dp(32), dp(32), Gravity.CENTER))
        }
        closeTarget = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            val p = dp(12)
            setPadding(p, p, p, p)
            addView(circle, LinearLayout.LayoutParams(dp(68), dp(68)))
            addView(TextView(context).apply {
                text = "Trascina qui per chiudere"
                textSize = 14f
                setTextColor(Color.WHITE)
                setShadowLayer(dp(3).toFloat(), 0f, 0f, Color.BLACK)
                setPadding(0, dp(6), 0, 0)
            })
        }
        closeParams = overlayParams(
            WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT,
            Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL,
        ).apply {
            flags = flags or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
            y = dp(56)
        }
    }

    private fun showCloseTarget() {
        if (closeTargetShown) return
        closeTargetShown = true
        setCloseTargetActive(false)
        closeTarget.alpha = 0f
        wm.addView(closeTarget, closeParams)
        closeTarget.animate().alpha(1f).setDuration(150).start()
    }

    private fun hideCloseTarget() {
        if (!closeTargetShown) return
        closeTargetShown = false
        removeQuietly(closeTarget)
    }

    private fun setCloseTargetActive(active: Boolean) {
        closeCircle.setColor(if (active) Color.rgb(198, 40, 40) else Color.argb(220, 43, 47, 54))
        val scale = if (active) 1.2f else 1f
        closeTarget.getChildAt(0).animate().scaleX(scale).scaleY(scale).setDuration(100).start()
    }

    /** True when the finger at ([rawX], [rawY]) is close enough to the close target to drop the bubble on it. */
    private fun isOverCloseTarget(rawX: Float, rawY: Float): Boolean {
        if (!closeTargetShown || !closeTarget.isAttachedToWindow) return false
        val circle = closeTarget.getChildAt(0)
        val loc = IntArray(2)
        circle.getLocationOnScreen(loc)
        val cx = loc[0] + circle.width / 2f
        val cy = loc[1] + circle.height / 2f
        return hypot(rawX - cx, rawY - cy) < dp(80)
    }

    private fun expand() {
        if (expanded) return
        expanded = true
        panelParams.width = minOf(screenSize().first - dp(16), dp(400))
        removeQuietly(bubble)
        wm.addView(panelRoot, panelParams)
        panel.render(MqttController.state)
        panel.alpha = 0f
        panel.scaleX = 0.92f
        panel.scaleY = 0.92f
        panel.animate().alpha(1f).scaleX(1f).scaleY(1f).setDuration(150).start()
    }

    private fun collapse() {
        if (!expanded) return
        expanded = false
        removeQuietly(panelRoot)
        clampBubble()
        wm.addView(bubble, bubbleParams)
    }

    private fun openSettings() {
        collapse()
        startActivity(
            Intent(this, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)
        )
    }

    /** Removes the overlay, closes any open app screen and ends the process (and with it the MQTT connection). */
    private fun quitApp() {
        quitting = true
        getSystemService(ActivityManager::class.java).appTasks.forEach { it.finishAndRemoveTask() }
        stopSelf()
    }

    private fun removeQuietly(view: View) {
        try {
            wm.removeView(view)
        } catch (_: IllegalArgumentException) {
        }
    }

    private fun bubbleSize() = dp(68 + 12)

    private fun clampBubble() {
        val (w, h) = screenSize()
        bubbleParams.x = bubbleParams.x.coerceIn(0, (w - bubbleSize()).coerceAtLeast(0))
        bubbleParams.y = bubbleParams.y.coerceIn(0, (h - bubbleSize()).coerceAtLeast(0))
    }

    private fun screenSize(): Pair<Int, Int> =
        if (Build.VERSION.SDK_INT >= 30) {
            wm.currentWindowMetrics.bounds.let { it.width() to it.height() }
        } else {
            val dm = DisplayMetrics()
            @Suppress("DEPRECATION")
            wm.defaultDisplay.getRealMetrics(dm)
            dm.widthPixels to dm.heightPixels
        }

    /** Drags the bubble, snaps it to the nearest side on release; a plain tap opens the panel. */
    private inner class BubbleDragListener : View.OnTouchListener {
        private val touchSlop = ViewConfiguration.get(this@OverlayService).scaledTouchSlop
        private var startX = 0
        private var startY = 0
        private var downX = 0f
        private var downY = 0f
        private var dragging = false
        private var overClose = false

        override fun onTouch(v: View, e: MotionEvent): Boolean {
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    startX = bubbleParams.x; startY = bubbleParams.y
                    downX = e.rawX; downY = e.rawY
                    dragging = false
                    overClose = false
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = e.rawX - downX
                    val dy = e.rawY - downY
                    if (!dragging && hypot(dx, dy) > touchSlop) {
                        dragging = true
                        showCloseTarget()
                    }
                    if (dragging) {
                        val over = isOverCloseTarget(e.rawX, e.rawY)
                        if (over != overClose) {
                            overClose = over
                            setCloseTargetActive(over)
                            if (over) v.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
                        }
                        bubbleParams.x = startX + dx.toInt()
                        bubbleParams.y = startY + dy.toInt()
                        clampBubble()
                        wm.updateViewLayout(bubble, bubbleParams)
                    }
                }
                MotionEvent.ACTION_UP -> {
                    hideCloseTarget()
                    if (dragging && overClose) {
                        stopSelf()
                    } else if (dragging) {
                        val w = screenSize().first
                        bubbleParams.x = if (bubbleParams.x + bubbleSize() / 2 < w / 2) 0 else w - bubbleSize()
                        wm.updateViewLayout(bubble, bubbleParams)
                        AppSettings.saveBubblePosition(this@OverlayService, bubbleParams.x, bubbleParams.y)
                    } else {
                        v.performClick()
                        expand()
                    }
                }
                MotionEvent.ACTION_CANCEL -> hideCloseTarget()
            }
            return true
        }
    }
}
