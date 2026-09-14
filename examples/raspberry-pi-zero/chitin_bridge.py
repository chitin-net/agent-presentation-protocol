#!/usr/bin/env python3
"""
Agent Presentation Protocol (APP) — Raspberry Pi Zero 2 W Headless Bridge

Connects a Raspberry Pi to an APP relay as a headless device.
Controls GPIO pins, reads CPU temperature, and handles device actions.

DISCLAIMER: This code is provided as-is for reference only.
See the top-level README for the full disclaimer.

Hardware (optional):
  - LED on GPIO 17 (with 330Ω resistor to GND)
  - Button on GPIO 27 (to GND, internal pull-up)
  - DHT22 on GPIO 4 (requires adafruit-circuitpython-dht)

Usage:
  pip install websockets
  python chitin_bridge.py
"""

import asyncio
import json
import os
import time
import uuid
import logging
from pathlib import Path

try:
    import websockets
except ImportError:
    print("Install websockets: pip install websockets")
    exit(1)

# Optional GPIO support — gracefully degrade on non-Pi systems
try:
    import RPi.GPIO as GPIO
    HAS_GPIO = True
except ImportError:
    HAS_GPIO = False
    print("[WARN] RPi.GPIO not available — running in simulation mode")

# Optional DHT sensor
try:
    import adafruit_dht
    import board
    HAS_DHT = True
except ImportError:
    HAS_DHT = False

# ============================================================
# CONFIGURATION
# ============================================================

BRIDGE_TOKEN = os.environ.get("BRIDGE_TOKEN", "YOUR_BRIDGE_TOKEN")
RELAY_URL = os.environ.get("APP_RELAY_URL", "wss://your-relay.example/ws/bridge")

LED_PIN = 17
BUTTON_PIN = 27
DHT_PIN = 4  # board.D4 for adafruit_dht

SENSOR_INTERVAL = 30  # seconds
HEARTBEAT_INTERVAL = 25  # seconds
RECONNECT_INITIAL = 1  # seconds
RECONNECT_MAX = 60  # seconds

# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("chitin-bridge")

# ============================================================
# Hardware abstraction
# ============================================================

led_state = False
dht_sensor = None


def setup_hardware():
    global dht_sensor
    if HAS_GPIO:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(LED_PIN, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        log.info("GPIO initialized (LED=%d, Button=%d)", LED_PIN, BUTTON_PIN)

    if HAS_DHT:
        dht_sensor = adafruit_dht.DHT22(board.D4)
        log.info("DHT22 sensor initialized on GPIO %d", DHT_PIN)


def cleanup_hardware():
    if HAS_GPIO:
        GPIO.cleanup()
    if dht_sensor:
        dht_sensor.exit()


def set_led(state: bool):
    global led_state
    led_state = state
    if HAS_GPIO:
        GPIO.output(LED_PIN, GPIO.HIGH if state else GPIO.LOW)
    log.info("LED set to %s", "ON" if state else "OFF")


def read_button() -> str:
    if HAS_GPIO:
        return "pressed" if GPIO.input(BUTTON_PIN) == GPIO.LOW else "released"
    return "released"


def read_cpu_temp() -> float:
    """Read Raspberry Pi CPU temperature from sysfs."""
    try:
        temp_path = Path("/sys/class/thermal/thermal_zone0/temp")
        if temp_path.exists():
            return int(temp_path.read_text().strip()) / 1000.0
    except Exception:
        pass
    return 0.0


def read_dht() -> dict:
    """Read DHT22 sensor. Returns dict with temperature_c and humidity_pct."""
    if dht_sensor:
        try:
            return {
                "temperature_c": round(dht_sensor.temperature, 1),
                "humidity_pct": round(dht_sensor.humidity, 1),
            }
        except RuntimeError:
            # DHT sensors occasionally fail reads — this is normal
            pass
    return {"temperature_c": None, "humidity_pct": None}


# ============================================================
# Protocol messages
# ============================================================


def build_agent_card() -> dict:
    dht_data = read_dht()
    card = {
        "protocol_version": "0.4",
        "agent": {
            "name": "Raspberry Pi Zero",
            "version": "1.0.0",
            "description": "Raspberry Pi Zero 2 W headless bridge with GPIO, CPU temp, and optional DHT22",
        },
        "device": {
            "type": "single_board_computer",
            "manufacturer": "Raspberry Pi Foundation",
            "model": "Pi Zero 2 W",
            "interaction_model": "headless",
            "status": {
                "led": "on" if led_state else "off",
                "cpu_temp_c": read_cpu_temp(),
                "button": read_button(),
                "temperature_c": dht_data["temperature_c"],
                "humidity_pct": dht_data["humidity_pct"],
                "uptime_s": round(time.monotonic()),
            },
            "available_actions": [
                {
                    "id": "set_led",
                    "name": "Set LED",
                    "description": f"Turn the LED on GPIO {LED_PIN} on, off, or toggle it",
                    "params": [
                        {
                            "name": "state",
                            "type": "string",
                            "required": True,
                            "options": ["on", "off", "toggle"],
                        }
                    ],
                },
                {
                    "id": "blink_led",
                    "name": "Blink LED",
                    "description": "Blink the LED a specified number of times",
                    "params": [
                        {
                            "name": "count",
                            "type": "integer",
                            "required": False,
                            "min": 1,
                            "max": 20,
                        }
                    ],
                },
                {
                    "id": "read_sensors",
                    "name": "Read Sensors",
                    "description": "Read all sensors immediately (CPU temp, DHT22, button state)",
                },
                {
                    "id": "run_command",
                    "name": "Run Command",
                    "description": "Run a safe system command (hostname, uptime, df, free, ip addr)",
                    "params": [
                        {
                            "name": "command",
                            "type": "string",
                            "required": True,
                            "options": ["hostname", "uptime", "df -h", "free -h", "ip addr"],
                        }
                    ],
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
    return {"type": "agent_card", "card": card}


def build_sensor_event(trigger: str = "periodic") -> dict:
    dht_data = read_dht()
    return {
        "type": "sensor_event",
        "id": str(uuid.uuid4()),
        "sensor": "system",
        "value": {
            "cpu_temp_c": read_cpu_temp(),
            "led": "on" if led_state else "off",
            "button": read_button(),
            "temperature_c": dht_data["temperature_c"],
            "humidity_pct": dht_data["humidity_pct"],
            "uptime_s": round(time.monotonic()),
        },
        "trigger": trigger,
        "timestamp": int(time.time() * 1000),
    }


# ============================================================
# Action handlers
# ============================================================


async def handle_action(ws, action: str, params: dict):
    log.info("Action received: %s %s", action, params)

    if action == "set_led":
        state = params.get("state", "toggle")
        if state == "on":
            set_led(True)
        elif state == "off":
            set_led(False)
        elif state == "toggle":
            set_led(not led_state)

    elif action == "blink_led":
        count = min(max(params.get("count", 3), 1), 20)
        for _ in range(count):
            set_led(True)
            await asyncio.sleep(0.2)
            set_led(False)
            await asyncio.sleep(0.2)
        # Restore
        set_led(led_state)

    elif action == "read_sensors":
        pass  # Sensor event sent below

    elif action == "run_command":
        cmd = params.get("command", "")
        allowed = ["hostname", "uptime", "df -h", "free -h", "ip addr"]
        if cmd in allowed:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            log.info("Command output:\n%s", stdout.decode())
        else:
            log.warning("Command not in allow list: %s", cmd)

    else:
        log.warning("Unknown action: %s", action)
        await ws.send(json.dumps({
            "type": "error",
            "code": "unknown_action",
            "message": f"Unknown action: {action}",
        }))
        return

    # Report updated state
    await ws.send(json.dumps(build_sensor_event(trigger="event")))


# ============================================================
# WebSocket connection loop
# ============================================================


async def bridge_loop():
    reconnect_delay = RECONNECT_INITIAL
    url = f"{RELAY_URL}?token={BRIDGE_TOKEN}"

    while True:
        try:
            log.info("Connecting to relay...")
            async with websockets.connect(url, ping_interval=HEARTBEAT_INTERVAL) as ws:
                log.info("Connected to relay")
                reconnect_delay = RECONNECT_INITIAL

                # Send Agent Card
                await ws.send(json.dumps(build_agent_card()))
                log.info("Agent Card sent")

                # Send initial sensor reading
                await ws.send(json.dumps(build_sensor_event()))

                # Run message handler and sensor reporter concurrently
                await asyncio.gather(
                    message_handler(ws),
                    sensor_reporter(ws),
                )

        except websockets.ConnectionClosed as e:
            log.warning("Connection closed: %s", e)
        except Exception as e:
            log.error("Connection error: %s", e)

        log.info("Reconnecting in %ds...", reconnect_delay)
        await asyncio.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 2, RECONNECT_MAX)


async def message_handler(ws):
    async for raw in ws:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue

        msg_type = msg.get("type")

        if msg_type == "device_action":
            await handle_action(
                ws,
                msg.get("action", ""),
                msg.get("parameters", {}),
            )
        else:
            log.debug("Received message type: %s", msg_type)


async def sensor_reporter(ws):
    while True:
        await asyncio.sleep(SENSOR_INTERVAL)
        try:
            await ws.send(json.dumps(build_sensor_event()))
            log.debug("Sensor event sent")
        except Exception:
            break  # Connection lost, outer loop will reconnect


# ============================================================
# Entry point
# ============================================================


def main():
    log.info("=== APP — Raspberry Pi Zero 2 W ===")

    if BRIDGE_TOKEN == "YOUR_BRIDGE_TOKEN":
        log.error("Set BRIDGE_TOKEN environment variable or edit the script")
        return

    setup_hardware()
    try:
        asyncio.run(bridge_loop())
    except KeyboardInterrupt:
        log.info("Shutting down...")
    finally:
        cleanup_hardware()


if __name__ == "__main__":
    main()
