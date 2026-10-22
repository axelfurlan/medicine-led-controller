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

import base64
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk
from secrets import token_bytes
from tkinter import ttk, messagebox, filedialog
from pathlib import Path

CONFIG_VERSION = 3
DEVICE_NAME = "led-farmaci"
MAX_STRIPS = 5
SUGGESTED_GPIOS = (16, 17, 18, 19, 21)
# ESP32 pins able to drive a data line (6-11 are flash, 34-39 are input-only).
VALID_OUTPUT_GPIOS = (0, 1, 2, 3, 4, 5, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 23, 25, 26, 27, 32, 33)
RESERVED_MODE_IDS = {"nessuna", "spento", "errore", "off", "update"}
OFF_PAYLOAD = "off"
UPDATE_PAYLOAD = "update"
DEFAULT_COMMAND_FEED = "led-farmaci-command"
DEFAULT_FEEDBACK_FEED = "led-farmaci-feedback"
DEFAULT_MOMENTS = (
    "Before breakfast", "After breakfast", "Lunch", "Before dinner", "After dinner",
    "Meals insulin pen", "Night insulin pen", "Non-dialysis days medicines",
)
DEFAULT_PULSE = {"on_ms": 700, "off_ms": 400, "transition_ms": 400}
TLS_MQTT_PORT = 8883
# Root of Adafruit IO's certificate chain (*.adafruit.com -> GeoTrust TLS RSA CA G1 -> DigiCert Global Root G2, valid
# until 2038-01-15; SHA-256 CB:3C:CB:B7:60:31:E5:E0:13:8F:8D:D3:9A:23:F9:DE:47:FF:C3:5E:43:C1:14:4C:EA:27:D4:6A:5A:B1:CB:5F).
# ESPHome only encrypts MQTT on the ESP32 when a certificate authority is configured. If Adafruit changes its root,
# update this and re-flash the device over the LAN.
ADAFRUIT_IO_CA = """-----BEGIN CERTIFICATE-----
MIIDjjCCAnagAwIBAgIQAzrx5qcRqaC7KGSxHQn65TANBgkqhkiG9w0BAQsFADBh
MQswCQYDVQQGEwJVUzEVMBMGA1UEChMMRGlnaUNlcnQgSW5jMRkwFwYDVQQLExB3
d3cuZGlnaWNlcnQuY29tMSAwHgYDVQQDExdEaWdpQ2VydCBHbG9iYWwgUm9vdCBH
MjAeFw0xMzA4MDExMjAwMDBaFw0zODAxMTUxMjAwMDBaMGExCzAJBgNVBAYTAlVT
MRUwEwYDVQQKEwxEaWdpQ2VydCBJbmMxGTAXBgNVBAsTEHd3dy5kaWdpY2VydC5j
b20xIDAeBgNVBAMTF0RpZ2lDZXJ0IEdsb2JhbCBSb290IEcyMIIBIjANBgkqhkiG
9w0BAQEFAAOCAQ8AMIIBCgKCAQEAuzfNNNx7a8myaJCtSnX/RrohCgiN9RlUyfuI
2/Ou8jqJkTx65qsGGmvPrC3oXgkkRLpimn7Wo6h+4FR1IAWsULecYxpsMNzaHxmx
1x7e/dfgy5SDN67sH0NO3Xss0r0upS/kqbitOtSZpLYl6ZtrAGCSYP9PIUkY92eQ
q2EGnI/yuum06ZIya7XzV+hdG82MHauVBJVJ8zUtluNJbd134/tJS7SsVQepj5Wz
tCO7TG1F8PapspUwtP1MVYwnSlcUfIKdzXOS0xZKBgyMUNGPHgm+F6HmIcr9g+UQ
vIOlCsRnKPZzFBQ9RnbDhxSJITRNrw9FDKZJobq7nMWxM4MphQIDAQABo0IwQDAP
BgNVHRMBAf8EBTADAQH/MA4GA1UdDwEB/wQEAwIBhjAdBgNVHQ4EFgQUTiJUIBiV
5uNu5g/6+rkS7QYXjzkwDQYJKoZIhvcNAQELBQADggEBAGBnKJRvDkhj6zHd6mcY
1Yl9PMWLSn/pvtsrF9+wX3N3KjITOYFnQoQj8kVnNeyIv/iPsGEMNKSuIEyExtv4
NeF22d+mQrvHRAiGfzZ0JFrabA0UWTW98kndth/Jsw1HKj2ZL7tcu7XUIOGZX1NG
Fdtom/DzMNU+MeKNhJ7jitralj41E6Vf8PlwUHBHQRFXGU7Aj64GxJUTFy8bJZ91
8rGOmaFvE7FBcf6IKshPECBV1/MUReXgRPTqh5Uykw7+U0b6LJ3/iyK5S9kJRaTe
pLiaWN0bfVKfjllDiIGknibVb63dDcY3fe0Dkhvld1927jyNxF1WW6LZZm6zNTfl
MrY=
-----END CERTIFICATE-----
"""
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
            {"name": "Medicine shelf", "gpio": 18, "num_leds": 62, "gap_before": 0, "segments": shelf},
            {"name": "Meals insulin pen", "gpio": 19, "num_leds": 6, "gap_before": 0, "segments": [
                {"name": "Meals insulin pen", "leds": 6, "gap_after": 0, "moments": ["meals_insulin_pen"]}]},
            {"name": "Night insulin pen", "gpio": 21, "num_leds": 6, "gap_before": 0, "segments": [
                {"name": "Night insulin pen", "leds": 6, "gap_after": 0, "moments": ["night_insulin_pen"]}]},
        ],
        "connections": {
            "mqtt_broker": "io.adafruit.com",
            "mqtt_port": TLS_MQTT_PORT,
            "mqtt_username": "",
            "mqtt_keepalive": 30,
            "command_feed": DEFAULT_COMMAND_FEED,
            "feedback_feed": DEFAULT_FEEDBACK_FEED,
            "firmware_url": "",
            "firmware_repo": "",
        },
        "pulse": dict(DEFAULT_PULSE),
        "status_led_gpio": None,
    }


def migrate_config(cfg):
    """Upgrade older files: version 2 (one feed per moment) to 3 (one command feed), and strips without edge gaps."""
    if not isinstance(cfg, dict):
        return cfg
    if cfg.get("version") == 2:
        cfg = json.loads(json.dumps(cfg))
        cfg["version"] = CONFIG_VERSION
        cfg["moments"] = [{"id": m["id"], "name": m["name"]} for m in cfg.get("moments", [])]
        conn = cfg.setdefault("connections", {})
        conn.pop("all_off_feed", None)
        conn.pop("topics", None)
        conn["command_feed"] = DEFAULT_COMMAND_FEED
        conn.setdefault("feedback_feed", DEFAULT_FEEDBACK_FEED)
    if cfg.get("version") == CONFIG_VERSION and any("gap_before" not in s for s in cfg.get("strips", [])):
        cfg = json.loads(json.dumps(cfg))
        for strip in cfg["strips"]:
            if "gap_before" not in strip:
                # Before edge gaps existed, the gap after the last segment was ignored; keep the layout identical.
                strip["gap_before"] = 0
                if strip.get("segments"):
                    strip["segments"][-1]["gap_after"] = 0
    return cfg


def compute_full_layout(segments, right_to_left=False, gap_before=0):
    """Return (segment ranges, gap ranges, used_leds) for a strip.

    Segments are listed as seen on the shelf, left to right, with a gap before the first one (gap_before), one
    after every segment (gap_after, so the last one is the gap at the right end) and nothing else. LED 0 sits at
    the left end, or at the right end when right_to_left. Ranges are (start, end) LED indices; the segment ranges
    follow the list order, gap_ranges has len(segments) + 1 entries (index 0 = before the first segment,
    index i + 1 = after segment i) and None for an empty gap. used_leds counts the gaps at both ends too.
    """
    items = [("gap", 0, gap_before)]
    for i, seg in enumerate(segments):
        items.append(("seg", i, seg["leds"]))
        items.append(("gap", i + 1, seg["gap_after"]))
    if right_to_left:
        items.reverse()
    seg_ranges, gap_ranges, pos = [None] * len(segments), [None] * (len(segments) + 1), 0
    for kind, index, size in items:
        span = (pos, pos + size - 1) if size > 0 else None
        (seg_ranges if kind == "seg" else gap_ranges)[index] = span
        pos += size
    return seg_ranges, gap_ranges, pos


def compute_layout(segments, right_to_left=False, gap_before=0):
    """Return ([(start, end) per segment, in list order], used_leds); see compute_full_layout."""
    ranges, _, used = compute_full_layout(segments, right_to_left, gap_before)
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
        if strip.get("gap_before", 0) < 0:
            errors.append(f"Strip '{label}': the gap at the start cannot be negative.")
            layout_ok = False
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
            _, used = compute_layout(strip["segments"], strip.get("right_to_left", False), strip.get("gap_before", 0))
            if used > strip["num_leds"]:
                errors.append(f"Strip '{label}' needs {used} LEDs but has only {strip['num_leds']}.")

    status_gpio = cfg.get("status_led_gpio")
    if status_gpio is not None:
        if status_gpio not in VALID_OUTPUT_GPIOS:
            errors.append(f"Status LED: GPIO {status_gpio} cannot be used as an output.")
        elif status_gpio in gpios:
            errors.append(f"Status LED: GPIO {status_gpio} is already used by '{gpios[status_gpio]}'.")

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
    firmware_url = conn.get("firmware_url", "").strip()
    if firmware_url and not (firmware_url.startswith("https://") and firmware_url.endswith(".bin")):
        errors.append("The firmware URL must start with https:// and end with .bin (or be left empty).")
    return errors


def generate_yaml(cfg):
    conn = cfg["connections"]
    pulse = cfg["pulse"]
    on_ms, off_ms, transition_ms = int(pulse["on_ms"]), int(pulse["off_ms"]), int(pulse["transition_ms"])
    username = conn["mqtt_username"].strip()
    firmware_url = conn.get("firmware_url", "").strip()
    status_gpio = cfg.get("status_led_gpio")
    feedback_topic = mqtt_topic(username, conn["feedback_feed"])
    command_topic = mqtt_topic(username, conn["command_feed"])
    moments = cfg["moments"]
    strips = cfg["strips"]
    mode_ids = [m["id"] for m in moments]
    # Two RMT memory blocks per strip fit up to 4 strips; 5 strips need one block each.
    rmt_symbols = 128 if len(strips) <= 4 else 64

    segments = []
    for n, strip in enumerate(strips, start=1):
        ranges, _ = compute_layout(strip["segments"], strip.get("right_to_left", False), strip.get("gap_before", 0))
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
    if status_gpio is not None:
        add("        - script.execute: led_stato")
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
    add("  # MQTT starts only once Wi-Fi is up: a broker lookup at boot fails at once, and ESPHome then waits 20 s")
    add("  # for an answer that never comes before retrying.")
    add("  on_connect:")
    add("    - mqtt.enable:")
    add("")
    add("api:")
    add("  encryption:")
    add("    key: !secret api_encryption_key")
    add("")
    add("ota:")
    add("  - platform: esphome")
    add("    password: !secret ota_password")
    if firmware_url:
        add("  - platform: http_request")
        add("    id: ota_remoto")
        add("")
        add("http_request:")
        add("  timeout: 30s")
        add("  watchdog_timeout: 60s")
    add("")
    add("logger:")
    add("  level: DEBUG")
    if status_gpio is not None:
        add("switch:")
        add("  - platform: gpio")
        add(f"    pin: GPIO{status_gpio}")
        add("    id: led_blu")
        add("    internal: true")
        add("    restore_mode: ALWAYS_ON")
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
    add("  enable_on_boot: false")
    add(f"  port: {int(conn['mqtt_port'])}")
    if int(conn["mqtt_port"]) == TLS_MQTT_PORT:
        add("  certificate_authority: |")
        for line in ADAFRUIT_IO_CA.splitlines():
            add(f"    {line}")
    else:
        add("  # WARNING: this port is not encrypted; the Adafruit IO key is sent in clear text.")
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
    if firmware_url:
        # Remote update: the device downloads <firmware_url> (+ ".md5") from a private repo over HTTPS.
        pad = " " * 10
        add(f"    - topic: {yaml_quote(command_topic)}")
        add(f"      payload: {yaml_quote(UPDATE_PAYLOAD)}")
        add("      then:")
        add(f"{pad}- logger.log: '>>> REMOTE FIRMWARE UPDATE'")
        publish(pad, "OK:aggiornamento")
        add(f"{pad}- ota.http_request.flash:")
        add(f"{pad}    id: ota_remoto")
        add(f"{pad}    url: {yaml_quote(firmware_url)}")
        add(f"{pad}    md5_url: {yaml_quote(firmware_url + '.md5')}")
        add(f"{pad}    username: x-access-token")
        add(f"{pad}    password: !secret github_token")
    # Any other payload on the command feed is reported back instead of being ignored silently.
    known = " && ".join(f'x != "{payload}"' for payload in mode_ids + [OFF_PAYLOAD] + ([UPDATE_PAYLOAD] if firmware_url else []))
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

    if status_gpio is not None:
        led = lambda state, pad: add(f"{pad}- switch.turn_{state}: led_blu")
        pad = " " * 6
        add("")
        add("  # On-board LED legend: solid = firmware started; then N pulses = reset reason (1 power-on,")
        add("  # 2 reset button, 3 software, 4 crash, 5 int. watchdog, 6 task watchdog, 7 other watchdog,")
        add("  # 9 brownout); then fast blink = no Wi-Fi, slow blink = no MQTT, short flash every 2 s = all OK.")
        add("  - id: led_stato")
        add("    mode: single")
        add("    then:")
        add(f"{pad}- delay: 1s")
        led("off", pad)
        add(f"{pad}- delay: 800ms")
        add(f"{pad}- repeat:")
        add(f"{pad}    count: !lambda 'return (int) esp_reset_reason();'")
        add(f"{pad}    then:")
        for state, ms in (("on", 200), ("off", 300)):
            led(state, pad + "      ")
            add(f"{pad}      - delay: {ms}ms")
        add(f"{pad}- delay: 1500ms")
        add(f"{pad}- while:")
        add(f"{pad}    condition:")
        add(f"{pad}      lambda: 'return true;'")
        add(f"{pad}    then:")
        add(f"{pad}      - if:")
        add(f"{pad}          condition:")
        add(f"{pad}            not:")
        add(f"{pad}              wifi.connected:")
        add(f"{pad}          then:")
        for state, ms in (("on", 100), ("off", 100)):
            led(state, pad + "            ")
            add(f"{pad}            - delay: {ms}ms")
        add(f"{pad}          else:")
        add(f"{pad}            - if:")
        add(f"{pad}                condition:")
        add(f"{pad}                  lambda: 'return !id(mqtt_connesso);'")
        add(f"{pad}                then:")
        for state, ms in (("on", 500), ("off", 500)):
            led(state, pad + "                  ")
            add(f"{pad}                  - delay: {ms}ms")
        add(f"{pad}                else:")
        for state, ms in (("on", 50), ("off", 1950)):
            led(state, pad + "                  ")
            add(f"{pad}                  - delay: {ms}ms")

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
    add('# api_encryption_key: "BASE64 KEY, 32 RANDOM BYTES (the configurator generates it)"')
    if firmware_url:
        add('# github_token: "READ-ONLY FINE-GRAINED TOKEN OF THE PRIVATE FIRMWARE REPO"')
    return "\n".join(lines) + "\n"


def security_warnings(cfg):
    """Things the user should confirm before generating firmware (not validation errors)."""
    warnings = []
    port = int(cfg["connections"].get("mqtt_port", 0))
    if port != TLS_MQTT_PORT:
        warnings.append(
            f"MQTT port {port} is not encrypted: your Adafruit IO key and every command travel in clear text. "
            f"Use port {TLS_MQTT_PORT} (TLS).")
    return warnings


def new_api_key():
    """A fresh ESPHome API encryption key (32 random bytes, base64)."""
    return base64.b64encode(token_bytes(32)).decode("ascii")


def write_project_files(cfg, directory):
    """Write led-farmaci.yaml and configuration.json into directory."""
    directory = Path(directory)
    (directory / f"{DEVICE_NAME}.yaml").write_text(generate_yaml(cfg), encoding="utf-8")
    (directory / "configuration.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def find_esphome():
    """Command (list) that runs ESPHome. The Device Builder's Scripts\\esphome.exe launcher is broken, so use its python."""
    device_builder_python = Path(os.environ.get("LOCALAPPDATA", "")) / "ESPHome Device Builder" / "python" / "python.exe"
    if device_builder_python.exists():
        return [str(device_builder_python), "-m", "esphome"]
    found = shutil.which("esphome")
    if found:
        return [found]
    raise RuntimeError("ESPHome not found: install it or add the esphome command to PATH.")


def run_logged(cmd, cwd, log):
    """Run cmd, sending each output line to log(); raises RuntimeError on a non-zero exit."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "GIT_TERMINAL_PROMPT": "0"}
    log("$ " + " ".join([Path(cmd[0]).name] + cmd[1:]))
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for line in proc.stdout:
        log(line.rstrip())
    if proc.wait() != 0:
        raise RuntimeError(f"{Path(cmd[0]).name} failed (exit code {proc.returncode}).")


def firmware_repo_dir(conn):
    return Path(conn.get("firmware_repo", "").strip() or SCRIPT_DIR.parent / "farmaci-firmware")


def publish_firmware(cfg, secrets, log):
    """Compile the firmware and push firmware.ota.bin + .md5 to the private firmware repository."""
    conn = cfg["connections"]
    match = re.match(r"https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/", conn.get("firmware_url", "").strip())
    if not match:
        raise RuntimeError("Set the firmware URL (https://raw.githubusercontent.com/<user>/<repo>/<branch>/firmware.ota.bin).")
    if not secrets.get("github_token", "").strip():
        raise RuntimeError("Enter the GitHub token.")
    repo = firmware_repo_dir(conn)

    write_project_files(cfg, SCRIPT_DIR)
    write_secrets(SCRIPT_DIR / "secrets.yaml", secrets)
    run_logged(find_esphome() + ["compile", f"{DEVICE_NAME}.yaml"], SCRIPT_DIR, log)
    build_dir = SCRIPT_DIR / ".esphome" / "build" / DEVICE_NAME
    # ESP-IDF based builds write to build/, PlatformIO ones to .pioenvs/<name>/.
    candidates = [build_dir / "build" / "firmware.ota.bin", build_dir / ".pioenvs" / DEVICE_NAME / "firmware.ota.bin"]
    built = next((path for path in candidates if path.exists()), None)
    if not built:
        raise RuntimeError("Compiled firmware not found in " + " or ".join(str(path) for path in candidates))

    if (repo / ".git").exists():
        run_logged(["git", "pull", "--ff-only"], repo, log)
    else:
        run_logged(["git", "clone", f"https://github.com/{match.group(1)}/{match.group(2)}.git", str(repo)], SCRIPT_DIR, log)
    shutil.copyfile(built, repo / "firmware.ota.bin")
    md5 = hashlib.md5(built.read_bytes()).hexdigest()
    (repo / "firmware.ota.bin.md5").write_text(md5, encoding="utf-8")
    log(f"md5 {md5}")

    run_logged(["git", "add", "firmware.ota.bin", "firmware.ota.bin.md5"], repo, log)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo).returncode == 0:
        log("Nothing changed in the repository.")
    else:
        run_logged(["git", "commit", "-m", f"Firmware {time.strftime('%Y-%m-%d %H:%M:%S')}"], repo, log)
        run_logged(["git", "push"], repo, log)
    log("Done. Tap 'Aggiorna firmware ESP32' in the app.")


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
    # Two-state segmented switch (ttk.Radiobutton buttons): the selected side is filled with the accent colour.
    flat_button("Segment.Toolbutton", c["input"], c["muted"], c["hover"], padding=(18, 5), font=(FONT, 10, "bold"))
    style.map("Segment.Toolbutton",
              background=[("selected", c["accent"]), ("pressed", c["hover"]), ("active", c["hover"])],
              foreground=[("selected", "#ffffff")],
              bordercolor=[("selected", c["accent"])], lightcolor=[("selected", c["accent"])],
              darkcolor=[("selected", c["accent"])])
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
        self.gap_before = tk.StringVar(value=str(data.get("gap_before", 0)))
        self.right_to_left = tk.BooleanVar(value=bool(data.get("right_to_left", False)))
        self.segments = [SegmentRow(app, self, s) for s in data.get("segments", [])]
        self.num_leds.trace_add("write", lambda *_: app.on_layout_changed(self))
        self.gap_before.trace_add("write", lambda *_: app.on_layout_changed(self))
        self.right_to_left.trace_add("write", lambda *_: app.after_idle(app.render_strips))
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
        self.github_token = tk.StringVar()
        self.api_key = tk.StringVar()
        self.firmware_url = tk.StringVar()
        self.firmware_repo = tk.StringVar()
        self.status_led_gpio = tk.StringVar()
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
        self.publish_button = ttk.Button(bar, text="Publish firmware…", command=self.publish_ui)
        self.publish_button.pack(side="right", padx=8)
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
        ttk.Label(toolbar, text="On-board status LED GPIO").pack(side="left", padx=(36, 0))
        ttk.Combobox(toolbar, textvariable=self.status_led_gpio, values=(2,), width=5).pack(side="left", padx=10)
        ttk.Label(toolbar, text="empty = off", style="PageSub.TLabel").pack(side="left")
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

        side = ttk.Frame(card, style="Card.TFrame")
        side.pack(fill="x", pady=(10, 0))
        ttk.Label(side, text="Board side (LED 0)", style="CardMuted.TLabel").pack(side="left", padx=(0, 12))
        for text, value in (("Left", False), ("Right", True)):
            ttk.Radiobutton(side, text=text, value=value, variable=strip.right_to_left,
                            style="Segment.Toolbutton").pack(side="left")
        ttk.Label(side, text="The first row is always the one next to the board; switching sides reverses the rows.",
                  style="CardMuted.TLabel").pack(side="left", padx=(14, 0))

        bar = tk.Canvas(card, height=18, highlightthickness=0, bd=0, background=COLORS["card"])
        bar.pack(fill="x", pady=(14, 14))

        table = ttk.Frame(card, style="Card.TFrame")
        table.pack(fill="x")
        table.columnconfigure(4, weight=1)
        for col, text in enumerate(("", "SEGMENT / GAP", "LEDS", "LED RANGE", "MOMENTS", "")):
            ttk.Label(table, text=text, style="ColHead.TLabel").grid(row=0, column=col, sticky="w", padx=4,
                                                                     pady=(0, 6))
        count = len(strip.segments)
        reverse = strip.right_to_left.get()
        # Rows run from the board (LED 0) to the far end; the data stays in shelf order (left to right).
        led_segments = strip.segments[::-1] if reverse else strip.segments
        led_gaps = ([strip.gap_before] + [seg.gap for seg in strip.segments])
        if reverse:
            led_gaps.reverse()
        range_labels, gap_labels = [None] * count, [None] * (count + 1)

        def gap_row(row, caption, var, gap_index):
            """A gap between two segments, or at one end of the strip."""
            tk.Frame(table, background=COLORS["border"], width=5, height=2).grid(row=row, column=0, sticky="ew",
                                                                                 padx=(0, 6))
            ttk.Label(table, text=caption, style="CardMuted.TLabel").grid(row=row, column=1, sticky="e", padx=4,
                                                                          pady=2)
            ttk.Spinbox(table, from_=0, to=99, width=4, textvariable=var).grid(row=row, column=2, sticky="nw",
                                                                              padx=4, pady=2)
            label = ttk.Label(table, style="CardMuted.TLabel", width=9)
            label.grid(row=row, column=3, sticky="nw", padx=4, pady=4)
            gap_labels[gap_index] = label

        if count:
            gap_row(1, "gap · at the board", led_gaps[0], count if reverse else 0)
        for position, seg in enumerate(led_segments):
            row = 2 + 2 * position
            data_index = count - 1 - position if reverse else position
            color = SEGMENT_COLORS[data_index % len(SEGMENT_COLORS)]
            tk.Frame(table, background=color, width=5).grid(row=row, column=0, sticky="ns", padx=(0, 6), pady=5)
            ttk.Entry(table, textvariable=seg.name, width=22).grid(row=row, column=1, sticky="nw", padx=4, pady=4)
            ttk.Spinbox(table, from_=1, to=999, width=4, textvariable=seg.leds).grid(row=row, column=2,
                                                                                    sticky="nw", padx=4, pady=4)
            range_label = ttk.Label(table, style="CardMuted.TLabel", width=9)
            range_label.grid(row=row, column=3, sticky="nw", padx=4, pady=7)
            range_labels[data_index] = range_label
            last = position == count - 1
            gap_row(row + 1, "gap · at the far end" if last else "gap", led_gaps[position + 1],
                    count - 1 - position if reverse else position + 1)

            checks = ttk.Frame(table, style="Card.TFrame")
            checks.grid(row=row, column=4, sticky="nw", padx=4, pady=4)
            for k, moment in enumerate(self.moments):
                ttk.Checkbutton(checks, text=moment.label(), variable=seg.checks[moment],
                                style="Card.TCheckbutton").grid(row=k // MOMENT_COLUMNS, column=k % MOMENT_COLUMNS,
                                                                sticky="w", padx=(0, 14))
            if not self.moments:
                ttk.Label(checks, text="Define moments first.", style="CardMuted.TLabel").grid(row=0, column=0)

            self._row_actions(
                table, position, count,
                lambda delta, s=seg: self.move_segment(strip, s, -delta if strip.right_to_left.get() else delta),
                lambda s=seg: self.remove_segment(strip, s),
            ).grid(row=row, column=5, sticky="ne", padx=(4, 0), pady=4)

        if not strip.segments:
            ttk.Label(table, text="No segments yet.", style="CardMuted.TLabel").grid(row=1, column=1, columnspan=4,
                                                                                    sticky="w", padx=4)
        ttk.Button(card, text="+ Add segment", style="Ghost.TButton",
                   command=lambda: self.add_segment(strip)).pack(anchor="w", pady=(10, 0))

        strip.view = {"usage": usage, "bar": bar, "ranges": range_labels, "gaps": gap_labels}
        bar.bind("<Configure>", lambda _e: self._update_strip_view(strip))
        self._update_strip_view(strip)

    def _strip_layout(self, strip):
        """Layout from the current (possibly invalid) widget values: (ranges, gap ranges, used, num); None if invalid."""
        num = parse_int(strip.num_leds.get())
        before = parse_int(strip.gap_before.get())
        segments = []
        for seg in strip.segments:
            leds, gap = parse_int(seg.leds.get()), parse_int(seg.gap.get())
            if leds is None or leds < 1 or gap is None or gap < 0:
                return None, None, None, num
            segments.append({"leds": leds, "gap_after": gap})
        if before is None or before < 0:
            return None, None, None, num
        ranges, gaps, used = compute_full_layout(segments, strip.right_to_left.get(), before)
        return ranges, gaps, used, num

    def _update_strip_view(self, strip):
        view = strip.view
        if not view:
            return
        ranges, gaps, used, num = self._strip_layout(strip)
        for i, label in enumerate(view["ranges"]):
            label.configure(text=f"{ranges[i][0]} – {ranges[i][1]}" if ranges else "—")
        for i, label in enumerate(view["gaps"]):
            span = gaps[i] if gaps else None
            label.configure(text="—" if not span else f"{span[0]}" if span[0] == span[1] else f"{span[0]} – {span[1]}")
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
            "name": f"Strip {len(self.strips) + 1}", "gpio": gpio, "num_leds": 6, "gap_before": 0,
            "segments": [{"name": self._unique_segment_name(), "leds": 6, "gap_after": 0, "moments": []}],
        }

    def _unique_segment_name(self):
        existing = {seg.name.get().strip() for strip in self.strips for seg in strip.segments}
        n = 1
        while f"Segment {n}" in existing:
            n += 1
        return f"Segment {n}"

    def add_segment(self, strip):
        """Append a segment at the far end of the strip (the bottom row); the gap at that end stays there."""
        reverse = strip.right_to_left.get()
        segments = strip.segments
        far = segments[0] if reverse and segments else segments[-1] if segments else None
        # The gap that now sits between the old and the new segment repeats the previous spacing.
        neighbour = segments[0] if reverse and len(segments) >= 2 else segments[-2] if len(segments) >= 2 else None
        between = neighbour.gap.get() if neighbour else "1"
        data = {"name": self._unique_segment_name(), "leds": far.leds.get() if far else 6, "gap_after": "0",
                "moments": []}
        if reverse:
            # Far end is the start of the shelf-ordered list; its gap is strip.gap_before and stays there.
            data["gap_after"] = between if far else "0"
            segments.insert(0, SegmentRow(self, strip, data))
        else:
            data["gap_after"] = far.gap.get() if far else "0"
            segments.append(SegmentRow(self, strip, data))
            if far:
                far.gap.set(between)
        self.render_strips()

    def move_segment(self, strip, seg, delta):
        i = strip.segments.index(seg)
        j = i + delta
        if 0 <= j < len(strip.segments):
            strip.segments[i], strip.segments[j] = strip.segments[j], strip.segments[i]
            # The gap is part of the shelf position, not of the segment, so it stays where it was.
            gap_i, gap_j = strip.segments[i].gap.get(), strip.segments[j].gap.get()
            strip.segments[i].gap.set(gap_j)
            strip.segments[j].gap.set(gap_i)
            self.render_strips()

    def remove_segment(self, strip, seg):
        i = strip.segments.index(seg)
        if i == len(strip.segments) - 1 and i > 0:
            strip.segments[i - 1].gap.set(seg.gap.get())  # the gap at the end stays at the end
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
            ("API encryption key", self.api_key, {**secret, "width": 50}),
        ))
        self._form(self._card(inner, "Remote firmware update (optional)"), (
            ("Firmware .bin URL", self.firmware_url, {"width": 60}),
            ("GitHub token", self.github_token, secret),
            ("Local repo folder", self.firmware_repo, {"width": 60}),
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
                "right_to_left": strip.right_to_left.get(),
                "gap_before": number(strip.gap_before, f"{strip_name}: gap at the start"),
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
                "firmware_url": self.firmware_url.get().strip(),
                "firmware_repo": self.firmware_repo.get().strip(),
                "topics": topics,
            },
            "pulse": {
                "on_ms": number(self.pulse_on, "LED on time"),
                "off_ms": number(self.pulse_off, "LED off time"),
                "transition_ms": number(self.pulse_transition, "Fade time"),
            },
            "status_led_gpio": number(self.status_led_gpio, "Status LED GPIO") if self.status_led_gpio.get().strip() else None,
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
        self.firmware_url.set(str(conn["firmware_url"]))
        self.firmware_repo.set(str(conn["firmware_repo"]))
        pulse = {**DEFAULT_PULSE, **cfg.get("pulse", {})}
        self.pulse_on.set(str(pulse["on_ms"]))
        self.pulse_off.set(str(pulse["off_ms"]))
        self.pulse_transition.set(str(pulse["transition_ms"]))
        self.status_led_gpio.set("" if cfg.get("status_led_gpio") is None else str(cfg["status_led_gpio"]))

        self.render_strips()
        self.render_moments()
        self.refresh_topics()

    def _apply_secrets(self, path):
        secrets = read_secrets(path)
        self.wifi_ssid.set(str(secrets.get("wifi_ssid", "")))
        self.wifi_password.set(str(secrets.get("wifi_password", "")))
        self.ota_password.set(str(secrets.get("ota_password", "")))
        self.mqtt_key.set(str(secrets.get("adafruit_io_key", "")))
        self.github_token.set(str(secrets.get("github_token", "")))
        self.api_key.set(str(secrets.get("api_encryption_key", "")))

    def _collect_secrets(self):
        if not self.api_key.get().strip():
            self.api_key.set(new_api_key())
        return {
            "api_encryption_key": self.api_key.get().strip(),
            "wifi_ssid": self.wifi_ssid.get(),
            "wifi_password": self.wifi_password.get(),
            "ota_password": self.ota_password.get(),
            "adafruit_io_key": self.mqtt_key.get(),
            "github_token": self.github_token.get(),
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

    def _confirm_security(self, cfg):
        warnings = security_warnings(cfg)
        return not warnings or messagebox.askyesno(
            "Unencrypted connection", "\n\n".join(warnings) + "\n\nContinue anyway?")

    def save_yaml(self):
        cfg = self._checked_config()
        if not cfg or not self._confirm_security(cfg):
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

    def publish_ui(self):
        cfg = self._checked_config()
        if not cfg or not self._confirm_security(cfg):
            return
        if not messagebox.askyesno(
                "Publish firmware",
                "Compile the firmware and upload it to the private firmware repository?\n\n"
                "Afterwards, tap 'Aggiorna firmware ESP32' in the app to update the device.\n"
                "This overwrites led-farmaci.yaml, configuration.json and secrets.yaml in the project folder."):
            return
        secrets = self._collect_secrets()
        win = tk.Toplevel(self)
        win.title("Publish firmware")
        win.geometry("820x480")
        win.configure(background=COLORS["bg"])
        text = tk.Text(win, background=COLORS["input"], foreground=COLORS["text"], font=("Consolas", 9),
                       wrap="none", state="disabled", borderwidth=0)
        text.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        close = ttk.Button(win, text="Close", command=win.destroy, state="disabled")
        close.pack(side="right", padx=12, pady=(0, 12))
        lines = queue.Queue()
        result = {"ok": False}

        def work():
            try:
                publish_firmware(cfg, secrets, lines.put)
                result["ok"] = True
            except Exception as exc:
                lines.put(f"ERROR: {exc}")
            lines.put(None)

        def pump():
            if not win.winfo_exists():
                return
            try:
                while True:
                    line = lines.get_nowait()
                    if line is None:
                        close.state(["!disabled"])
                        self.publish_button.state(["!disabled"])
                        ok = result["ok"]
                        self.set_status("Firmware published." if ok else "Firmware publish failed.", "ok" if ok else "error")
                        return
                    text.configure(state="normal")
                    text.insert("end", line + "\n")
                    text.see("end")
                    text.configure(state="disabled")
            except queue.Empty:
                win.after(100, pump)

        self.publish_button.state(["disabled"])
        self.set_status("Publishing firmware…", "muted")
        threading.Thread(target=work, daemon=True).start()
        pump()


if __name__ == "__main__":
    app = Configurator()
    app.mainloop()
