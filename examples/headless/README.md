# Headless Device

Give a robot, combine harvester, CNC machine, edge device or any screenless machine a conversational interface — without adding a screen, a speaker, or any AI to the device.

## How It Works

```
Machine (no screen, no AI)
  ▲
  │  Native API (HTTP, MQTT, serial, etc.)
  │
Thin Adapter (this script)
  │
  │  WSS → APP Relay (any conforming relay)
  │              │
  │              │  Relay intelligence maps natural
  │              │  language → device_action commands
  │              ▼
  │        APP Surfaces (phone, kiosk, in-vehicle)
  │
  │  device_action commands (structured JSON)
  ▼
Machine executes command
```

The machine never sees natural language. The thin adapter publishes the machine's state and available actions. The relay-side intelligence layer handles interpretation. The user talks; the machine acts.

## Quick Start: Robot Vacuum

### Install

```bash
npm install ws
```

### The Adapter

APP is a WebSocket protocol — the adapter connects to the relay, sends an
Agent Card, and exchanges JSON messages. This example uses the `ws`
package directly so the wire format is fully visible.

```javascript
const WebSocket = require('ws');

const VACUUM_API = 'http://192.168.1.42'; // Your robot vacuum's local API

// --- Agent Card (SPEC §5) — headless device, no onboard AI -------------
const AGENT_CARD = {
  protocol_version: '0.4',
  agent: {
    name: 'Robot Vacuum',
    description: 'Living room robot vacuum',
    version: '4.2.1'
  },
  device: {
    type: 'appliance',
    manufacturer: 'Acme Robotics',
    model: 'RV-200',
    interaction_model: 'headless',
    status: {},
    available_actions: [
      { id: 'start', name: 'Start cleaning', params: [] },
      { id: 'stop', name: 'Stop and stay', params: [] },
      { id: 'dock', name: 'Return to dock', params: [] },
      { id: 'clean_room', name: 'Clean specific room', params: [
        { name: 'room', type: 'string',
          options: ['living_room', 'kitchen', 'master_bedroom', 'hallway', 'office'] }
      ]},
      { id: 'exclude_zone', name: 'Skip a room for this run', params: [
        { name: 'room', type: 'string' }
      ]}
    ]
  },
  capabilities: {
    streaming: false,
    emotions: [],
    memory: { read: false, write: false },
    sensor_events: ['state_change', 'error', 'zone_complete', 'bin_full']
  }
};

// --- Connect to the relay ----------------------------------------------
const ws = new WebSocket(
  `wss://your-relay.example/ws/bridge?token=${process.env.BRIDGE_TOKEN}`
);

ws.on('open', () => {
  // Card Exchange: the Agent Card is the first message sent (SPEC §3.3).
  ws.send(JSON.stringify({ type: 'agent_card', card: AGENT_CARD }));
  console.log('Vacuum adapter connected to relay');
});

ws.on('message', (raw) => {
  const message = JSON.parse(raw);
  // The relay maps natural language to structured device_action commands
  if (message.type === 'device_action') handleDeviceAction(message);
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

// Send status updates every 30 seconds
setInterval(async () => {
  const state = await fetch(`${VACUUM_API}/state`).then(r => r.json());

  // Update the Agent Card's device.status and resend the card (SPEC §6.1).
  // Surfaces display this status.
  AGENT_CARD.device.status = {
    battery_percent: state.battery,
    state: state.cleaning ? 'cleaning' : 'idle',
    current_zone: state.currentRoom,
    bin_full: state.binFull,
    zones_completed: state.completedRooms,
    zones_remaining: state.remainingRooms
  };
  ws.send(JSON.stringify({ type: 'agent_card', card: AGENT_CARD }));

  // Send sensor events for thresholds
  if (state.binFull) {
    sendSensorEvent('bin_full', { full: true }, 'threshold');
  }
}, 30000);

// --- Handle device_action commands from relay intelligence (SPEC §4.7) -
async function handleDeviceAction(action) {
  console.log(`Executing: ${action.action}`, action.parameters);

  switch (action.action) {
    case 'start':
      await fetch(`${VACUUM_API}/start`, { method: 'POST' });
      break;
    case 'stop':
      await fetch(`${VACUUM_API}/stop`, { method: 'POST' });
      break;
    case 'dock':
      await fetch(`${VACUUM_API}/dock`, { method: 'POST' });
      break;
    case 'clean_room':
      await fetch(`${VACUUM_API}/clean`, {
        method: 'POST',
        body: JSON.stringify({ room: action.parameters.room })
      });
      break;
    case 'exclude_zone':
      await fetch(`${VACUUM_API}/exclude`, {
        method: 'POST',
        body: JSON.stringify({ room: action.parameters.room })
      });
      break;
  }
}
```

### What happens when the user talks

1. User says to their phone: "Skip the kitchen today, the dog made a mess"
2. Phone sends `chat_message` to relay
3. Relay intelligence reads the vacuum's Agent Card, sees `interaction_model: "headless"` and the `available_actions` list
4. Intelligence maps "skip the kitchen" → `{ action: "exclude_zone", parameters: { room: "kitchen" } }`
5. Relay sends `device_action` to the adapter
6. Adapter calls `POST /exclude { room: "kitchen" }` on the vacuum's API
7. Intelligence generates confirmation: "Got it — I'll skip the kitchen for this run. Currently finishing the master bedroom, then hallway and office."
8. Confirmation sent to user's phone. Avatar speaks it.

The vacuum never saw natural language. It received a structured JSON command.

## More Examples

### Combine Harvester

```javascript
const AGENT_CARD = {
  protocol_version: '0.4',
  agent: { name: 'Combine Harvester', version: '3.1.0' },
  device: {
    type: 'vehicle',
    manufacturer: 'Acme Ag',
    model: 'Model-X Combine',
    interaction_model: 'headless',
    status: {},
    available_actions: [
      { id: 'start_row', name: 'Start harvesting row', params: [
        { name: 'row', type: 'integer' }
      ]},
      { id: 'end_row', name: 'Stop and end current row', params: [] },
      { id: 'return_to_start', name: 'Return to starting position', params: [] },
      { id: 'set_speed', name: 'Set ground speed', params: [
        { name: 'mph', type: 'number' }
      ]},
      { id: 'unload', name: 'Unload grain tank', params: [] }
    ]
  },
  capabilities: {
    sensor_events: ['harvest_progress', 'fuel_level', 'grain_tank',
                    'yield_rate', 'position', 'engine_alert']
  }
};

// ...connect and dispatch device_action as in the vacuum example...

// Send harvest progress every 30s
setInterval(async () => {
  const state = await harvesterAPI.getState();
  sendSensorEvent('harvest_progress', {
    field: 'north_40',
    percent_complete: state.progress,
    acres_remaining: state.acresLeft,
    yield_bushels_per_acre: state.yieldRate
  }, 'periodic');
}, 30000);
```

User says: "How's the north field?" → Gets: "The north field is 73% done. About 10.8 acres remaining, yielding 185 bushels per acre. Fuel is at 64%."

### Irrigation Controller

```javascript
const AGENT_CARD = {
  protocol_version: '0.4',
  agent: { name: 'RainMachine Pro', version: '2.4.0' },
  device: {
    type: 'appliance',
    interaction_model: 'headless',
    fleet_tags: ['irrigation'],
    available_actions: [
      { id: 'irrigate_zone', name: 'Water a zone', params: [
        { name: 'zone', type: 'string', options: ['front_lawn', 'back_garden', 'east_field', 'orchard'] },
        { name: 'duration_minutes', type: 'integer' }
      ]},
      { id: 'skip_zone', name: 'Skip zone in next cycle', params: [
        { name: 'zone', type: 'string' },
        { name: 'reason', type: 'string' }
      ]},
      { id: 'set_schedule', name: 'Set watering schedule', params: [
        { name: 'zone', type: 'string' },
        { name: 'days', type: 'array' },
        { name: 'start_time', type: 'string' }
      ]}
    ]
  },
  capabilities: {
    sensor_events: ['soil_moisture', 'flow_rate', 'zone_complete', 'freeze_warning']
  }
};
```

User says: "Don't water the east field tomorrow, it's going to rain" → Relay maps to `skip_zone` with `zone: "east_field"`.

`device.fleet_tags: ['irrigation']` makes this controller eligible for fan-in to an Irrigation Spokesperson aggregator subscribed to `fleet_tags: ['irrigation']`. See [`examples/aggregator/`](../aggregator/) for the aggregator-side worked example. The field is optional — a single irrigation controller works exactly as before without it.

### CNC Machine

```javascript
const AGENT_CARD = {
  protocol_version: '0.4',
  agent: { name: 'Haas VF-2SS', version: '1.0.0' },
  device: {
    type: 'machine',
    manufacturer: 'Haas',
    interaction_model: 'headless',
    available_actions: [
      { id: 'pause', name: 'Pause current job', params: [] },
      { id: 'resume', name: 'Resume job', params: [] },
      { id: 'abort_job', name: 'Abort and reset', params: [
        // Safety-critical: requires confirmation
      ]},
      { id: 'next_job', name: 'Load next job in queue', params: [] },
      { id: 'set_feed_override', name: 'Adjust feed rate', params: [
        { name: 'percent', type: 'integer' }
      ]}
    ]
  },
  capabilities: {
    sensor_events: ['job_progress', 'tool_wear', 'coolant_level',
                    'spindle_load', 'error']
  }
};
```

User says from across the shop: "Is the batch done yet?" → Gets: "Job 3 of 5 is at 87%. Estimated 12 minutes remaining on this part, about 45 minutes for the full batch. Tool wear is at 62% — you'll want to change the insert after this batch."

## Key Design Points

**The adapter is trivial.** The intelligence lives in the relay, not the adapter. Your adapter just reads the device's API and translates `device_action` commands to native API calls. A small adapter — no AI, no NLP.

**The device manufacturer doesn't need to change anything.** If the device has any kind of API (HTTP, MQTT, serial, Modbus, whatever), you can write an adapter for it. The adapter bridges between the device's native protocol and APP.

**Available actions define what's possible.** The relay intelligence can only generate `device_action` commands that match entries in `available_actions`. It won't hallucinate commands that don't exist. The typed `params` with `options` arrays further constrain what the intelligence can generate.

**Sensor events make the conversation contextual.** When the user asks "how's the vacuum?", the relay intelligence uses recent `sensor_event` data to compose a meaningful answer — not a generic "it's running." The more sensor events you send, the better the conversational experience.

**No `initiation_profile` on these examples.** Headless devices don't initiate; the relay's intelligence layer composes initiation when sensor thresholds are crossed. See SPEC §13 Initiative.

## See Also

- [Main README](../../README.md) — Protocol overview
- [SPEC.md](../../SPEC.md) — Full specification, especially Section 11.4 (Headless Devices)
- [Device example](../device/) — For devices that have onboard AI and project outward
