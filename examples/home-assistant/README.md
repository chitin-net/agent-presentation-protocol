# Agent Presentation Protocol (APP) — Home Assistant Bridge

Bridges your Home Assistant instance to APP, giving you natural language control of your smart home through any conforming APP surface (phone, desktop, in-vehicle, kiosk). Point it at any conforming APP relay — set `APP_RELAY_URL` (defaults to the `wss://your-relay.example/ws/bridge` placeholder).

> **⚠️ Not tested against a live Home Assistant instance. See [disclaimer](../README.md).**

## How It Works

This bridge connects to both your Home Assistant REST API and an APP relay simultaneously. On startup, it:

1. Fetches all entity states from Home Assistant
2. Filters to exposed domains (lights, switches, climate, locks, covers, fans, scenes, media players, vacuums)
3. Builds an Agent Card with actions derived from your actual entities
4. Sends the card to the relay, which teaches the intelligence layer what your home can do

When you say something like *"Turn off the living room lights"* to a paired APP surface, the relay matches it to the `light_turn_off` action with the correct entity, sends a `device_action` to this bridge, and the bridge calls the HA service API.

## Prerequisites

- Home Assistant instance (any installation method)
- Long-Lived Access Token from HA (Profile → Security → Long-Lived Access Tokens → Create Token)
- Bridge pairing token (from your relay's pairing flow)
- Python 3.9+

## Setup

```bash
mkdir ~/chitin-bridge && cd ~/chitin-bridge
# Copy chitin_ha_bridge.py and requirements.txt here

pip install -r requirements.txt

export BRIDGE_TOKEN="your_token"
export HA_URL="http://homeassistant.local:8123"
export HA_TOKEN="your_ha_long_lived_access_token"

python chitin_ha_bridge.py
```

### Auto-start with systemd

```bash
sudo cp chitin-ha-bridge.service /etc/systemd/system/
# Edit the service file: set your tokens and HA_URL
sudo systemctl daemon-reload
sudo systemctl enable chitin-ha-bridge
sudo systemctl start chitin-ha-bridge
```

## Supported Domains

| Domain | Actions | Example Commands |
|--------|---------|-----------------|
| `light` | Turn on (with brightness), turn off | *"Turn on the kitchen lights at 50%"* |
| `switch` | On, off, toggle | *"Toggle the office fan switch"* |
| `climate` | Set temperature, set mode | *"Set the thermostat to 72"*, *"Turn on the AC"* |
| `lock` | Lock, unlock | *"Lock the front door"* |
| `cover` | Open, close, stop | *"Close the garage door"*, *"Open the blinds"* |
| `fan` | On, off | *"Turn on the bedroom fan"* |
| `scene` | Activate | *"Activate movie night"* |
| `media_player` | Play, pause, stop, next, previous, volume | *"Pause the living room TV"* |
| `vacuum` | Start, stop, return to base, locate | *"Start the vacuum"*, *"Send the vacuum home"* |

## Configuration

### Controlling which entities are exposed

Edit `EXPOSED_DOMAINS` in the script to add or remove domains. The bridge exposes up to 40 entities by default (`MAX_ENTITIES`) — a conservative cap for headless intelligence prompt size; tune to your target relay's capacity.

### Entity name matching

The bridge resolves entities by their Home Assistant **friendly name** (as shown in the HA UI). The relay's intelligence layer matches user speech to the closest entity name in the Agent Card's action options. If you have entities with similar names, consider renaming them in HA to be more distinct.

## Architecture

```
APP Surface ──→ APP Relay ──→ Relay Intelligence Layer
                                  ↓
                          device_action { action: "light_turn_on",
                                          parameters: { entity_name: "Kitchen Lights" } }
                                  ↓
                     This Bridge (chitin_ha_bridge.py)
                                  ↓
                     HA REST API: POST /api/services/light/turn_on
                                  { entity_id: "light.kitchen_lights" }
```

## Limitations

- Entity states are polled every 60 seconds. Real-time state push (via HA WebSocket API) is not yet implemented.
- The bridge does not support HA automations or scripts with complex inputs.
- Color control for lights is not yet implemented (brightness only).
- Media player volume is relative (up/down) not absolute.
- Reactive bridge; no agent-side initiation. No `initiation_profile` declared (SPEC §13).

## License

Apache License 2.0
