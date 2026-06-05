# Smart Home Ecosystem Integration

The Agent Presentation Protocol (APP) does not replace Matter, Alexa, Google Home, or HomeKit. It sits above them as a **conversational interaction layer** — adding multi-turn conversation, persistent memory, personality, and multi-surface presence to devices that currently only support one-shot voice commands.

## The Gap in Smart Home Interaction

Today's smart home interaction model across every major platform is fundamentally the same:

| Platform | What you can say | What you can't say |
|----------|-----------------|-------------------|
| Alexa | "Turn off the lights" | "I'm going to bed" (and have it know your routine) |
| Google Home | "What's the temperature?" | "How's the house?" (aggregated across all devices) |
| HomeKit | "Lock the front door" | "Don't water the garden tomorrow, it's going to rain" |
| All | One-shot commands | Multi-turn conversations about your home with memory |

Every platform excels at **command-and-control**: short imperative statements that map to a single device action. None provides **conversational interaction**: multi-turn dialogue with memory, context, personality, and aggregate intelligence across devices.

This is the layer APP fills.

## What APP Adds

### Conversational Depth

"I'm going to bed" is not a single command. With APP, the relay intelligence interprets it as a personalized sequence based on the user's soul file:

- Lock all doors (user preference: always lock at night)
- Set thermostat to 68°F (user preference: sleep temperature)
- Turn off downstairs lights (user preference: keep hallway nightlight)
- Arm the alarm system (user preference: home mode at night)
- Tell the robot vacuum to start the bedroom (user preference: runs after going to bed)

These preferences are learned over time through conversation and stored in the soul file. The user said "I'm going to bed" once; the relay remembers what that means to this specific user.

### Cross-Device Memory

Alexa doesn't remember that you told the robot vacuum to skip the kitchen last Tuesday because you were having the floors redone. The soul file does. The relay intelligence uses accumulated context:

- "Skip the kitchen" → stores in soul file: `floor work in kitchen, started March 25`
- Next week: "Is the kitchen floor done?" → relay checks soul file, asks the user
- User: "Yeah, finished yesterday" → removes the note, resumes normal cleaning

No smart home platform maintains this kind of conversational state across devices and time.

### Aggregate Intelligence

"Is the house secure?" requires checking locks, garage door, windows, cameras, and alarm status — then synthesizing a single conversational response. Every smart home platform can check these individually. None synthesizes them conversationally:

> "[happy] Everything looks good. All doors are locked, garage is closed, alarm is armed in home mode. The only thing — the back patio door was unlocked, so I just locked it for you. Cameras are all online, no recent alerts."

This requires the relay intelligence to see all devices simultaneously and compose a natural language response — something that falls out naturally from the headless device model when all home devices are connected through the bridge.

### Multi-Surface Presence

Your home's status follows you across surfaces:

- **Kitchen kiosk:** Full dashboard with all device status, camera feeds, energy report
- **Phone (at work):** Notifications for threshold events (door unlocked, water leak, motion alert)
- **CarPlay (driving home):** "Hey, warm up the house, I'll be there in 20 minutes"
- **Desktop (home office):** Ambient status in menu bar, conversational access in companion window

Same agent, same memory, same personality, different surfaces adapted to context.

## The Bridge Architecture

### How Devices Connect

An APP smart home bridge reads devices from an existing controller and exposes them as headless APP endpoints:

```
┌─────────────────────────────────────────────┐
│            Your Existing Smart Home          │
│                                              │
│  Matter │ Zigbee │ Z-Wave │ Wi-Fi │ BLE     │
│  lights   locks   sensors  cameras  plugs   │
│    │        │        │        │       │      │
│    └────────┴────────┴────────┴───────┘      │
│                      │                        │
│              Home Assistant                   │
│              (aggregates all protocols)       │
└──────────────────────┬────────────────────────┘
                       │
                       │  REST API / WebSocket
                       ▼
              ┌─────────────────┐
              │  APP Smart Home │
              │  Bridge         │
              │  (any conforming│
              │   adapter)      │
              └────────┬────────┘
                       │
                       │  APP (WSS)
                       ▼
              ┌─────────────────┐
              │  APP Relay      │
              │                 │
              │ Relay Intel-    │
              │ ligence Layer   │
              │ + Soul File     │
              └────────┬────────┘
                       │
            ┌──────────┼──────────┐
            ▼          ▼          ▼
         Phone      Kiosk    In-vehicle
        surface    surface    surface
```

### Home Assistant as First Target

Home Assistant is the natural first integration target:

- **2,000+ integrations** covering virtually every smart home device
- **Documented REST API** and WebSocket API for real-time state
- **Power user community** that overlaps heavily with APP's early adopter audience
- **Local-first architecture** — no cloud dependency, aligns with privacy positioning
- **Add-on ecosystem** — an APP bridge could be distributed as a Home Assistant add-on

### Bridge Implementation

The bridge adapter reads the Home Assistant state and generates Agent Cards:

```python
import asyncio
import json
import os
import websockets
import homeassistant_api as ha

# Connect to Home Assistant
ha_client = ha.Client(
    url="http://homeassistant.local:8123",
    token=os.environ["HA_TOKEN"]
)

# Generate an aggregate Agent Card for the whole home
devices = ha_client.get_states()
available_actions = []
sensors = []

for device in devices:
    if device.domain == "light":
        available_actions.append({
            "id": f"light_{device.entity_id}",
            "name": f"Toggle {device.attributes.get('friendly_name', device.entity_id)}",
            "params": [
                {"name": "state", "type": "string", "options": ["on", "off"]},
                {"name": "brightness", "type": "integer"}
            ]
        })
    elif device.domain == "lock":
        available_actions.append({
            "id": f"lock_{device.entity_id}",
            "name": f"Lock/unlock {device.attributes.get('friendly_name')}",
            "params": [
                {"name": "state", "type": "string", "options": ["lock", "unlock"]}
            ],
            "safety": {"requires_confirmation": True}  # Locks need confirmation
        })
    elif device.domain == "climate":
        available_actions.append({
            "id": f"climate_{device.entity_id}",
            "name": f"Set {device.attributes.get('friendly_name')} temperature",
            "params": [
                {"name": "temperature", "type": "number"},
                {"name": "mode", "type": "string", "options": ["heat", "cool", "auto", "off"]}
            ]
        })
    # ... more device domains

    # Add sensors for devices with state we want to report
    sensors.append(device.entity_id)

# Agent Card (SPEC §5)
AGENT_CARD = {
    "protocol_version": "0.4",
    "agent": {
        "name": "Home",
        "description": f"Smart home ({len(devices)} devices)",
        "version": "1.0.0"
    },
    "device": {
        "type": "hub",
        "interaction_model": "headless",
        "status": {},
        "available_actions": available_actions
    },
    "capabilities": {
        "streaming": False,
        "emotions": [],
        "memory": {"read": True, "write": True},
        "sensor_events": sensors
    }
}

# Handle device_action commands from relay intelligence (SPEC §4.7)
def handle_action(action):
    entity_id = action["action"].split("_", 1)[1]  # "light_living_room" → "living_room"
    domain = action["action"].split("_")[0]
    params = action.get("parameters", {})

    if domain == "light":
        ha_client.call_service(
            "light", "turn_on" if params["state"] == "on" else "turn_off",
            entity_id=entity_id,
            brightness=params.get("brightness")
        )
    elif domain == "lock":
        ha_client.call_service("lock", params["state"], entity_id=entity_id)
    elif domain == "climate":
        ha_client.call_service(
            "climate", "set_temperature",
            entity_id=entity_id,
            temperature=params["temperature"]
        )


async def main():
    url = f"wss://your-relay.example/ws/bridge?token={os.environ['BRIDGE_TOKEN']}"
    async with websockets.connect(url) as ws:
        # Card Exchange: the Agent Card is the first message sent (SPEC §3.3)
        await ws.send(json.dumps({"type": "agent_card", "card": AGENT_CARD}))

        async def sync_state():
            while True:
                states = ha_client.get_states()
                # Update device.status and resend the card (SPEC §6.1)
                AGENT_CARD["device"]["status"] = {
                    s.entity_id: {
                        "state": s.state,
                        "name": s.attributes.get("friendly_name"),
                        "last_changed": s.last_changed,
                    }
                    for s in states
                }
                await ws.send(json.dumps({"type": "agent_card", "card": AGENT_CARD}))
                await asyncio.sleep(30)

        async def dispatch():
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") == "device_action":
                    handle_action(msg)

        await asyncio.gather(sync_state(), dispatch())


# Happy-path connection only. For production heartbeat + reconnection,
# see examples/raspberry-pi-zero — it shows a full reconnect loop.
asyncio.run(main())
```

## What APP is NOT

To be explicit about boundaries:

**Not a device control protocol.** APP does not compete with Matter, Zigbee, Z-Wave, or Thread. It does not define how devices communicate on the local network. It does not handle device commissioning, mesh networking, or radio-layer concerns.

**Not a smart home controller.** APP does not replace Home Assistant, Alexa, Google Home, or HomeKit. It does not manage device groups, rooms, or automation rules. It bridges to these systems and adds a conversational layer.

**Not a voice assistant replacement.** Alexa and Google Assistant handle billions of short commands per day. APP is not optimized for one-shot commands — it's optimized for conversation, memory, personality, and multi-surface presence. They serve different interaction patterns.

**The positioning is composability:** keep Matter for device connectivity, keep Home Assistant or Alexa for device control and automation, add APP for the conversational interaction layer.

## Other Controller Integrations

The bridge architecture is not limited to Home Assistant. Any smart home controller with an API can be bridged to APP using the same adapter pattern. The headless device model and relay intelligence layer work identically regardless of which controller provides the underlying device data.

## See Also

- [SPEC.md](../SPEC.md) — Section 11.5 (Smart Home Ecosystem Integration)
- [Architecture](./architecture.md) — System overview
- [Physical Devices](./physical-devices.md) — Headless device integration (which smart home devices are)
- [Headless example](../examples/headless/) — Adapter code patterns applicable to smart home devices
