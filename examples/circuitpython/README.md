# Agent Presentation Protocol (APP) — CircuitPython (Adafruit ESP32-S3)

A CircuitPython headless bridge for Adafruit ESP32-S3 boards. Controls the onboard NeoPixel with named colors, custom RGB, brightness control, and rainbow effects — all via natural language.

> **⚠️ Not tested on physical hardware. See [disclaimer](../README.md).**

## Compatible Boards

Any Adafruit board running CircuitPython 9+ with WiFi and a NeoPixel:
- Adafruit Feather ESP32-S3
- Adafruit QT Py ESP32-S3
- Adafruit Metro ESP32-S3

## Setup

### 1. Install CircuitPython

Download the `.uf2` file for your board from [circuitpython.org/downloads](https://circuitpython.org/downloads). Double-tap the reset button to enter bootloader mode, then drag the file onto the mounted drive.

### 2. Install libraries

Download the [CircuitPython Library Bundle](https://circuitpython.org/libraries) and copy these to the `lib/` folder on your CIRCUITPY drive:
- `adafruit_requests.mpy`
- `adafruit_connection_manager.mpy`

### 3. Configure

Copy `settings.toml.example` to the CIRCUITPY drive as `settings.toml` and fill in your credentials.

### 4. Deploy

Copy `code.py` to the CIRCUITPY drive. The board will auto-restart and connect.

## Example Commands

- *"Set the light to blue"*
- *"Make it purple"*
- *"Turn off the LED"*
- *"Set brightness to 50%"*
- *"Do a rainbow cycle for 10 seconds"*
- *"Set RGB to 255, 128, 0"* (orange)
- *"What's the CPU temperature?"*

## Protocol notes

- **`sensor_event.timestamp`**: SPEC §4.6 calls for Unix epoch milliseconds. CircuitPython on bare ESP32-S3 has no real-time clock; this example emits `int(time.monotonic() * 1000)` (monotonic milliseconds since boot) and labels it `timestamp`. Downstream consumers needing wall-clock time should stamp it on receipt. To get a real wall clock, add NTP sync at boot (omitted here to keep the example minimal).
- **`sensor_event.id`**: SPEC §4.6 calls for a UUID v4. CircuitPython has no UUID library, so this example emits a 128-bit random hex string formatted UUID-style (`os.urandom(16).hex()` + dashes). The v4 format-specific bits (version nibble, variant bits) are not enforced — the field's purpose is dedup/correlation, not security identification.

## License

Apache License 2.0
