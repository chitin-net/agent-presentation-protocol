# Agent Presentation Protocol (APP) — Arduino UNO R4 WiFi

A headless bridge for the Arduino UNO R4 WiFi. Controls the built-in LED, reads an analog sensor, and supports PWM output — all controllable via natural language from any APP surface.

> **⚠️ Not tested on physical hardware. See [disclaimer](../README.md).**

## Hardware

- **Arduino UNO R4 WiFi** (built-in WiFi via ESP32-S3 coprocessor)
- Optional: potentiometer or photoresistor on A0, external LED on pin 9, button on pin 7

## Setup

1. **Install UNO R4 board package**: Tools → Board → Board Manager → search "Arduino UNO R4" → Install
2. **Install libraries** via Library Manager: `ArduinoWebsockets`, `ArduinoJson`
3. **Edit credentials** in the `.ino` file
4. **Upload**

## Notes

- The UNO R4 WiFi uses the `WiFiS3` library (not the ESP-32 WiFi library)
- The 12×8 LED matrix is supported but commented out by default — uncomment the `Arduino_LED_Matrix` includes to use it
- RAM is more constrained than ESP-32 — keep Agent Cards concise if you run into memory issues

## Protocol notes

- **`sensor_event.timestamp`**: SPEC §4.6 calls for Unix epoch milliseconds. The UNO R4 has no real-time clock; this example emits `millis()` (monotonic milliseconds since boot) and labels it `timestamp`. Downstream consumers needing wall-clock time should stamp it on receipt.
- **`sensor_event.id`**: SPEC §4.6 calls for a UUID v4. The Renesas RA4M1 has no `esp_random()`-style hardware RNG exposed in the standard Arduino API, so this example uses Arduino's `random()` (PRNG) seeded from analog noise on the sensor pin in `setup()`. The id is a 128-bit hex string formatted UUID-style; v4 format-specific bits are not enforced — the field's purpose is dedup/correlation, not security identification.

## License

Apache License 2.0
