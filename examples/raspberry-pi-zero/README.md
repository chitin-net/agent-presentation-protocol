# Agent Presentation Protocol (APP) — Raspberry Pi Zero 2 W

A Python headless bridge for the Raspberry Pi. Controls GPIO, reads CPU temperature and optional DHT22 sensor, and can run safe system commands — all via natural language from any APP surface.

> **⚠️ Not tested on physical hardware. See [disclaimer](../README.md).**

## Requirements

- Raspberry Pi Zero 2 W (or any Pi with WiFi)
- Raspberry Pi OS (Bullseye or Bookworm)
- Python 3.9+

## Setup

```bash
# Clone or copy files to Pi
mkdir ~/chitin-bridge && cd ~/chitin-bridge
# Copy chitin_bridge.py, requirements.txt, chitin-bridge.service here

# Install dependencies
pip install -r requirements.txt

# Set your bridge pairing token
export BRIDGE_TOKEN="your_token_here"

# Run
python3 chitin_bridge.py
```

### Auto-start with systemd

```bash
# Edit the service file — set your token in the Environment line
sudo cp chitin-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable chitin-bridge
sudo systemctl start chitin-bridge

# Check status
sudo systemctl status chitin-bridge
journalctl -u chitin-bridge -f
```

## Hardware (optional)

| Component | GPIO | Notes |
|-----------|------|-------|
| LED | GPIO 17 | 330Ω resistor to GND |
| Button | GPIO 27 | To GND; internal pull-up enabled |
| DHT22 | GPIO 4 | Install `adafruit-circuitpython-dht` |

The bridge works without any external hardware — it will still report CPU temperature and handle system info commands.

## Available Actions

| Action | Description |
|--------|-------------|
| `set_led` | Turn GPIO LED on/off/toggle |
| `blink_led` | Blink the LED N times |
| `read_sensors` | Immediate sensor reading |
| `run_command` | Run a safe system command (hostname, uptime, df, free, ip addr) |

### Example voice commands

- *"What's the Pi's CPU temperature?"*
- *"Turn on the light"*
- *"How much disk space is left?"*
- *"What's the Pi's IP address?"*

## Simulation Mode

If `RPi.GPIO` is not available (e.g., running on a Mac/PC for development), the bridge runs in simulation mode — all GPIO operations are logged but no actual hardware is touched.

## License

Apache License 2.0
