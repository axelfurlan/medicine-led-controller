package com.medicinled.controller

import android.animation.ArgbEvaluator
import android.animation.ValueAnimator
import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.view.Gravity
import android.view.View
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import kotlin.math.roundToInt

fun Context.dp(value: Number): Int = (value.toFloat() * resources.displayMetrics.density).roundToInt()

fun Context.rounded(color: Int, radiusDp: Int): GradientDrawable =
    GradientDrawable().apply { cornerRadius = dp(radiusDp).toFloat(); setColor(color) }

private val GREEN = Color.rgb(57, 231, 95)
private val ACTIVE_FILL = Color.rgb(190, 247, 170)

/** Rounded, colored button for one command; blinks green while the device confirms or shows it. */
class CommandTile(context: Context, val command: Command, iconWidthDp: Int, iconHeightDp: Int) : LinearLayout(context) {
    enum class Highlight { NONE, PENDING, ACTIVE }

    private val bg = context.rounded(command.color, 22)
    private var animator: ValueAnimator? = null
    private var highlight = Highlight.NONE
    private val dark = command == Command.SPEGNI_TUTTO
    private val argb = ArgbEvaluator()

    init {
        orientation = if (dark) HORIZONTAL else VERTICAL
        gravity = Gravity.CENTER
        background = bg
        foreground = RippleDrawable(ColorStateList.valueOf(0x33000000), null, context.rounded(Color.WHITE, 22))
        isClickable = true
        contentDescription = listOfNotNull(command.label, command.subtitle).joinToString(", ")
        setPadding(context.dp(8), context.dp(8), context.dp(8), context.dp(8))

        addView(ImageView(context).apply { setImageResource(command.icon) }, LayoutParams(context.dp(iconWidthDp), context.dp(iconHeightDp)))
        val label = TextView(context).apply {
            text = command.label
            textSize = if (command.subtitle != null) 16f else 21f
            setTypeface(typeface, Typeface.BOLD)
            gravity = Gravity.CENTER
            setTextColor(if (dark) Color.WHITE else Color.rgb(28, 32, 40))
        }
        addView(label, LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT).apply {
            if (dark) leftMargin = context.dp(14) else topMargin = context.dp(4)
        })
        command.subtitle?.let { subtitle ->
            addView(TextView(context).apply {
                text = subtitle
                textSize = 14f
                gravity = Gravity.CENTER
                setTextColor(Color.rgb(55, 62, 75))
            })
        }
    }

    fun setHighlight(value: Highlight) {
        if (value == highlight) return
        highlight = value
        animator?.cancel()
        animator = null
        if (value == Highlight.NONE) {
            bg.setColor(command.color)
            bg.setStroke(0, Color.TRANSPARENT)
            return
        }
        val active = value == Highlight.ACTIVE
        animator = ValueAnimator.ofFloat(0f, 1f).apply {
            duration = if (active) 700L else 350L
            repeatMode = ValueAnimator.REVERSE
            repeatCount = ValueAnimator.INFINITE
            addUpdateListener {
                val f = it.animatedValue as Float
                bg.setColor(argb.evaluate(if (active) f else f * 0.35f, command.color, ACTIVE_FILL) as Int)
                bg.setStroke(context.dp(4), Color.argb((90 + 165 * f).toInt(), Color.red(GREEN), Color.green(GREEN), Color.blue(GREEN)))
            }
            start()
        }
    }

    override fun onDetachedFromWindow() {
        super.onDetachedFromWindow()
        // Stop animating while hidden; the next render() restarts it.
        setHighlight(Highlight.NONE)
    }
}

/**
 * The "Farmaci" panel: header, 2x4 grid of commands, "Spegni" (active view only) and a feedback banner.
 * [onSettings] / [onQuit] / [onClose] add the gear / exit / X buttons to the header when not null.
 */
class CommandPanel(
    context: Context,
    onSettings: (() -> Unit)? = null,
    onClose: (() -> Unit)? = null,
    onQuit: (() -> Unit)? = null,
) : LinearLayout(context) {
    private val tiles = mutableListOf<CommandTile>()
    private val gridView = LinearLayout(context)
    private val activeView = LinearLayout(context)
    private val activeContent = LinearLayout(context).apply { orientation = VERTICAL }
    private var shownCommand: Command? = null
    private var activeTile: CommandTile? = null
    private val connectionText: TextView
    private val banner = LinearLayout(context)
    private val bannerProgress = ProgressBar(context)
    private val bannerIcon = ImageView(context)
    private val bannerTitle = TextView(context)
    private val bannerDetail = TextView(context)

    init {
        orientation = VERTICAL
        background = context.rounded(Color.rgb(43, 47, 54), 28)
        val pad = context.dp(14)
        setPadding(pad, context.dp(10), pad, pad)

        val header = LinearLayout(context).apply { orientation = HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        val titles = LinearLayout(context).apply { orientation = VERTICAL }
        titles.addView(TextView(context).apply {
            text = "Farmaci"; textSize = 26f; setTypeface(typeface, Typeface.BOLD); setTextColor(Color.WHITE)
        })
        connectionText = TextView(context).apply { textSize = 13f }
        titles.addView(connectionText)
        header.addView(titles, LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f))
        onSettings?.let { header.addView(headerButton(R.drawable.ic_settings, "Impostazioni", it)) }
        onQuit?.let { header.addView(headerButton(R.drawable.ic_exit, "Esci dall'app", it)) }
        onClose?.let { header.addView(headerButton(R.drawable.ic_close, "Chiudi", it)) }
        addView(header, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT).apply { bottomMargin = context.dp(8) })

        gridView.orientation = VERTICAL
        addRow(Command.PRIMA_COLAZIONE, Command.DOPO_COLAZIONE, heightDp = 112, iconW = 48, iconH = 48)
        addRow(Command.PRANZO, Command.LOKELMA, heightDp = 104, iconW = 48, iconH = 48)
        addRow(Command.PRIMA_CENA, Command.DOPO_CENA, heightDp = 112, iconW = 48, iconH = 48)
        addRow(Command.INSULINA_PASTI, Command.INSULINA_NOTTE, heightDp = 132, iconW = 110, iconH = 48)
        addView(gridView, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT))

        // While a command is blinking, the grid is replaced by this view: the active tile, its medicines and "Spegni".
        activeView.orientation = VERTICAL
        activeView.visibility = GONE
        activeView.addView(activeContent, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT))
        addTile(Command.SPEGNI_TUTTO, activeView, LayoutParams(LayoutParams.MATCH_PARENT, context.dp(64)).apply { topMargin = context.dp(12) }, 32, 32)
        addView(activeView, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT))

        banner.apply {
            orientation = HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(context.dp(14), context.dp(10), context.dp(14), context.dp(10))
            visibility = GONE
        }
        bannerProgress.indeterminateTintList = ColorStateList.valueOf(Color.WHITE)
        banner.addView(bannerProgress, LayoutParams(context.dp(30), context.dp(30)))
        banner.addView(bannerIcon, LayoutParams(context.dp(30), context.dp(30)))
        val bannerTexts = LinearLayout(context).apply { orientation = VERTICAL; setPadding(context.dp(12), 0, 0, 0) }
        bannerTitle.apply { textSize = 16f; setTypeface(typeface, Typeface.BOLD); setTextColor(Color.WHITE) }
        bannerDetail.apply { textSize = 14f; setTextColor(Color.WHITE) }
        bannerTexts.addView(bannerTitle)
        bannerTexts.addView(bannerDetail)
        banner.addView(bannerTexts, LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f))
        addView(banner, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT).apply { topMargin = context.dp(10) })
    }

    private fun headerButton(icon: Int, description: String, action: () -> Unit) = ImageView(context).apply {
        setImageResource(icon)
        contentDescription = description
        val p = context.dp(10)
        setPadding(p, p, p, p)
        background = RippleDrawable(ColorStateList.valueOf(0x33FFFFFF), null, null)
        layoutParams = LayoutParams(context.dp(48), context.dp(48))
        setOnClickListener { action() }
    }

    private fun addRow(left: Command, right: Command, heightDp: Int, iconW: Int, iconH: Int) {
        val row = LinearLayout(context).apply { orientation = HORIZONTAL }
        val gap = context.dp(5)
        addTile(left, row, LayoutParams(0, LayoutParams.MATCH_PARENT, 1f).apply { rightMargin = gap }, iconW, iconH)
        addTile(right, row, LayoutParams(0, LayoutParams.MATCH_PARENT, 1f).apply { leftMargin = gap }, iconW, iconH)
        gridView.addView(row, LayoutParams(LayoutParams.MATCH_PARENT, context.dp(heightDp)).apply { topMargin = context.dp(10) })
    }

    private fun showActive(command: Command?) {
        shownCommand = command
        activeContent.removeAllViews()
        activeTile = null
        if (command == null) return

        val tile = CommandTile(context, command, 64, 64)
        activeTile = tile
        activeContent.addView(tile, LayoutParams(context.dp(200), context.dp(150)).apply {
            gravity = Gravity.CENTER_HORIZONTAL
            topMargin = context.dp(6)
        })

        val names = MedicineCatalog.namesFor(context, command)
        val card = LinearLayout(context).apply {
            orientation = VERTICAL
            background = context.rounded(Color.rgb(34, 38, 46), 22)
            setPadding(context.dp(12), context.dp(12), context.dp(12), context.dp(12))
        }
        val header = LinearLayout(context).apply { orientation = HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        val titles = LinearLayout(context).apply { orientation = VERTICAL }
        titles.addView(TextView(context).apply {
            text = listOfNotNull(command.label, command.subtitle.takeIf { command.displayNames == null }).joinToString(" · ")
            textSize = 24f; setTypeface(typeface, Typeface.BOLD); setTextColor(Color.WHITE)
        })
        titles.addView(TextView(context).apply {
            text = if (names.size == 1) "Viene illuminato:" else "Vengono illuminate le seguenti medicine:"
            textSize = 13f; setTextColor(Color.rgb(184, 190, 201))
        })
        header.addView(titles, LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f))
        val badge = LinearLayout(context).apply {
            orientation = HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            background = context.rounded(Color.rgb(30, 142, 62), 16)
            setPadding(context.dp(10), context.dp(6), context.dp(10), context.dp(6))
        }
        badge.addView(ProgressBar(context).apply { indeterminateTintList = ColorStateList.valueOf(Color.WHITE) },
            LayoutParams(context.dp(22), context.dp(22)))
        badge.addView(TextView(context).apply {
            text = "LED in corso di lampeggio…"
            textSize = 12f; maxWidth = context.dp(104); setTypeface(typeface, Typeface.BOLD); setTextColor(Color.WHITE)
        }, LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT).apply { leftMargin = context.dp(8) })
        header.addView(badge, LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT).apply { leftMargin = context.dp(8) })
        card.addView(header)

        if (names.isEmpty()) {
            card.addView(TextView(context).apply {
                text = "Nessuna medicina assegnata a questo momento."
                textSize = 15f; setTextColor(Color.WHITE)
            }, LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT).apply { topMargin = context.dp(10) })
        }
        names.forEachIndexed { i, name ->
            val row = LinearLayout(context).apply {
                orientation = HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                background = context.rounded(Color.rgb(27, 31, 38), 16)
                setPadding(context.dp(14), context.dp(12), context.dp(14), context.dp(12))
            }
            row.addView(View(context).apply { background = context.rounded(PILL_COLORS[i % PILL_COLORS.size], 10) },
                LayoutParams(context.dp(32), context.dp(18)))
            row.addView(TextView(context).apply {
                text = name
                textSize = 19f; setTypeface(typeface, Typeface.BOLD); setTextColor(Color.WHITE)
            }, LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f).apply { leftMargin = context.dp(14) })
            card.addView(row, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT).apply { topMargin = context.dp(8) })
        }
        activeContent.addView(card, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT).apply { topMargin = context.dp(12) })
    }

    private fun addTile(command: Command, parent: LinearLayout, params: LayoutParams, iconW: Int, iconH: Int) {
        val tile = CommandTile(context, command, iconW, iconH)
        tile.setOnClickListener { MqttController.send(command) }
        tiles += tile
        parent.addView(tile, params)
    }

    fun render(state: MqttController.State) {
        if (state.active != shownCommand) showActive(state.active)
        gridView.visibility = if (state.active == null) VISIBLE else GONE
        activeView.visibility = if (state.active == null) GONE else VISIBLE
        activeTile?.setHighlight(CommandTile.Highlight.ACTIVE)

        for (tile in tiles) {
            tile.setHighlight(
                when (tile.command) {
                    state.pending -> CommandTile.Highlight.PENDING
                    state.active -> CommandTile.Highlight.ACTIVE
                    else -> CommandTile.Highlight.NONE
                }
            )
        }

        val (label, color) = connectionLabel(state)
        connectionText.text = "● $label"
        connectionText.setTextColor(color)

        val b = state.banner
        // Success is already shown by the active view and a pending tile pulses, so the banner only reports
        // problems, plus "sending" while the active view is open (where "Spegni" is pressed).
        val show = b != null && (b.kind == MqttController.BannerKind.ERROR ||
            (b.kind == MqttController.BannerKind.SENDING && state.active != null))
        if (b == null || !show) {
            banner.visibility = GONE
            return
        }
        banner.visibility = VISIBLE
        banner.background = context.rounded(
            if (b.kind == MqttController.BannerKind.ERROR) Color.rgb(198, 40, 40) else Color.rgb(30, 142, 62), 18
        )
        bannerProgress.visibility = if (b.kind == MqttController.BannerKind.SENDING) VISIBLE else GONE
        bannerIcon.visibility = if (b.kind == MqttController.BannerKind.SENDING) GONE else VISIBLE
        bannerIcon.setImageResource(if (b.kind == MqttController.BannerKind.ERROR) R.drawable.ic_error else R.drawable.ic_check)
        bannerTitle.text = b.title
        bannerDetail.text = b.detail
    }

    companion object {
        private val PILL_COLORS = intArrayOf(
            Color.rgb(236, 236, 240), Color.rgb(240, 150, 140), Color.rgb(236, 205, 140), Color.rgb(255, 193, 7),
        )

        fun connectionLabel(state: MqttController.State): Pair<String, Int> = when (state.connection) {
            MqttController.Connection.CONNECTED -> "Connesso" to Color.rgb(76, 217, 100)
            MqttController.Connection.CONNECTING -> "Connessione…" to Color.rgb(255, 193, 7)
            MqttController.Connection.DISCONNECTED -> "Non connesso" to Color.rgb(170, 176, 186)
            MqttController.Connection.FAILED -> "Non connesso" to Color.rgb(255, 107, 107)
        }
    }
}
