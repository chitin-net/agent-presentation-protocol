# Agent Presentation Protocol (APP) — Raspberry Pi Pico W (MicroPython)

A MicroPython headless bridge for the Raspberry Pi Pico W. Uses the built-in WiFi, onboard LED, and internal temperature sensor — no external components required.

> **⚠️ Not tested on physical hardware. See [disclaimer](../README.md).**

## Requirements

- Raspberry Pi Pico W
- MicroPython firmware v1.22+ ([download](https://micropython.org/download/RPI_PICO_W/))
- [Thonny IDE](https://thonny.org/) or `mpremote` for file transfer

## Setup

### 1. Flash MicroPython firmware

Hold the BOOTSEL button while plugging in the Pico W via USB. It mounts as a drive — drag the `.uf2` firmware file onto it.

### 2. Edit configuration

Open `main.py` and set your WiFi credentials and bridge pairing token at the top.

### 3. Deploy

Using Thonny:
- Open `main.py` in Thonny
- Save As → MicroPython device → `main.py`

Using mpremote:
```bash
mpremote cp main.py :main.py
mpremote reset
```

The Pico W will auto-run `main.py` on every boot.

## Notes

- **WebSocket client**: MicroPython doesn't include a WebSocket library, so this example includes a minimal implementation (`SimpleWebSocket` class). It handles text frames, ping/pong, and reconnection. For production use, consider the `micropython-uwebsockets` library.
- **Memory**: The Pico W has 264KB RAM. The code uses `gc.collect()` before sensor reports to keep memory usage stable. If you add many actions or large Agent Cards, watch `free_mem` in the sensor events.
- **TLS**: The Pico W's `ussl` module has limited certificate validation. This example connects via TLS but does not verify the server certificate. This is acceptable for development but not for production deployments handling sensitive data.

## Protocol notes

- **`sensor_event.timestamp`**: SPEC §4.6 calls for Unix epoch milliseconds. The Pico W has no real-time clock; this example emits `time.ticks_ms()` (monotonic milliseconds since boot) and labels it `timestamp`. Downstream consumers that need wall-clock time should stamp it on receipt. To get a real wall clock, add NTP sync at boot (omitted here to keep the example minimal).
- **`sensor_event.id`**: SPEC §4.6 calls for a UUID v4. MicroPython has no UUID library, so this example emits a 128-bit random hex string formatted UUID-style (`uos.urandom(16)` + dashes). The v4 format-specific bits (version nibble, variant bits) are not enforced — the field's purpose is dedup/correlation, not security identification.

## License

Apache License 2.0
