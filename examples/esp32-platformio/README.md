# Agent Presentation Protocol (APP) — ESP-32 (PlatformIO)

A complete PlatformIO project that connects an ESP-32 to an APP relay as a headless sensor hub. Users can control the LED, read temperature/humidity, and monitor device status by speaking naturally to any conforming APP surface.

> **⚠️ This example has not been tested on physical hardware and is provided as-is. See the [parent README](../README.md) for the full disclaimer.**

## Hardware

| Component | Pin | Notes |
|-----------|-----|-------|
| Built-in LED | GPIO 2 | Most ESP-32 DevKit boards have one here |
| DHT22 sensor | GPIO 4 | 10kΩ pull-up resistor between DATA and VCC |
| Push button | GPIO 15 | Connected to GND; uses internal pull-up |

### Wiring Diagram (text)

```
ESP-32 DevKit
┌─────────────┐
│         3V3 ├──── DHT22 VCC (pin 1)
│         GND ├──── DHT22 GND (pin 4) ──── Button (one leg)
│        GP4  ├──── DHT22 DATA (pin 2)  [10kΩ pull-up to 3V3]
│        GP2  ├──── (built-in LED, no wiring needed)
│       GP15  ├──── Button (other leg)
└─────────────┘
```

## Setup

### 1. Install PlatformIO

Follow the instructions at [platformio.org/install](https://platformio.org/install). The VS Code extension is recommended.

### 2. Configure credentials

Edit `src/main.cpp` and set:

```cpp
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* BRIDGE_TOKEN  = "YOUR_BRIDGE_TOKEN";
```

### 3. Build and flash

```bash
# Build
pio run

# Upload to board
pio run --target upload

# Open serial monitor
pio device monitor --baud 115200
```

## What It Does

Once running, the ESP-32:

1. Connects to WiFi and opens a WebSocket to a conforming APP relay
2. Sends an **Agent Card** declaring four available actions: `set_led`, `set_led_brightness`, `blink_led`, `read_sensors`
3. Reports **sensor events** every 30 seconds (temperature, humidity, LED state, WiFi signal strength)
4. Handles **device_action** messages from the relay, which are triggered when a user speaks to any conforming APP surface

### Example voice commands (from any conforming surface — Chitin Phone and Avatar are reference implementations)

- *"Turn on the LED"* → `set_led { state: "on" }`
- *"Set brightness to 50%"* → `set_led_brightness { level: 128 }`
- *"Blink the light 5 times"* → `blink_led { count: 5 }`
- *"What's the temperature?"* → `read_sensors {}`
- *"How's the sensor hub doing?"* → Returns status from last sensor event

## Adapting for Your Project

This example is a starting point. To adapt it:

- **Add actions**: Follow the pattern in `buildAgentCard()` to declare new actions with typed parameters. The relay intelligence layer will automatically learn to dispatch them.
- **Add sensors**: Add new fields to the `buildSensorEvent()` value object (SPEC §4.6 `sensor_event.value`). The relay will include them in its context for natural language understanding.
- **Remove the DHT22**: If you don't have a DHT22, remove the `#include <DHT.h>`, the `dht` object, and the temperature/humidity references. The rest of the example still works with just the built-in LED and button.
- **Multiple devices**: Each device needs its own bridge pairing token. Pair each one separately through the surface paired to your relay.

## Troubleshooting

- **Can't connect to WiFi**: Verify SSID/password. ESP-32 only supports 2.4GHz networks.
- **WebSocket fails to connect**: Check that your bridge pairing token is valid. Tokens are long-lived but can be revoked.
- **DHT22 reads NaN**: Check wiring and the 10kΩ pull-up resistor. The DHT22 needs 1-2 seconds between reads.
- **Frequent disconnects**: The relay expects a ping every 30 seconds. The code sends one every 25 seconds with margin. If your loop is blocked (e.g., by `delay()` in blink), pings may be missed.

## Protocol notes

- **`sensor_event.timestamp`**: SPEC §4.6 calls for Unix epoch milliseconds. The ESP-32 DevKit has no real-time clock by default; this example emits `millis()` (monotonic milliseconds since boot) and labels it `timestamp`. Downstream consumers needing wall-clock time should stamp it on receipt. To get a real wall clock, configure `configTime()` with NTP at boot (omitted here to keep the example minimal).
- **`sensor_event.id`**: SPEC §4.6 calls for a UUID v4. Arduino-ESP32 has no UUID library, so this example emits a 128-bit random hex string formatted UUID-style (`esp_random()` × 4 + dashes). The v4 format-specific bits (version nibble, variant bits) are not enforced — the field's purpose is dedup/correlation, not security identification.

## License

Apache License 2.0 — see [LICENSE](../../LICENSE).
