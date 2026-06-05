# SPDX-License-Identifier: Apache-2.0
"""
Agent Presentation Protocol (APP) — CircuitPython Headless Bridge

For Adafruit ESP32-S3 boards (Feather, QT Py, Metro) running CircuitPython.
Controls the onboard NeoPixel, reads analog sensors, and handles device actions.

DISCLAIMER: This code is provided as-is for reference only.
See the top-level README for the full disclaimer.

Firmware: CircuitPython 9.x+ for your board
  Download: https://circuitpython.org/downloads

Required libraries (copy to /lib on CIRCUITPY drive):
  - adafruit_requests
  - adafruit_connection_manager

Transfer this file to the board as code.py.
Create settings.toml for WiFi credentials.
"""

import board
import digitalio
import analogio
import neopixel
import microcontroller
import time
import json
import gc
import os
import ssl
import socketpool
import wifi

# ============================================================
# CONFIGURATION
# ============================================================

# WiFi credentials — set these in settings.toml:
#   CIRCUITPY_WIFI_SSID = "your_ssid"
#   CIRCUITPY_WIFI_PASSWORD = "your_password"
#   BRIDGE_TOKEN = "your_token"

BRIDGE_TOKEN = os.getenv("BRIDGE_TOKEN", "YOUR_BRIDGE_TOKEN")
RELAY_HOST = "your-relay.example"
RELAY_PORT = 443
RELAY_PATH = "/ws/bridge"

SENSOR_INTERVAL = 30
HEARTBEAT_INTERVAL = 25

# NeoPixel (built-in on most Adafruit ESP32-S3 boards)
pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.3)

# Optional external hardware
try:
    button = digitalio.DigitalInOut(board.D9)
    button.direction = digitalio.Direction.INPUT
    button.pull = digitalio.Pull.UP
    HAS_BUTTON = True
except Exception:
    HAS_BUTTON = False

try:
    analog = analogio.AnalogIn(board.A0)
    HAS_ANALOG = True
except Exception:
    HAS_ANALOG = False

# ============================================================
# State
# ============================================================

led_color = (0, 0, 0)  # RGB tuple
led_on = False
last_button = True


def set_pixel(r, g, b):
    global led_color, led_on
    led_color = (r, g, b)
    led_on = (r + g + b) > 0
    pixel[0] = led_color


def cpu_temp():
    try:
        return round(microcontroller.cpu.temperature, 1)
    except Exception:
        return 0.0


def analog_value():
    if HAS_ANALOG:
        return analog.value
    return 0


# ============================================================
# Minimal WebSocket (CircuitPython)
#
# CircuitPython's socket API differs from MicroPython.
# This is a minimal text-frame-only WebSocket client.
# ============================================================


class WebSocket:
    def __init__(self):
        self.sock = None
        self.pool = socketpool.SocketPool(wifi.radio)
        self.ssl_ctx = ssl.create_default_context()

    def connect(self, host, port, path, token):
        self.sock = self.pool.socket(socketpool.SocketPool.AF_INET,
                                      socketpool.SocketPool.SOCK_STREAM)
        self.sock.settimeout(10)
        addr = self.pool.getaddrinfo(host, port)[0][4]
        self.sock.connect(addr)
        self.sock = self.ssl_ctx.wrap_socket(self.sock, server_hostname=host)

        # Handshake
        import binascii
        key = binascii.b2a_base64(os.urandom(16)).strip()
        req = (
            f"GET {path}?token={token} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key.decode()}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.send(req.encode())

        # Read response
        buf = bytearray(1024)
        self.sock.settimeout(5)
        try:
            while True:
                n = self.sock.recv_into(buf)
                if n == 0 or b"\r\n\r\n" in buf[:n]:
                    break
        except OSError:
            pass
        self.sock.settimeout(0.1)
        print("[WS] Connected")

    def send(self, data):
        if not self.sock:
            return
        payload = data.encode() if isinstance(data, str) else data
        length = len(payload)
        header = bytearray([0x81])
        mask_key = os.urandom(4)
        if length < 126:
            header.append(0x80 | length)
        else:
            header.append(0x80 | 126)
            header.append((length >> 8) & 0xFF)
            header.append(length & 0xFF)
        header.extend(mask_key)
        masked = bytearray(length)
        for i in range(length):
            masked[i] = payload[i] ^ mask_key[i % 4]
        self.sock.send(header + masked)

    def recv(self):
        if not self.sock:
            return None
        try:
            hdr = bytearray(2)
            n = self.sock.recv_into(hdr)
            if n < 2:
                return None
            opcode = hdr[0] & 0x0F
            length = hdr[1] & 0x7F
            if length == 126:
                ext = bytearray(2)
                self.sock.recv_into(ext)
                length = (ext[0] << 8) | ext[1]
            if opcode == 0x9:  # Ping
                self.send_pong()
                return None
            if opcode == 0x8:  # Close
                self.close()
                return None
            if length > 0:
                payload = bytearray(length)
                received = 0
                while received < length:
                    chunk = bytearray(min(512, length - received))
                    n = self.sock.recv_into(chunk)
                    payload[received:received + n] = chunk[:n]
                    received += n
                if opcode == 0x1:
                    return payload.decode()
        except OSError:
            pass
        return None

    def ping(self):
        if self.sock:
            mask = os.urandom(4)
            self.sock.send(bytearray([0x89, 0x80]) + mask)

    def send_pong(self):
        if self.sock:
            mask = os.urandom(4)
            self.sock.send(bytearray([0x8A, 0x80]) + mask)

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None


# ============================================================
# Protocol messages
# ============================================================


def make_id():
    """128-bit random hex string formatted UUID-style.

    CircuitPython has no UUID library and the v4 format-specific bits are
    not enforced — this id is a dedup/correlation key, not a security
    identifier. See README "Protocol notes" for context.
    """
    h = os.urandom(16).hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def agent_card():
    card = {
        "protocol_version": "0.4",
        "agent": {
            "name": "CircuitPython Sensor",
            "version": "1.0.0",
            "description": "Adafruit ESP32-S3 with NeoPixel and sensors",
        },
        "device": {
            "type": "microcontroller",
            "manufacturer": "Adafruit",
            "model": "ESP32-S3",
            "interaction_model": "headless",
            "status": {
                "neopixel": f"#{led_color[0]:02x}{led_color[1]:02x}{led_color[2]:02x}",
                "cpu_temp_c": cpu_temp(),
                "analog": analog_value(),
            },
            "available_actions": [
                {
                    "id": "set_color",
                    "name": "Set NeoPixel Color",
                    "description": "Set the NeoPixel LED to a color (red, green, blue, white, off, or custom RGB)",
                    "params": [{
                        "name": "color",
                        "type": "string",
                        "required": True,
                        "options": ["red", "green", "blue", "yellow", "purple", "white", "off"],
                    }],
                },
                {
                    "id": "set_rgb",
                    "name": "Set RGB",
                    "description": "Set NeoPixel to exact RGB values (0-255 each)",
                    "params": [
                        {"name": "r", "type": "integer", "required": True, "min": 0, "max": 255},
                        {"name": "g", "type": "integer", "required": True, "min": 0, "max": 255},
                        {"name": "b", "type": "integer", "required": True, "min": 0, "max": 255},
                    ],
                },
                {
                    "id": "set_brightness",
                    "name": "Set Brightness",
                    "description": "Set NeoPixel brightness (0.0 to 1.0)",
                    "params": [{
                        "name": "level",
                        "type": "number",
                        "required": True,
                        "min": 0.0,
                        "max": 1.0,
                    }],
                },
                {
                    "id": "read_sensors",
                    "name": "Read Sensors",
                    "description": "Read CPU temperature and analog input",
                },
                {
                    "id": "rainbow",
                    "name": "Rainbow Cycle",
                    "description": "Cycle through rainbow colors on the NeoPixel",
                    "params": [{
                        "name": "duration",
                        "type": "integer",
                        "required": False,
                        "min": 1,
                        "max": 30,
                    }],
                },
            ],
        },
        # Headless device: interaction_model="headless" plus omitted
        # input_accepts/output_modalities declares no direct human I/O.
        "capabilities": {
            "streaming": False,
            "emotions": [],
        },
    }
    return json.dumps({"type": "agent_card", "card": card})


def sensor_event(trigger="periodic"):
    gc.collect()
    return json.dumps({
        "type": "sensor_event",
        "id": make_id(),
        "sensor": "system",
        "value": {
            "neopixel": f"#{led_color[0]:02x}{led_color[1]:02x}{led_color[2]:02x}",
            "cpu_temp_c": cpu_temp(),
            "analog": analog_value(),
            "free_mem": gc.mem_free(),
        },
        "trigger": trigger,
        # ESP32-S3 board running CircuitPython has no real-time clock by
        # default; timestamp is monotonic ms-since-boot. See README
        # "Protocol notes". Downstream consumers needing wall-clock time
        # should stamp it on receipt.
        "timestamp": int(time.monotonic() * 1000),
    })


# ============================================================
# Action handlers
# ============================================================

COLOR_MAP = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "purple": (128, 0, 128),
    "white": (255, 255, 255),
    "off": (0, 0, 0),
}


def handle_action(ws, action, params):
    print(f"[ACTION] {action} {params}")

    if action == "set_color":
        color = params.get("color", "off").lower()
        r, g, b = COLOR_MAP.get(color, (0, 0, 0))
        set_pixel(r, g, b)

    elif action == "set_rgb":
        r = max(0, min(255, params.get("r", 0)))
        g = max(0, min(255, params.get("g", 0)))
        b = max(0, min(255, params.get("b", 0)))
        set_pixel(r, g, b)

    elif action == "set_brightness":
        level = max(0.0, min(1.0, params.get("level", 0.3)))
        pixel.brightness = level

    elif action == "rainbow":
        duration = max(1, min(30, params.get("duration", 5)))
        steps = duration * 10
        for i in range(steps):
            hue = (i / steps) * 360
            r, g, b = _hsv_to_rgb(hue, 1.0, 1.0)
            pixel[0] = (r, g, b)
            time.sleep(0.1)
        pixel[0] = led_color  # Restore

    elif action == "read_sensors":
        pass

    ws.send(sensor_event(trigger="event"))


def _hsv_to_rgb(h, s, v):
    """Simple HSV to RGB for rainbow effect."""
    h = h % 360
    c = v * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = v - c
    if h < 60:    r, g, b = c, x, 0
    elif h < 120: r, g, b = x, c, 0
    elif h < 180: r, g, b = 0, c, x
    elif h < 240: r, g, b = 0, x, c
    elif h < 300: r, g, b = x, 0, c
    else:         r, g, b = c, 0, x
    return int((r + m) * 255), int((g + m) * 255), int((b + m) * 255)


# ============================================================
# Main
# ============================================================


def main():
    print("=== APP — CircuitPython ===")

    # Connect WiFi (uses settings.toml automatically in CP 9+)
    print(f"[WIFI] Connecting to {os.getenv('CIRCUITPY_WIFI_SSID', WIFI_SSID)}...")
    wifi.radio.connect(
        os.getenv("CIRCUITPY_WIFI_SSID", WIFI_SSID),
        os.getenv("CIRCUITPY_WIFI_PASSWORD", WIFI_PASSWORD),
    )
    print(f"[WIFI] Connected: {wifi.radio.ipv4_address}")

    # Start-up flash
    set_pixel(0, 0, 255)
    time.sleep(0.5)
    set_pixel(0, 0, 0)

    ws = WebSocket()
    reconnect_delay = 1

    while True:
        try:
            ws.connect(RELAY_HOST, RELAY_PORT, RELAY_PATH, BRIDGE_TOKEN)
            reconnect_delay = 1

            ws.send(agent_card())
            print("[WS] Agent Card sent")
            ws.send(sensor_event())

            last_sensor = time.monotonic()
            last_ping = time.monotonic()

            while True:
                msg = ws.recv()
                if msg:
                    try:
                        data = json.loads(msg)
                        if data.get("type") == "device_action":
                            handle_action(ws, data.get("action", ""), data.get("parameters", {}))
                    except (ValueError, KeyError):
                        pass

                now = time.monotonic()
                if now - last_ping >= HEARTBEAT_INTERVAL:
                    ws.ping()
                    last_ping = now

                if now - last_sensor >= SENSOR_INTERVAL:
                    ws.send(sensor_event())
                    last_sensor = now

                time.sleep(0.05)

        except Exception as e:
            print(f"[ERR] {e}")
            ws.close()

        # Indicate disconnected state
        set_pixel(255, 0, 0)
        time.sleep(0.5)
        set_pixel(0, 0, 0)

        print(f"[WS] Reconnecting in {reconnect_delay}s...")
        time.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 2, 60)


main()
