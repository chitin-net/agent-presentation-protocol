# Agent Presentation Protocol (APP) — ESP-32 (Arduino IDE)

Same functionality as the [PlatformIO version](../esp32-platformio/), packaged as a single `.ino` sketch for the Arduino IDE.

> **⚠️ Not tested on physical hardware. See [disclaimer](../README.md).**

## Setup

1. **Add ESP-32 board support** in Arduino IDE:
   - File → Preferences → Additional Board Manager URLs: `https://espressif.github.io/arduino-esp32/package_esp32_index.json`
   - Tools → Board → Board Manager → search "esp32" → Install

2. **Install libraries** via Sketch → Include Library → Manage Libraries:
   - `ArduinoWebsockets` by Gil Maimon
   - `ArduinoJson` by Benoit Blanchon
   - `DHT sensor library` by Adafruit
   - `Adafruit Unified Sensor` by Adafruit

3. **Edit credentials** at the top of the `.ino` file

4. **Select board**: Tools → Board → ESP32 Arduino → ESP32 Dev Module

5. **Upload**: Click the Upload button

See the [PlatformIO README](../esp32-platformio/README.md) for hardware wiring and usage details.

## Protocol notes

Same as the PlatformIO version — see [esp32-platformio/README.md "Protocol notes"](../esp32-platformio/README.md#protocol-notes). In short: `sensor_event.timestamp` is `millis()` (monotonic ms since boot, not wall-clock Unix epoch ms — ESP-32 has no real-time clock by default), and `sensor_event.id` is a 128-bit random hex string formatted UUID-style, with the v4 format-specific bits not enforced.

## License

Apache License 2.0
