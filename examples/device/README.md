# Device Projection

Project a device's onboard agent to any conforming APP surface. The device runs the agent; APP surfaces render the conversation.

## How It Works

```
Device with Onboard AI (electric vehicle, robot, smart hub)
  │
  │  APP SDK (runs on device or companion computer)
  ▼
APP Relay (any conforming relay)
  │
  ▼
APP Surfaces (phone, kiosk, in-vehicle, desktop)
```

The device connects to the relay as an agent. It publishes an Agent Card with device metadata (type, model, status, available actions). APP surfaces render the device's output with a conversational interface, status indicators, and actionable buttons.

## Quick Start: Electric Vehicle Projection

This example shows an electric vehicle projecting to the owner's phone via the vehicle's cloud API.

### Install

```bash
npm install ws
```

### Run

APP is a WebSocket protocol — the device connects to the relay, sends its
Agent Card, and exchanges JSON messages. This example uses the `ws`
package directly so the wire format is fully visible.

```javascript
const WebSocket = require('ws');

// --- Agent Card (SPEC §5) — declares device metadata + actions ---------
const AGENT_CARD = {
  protocol_version: '0.4',
  agent: {
    name: 'Electric Vehicle',
    description: "Owner's electric vehicle",
    version: '2026.8.1'
  },
  device: {
    type: 'vehicle',
    manufacturer: 'Acme Motors',
    model: 'EV Sedan 2024',
    interaction_model: 'standard',
    status: {},         // Updated dynamically below
    available_actions: [
      { id: 'climate_start', name: 'Start climate', params: [] },
      { id: 'climate_stop', name: 'Stop climate', params: [] },
      { id: 'lock', name: 'Lock doors', params: [] },
      { id: 'unlock', name: 'Unlock doors', params: [] },
      { id: 'flash_lights', name: 'Flash lights', params: [] },
      { id: 'honk', name: 'Honk horn', params: [] },
      { id: 'open_frunk', name: 'Open frunk', params: [] },
      { id: 'open_trunk', name: 'Open trunk', params: [] },
      { id: 'summon', name: 'Summon vehicle', params: [
        { name: 'direction', type: 'string', options: ['forward', 'reverse'] }
      ]},
      { id: 'navigate_to', name: 'Set navigation', params: [
        { name: 'destination', type: 'string' }
      ]}
    ]
  },
  capabilities: {
    streaming: true,
    emotions: ['neutral', 'alert', 'ready'],
    memory: { read: true, write: false },
    sensor_events: ['location', 'battery', 'security_alert', 'charge_complete']
  },
  initiation_profile: {
    expected_warrants: ['external_event', 'user_authorized'],
    expected_volume_per_day: '0-5',
    typical_urgency: 'medium',
    requires_response_typical: false
  }
};

// --- Connect to the relay ----------------------------------------------
const ws = new WebSocket(
  `wss://your-relay.example/ws/bridge?token=${process.env.BRIDGE_TOKEN}`
);

ws.on('open', () => {
  // Card Exchange: the Agent Card is the first message sent (SPEC §3.3).
  ws.send(JSON.stringify({ type: 'agent_card', card: AGENT_CARD }));
});

ws.on('message', (raw) => {
  const message = JSON.parse(raw);
  if (message.type === 'chat_message') handleChatMessage(message);
});

// Happy-path connection only. For production heartbeat + reconnection,
// see examples/raspberry-pi-zero — it shows a full reconnect loop.

// --- Send a sensor_event (SPEC §4.6) -----------------------------------
function sendSensorEvent(sensor, value, trigger) {
  ws.send(JSON.stringify({
    type: 'sensor_event',
    id: crypto.randomUUID(),
    sensor,
    value,
    trigger,
    timestamp: Date.now()
  }));
}

// Periodically fetch vehicle state and send sensor events
setInterval(async () => {
  const state = await vehicleAPI.getVehicleState();

  sendSensorEvent('battery', {
    percent: state.battery_level,
    charging: state.charging_state === 'Charging',
    range_miles: state.battery_range
  }, 'periodic');

  sendSensorEvent('location', {
    lat: state.drive_state.latitude,
    lng: state.drive_state.longitude
  }, 'periodic');
}, 60000); // Every 60 seconds

// --- Handle a chat message ---------------------------------------------
// The device has onboard AI (interaction_model: standard).
async function handleChatMessage(message) {
  const state = await vehicleAPI.getVehicleState();

  // Use an LLM to interpret the request with vehicle context
  const response = await callLLM({
    system: `You are the voice of an electric vehicle. Current state:
Battery: ${state.battery_level}%, ${state.charging_state}
Location: ${state.drive_state.latitude}, ${state.drive_state.longitude}
Cabin temp: ${state.climate_state.inside_temp}°F
Security mode: ${state.vehicle_state.security_mode ? 'ON' : 'OFF'}

Available commands: climate_start, climate_stop, lock, unlock, flash_lights, 
honk, open_frunk, open_trunk, summon (forward/reverse), navigate_to (destination).

When the user asks you to do something, respond conversationally AND execute 
the command. Use emotion tags: [ready] for confirmations, [alert] for warnings.`,
    messages: message.messages
  });

  // Execute any commands the LLM identified
  if (response.commands) {
    for (const cmd of response.commands) {
      await vehicleAPI.executeCommand(cmd.id, cmd.params);
    }
  }

  // chat_stream_end carries the final response (SPEC §4.2)
  ws.send(JSON.stringify({
    type: 'chat_stream_end',
    reply_to: message.id,
    content: response.text,
    timestamp: Date.now()
  }));
}
```

## Quick Start: Smart Home Hub

A Raspberry Pi running a home agent that projects to all screens:

```javascript
const AGENT_CARD = {
  protocol_version: '0.4',
  agent: {
    name: 'Home',
    description: 'Smart home agent',
    version: '1.0.0'
  },
  device: {
    type: 'hub',
    interaction_model: 'standard',
    status: {
      devices_online: 23,
      alerts: [],
      mode: 'home'
    },
    available_actions: [
      { id: 'set_mode', name: 'Set home mode', params: [
        { name: 'mode', type: 'string', options: ['home', 'away', 'sleep', 'vacation'] }
      ]},
      { id: 'lock_all', name: 'Lock all doors', params: [] },
      { id: 'lights_off', name: 'Turn off all lights', params: [] }
    ]
  },
  capabilities: {
    streaming: true,
    emotions: ['neutral', 'happy', 'alert'],
    memory: { read: true, write: true },
    sensor_events: ['security_alert', 'device_offline', 'energy_report']
  },
  initiation_profile: {
    expected_warrants: ['external_event', 'user_authorized'],
    expected_volume_per_day: '0-5',
    typical_urgency: 'medium',
    requires_response_typical: false
  }
};

// ...connect and dispatch chat_message as in the vehicle example...

// The hub's LLM has access to all home device states
async function handleChatMessage(message) {
  const homeState = await homeAssistant.getFullState();
  // ... LLM generates `response` with full home context
  ws.send(JSON.stringify({
    type: 'chat_stream_end',
    reply_to: message.id,
    content: response,
    timestamp: Date.now()
  }));
}
```

## Sensor Events

Devices should send sensor events proactively so surfaces can display real-time status:

```javascript
// Uses the sendSensorEvent helper defined in the vehicle example above.

// Threshold event — something needs attention
sendSensorEvent('security_alert', {
  type: 'motion_detected',
  camera: 'front',
  thumbnail_url: 'https://...',
  time: Date.now()
}, 'event');

// Periodic — routine status updates
sendSensorEvent('battery', { percent: 72 }, 'periodic');

// Threshold — value crossed a boundary
sendSensorEvent('battery', { percent: 19, low: true }, 'threshold');
```

## Cross-Surface Continuity

A conversation that starts on one surface continues seamlessly on another. The relay persists the session; memory is stored in the soul file. The user talks to their car on their phone while walking to the garage, then the conversation continues on the car's screen when they get in.

No special code is needed for this — the relay handles session routing automatically based on the user's connected surfaces.

## See Also

- [Main README](../../README.md) — Protocol overview
- [SPEC.md](../../SPEC.md) — Full specification, especially Section 11.3 (Device Projection)
- [Headless example](../headless/) — For devices without onboard AI
