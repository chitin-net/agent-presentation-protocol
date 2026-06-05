"""
Agent Presentation Protocol (APP) — Raspberry Pi Pico W Headless Bridge (MicroPython)

Connects a Pico W to an APP relay as a headless device.
Controls the onboard LED, reads the built-in temperature sensor,
and handles device actions.

DISCLAIMER: This code is provided as-is for reference only.
See the top-level README for the full disclaimer.

Hardware:
  - Raspberry Pi Pico W (built-in WiFi + built-in LED on 'LED'/GPIO CYW43)
  - Built-in temperature sensor (ADC channel 4)
  - Optional: external LED on GPIO 15, button on GPIO 14

Firmware: MicroPython for Pico W (v1.22+)
  Download: https://micropython.org/download/RPI_PICO_W/

Transfer this file to the Pico W as main.py using Thonny or mpremote:
  mpremote cp main.py :main.py
  mpremote reset
"""

import network
import socket
import json
import time
import machine
import gc
import ubinascii
import uos
import usys

# ============================================================
# CONFIGURATION
# ============================================================

WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
BRIDGE_TOKEN = "YOUR_BRIDGE_TOKEN"
RELAY_HOST = "your-relay.example"
RELAY_PORT = 443
RELAY_PATH = "/ws/bridge"

LED_PIN = "LED"  # Onboard LED (Pico W uses "LED" string, not a number)
EXT_LED_PIN = 15
BUTTON_PIN = 14

SENSOR_INTERVAL = 30  # seconds
HEARTBEAT_INTERVAL = 25

# ============================================================
# Hardware
# ============================================================

led = machine.Pin(LED_PIN, machine.Pin.OUT)
ext_led = machine.Pin(EXT_LED_PIN, machine.Pin.OUT)
button = machine.Pin(BUTTON_PIN, machine.Pin.IN, machine.Pin.PULL_UP)
temp_sensor = machine.ADC(4)  # Built-in temperature sensor

led_state = False
last_button = 1


def read_temp():
    """Read the Pico's built-in temperature sensor."""
    reading = temp_sensor.read_u16()
    voltage = reading * 3.3 / 65535
    temperature = 27 - (voltage - 0.706) / 0.001721
    return round(temperature, 1)


def set_led(state):
    global led_state
    led_state = state
    led.value(1 if state else 0)


# ============================================================
# WiFi
# ============================================================


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print(f"[WIFI] Connecting to {WIFI_SSID}...")
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        timeout = 30
        while not wlan.isconnected() and timeout > 0:
            time.sleep(1)
            timeout -= 1
        if not wlan.isconnected():
            raise RuntimeError("WiFi connection failed")
    ip = wlan.ifconfig()[0]
    print(f"[WIFI] Connected: {ip}")
    return wlan


# ============================================================
# Minimal WebSocket client (MicroPython)
#
# MicroPython doesn't have a built-in WebSocket library.
# This is a minimal implementation for the APP protocol.
# For production, consider using micropython-uwebsockets.
# ============================================================


class SimpleWebSocket:
    """Bare-minimum WebSocket client for MicroPython (text frames only)."""

    def __init__(self):
        self.sock = None

    def connect(self, host, port, path, token):
        import ussl
        addr = socket.getaddrinfo(host, port)[0][-1]
        self.sock = socket.socket()
        self.sock.connect(addr)
        self.sock = ussl.wrap_socket(self.sock, server_hostname=host)

        # WebSocket handshake
        key = ubinascii.b2a_base64(uos.urandom(16)).strip()
        request = (
            f"GET {path}?token={token} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key.decode()}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        self.sock.write(request.encode())

        # Read response headers
        while True:
            line = self.sock.readline()
            if line == b"\r\n" or line == b"":
                break
        print("[WS] Connected")

    def send(self, data):
        """Send a text frame."""
        if not self.sock:
            return
        payload = data.encode() if isinstance(data, str) else data
        length = len(payload)
        # Frame: FIN + TEXT opcode, masked
        header = bytearray()
        header.append(0x81)  # FIN + text
        mask_key = uos.urandom(4)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.append((length >> 8) & 0xFF)
            header.append(length & 0xFF)
        header.extend(mask_key)
        # Mask payload
        masked = bytearray(length)
        for i in range(length):
            masked[i] = payload[i] ^ mask_key[i % 4]
        self.sock.write(header + masked)

    def recv(self, timeout_ms=100):
        """Non-blocking receive. Returns string or None."""
        if not self.sock:
            return None
        self.sock.setblocking(False)
        try:
            # Read frame header
            hdr = self.sock.read(2)
            if not hdr or len(hdr) < 2:
                return None
            opcode = hdr[0] & 0x0F
            length = hdr[1] & 0x7F
            if length == 126:
                ext = self.sock.read(2)
                length = (ext[0] << 8) | ext[1]
            elif length == 127:
                ext = self.sock.read(8)
                length = int.from_bytes(ext, "big")

            if opcode == 0x8:  # Close
                self.close()
                return None
            if opcode == 0x9:  # Ping → send pong
                data = self.sock.read(length) if length else b""
                self._send_pong(data)
                return None

            payload = b""
            while len(payload) < length:
                chunk = self.sock.read(length - len(payload))
                if chunk:
                    payload += chunk
                else:
                    break

            if opcode == 0x1:  # Text
                return payload.decode()
        except OSError:
            pass
        finally:
            self.sock.setblocking(True)
        return None

    def ping(self):
        if self.sock:
            self.sock.write(bytearray([0x89, 0x80]) + uos.urandom(4))

    def _send_pong(self, data):
        if self.sock:
            frame = bytearray([0x8A, 0x80 | len(data)]) + uos.urandom(4)
            self.sock.write(frame)

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

    Pico W has no UUID library and the v4 format-specific bits are not
    enforced — this id is a dedup/correlation key, not a security identifier.
    See README "Protocol notes" for context.
    """
    h = ubinascii.hexlify(uos.urandom(16)).decode()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def agent_card():
    card = {
        "protocol_version": "0.4",
        "agent": {
            "name": "Pico W Sensor Hub",
            "version": "1.0.0",
            "description": "Raspberry Pi Pico W with LED and temperature sensor",
        },
        "device": {
            "type": "microcontroller",
            "manufacturer": "Raspberry Pi Foundation",
            "model": "Pico W",
            "interaction_model": "headless",
            "status": {
                "led": "on" if led_state else "off",
                "cpu_temp_c": read_temp(),
                "button": "pressed" if button.value() == 0 else "released",
                "free_mem": gc.mem_free(),
            },
            "available_actions": [
                {
                    "id": "set_led",
                    "name": "Set LED",
                    "description": "Turn the onboard LED on or off",
                    "params": [{
                        "name": "state",
                        "type": "string",
                        "required": True,
                        "options": ["on", "off", "toggle"],
                    }],
                },
                {
                    "id": "blink_led",
                    "name": "Blink LED",
                    "description": "Blink the LED a number of times",
                    "params": [{
                        "name": "count",
                        "type": "integer",
                        "required": False,
                        "min": 1,
                        "max": 20,
                    }],
                },
                {
                    "id": "read_sensors",
                    "name": "Read Sensors",
                    "description": "Read onboard temperature sensor and memory status",
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
            "cpu_temp_c": read_temp(),
            "led": "on" if led_state else "off",
            "button": "pressed" if button.value() == 0 else "released",
            "free_mem": gc.mem_free(),
            "uptime_ms": time.ticks_ms(),
        },
        "trigger": trigger,
        # Pico W has no real-time clock; timestamp is monotonic ms-since-boot
        # (`time.ticks_ms()`). See README "Protocol notes". A downstream
        # consumer that needs wall-clock time should stamp it on receipt.
        "timestamp": time.ticks_ms(),
    })


# ============================================================
# Action handlers
# ============================================================


def handle_action(ws, action, params):
    print(f"[ACTION] {action} {params}")

    if action == "set_led":
        state = params.get("state", "toggle")
        if state == "on":
            set_led(True)
        elif state == "off":
            set_led(False)
        else:
            set_led(not led_state)

    elif action == "blink_led":
        count = min(max(params.get("count", 3), 1), 20)
        for _ in range(count):
            set_led(True)
            time.sleep(0.2)
            set_led(False)
            time.sleep(0.2)
        set_led(led_state)

    elif action == "read_sensors":
        pass  # Sensor event sent below

    else:
        print(f"[ACTION] Unknown: {action}")

    ws.send(sensor_event(trigger="event"))


# ============================================================
# Main loop
# ============================================================


def main():
    print("=== APP — Pico W ===")
    wlan = connect_wifi()
    ws = SimpleWebSocket()
    reconnect_delay = HEARTBEAT_INTERVAL

    while True:
        try:
            ws.connect(RELAY_HOST, RELAY_PORT, RELAY_PATH, BRIDGE_TOKEN)
            reconnect_delay = 1

            ws.send(agent_card())
            print("[WS] Agent Card sent")
            ws.send(sensor_event())

            last_sensor = time.ticks_ms()
            last_ping = time.ticks_ms()

            while True:
                # Check for incoming messages
                msg = ws.recv()
                if msg:
                    try:
                        data = json.loads(msg)
                        if data.get("type") == "device_action":
                            handle_action(
                                ws,
                                data.get("action", ""),
                                data.get("parameters", {}),
                            )
                    except (ValueError, KeyError) as e:
                        print(f"[WS] Parse error: {e}")

                # Heartbeat
                now = time.ticks_ms()
                if time.ticks_diff(now, last_ping) >= HEARTBEAT_INTERVAL * 1000:
                    ws.ping()
                    last_ping = now

                # Periodic sensor report
                if time.ticks_diff(now, last_sensor) >= SENSOR_INTERVAL * 1000:
                    ws.send(sensor_event())
                    last_sensor = now

                # Button check
                global last_button
                btn = button.value()
                if btn == 0 and last_button == 1:
                    ws.send(json.dumps({
                        "type": "sensor_event",
                        "id": make_id(),
                        "sensor": "button",
                        "value": {"button": "pressed"},
                        "trigger": "event",
                        "timestamp": time.ticks_ms(),
                    }))
                    time.sleep_ms(50)
                last_button = btn

                time.sleep_ms(50)

        except Exception as e:
            print(f"[ERR] {e}")
            ws.close()

        print(f"[WS] Reconnecting in {reconnect_delay}s...")
        time.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 2, 60)

        # Reconnect WiFi if needed
        if not wlan.isconnected():
            wlan = connect_wifi()


if __name__ == "__main__":
    main()
