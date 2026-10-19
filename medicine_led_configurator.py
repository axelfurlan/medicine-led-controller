#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configurator for the ESPHome device "led-farmaci".
Dependencies: Python standard library only (Tkinter).
Generates:
  - configuration.json
  - led-farmaci.yaml
  - secrets.yaml (credentials; never embedded in the generated firmware)
"""

import json
import re
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path

CONFIG_VERSION = 3
DEVICE_NAME = "led-farmaci"
MAX_STRIPS = 5
SUGGESTED_GPIOS = (16, 17, 18, 19, 21)
# ESP32 pins able to drive a data line (6-11 are flash, 34-39 are input-only).
VALID_OUTPUT_GPIOS = (0, 1, 2, 3, 4, 5, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 23, 25, 26, 27, 32, 33)
RESERVED_MODE_IDS = {"nessuna", "spento", "errore", "off"}
OFF_PAYLOAD = "off"
DEFAULT_COMMAND_FEED = "led-farmaci-command"
DEFAULT_FEEDBACK_FEED = "led-farmaci-feedback"
DEFAULT_MOMENTS = (
    "Before breakfast", "After breakfast", "Lunch", "Before dinner", "After dinner",
    "Meals insulin pen", "Night insulin pen", "Non-dialysis days medicines",
)
DEFAULT_PULSE = {"on_ms": 700, "off_ms": 400, "transition_ms": 400}
MOMENT_ID_RE = re.compile(r"[a-z][a-z0-9_]*")
FEED_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
MOMENT_COLUMNS = 3
SCRIPT_DIR = Path(__file__).resolve().parent

FONT = "Segoe UI"
COLORS = {
    "bg": "#1e1f24",
    "sidebar": "#17181c",
    "card": "#272932",
    "input": "#30333d",
    "border": "#3a3d48",
    "hover": "#3f4350",
    "text": "#e6e8ee",
    "muted": "#9aa0ad",
    "accent": "#4f8cff",
    "accent_hover": "#6a9fff",
    "success": "#3ecf8e",
    "danger": "#ff6b6b",
    "led_off": "#3a3d48",
    "led_green": "#2ee66b",
    "led_red": "#ff3b3b",
}
SEGMENT_COLORS = ("#4f8cff", "#3ecf8e", "#f5a623", "#b57bff", "#ff7eb6", "#4dd0e1", "#ffd54f", "#a1e44d")


# ---------------------------------------------------------------------------
# Configuration model (no Tk: usable headless)
# ---------------------------------------------------------------------------

def yaml_quote(value):
    """Return a YAML-compatible quoted string."""
    return json.dumps(str(value), ensure_ascii=False)


def safe_id(value):
    value = re.sub(r"[^a-zA-Z0-9_]", "_", value.strip().lower())
    if not value or value[0].isdigit():
        value = "x_" + value
    return value


def moment_id_from_name(name):
    value = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    if not value:
        return "moment"
    return value if value[0].isalpha() else "m_" + value


def parse_int(text):
    try:
        return int(str(text).strip())
    except ValueError:
        return None


def mqtt_topic(username, feed):
    return f"{username}/feeds/{feed}"


def default_config():
    moments = []
    for name in DEFAULT_MOMENTS:
        moment_id = moment_id_from_name(name)
        moments.append({"id": moment_id, "name": name})
    shelf = [
        {"name": f"Medicine {i}", "leds": 6, "gap_after": 1 if i < 9 else 0, "moments": ["after_breakfast"]}
        for i in range(1, 10)
    ]
    return {
        "version": CONFIG_VERSION,
        "device_name": DEVICE_NAME,
        "moments": moments,
        "strips": [
            {"name": "Medicine shelf", "gpio": 18, "num_leds": 62, "segments": shelf},
            {"name": "Meals insulin pen", "gpio": 19, "num_leds": 6, "segments": [
                {"name": "Meals insulin pen", "leds": 6, "gap_after": 0, "moments": ["meals_insulin_pen"]}]},
            {"name": "Night insulin pen", "gpio": 21, "num_leds": 6, "segments": [
                {"name": "Night insulin pen", "leds": 6, "gap_after": 0, "moments": ["night_insulin_pen"]}]},
        ],
        "connections": {
            "mqtt_broker": "io.adafruit.com",
            "mqtt_port": 1883,
            "mqtt_username": "",
            "mqtt_keepalive": 30,
            "command_feed": DEFAULT_COMMAND_FEED,
            "feedback_feed": DEFAULT_FEEDBACK_FEED,
        },
        "pulse": dict(DEFAULT_PULSE),
    }


def migrate_config(cfg):
    """Upgrade a version 2 configuration (one feed per moment) to version 3 (one command feed)."""
    if not isinstance(cfg, dict) or cfg.get("version") != 2:
        return cfg
    cfg = json.loads(json.dumps(cfg))
    cfg["version"] = CONFIG_VERSION
    cfg["moments"] = [{"id": m["id"], "name": m["name"]} for m in cfg.get("moments", [])]
    conn = cfg.setdefault("connections", {})
    conn.pop("all_off_feed", None)
    conn.pop("topics", None)
    conn["command_feed"] = DEFAULT_COMMAND_FEED
    conn.setdefault("feedback_feed", DEFAULT_FEEDBACK_FEED)
    return cfg


def compute_layout(segments):
    """Return ([(start, end) per segment], used_leds); segments are laid out in order."""
    ranges, pos = [], 0
    for seg in segments:
        start = pos
        end = start + seg["leds"] - 1
        ranges.append((start, end))
        pos = end + 1 + seg["gap_after"]
    used = ranges[-1][1] + 1 if ranges else 0
    return ranges, used


def validate_config(cfg):
    errors = []
    moments = cfg.get("moments", [])
    strips = cfg.get("strips", [])
    conn = cfg.get("connections", {})
    command_feed = conn.get("command_feed", "")
    feedback_feed = conn.get("feedback_feed", "")

    if not moments:
        errors.append("Add at least one moment.")
    moment_ids = {m["id"] for m in moments}
    ids = set()
    for i, moment in enumerate(moments, start=1):
        label = moment["name"] or f"Moment {i}"
        if not moment["name"]:
            errors.append(f"Moment {i} needs a name.")
        if not MOMENT_ID_RE.fullmatch(moment["id"]):
            errors.append(f"Moment '{label}': ID '{moment['id']}' must start with a letter and use only a-z, 0-9 and _.")
        elif moment["id"] in RESERVED_MODE_IDS:
            errors.append(f"Moment '{label}': ID '{moment['id']}' is reserved by the firmware.")
        elif moment["id"] in ids:
            errors.append(f"Moment ID '{moment['id']}' is used more than once.")
        ids.add(moment["id"])

    for key, label in (("command_feed", "Command"), ("feedback_feed", "Feedback")):
        if not FEED_RE.fullmatch(conn.get(key, "")):
            errors.append(f"{label} feed '{conn.get(key, '')}' must use only a-z, 0-9 and -.")
    if command_feed and command_feed == feedback_feed:
        errors.append("The command and feedback feeds must be different.")

    if not 1 <= len(strips) <= MAX_STRIPS:
        errors.append(f"Configure between 1 and {MAX_STRIPS} strips.")
    gpios = {}
    segment_ids = set()
    for i, strip in enumerate(strips, start=1):
        label = strip["name"] or f"Strip {i}"
        gpio = strip["gpio"]
        if gpio not in VALID_OUTPUT_GPIOS:
            errors.append(f"Strip '{label}': GPIO {gpio} cannot drive an LED strip.")
        elif gpio in gpios:
            errors.append(f"GPIO {gpio} is used by both '{gpios[gpio]}' and '{label}'.")
        gpios[gpio] = label
        if strip["num_leds"] < 1:
            errors.append(f"Strip '{label}' must have at least 1 LED.")
        if not strip["segments"]:
            errors.append(f"Strip '{label}' has no segments.")

        layout_ok = True
        for j, seg in enumerate(strip["segments"], start=1):
            seg_label = seg["name"] or f"{label}, segment {j}"
            if not seg["name"]:
                errors.append(f"{seg_label} needs a name.")
            elif safe_id(seg["name"]) in segment_ids:
                errors.append(f"Segment name '{seg['name']}' is used more than once.")
            segment_ids.add(safe_id(seg["name"]))
            if seg["leds"] < 1:
                errors.append(f"Segment '{seg_label}' must use at least 1 LED.")
                layout_ok = False
            if seg["gap_after"] < 0:
                errors.append(f"Segment '{seg_label}': the gap cannot be negative.")
                layout_ok = False
            if not seg["moments"]:
                errors.append(f"Segment '{seg_label}' is not assigned to any moment.")
            for moment_id in seg["moments"]:
                if moment_id not in moment_ids:
                    errors.append(f"Segment '{seg_label}' refers to unknown moment '{moment_id}'.")
        if layout_ok and strip["segments"]:
            _, used = compute_layout(strip["segments"])
            if used > strip["num_leds"]:
                errors.append(f"Strip '{label}' needs {used} LEDs but has only {strip['num_leds']}.")

    pulse = cfg.get("pulse", {})
    on_ms, off_ms, transition_ms = pulse.get("on_ms", 0), pulse.get("off_ms", 0), pulse.get("transition_ms", -1)
    if on_ms < 50 or off_ms < 50:
        errors.append("Blink on and off times must be at least 50 ms.")
    if transition_ms < 0 or transition_ms > min(on_ms, off_ms):
        errors.append("The fade transition must be between 0 ms and the shorter of the on/off times.")

    if not conn.get("mqtt_broker", "").strip():
        errors.append("MQTT broker cannot be empty.")
    if not 1 <= int(conn.get("mqtt_port", 0)) <= 65535:
        errors.append("MQTT port must be between 1 and 65535.")
    if not conn.get("mqtt_username", "").strip():
        errors.append("Enter your MQTT username.")
    if int(conn.get("mqtt_keepalive", 0)) < 1:
        errors.append("MQTT keepalive must be at least 1 second.")
    return errors


def generate_yaml(cfg):
    conn = cfg["connections"]
    pulse = cfg["pulse"]
    on_ms, off_ms, transition_ms = int(pulse["on_ms"]), int(pulse["off_ms"]), int(pulse["transition_ms"])
    username = conn["mqtt_username"].strip()
    feedback_topic = mqtt_topic(username, conn["feedback_feed"])
    command_topic = mqtt_topic(username, conn["command_feed"])
    moments = cfg["moments"]
    strips = cfg["strips"]
    mode_ids = [m["id"] for m in moments]
    # Two RMT memory blocks per strip fit up to 4 strips; 5 strips need one block each.
    rmt_symbols = 128 if len(strips) <= 4 else 64

    segments = []
    for n, strip in enumerate(strips, start=1):
        ranges, _ = compute_layout(strip["segments"])
        for m, (seg, (start, end)) in enumerate(zip(strip["segments"], ranges), start=1):
            segments.append({
                "id": f"seg_{n}_{m}", "name": seg["name"], "strip_id": f"strip_{n}",
                "start": start, "end": end, "moments": set(seg["moments"]),
            })
    all_ids = [s["id"] for s in segments]

    lines = []
    add = lines.append

    def light_on(pad, entity_id, red, green, transition=False):
        add(f"{pad}- light.turn_on:")
        add(f"{pad}    id: {entity_id}")
        add(f"{pad}    red: {red}%")
        add(f"{pad}    green: {green}%")
        add(f"{pad}    blue: 0%")
        add(f"{pad}    brightness: 100%")
        if transition:
            add(f"{pad}    transition_length: {transition_ms}ms")

    def light_off(pad, entity_id):
        add(f"{pad}- light.turn_off:")
        add(f"{pad}    id: {entity_id}")
        add(f"{pad}    transition_length: {transition_ms}ms")

    def all_red(pad):
        for entity_id in all_ids:
            light_on(pad, entity_id, 100, 0)

    def stop_scripts(pad, include_error=True):
        if include_error:
            add(f"{pad}- script.stop: lampeggio_errore")
        for mode in mode_ids:
            add(f"{pad}- script.stop: lampeggio_{mode}")

    def set_mode(pad, mode, connected=None):
        add(f"{pad}- lambda: |-")
        if connected is not None:
            add(f"{pad}    id(mqtt_connesso) = {'true' if connected else 'false'};")
        add(f'{pad}    id(modalita_attiva) = "{mode}";')

    def publish(pad, payload):
        add(f"{pad}- mqtt.publish:")
        add(f"{pad}    topic: {yaml_quote(feedback_topic)}")
        add(f"{pad}    payload: {yaml_quote(payload)}")

    def blink_loop(pad, ids, red, green):
        for entity_id in ids:
            light_on(pad, entity_id, red, green, transition=True)
        add(f"{pad}- delay: {on_ms}ms")
        for entity_id in ids:
            light_off(pad, entity_id)
        add(f"{pad}- delay: {off_ms}ms")

    def on_command(payload, log_text, mode, ack, start_script):
        pad = " " * 10
        add(f"    - topic: {yaml_quote(command_topic)}")
        add(f"      payload: {yaml_quote(payload)}")
        add("      then:")
        add(f"{pad}- logger.log: {yaml_quote(log_text)}")
        stop_scripts(pad)
        set_mode(pad, mode)
        all_red(pad)
        if start_script:
            add(f"{pad}- script.execute: lampeggio_{mode}")
        publish(pad, ack)

    add("# Automatically generated by the Medicine LED Configurator. Do not edit by hand.")
    add("# MQTT username and topics come from configuration.json; credentials are read from secrets.yaml.")
    add("")
    add("esphome:")
    add(f"  name: {cfg.get('device_name', DEVICE_NAME)}")
    add("")
    add("  on_boot:")
    add("    - priority: 600")
    add("      then:")
    set_mode(" " * 8, "nessuna", connected=False)
    all_red(" " * 8)
    add("        - script.execute: lampeggio_errore")
    add("")
    add("esp32:")
    add("  board: esp32dev")
    add("  framework:")
    add("    type: arduino")
    add("")
    add("wifi:")
    add("  ssid: !secret wifi_ssid")
    add("  password: !secret wifi_password")
    add("")
    add("api:")
    add("")
    add("ota:")
    add("  - platform: esphome")
    add("    password: !secret ota_password")
    add("")
    add("logger:")
    add("  level: DEBUG")
    add("")
    add("globals:")
    add("  - id: mqtt_connesso")
    add("    type: bool")
    add("    restore_value: no")
    add("    initial_value: 'false'")
    add("  - id: modalita_attiva")
    add("    type: std::string")
    add("    restore_value: no")
    add("    initial_value: '\"nessuna\"'")
    add("")
    add("mqtt:")
    add(f"  broker: {yaml_quote(conn['mqtt_broker'])}")
    add(f"  port: {int(conn['mqtt_port'])}")
    add(f"  username: {yaml_quote(username)}")
    add("  password: !secret adafruit_io_key")
    add(f"  keepalive: {int(conn['mqtt_keepalive'])}s")
    add("  clean_session: true")
    add("  discovery: false")
    add("  discover_ip: false")
    add("  topic_prefix: null")
    add("")
    add("  on_connect:")
    set_mode(" " * 4, "nessuna", connected=True)
    stop_scripts(" " * 4)
    all_red(" " * 4)
    add("")
    add("  on_disconnect:")
    set_mode(" " * 4, "nessuna", connected=False)
    stop_scripts(" " * 4, include_error=False)
    add("    - script.execute: lampeggio_errore")
    add("")
    add("  on_message:")
    for moment in moments:
        on_command(moment["id"], f">>> {moment['name']} ({moment['id']})", moment["id"], f"OK:{moment['id']}", True)
    on_command(OFF_PAYLOAD, ">>> ALL OFF: STEADY RED", "nessuna", "OK:spento", False)
    # Any other payload on the command feed is reported back instead of being ignored silently.
    known = " && ".join(f'x != "{payload}"' for payload in mode_ids + [OFF_PAYLOAD])
    add(f"    - topic: {yaml_quote(command_topic)}")
    add("      then:")
    add("        - if:")
    add(f"            condition: {{lambda: 'return {known};'}}")
    add("            then:")
    publish(" " * 14, "ERRORE:payload_non_valido")

    add("")
    add("script:")
    add("  - id: lampeggio_errore")
    add("    mode: restart")
    add("    then:")
    add("      - while:")
    add("          condition:")
    add("            lambda: 'return !id(mqtt_connesso);'")
    add("          then:")
    blink_loop(" " * 12, all_ids, 100, 0)

    for moment in moments:
        selected = [s["id"] for s in segments if moment["id"] in s["moments"]]
        add("")
        add(f"  - id: lampeggio_{moment['id']}")
        add("    mode: restart")
        add("    then:")
        add("      - while:")
        add("          condition:")
        add("            lambda: |-")
        add(f'              return id(mqtt_connesso) && id(modalita_attiva) == "{moment["id"]}";')
        add("          then:")
        if selected:
            blink_loop(" " * 12, selected, 0, 100)
        else:
            add("            - delay: 1200ms")

    add("")
    add("light:")
    for n, strip in enumerate(strips, start=1):
        add("  - platform: esp32_rmt_led_strip")
        add("    chipset: WS2812")
        add(f"    pin: GPIO{strip['gpio']}")
        add(f"    num_leds: {strip['num_leds']}")
        add(f"    rmt_symbols: {rmt_symbols}")
        add("    channel_colors: GRB")
        add(f"    id: strip_{n}")
        add("    internal: true")
    add("")
    for seg in segments:
        add("  - platform: partition")
        add(f"    name: {yaml_quote(seg['name'])}")
        add(f"    id: {seg['id']}")
        add("    segments:")
        add(f"      - id: {seg['strip_id']}")
        add(f"        from: {seg['start']}")
        add(f"        to: {seg['end']}")
    add("")
    add("# MQTT feeds used by this firmware (create these feeds in Adafruit IO):")
    add(f"#   {command_topic}   payloads: {', '.join(mode_ids + [OFF_PAYLOAD])}")
    add(f"#   {feedback_topic}")
    add("")
    add("# Required secrets.yaml keys (kept in a separate private file):")
    add('# wifi_ssid: "YOUR_WIFI_SSID"')
    add('# wifi_password: "YOUR_WIFI_PASSWORD"')
    add('# ota_password: "YOUR_OTA_PASSWORD"')
    add('# adafruit_io_key: "YOUR_ADAFRUIT_IO_KEY"')
    return "\n".join(lines) + "\n"


def write_secrets(path, secrets):
    lines = ["# Private credentials for ESPHome. Do not share or commit this file."]
    for key, value in secrets.items():
        lines.append(f"{key}: {yaml_quote(value)}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_secrets(path):
    values = {}
    if not Path(path).exists():
        return values
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)\s*$", line)
        if not match:
            continue
        raw = match.group(2)
        try:
            values[match.group(1)] = json.loads(raw) if raw.startswith(('"', "'")) else raw
        except json.JSONDecodeError:
            values[match.group(1)] = raw.strip('"\'')
    return values


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

def blend(color_a, color_b, t):
    a = [int(color_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(color_b[i:i + 2], 16) for i in (1, 3, 5)]
    t = max(0.0, min(1.0, t))
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def apply_dark_theme(root):
    c = COLORS
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(background=c["bg"])

    style.configure(
        ".", background=c["bg"], foreground=c["text"], fieldbackground=c["input"],
        bordercolor=c["border"], lightcolor=c["border"], darkcolor=c["border"],
        troughcolor=c["bg"], focuscolor=c["accent"], selectbackground=c["accent"],
        selectforeground="#ffffff", insertcolor=c["text"], font=(FONT, 10),
    )
    style.configure("TFrame", background=c["bg"])
    style.configure("Card.TFrame", background=c["card"])
    style.configure("Sidebar.TFrame", background=c["sidebar"])
    style.configure("Bar.TFrame", background=c["sidebar"])

    style.configure("TLabel", background=c["bg"], foreground=c["text"])
    style.configure("PageTitle.TLabel", font=(FONT, 18, "bold"))
    style.configure("PageSub.TLabel", foreground=c["muted"])
    style.configure("Card.TLabel", background=c["card"])
    style.configure("CardMuted.TLabel", background=c["card"], foreground=c["muted"])
    style.configure("CardTitle.TLabel", background=c["card"], font=(FONT, 12, "bold"))
    style.configure("ColHead.TLabel", background=c["card"], foreground=c["muted"], font=(FONT, 9, "bold"))
    style.configure("Badge.TLabel", background=c["card"], foreground=c["accent"], font=(FONT, 10, "bold"))
    style.configure("Mono.TLabel", background=c["card"], font=("Consolas", 10))
    style.configure("Brand.TLabel", background=c["sidebar"], font=(FONT, 15, "bold"))
    style.configure("BrandSub.TLabel", background=c["sidebar"], foreground=c["muted"], font=(FONT, 9))
    style.configure("Status.TLabel", background=c["sidebar"], foreground=c["muted"])

    def flat_button(name, bg, fg, hover, **extra):
        style.configure(
            name, background=bg, foreground=fg, bordercolor=bg, lightcolor=bg, darkcolor=bg,
            focuscolor=bg, borderwidth=0, relief="flat", **extra,
        )
        states = [("pressed", hover), ("active", hover)]
        style.map(name, background=states, bordercolor=states, lightcolor=states, darkcolor=states,
                  focuscolor=states)

    flat_button("TButton", c["input"], c["text"], c["hover"], padding=(14, 7))
    flat_button("Accent.TButton", c["accent"], "#ffffff", c["accent_hover"], padding=(16, 7),
                font=(FONT, 10, "bold"))
    flat_button("Ghost.TButton", c["card"], c["accent"], c["input"], padding=(8, 5), font=(FONT, 10, "bold"))
    # A symbol font with monochrome glyphs, so Windows does not fall back to colour emoji.
    for name, fg in (("Icon.TButton", c["muted"]), ("Danger.TButton", c["danger"])):
        flat_button(name, c["card"], fg, c["input"], padding=(4, 2), width=2, font=("Segoe UI Symbol", 10))
        style.map(name, foreground=[("disabled", c["card"])])
    flat_button("Nav.TButton", c["sidebar"], c["muted"], c["card"], padding=(22, 11), anchor="w",
                font=(FONT, 11))
    style.map("Nav.TButton", foreground=[("selected", c["text"]), ("active", c["text"])],
              background=[("selected", c["card"]), ("active", c["bg"])])

    for name in ("TEntry", "TSpinbox", "TCombobox"):
        style.configure(name, fieldbackground=c["input"], foreground=c["text"], bordercolor=c["border"],
                        lightcolor=c["input"], darkcolor=c["input"], insertcolor=c["text"], padding=(6, 4),
                        background=c["input"], arrowcolor=c["muted"])
        style.map(name, bordercolor=[("focus", c["accent"])], lightcolor=[("focus", c["accent"])],
                  fieldbackground=[("readonly", c["input"]), ("disabled", c["card"])],
                  foreground=[("readonly", c["text"]), ("disabled", c["muted"])],
                  background=[("active", c["hover"])], arrowcolor=[("active", c["text"])])
    style.configure("TSpinbox", arrowsize=12)

    style.configure("Card.TCheckbutton", background=c["card"], foreground=c["text"],
                    indicatorbackground=c["input"], indicatorforeground="#ffffff",
                    upperbordercolor=c["border"], lowerbordercolor=c["border"],
                    focuscolor=c["card"], padding=(0, 2))
    style.map("Card.TCheckbutton", background=[("active", c["card"])],
              indicatorbackground=[("pressed", c["accent"]), ("selected", c["accent"]), ("active", c["hover"])])

    style.configure("Vertical.TScrollbar", background=c["input"], troughcolor=c["bg"], bordercolor=c["bg"],
                    lightcolor=c["input"], darkcolor=c["input"], arrowcolor=c["muted"], gripcount=0,
                    arrowsize=12)
    style.map("Vertical.TScrollbar", background=[("active", c["hover"])])

    root.option_add("*TCombobox*Listbox.background", c["input"])
    root.option_add("*TCombobox*Listbox.foreground", c["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", c["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*TCombobox*Listbox.font", (FONT, 10))


def enable_dark_title_bar(window):
    """Ask Windows 10/11 for a dark title bar; silently ignored elsewhere."""
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1)
        for attribute in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value),
                                                          ctypes.sizeof(value)) == 0:
                break
    except (AttributeError, OSError):
        pass


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent, *args, padding=(28, 24, 28, 24), **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0, background=COLORS["bg"])
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, padding=padding)
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", self._update_scrollregion)
        self.canvas.bind("<Configure>", self._resize_inner)

    def _update_scrollregion(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize_inner(self, event):
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def scroll(self, delta):
        if self.inner.winfo_reqheight() > self.canvas.winfo_height():
            self.canvas.yview_scroll(int(-delta / 120) or (-1 if delta > 0 else 1), "units")


# ---------------------------------------------------------------------------
# UI state objects
# ---------------------------------------------------------------------------

class MomentRow:
    """A moment of the day. The ID (the command payload) follows the name until edited by hand."""

    def __init__(self, app, data):
        self.app = app
        name = str(data.get("name", ""))
        moment_id = str(data.get("id") or moment_id_from_name(name))
        self.name = tk.StringVar(value=name)
        self.id = tk.StringVar(value=moment_id)
        self._prev_name, self._prev_id = name, moment_id
        self.name.trace_add("write", self._on_name)
        self.id.trace_add("write", self._on_id)

    def _on_name(self, *_):
        new = self.name.get()
        if self.id.get() == moment_id_from_name(self._prev_name):
            self.id.set(moment_id_from_name(new))
        self._prev_name = new
        self.app.on_moment_text_changed()

    def _on_id(self, *_):
        new = self.id.get()
        self._prev_id = new
        self.app.on_moment_text_changed()

    def label(self):
        return self.name.get().strip() or self.id.get().strip() or "(unnamed)"

    def to_dict(self):
        return {"id": self.id.get().strip(), "name": self.name.get().strip()}


class SegmentRow:
    def __init__(self, app, strip, data):
        self.name = tk.StringVar(value=str(data.get("name", "")))
        self.leds = tk.StringVar(value=str(data.get("leds", 6)))
        self.gap = tk.StringVar(value=str(data.get("gap_after", 0)))
        selected = set(data.get("moments", []))
        # Keyed by MomentRow, so renaming a moment ID keeps the selection.
        self.checks = {m: tk.BooleanVar(value=m.id.get() in selected) for m in app.moments}
        for var in (self.leds, self.gap):
            var.trace_add("write", lambda *_: app.on_layout_changed(strip))


class StripModel:
    def __init__(self, app, data):
        self.name = tk.StringVar(value=str(data.get("name", "")))
        self.gpio = tk.StringVar(value=str(data.get("gpio", "")))
        self.num_leds = tk.StringVar(value=str(data.get("num_leds", 6)))
        self.segments = [SegmentRow(app, self, s) for s in data.get("segments", [])]
        self.num_leds.trace_add("write", lambda *_: app.on_layout_changed(self))
        self.view = None  # widgets of the currently rendered card


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class Configurator(tk.Tk):
    PAGES = (
        ("strips", "Strips & segments"),
        ("moments", "Moments"),
        ("blink", "Blinking"),
        ("connections", "Connections"),
    )

    def __init__(self):
        super().__init__()
        self.title("Medicine LED Configurator")
        width = min(1380, self.winfo_screenwidth() - 60)
        height = min(880, self.winfo_screenheight() - 90)
        self.geometry(f"{width}x{height}")
        self.minsize(1080, 640)
        apply_dark_theme(self)

        self.moments = []
        self.strips = []
        self.strip_count = tk.StringVar(value="1")
        self.wifi_ssid = tk.StringVar()
        self.wifi_password = tk.StringVar()
        self.ota_password = tk.StringVar()
        self.mqtt_broker = tk.StringVar()
        self.mqtt_port = tk.StringVar()
        self.mqtt_username = tk.StringVar()
        self.mqtt_key = tk.StringVar()
        self.mqtt_keepalive = tk.StringVar()
        self.command_feed = tk.StringVar()
        self.feedback_feed = tk.StringVar()
        self.pulse_on = tk.StringVar()
        self.pulse_off = tk.StringVar()
        self.pulse_transition = tk.StringVar()
        for var in (self.mqtt_username, self.command_feed, self.feedback_feed):
            var.trace_add("write", lambda *_: self.refresh_topics())

        self._strips_dirty = False
        self.current_page = None
        self._build_shell()
        self._load_startup_config()
        self.show_page("strips")
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        enable_dark_title_bar(self)

    # ----- layout -----------------------------------------------------------

    def _build_shell(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(self, style="Sidebar.TFrame", padding=(0, 26, 0, 18), width=220)
        sidebar.grid(row=0, column=0, rowspan=2, sticky="ns")
        sidebar.pack_propagate(False)
        ttk.Label(sidebar, text="  Medicine LED", style="Brand.TLabel").pack(anchor="w", padx=12)
        ttk.Label(sidebar, text="    ESPHome configurator", style="BrandSub.TLabel").pack(anchor="w", padx=12,
                                                                                       pady=(0, 24))
        self.nav_buttons = {}
        for key, title in self.PAGES:
            button = ttk.Button(sidebar, text=title, style="Nav.TButton", command=lambda k=key: self.show_page(k))
            button.pack(fill="x")
            self.nav_buttons[key] = button
        ttk.Label(sidebar, text=f"    Device: {DEVICE_NAME}", style="BrandSub.TLabel").pack(side="bottom",
                                                                                       anchor="w", padx=12)

        container = ttk.Frame(self)
        container.grid(row=0, column=1, sticky="nsew")
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        self.pages = {}
        self.page_scrolls = {}
        for key in ("strips", "moments", "connections"):
            scroll = ScrollableFrame(container)
            scroll.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = scroll
            self.page_scrolls[key] = scroll
        blink = ttk.Frame(container, padding=(28, 24))
        blink.grid(row=0, column=0, sticky="nsew")
        self.pages["blink"] = blink

        self._build_blink_page(blink)
        self._build_connections_page(self.page_scrolls["connections"].inner)

        bar = ttk.Frame(self, style="Bar.TFrame", padding=(28, 12))
        bar.grid(row=1, column=1, sticky="ew")
        self.status_label = ttk.Label(bar, text="Ready.", style="Status.TLabel")
        self.status_label.pack(side="left")
        ttk.Button(bar, text="Generate YAML…", style="Accent.TButton", command=self.save_yaml).pack(
            side="right")
        ttk.Button(bar, text="Validate", command=self.validate_ui).pack(side="right", padx=8)
        ttk.Button(bar, text="Save…", command=self.save_json).pack(side="right")
        ttk.Button(bar, text="Load…", command=self.load_json).pack(side="right", padx=8)

    def show_page(self, key):
        if key == "strips" and self._strips_dirty:
            self.render_strips()
        self.pages[key].tkraise()
        for name, button in self.nav_buttons.items():
            button.state(["selected"] if name == key else ["!selected"])
        self.current_page = key

    def _on_mousewheel(self, event):
        try:
            if event.widget.winfo_toplevel() is not self:
                return
        except (AttributeError, KeyError, tk.TclError):
            return
        scroll = self.page_scrolls.get(self.current_page)
        if scroll:
            scroll.scroll(event.delta)

    def set_status(self, text, kind="muted"):
        color = {"muted": COLORS["muted"], "ok": COLORS["success"], "error": COLORS["danger"]}[kind]
        self.status_label.configure(text=text, foreground=color)

    @staticmethod
    def _page_header(parent, title, subtitle):
        ttk.Label(parent, text=title, style="PageTitle.TLabel").pack(anchor="w")
        ttk.Label(parent, text=subtitle, style="PageSub.TLabel").pack(anchor="w", pady=(2, 18))

    @staticmethod
    def _card(parent, title=None, **pack):
        card = ttk.Frame(parent, style="Card.TFrame", padding=18)
        card.pack(fill="x", pady=(0, 14), **pack)
        if title:
            ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor="w", pady=(0, 10))
        return card

    @staticmethod
    def _row_actions(parent, index, count, move, remove):
        """Up / down / remove buttons; unavailable moves stay as invisible placeholders to keep columns aligned."""
        frame = ttk.Frame(parent, style="Card.TFrame")
        for text, command, enabled, style in (
                ("↑", lambda: move(-1), index > 0, "Icon.TButton"),
                ("↓", lambda: move(1), index < count - 1, "Icon.TButton"),
                ("✕", remove, True, "Danger.TButton")):
            button = ttk.Button(frame, text=text, style=style, command=command)
            if not enabled:
                button.state(["disabled"])
            button.pack(side="left", padx=1)
        return frame

    # ----- strips page ------------------------------------------------------

    def render_strips(self):
        inner = self.page_scrolls["strips"].inner
        for child in inner.winfo_children():
            child.destroy()
        for strip in self.strips:
            strip.view = None
        self._page_header(inner, "Strips & segments",
                          "Segments are consecutive LEDs on a strip; tick the moments that make each one blink.")
        toolbar = ttk.Frame(inner)
        toolbar.pack(fill="x", pady=(0, 14))
        ttk.Label(toolbar, text="Number of strips").pack(side="left")
        ttk.Spinbox(toolbar, from_=1, to=MAX_STRIPS, width=4, textvariable=self.strip_count, state="readonly",
                    command=self.on_strip_count_changed).pack(side="left", padx=10)
        ttk.Label(toolbar, text=f"max {MAX_STRIPS}", style="PageSub.TLabel").pack(side="left")
        for index, strip in enumerate(self.strips):
            self._build_strip_card(inner, index, strip)
        self._strips_dirty = False

    def _build_strip_card(self, parent, index, strip):
        card = self._card(parent)
        head = ttk.Frame(card, style="Card.TFrame")
        head.pack(fill="x")
        ttk.Label(head, text=f"STRIP {index + 1}", style="Badge.TLabel").pack(side="left")
        ttk.Entry(head, textvariable=strip.name, width=24).pack(side="left", padx=(12, 20))
        ttk.Label(head, text="GPIO", style="CardMuted.TLabel").pack(side="left")
        ttk.Combobox(head, textvariable=strip.gpio, values=SUGGESTED_GPIOS, width=5).pack(side="left",
                                                                                          padx=(6, 20))
        ttk.Label(head, text="Physical LEDs", style="CardMuted.TLabel").pack(side="left")
        ttk.Spinbox(head, from_=1, to=1000, width=6, textvariable=strip.num_leds).pack(side="left", padx=6)
        usage = ttk.Label(head, style="CardMuted.TLabel")
        usage.pack(side="right")

        bar = tk.Canvas(card, height=18, highlightthickness=0, bd=0, background=COLORS["card"])
        bar.pack(fill="x", pady=(14, 14))

        table = ttk.Frame(card, style="Card.TFrame")
        table.pack(fill="x")
        table.columnconfigure(5, weight=1)
        for col, text in enumerate(("", "SEGMENT", "LEDS", "GAP AFTER", "LED RANGE", "MOMENTS", "")):
            ttk.Label(table, text=text, style="ColHead.TLabel").grid(row=0, column=col, sticky="w", padx=4,
                                                                     pady=(0, 6))
        range_labels = []
        for row, seg in enumerate(strip.segments, start=1):
            color = SEGMENT_COLORS[(row - 1) % len(SEGMENT_COLORS)]
            tk.Frame(table, background=color, width=5).grid(row=row, column=0, sticky="ns", padx=(0, 6), pady=5)
            ttk.Entry(table, textvariable=seg.name, width=22).grid(row=row, column=1, sticky="nw", padx=4, pady=4)
            ttk.Spinbox(table, from_=1, to=999, width=4, textvariable=seg.leds).grid(row=row, column=2,
                                                                                    sticky="nw", padx=4, pady=4)
            ttk.Spinbox(table, from_=0, to=99, width=4, textvariable=seg.gap).grid(row=row, column=3,
                                                                                  sticky="nw", padx=4, pady=4)
            range_label = ttk.Label(table, style="CardMuted.TLabel", width=9)
            range_label.grid(row=row, column=4, sticky="nw", padx=4, pady=7)
            range_labels.append(range_label)

            checks = ttk.Frame(table, style="Card.TFrame")
            checks.grid(row=row, column=5, sticky="nw", padx=4, pady=4)
            for k, moment in enumerate(self.moments):
                ttk.Checkbutton(checks, text=moment.label(), variable=seg.checks[moment],
                                style="Card.TCheckbutton").grid(row=k // MOMENT_COLUMNS, column=k % MOMENT_COLUMNS,
                                                                sticky="w", padx=(0, 14))
            if not self.moments:
                ttk.Label(checks, text="Define moments first.", style="CardMuted.TLabel").grid(row=0, column=0)

            self._row_actions(
                table, row - 1, len(strip.segments),
                lambda delta, s=seg: self.move_segment(strip, s, delta),
                lambda s=seg: self.remove_segment(strip, s),
            ).grid(row=row, column=6, sticky="ne", padx=(4, 0), pady=4)

        if not strip.segments:
            ttk.Label(table, text="No segments yet.", style="CardMuted.TLabel").grid(row=1, column=1, columnspan=5,
                                                                                    sticky="w", padx=4)
        ttk.Button(card, text="+ Add segment", style="Ghost.TButton",
                   command=lambda: self.add_segment(strip)).pack(anchor="w", pady=(10, 0))

        strip.view = {"usage": usage, "bar": bar, "ranges": range_labels}
        bar.bind("<Configure>", lambda _e: self._update_strip_view(strip))
        self._update_strip_view(strip)

    def _strip_layout(self, strip):
        """Layout from the current (possibly invalid) widget values: (ranges or None, used or None, num or None)."""
        num = parse_int(strip.num_leds.get())
        segments = []
        for seg in strip.segments:
            leds, gap = parse_int(seg.leds.get()), parse_int(seg.gap.get())
            if leds is None or leds < 1 or gap is None or gap < 0:
                return None, None, num
            segments.append({"leds": leds, "gap_after": gap})
        ranges, used = compute_layout(segments)
        return ranges, used, num

    def _update_strip_view(self, strip):
        view = strip.view
        if not view:
            return
        ranges, used, num = self._strip_layout(strip)
        for i, label in enumerate(view["ranges"]):
            label.configure(text=f"{ranges[i][0]} – {ranges[i][1]}" if ranges else "—")
        if used is None:
            view["usage"].configure(text="Check the LED counts", foreground=COLORS["danger"])
        elif num is None:
            view["usage"].configure(text=f"{used} LEDs used", foreground=COLORS["muted"])
        else:
            over = used > num
            view["usage"].configure(
                text=f"{used} / {num} LEDs used" + ("  ·  too many" if over else ""),
                foreground=COLORS["danger"] if over else COLORS["muted"])
        self._draw_usage_bar(view["bar"], ranges, used, num)

    @staticmethod
    def _draw_usage_bar(canvas, ranges, used, num):
        canvas.delete("all")
        width, height = canvas.winfo_width(), int(canvas["height"])
        if width < 10:
            return
        total = max(num or 0, used or 0, 1)
        owner = [None] * total
        for i, (start, end) in enumerate(ranges or []):
            for k in range(start, end + 1):
                owner[k] = i
        step = width / total
        spacing = 1 if step >= 4 else 0
        for k in range(total):
            beyond = num is not None and k >= num
            if owner[k] is None:
                if beyond:
                    continue
                color = COLORS["led_off"]
            else:
                color = COLORS["danger"] if beyond else SEGMENT_COLORS[owner[k] % len(SEGMENT_COLORS)]
            canvas.create_rectangle(k * step, 2, (k + 1) * step - spacing, height - 2, fill=color, outline="")

    def on_layout_changed(self, strip):
        self._update_strip_view(strip)

    def on_strip_count_changed(self):
        target = max(1, min(MAX_STRIPS, parse_int(self.strip_count.get()) or 1))
        current = len(self.strips)
        if target > current:
            for _ in range(target - current):
                self.strips.append(StripModel(self, self._new_strip_data()))
        elif target < current:
            removed = self.strips[target:]
            if any(s.segments for s in removed):
                names = ", ".join(f"'{s.name.get()}'" for s in removed)
                if not messagebox.askyesno("Remove strip?", f"Remove {names} and all its segments?"):
                    self.strip_count.set(str(current))
                    return
            del self.strips[target:]
        self.render_strips()

    def _new_strip_data(self):
        used = {parse_int(s.gpio.get()) for s in self.strips}
        gpio = next((g for g in SUGGESTED_GPIOS if g not in used), "")
        return {
            "name": f"Strip {len(self.strips) + 1}", "gpio": gpio, "num_leds": 6,
            "segments": [{"name": self._unique_segment_name(), "leds": 6, "gap_after": 0, "moments": []}],
        }

    def _unique_segment_name(self):
        existing = {seg.name.get().strip() for strip in self.strips for seg in strip.segments}
        n = 1
        while f"Segment {n}" in existing:
            n += 1
        return f"Segment {n}"

    def add_segment(self, strip):
        last = strip.segments[-1] if strip.segments else None
        strip.segments.append(SegmentRow(self, strip, {
            "name": self._unique_segment_name(),
            "leds": last.leds.get() if last else 6,
            "gap_after": last.gap.get() if last else 1,
            "moments": [],
        }))
        self.render_strips()

    def move_segment(self, strip, seg, delta):
        i = strip.segments.index(seg)
        j = i + delta
        if 0 <= j < len(strip.segments):
            strip.segments[i], strip.segments[j] = strip.segments[j], strip.segments[i]
            self.render_strips()

    def remove_segment(self, strip, seg):
        strip.segments.remove(seg)
        self.render_strips()

    # ----- moments page -----------------------------------------------------

    def render_moments(self):
        inner = self.page_scrolls["moments"].inner
        for child in inner.winfo_children():
            child.destroy()
        self._page_header(inner, "Moments",
                          "Each moment is a command: publishing its firmware ID to the command feed makes the assigned segments blink.")
        card = self._card(inner)
        table = ttk.Frame(card, style="Card.TFrame")
        table.pack(fill="x")
        for col, text in enumerate(("#", "NAME", "FIRMWARE ID (COMMAND PAYLOAD)", "")):
            ttk.Label(table, text=text, style="ColHead.TLabel").grid(row=0, column=col, sticky="w", padx=6,
                                                                     pady=(0, 6))
        for row, moment in enumerate(self.moments, start=1):
            ttk.Label(table, text=str(row), style="CardMuted.TLabel").grid(row=row, column=0, sticky="w", padx=6)
            ttk.Entry(table, textvariable=moment.name, width=32).grid(row=row, column=1, sticky="w", padx=6, pady=4)
            ttk.Entry(table, textvariable=moment.id, width=34).grid(row=row, column=2, sticky="w", padx=6, pady=4)
            self._row_actions(
                table, row - 1, len(self.moments),
                lambda delta, m=moment: self.move_moment(m, delta),
                lambda m=moment: self.remove_moment(m),
            ).grid(row=row, column=3, sticky="w", padx=(6, 0))
        ttk.Button(card, text="+ Add moment", style="Ghost.TButton", command=self.add_moment).pack(anchor="w",
                                                                                                pady=(10, 0))
        ttk.Label(card, text="The device confirms a command with OK:<firmware ID> on the feedback feed.",
                  style="CardMuted.TLabel").pack(anchor="w", pady=(10, 0))

    def on_moment_text_changed(self):
        self._strips_dirty = True
        self.refresh_topics()

    def _all_segments(self):
        return [seg for strip in self.strips for seg in strip.segments]

    def add_moment(self):
        existing = {m.name.get().strip() for m in self.moments}
        name, n = "New moment", 2
        while name in existing:
            name, n = f"New moment {n}", n + 1
        moment = MomentRow(self, {"name": name})
        self.moments.append(moment)
        for seg in self._all_segments():
            seg.checks[moment] = tk.BooleanVar(value=False)
        self._moments_structure_changed()

    def move_moment(self, moment, delta):
        i = self.moments.index(moment)
        j = i + delta
        if 0 <= j < len(self.moments):
            self.moments[i], self.moments[j] = self.moments[j], self.moments[i]
            self._moments_structure_changed()

    def remove_moment(self, moment):
        users = [seg.name.get() for seg in self._all_segments() if seg.checks[moment].get()]
        if users and not messagebox.askyesno(
                "Remove moment?",
                f"'{moment.label()}' is assigned to {len(users)} segment(s):\n{', '.join(users)}\n\nRemove it anyway?"):
            return
        self.moments.remove(moment)
        for seg in self._all_segments():
            seg.checks.pop(moment, None)
        self._moments_structure_changed()

    def _moments_structure_changed(self):
        self.render_moments()
        self._strips_dirty = True
        self.refresh_topics()

    # ----- blinking page ----------------------------------------------------

    def _build_blink_page(self, page):
        self._page_header(page, "Blinking", "Timing used by every moment and by the red “disconnected” blink.")
        card = self._card(page, "Timing")
        form = ttk.Frame(card, style="Card.TFrame")
        form.pack(anchor="w")
        rows = (
            ("LED on", self.pulse_on, "How long the LEDs stay lit."),
            ("LED off", self.pulse_off, "How long the LEDs stay dark."),
            ("Fade", self.pulse_transition, "Fade-in/out time; at most the shorter of on and off."),
        )
        for row, (label, var, hint) in enumerate(rows):
            ttk.Label(form, text=label, style="Card.TLabel", width=10).grid(row=row, column=0, sticky="w", pady=5)
            ttk.Spinbox(form, from_=0, to=10000, increment=50, width=7, textvariable=var).grid(row=row, column=1,
                                                                                               sticky="w", pady=5)
            ttk.Label(form, text="ms", style="CardMuted.TLabel").grid(row=row, column=2, sticky="w", padx=(6, 24))
            ttk.Label(form, text=hint, style="CardMuted.TLabel").grid(row=row, column=3, sticky="w")
        ttk.Button(card, text="Reset to defaults", command=self._reset_pulse).pack(anchor="w", pady=(12, 0))

        preview = self._card(page, "Preview")
        self.preview_canvas = tk.Canvas(preview, width=560, height=96, highlightthickness=0, bd=0,
                                        background=COLORS["card"])
        self.preview_canvas.pack(anchor="w")
        self.preview_leds = []
        x = 14
        for i in range(8):
            if i == 5:
                x += 30
            item = self.preview_canvas.create_oval(x, 14, x + 34, 48, outline="")
            self.preview_leds.append(item)
            x += 46
        self.preview_canvas.create_text(14, 72, anchor="w", text="Segments of the selected moment",
                                        fill=COLORS["muted"], font=(FONT, 9))
        self.preview_canvas.create_text(14 + 5 * 46 + 30, 72, anchor="w", text="Other segments",
                                        fill=COLORS["muted"], font=(FONT, 9))
        for item in self.preview_leds[5:]:
            self.preview_canvas.itemconfigure(item, fill=COLORS["led_red"])
        self.cycle_label = ttk.Label(preview, style="CardMuted.TLabel")
        self.cycle_label.pack(anchor="w", pady=(8, 0))
        self._blink_t0 = time.monotonic()
        self._animate_blink()

    def _reset_pulse(self):
        self.pulse_on.set(str(DEFAULT_PULSE["on_ms"]))
        self.pulse_off.set(str(DEFAULT_PULSE["off_ms"]))
        self.pulse_transition.set(str(DEFAULT_PULSE["transition_ms"]))

    def _animate_blink(self):
        on, off, fade = (parse_int(v.get()) for v in (self.pulse_on, self.pulse_off, self.pulse_transition))
        if None in (on, off, fade) or on < 1 or off < 1 or fade < 0:
            level, text = 0.0, "Enter valid timings."
        else:
            # Like the firmware: the fade starts with each turn_on/turn_off and runs during the delay.
            fade_in, fade_out = min(fade, on), min(fade, off)
            t = (time.monotonic() - self._blink_t0) * 1000 % (on + off)
            if t < on:
                level = t / fade_in if fade_in else 1.0
            else:
                level = 1.0 - ((t - on) / fade_out if fade_out else 1.0)
            text = f"Cycle {on + off} ms  ·  {60000 / (on + off):.0f} blinks per minute"
        color = blend(COLORS["led_off"], COLORS["led_green"], level)
        for item in self.preview_leds[:5]:
            self.preview_canvas.itemconfigure(item, fill=color)
        if self.cycle_label.cget("text") != text:
            self.cycle_label.configure(text=text)
        self.after(30, self._animate_blink)

    # ----- connections page -------------------------------------------------

    @staticmethod
    def _form(card, rows):
        form = ttk.Frame(card, style="Card.TFrame")
        form.pack(anchor="w")
        for row, (label, var, options) in enumerate(rows):
            ttk.Label(form, text=label, style="Card.TLabel", width=20).grid(row=row, column=0, sticky="w", pady=4)
            ttk.Entry(form, textvariable=var, width=options.get("width", 40),
                      show=options.get("show", "")).grid(row=row, column=1, sticky="w", pady=4)

    def _build_connections_page(self, inner):
        self._page_header(inner, "Connections", "Wi-Fi, OTA and MQTT. Passwords and the AIO key go only to secrets.yaml.")
        secret = {"show": "•"}
        self._form(self._card(inner, "Wi-Fi & OTA"), (
            ("Wi-Fi SSID", self.wifi_ssid, {}),
            ("Wi-Fi password", self.wifi_password, secret),
            ("OTA password", self.ota_password, secret),
        ))
        self._form(self._card(inner, "MQTT / Adafruit IO"), (
            ("Broker", self.mqtt_broker, {}),
            ("Port", self.mqtt_port, {"width": 10}),
            ("Username", self.mqtt_username, {}),
            ("AIO key", self.mqtt_key, secret),
            ("Keepalive (s)", self.mqtt_keepalive, {"width": 10}),
        ))
        self._form(self._card(inner, "Feeds"), (
            ("Command feed", self.command_feed, {}),
            ("Feedback feed", self.feedback_feed, {}),
        ))
        topics_card = self._card(inner, "Topics")
        self.topics_frame = ttk.Frame(topics_card, style="Card.TFrame")
        self.topics_frame.pack(anchor="w")

    def refresh_topics(self):
        frame = getattr(self, "topics_frame", None)
        if frame is None:
            return
        for child in frame.winfo_children():
            child.destroy()
        username = self.mqtt_username.get().strip() or "USERNAME"
        rows = [
            ("Command feed", mqtt_topic(username, self.command_feed.get().strip())),
            ("Feedback feed", mqtt_topic(username, self.feedback_feed.get().strip())),
            ("", ""),
        ]
        rows += [(f"Payload: {m.label()}", m.id.get().strip()) for m in self.moments]
        rows.append(("Payload: turn everything off", OFF_PAYLOAD))
        for row, (label, text) in enumerate(rows):
            ttk.Label(frame, text=label, style="CardMuted.TLabel", width=34).grid(row=row, column=0, sticky="w",
                                                                                  pady=2)
            ttk.Label(frame, text=text, style="Mono.TLabel").grid(row=row, column=1, sticky="w", pady=2)

    # ----- config <-> widgets ----------------------------------------------

    def collect_config(self):
        def number(var, label):
            value = parse_int(var.get())
            if value is None:
                raise ValueError(f"{label} must be a whole number (got '{var.get()}').")
            return value

        moments = [m.to_dict() for m in self.moments]
        strips = []
        for i, strip in enumerate(self.strips, start=1):
            strip_name = strip.name.get().strip() or f"Strip {i}"
            segments = []
            for j, seg in enumerate(strip.segments, start=1):
                segments.append({
                    "name": seg.name.get().strip(),
                    "leds": number(seg.leds, f"{strip_name}, segment {j}: LEDs"),
                    "gap_after": number(seg.gap, f"{strip_name}, segment {j}: gap"),
                    "moments": [m.id.get().strip() for m in self.moments if seg.checks[m].get()],
                })
            strips.append({
                "name": strip_name,
                "gpio": number(strip.gpio, f"{strip_name}: GPIO"),
                "num_leds": number(strip.num_leds, f"{strip_name}: physical LEDs"),
                "segments": segments,
            })

        username = self.mqtt_username.get().strip()
        command_feed = self.command_feed.get().strip()
        feedback_feed = self.feedback_feed.get().strip()
        topics = {
            "command": mqtt_topic(username, command_feed),
            "feedback": mqtt_topic(username, feedback_feed),
        }
        return {
            "version": CONFIG_VERSION,
            "device_name": DEVICE_NAME,
            "moments": moments,
            "strips": strips,
            "connections": {
                "mqtt_broker": self.mqtt_broker.get().strip(),
                "mqtt_port": number(self.mqtt_port, "MQTT port"),
                "mqtt_username": username,
                "mqtt_keepalive": number(self.mqtt_keepalive, "MQTT keepalive"),
                "command_feed": command_feed,
                "feedback_feed": feedback_feed,
                "topics": topics,
            },
            "pulse": {
                "on_ms": number(self.pulse_on, "LED on time"),
                "off_ms": number(self.pulse_off, "LED off time"),
                "transition_ms": number(self.pulse_transition, "Fade time"),
            },
        }

    def load_config(self, cfg):
        cfg = migrate_config(cfg)
        if not isinstance(cfg, dict) or cfg.get("version") != CONFIG_VERSION:
            raise ValueError(f"Unsupported configuration format (expected version {CONFIG_VERSION}).")
        defaults = default_config()
        self.moments = [MomentRow(self, m) for m in cfg.get("moments", [])]
        self.strips = [StripModel(self, s) for s in cfg.get("strips", [])][:MAX_STRIPS]
        if not self.strips:
            self.strips = [StripModel(self, self._new_strip_data())]
        self.strip_count.set(str(len(self.strips)))

        conn = {**defaults["connections"], **cfg.get("connections", {})}
        self.mqtt_broker.set(str(conn["mqtt_broker"]))
        self.mqtt_port.set(str(conn["mqtt_port"]))
        self.mqtt_username.set(str(conn["mqtt_username"]))
        self.mqtt_keepalive.set(str(conn["mqtt_keepalive"]))
        self.command_feed.set(str(conn["command_feed"]))
        self.feedback_feed.set(str(conn["feedback_feed"]))
        pulse = {**DEFAULT_PULSE, **cfg.get("pulse", {})}
        self.pulse_on.set(str(pulse["on_ms"]))
        self.pulse_off.set(str(pulse["off_ms"]))
        self.pulse_transition.set(str(pulse["transition_ms"]))

        self.render_strips()
        self.render_moments()
        self.refresh_topics()

    def _apply_secrets(self, path):
        secrets = read_secrets(path)
        self.wifi_ssid.set(str(secrets.get("wifi_ssid", "")))
        self.wifi_password.set(str(secrets.get("wifi_password", "")))
        self.ota_password.set(str(secrets.get("ota_password", "")))
        self.mqtt_key.set(str(secrets.get("adafruit_io_key", "")))

    def _collect_secrets(self):
        return {
            "wifi_ssid": self.wifi_ssid.get(),
            "wifi_password": self.wifi_password.get(),
            "ota_password": self.ota_password.get(),
            "adafruit_io_key": self.mqtt_key.get(),
        }

    def _load_startup_config(self):
        path = SCRIPT_DIR / "configuration.json"
        note = "Started from the default configuration."
        cfg = default_config()
        if path.exists():
            try:
                loaded = migrate_config(json.loads(path.read_text(encoding="utf-8")))
                if isinstance(loaded, dict) and loaded.get("version") == CONFIG_VERSION:
                    cfg, note = loaded, f"Loaded {path.name}."
                else:
                    note = f"{path.name} uses an old format: started from the default configuration."
            except (OSError, json.JSONDecodeError):
                note = f"Could not read {path.name}: started from the default configuration."
        try:
            self.load_config(cfg)
        except (ValueError, TypeError, KeyError, AttributeError):
            self.load_config(default_config())
            note = f"{path.name} is invalid: started from the default configuration."
        self._apply_secrets(SCRIPT_DIR / "secrets.yaml")
        self.set_status(note)

    # ----- actions ----------------------------------------------------------

    def _checked_config(self):
        """Return a valid config, or None after showing the errors."""
        try:
            cfg = self.collect_config()
            errors = validate_config(cfg)
        except (ValueError, TypeError) as exc:
            cfg, errors = None, [str(exc)]
        if errors:
            shown = errors[:20]
            if len(errors) > len(shown):
                shown.append(f"… and {len(errors) - len(shown)} more.")
            messagebox.showerror("Invalid configuration", "\n".join(f"• {e}" for e in shown))
            self.set_status(f"Configuration has {len(errors)} problem(s).", "error")
            return None
        return cfg

    def _save_secrets_beside(self, path):
        secrets_path = Path(path).with_name("secrets.yaml")
        if not secrets_path.exists() or messagebox.askyesno(
                "Overwrite secrets?",
                f"The file already exists:\n{secrets_path}\n\nOverwrite it with the credentials currently entered?"):
            write_secrets(secrets_path, self._collect_secrets())
        return secrets_path

    def validate_ui(self):
        if self._checked_config():
            self.set_status("Configuration is valid.", "ok")

    def save_json(self):
        cfg = self._checked_config()
        if not cfg:
            return
        path = filedialog.asksaveasfilename(
            title="Save configuration", defaultextension=".json", initialdir=SCRIPT_DIR,
            initialfile="configuration.json", filetypes=[("JSON file", "*.json")])
        if not path:
            return
        Path(path).write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        secrets_path = self._save_secrets_beside(path)
        self.set_status(f"Saved {Path(path).name} and {secrets_path.name}.", "ok")

    def load_json(self):
        path = filedialog.askopenfilename(
            title="Load configuration", initialdir=SCRIPT_DIR,
            filetypes=[("JSON file", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.load_config(json.loads(Path(path).read_text(encoding="utf-8")))
            self._apply_secrets(Path(path).with_name("secrets.yaml"))
            self.show_page(self.current_page)
            errors = validate_config(self.collect_config())
        except (OSError, json.JSONDecodeError, TypeError, ValueError, KeyError, AttributeError) as exc:
            messagebox.showerror("Load error", f"Could not load the configuration.\n\n{exc}")
            self.set_status("Could not load the configuration.", "error")
            return
        if errors:
            self.set_status(f"Loaded {Path(path).name} with {len(errors)} problem(s). Press Validate for details.",
                            "error")
        else:
            self.set_status(f"Loaded {Path(path).name}.", "ok")

    def save_yaml(self):
        cfg = self._checked_config()
        if not cfg:
            return
        path = filedialog.asksaveasfilename(
            title="Generate ESPHome configuration", defaultextension=".yaml", initialdir=SCRIPT_DIR,
            initialfile=f"{DEVICE_NAME}.yaml", filetypes=[("YAML files", "*.yaml *.yml")])
        if not path:
            return
        Path(path).write_text(generate_yaml(cfg), encoding="utf-8")
        json_path = Path(path).with_name("configuration.json")
        json_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        secrets_path = self._save_secrets_beside(path)
        self.set_status(f"Generated {Path(path).name}, {json_path.name} and {secrets_path.name}.", "ok")
        messagebox.showinfo(
            "Firmware generated",
            f"Created files:\n- {path}\n- {json_path}\n- {secrets_path}\n\n"
            "Keep secrets.yaml private. Do not upload it when sharing the project.")


if __name__ == "__main__":
    app = Configurator()
    app.mainloop()
