# Agent Presentation Protocol (APP)

**The presentation layer for AI. An open protocol for giving any agent a way to meet users on any conforming surface.**

The Agent Presentation Protocol (APP) is an open protocol that allows any AI agent, device, or service to project itself through any conforming presentation surface — phones, tablets, desktops, watches, in-vehicle HMIs (Apple CarPlay, Android Auto, and others), kiosks, embedded displays, robotics, edge devices, and many other surfaces. APP is the presentation layer for agentic AI: it defines the wire contract between an agent backend and a rendering surface, and is implementable by any party.

→ **[Documentation](https://chitin.net/protocol)**

---

## What is APP?

MCP gives your agent tools. A2A lets your agent collaborate. **APP gives your agent a presentation layer.**

APP defines how an agent backend communicates with a presentation surface through a cloud relay. Your agent sends JSON messages over a WebSocket; any conforming surface renders the output — text, streaming voice, audio, emotional expression, persistent memory — across every device the user carries.

```
Your Agent (any framework)
  │  APP (WSS)
  ▼
APP Relay (any conforming relay)
  │
  ▼
APP Surfaces (any conforming surface — phones, desktops, kiosks,
              vehicles, custom shells)
```

### What the protocol provides

- **Streaming text output** with sentence-level chunking suitable for natural voice
- **Audio streaming** alongside or instead of text — speech-to-speech models, `text+audio` output mode
- **Emotion tags** (`[happy]`, `[thinking]`, etc.) that surfaces with expression rendering can use
- **Persistent memory** (soul files) keyed by `(user_id, agent_id)`, opaque to the relay
- **End-to-end encryption** (ECDH P-256 + AES-256-GCM) for message payloads between agent and surface
- **Agent initiative** with declared `warrant` and `if_unanswered` stakes (§13)
- **Fleet aggregation** — fan-in spokesperson agent pattern for device fleets (§14)
- **Device projection** — physical devices project their agent to any conforming surface
- **Headless device support** — relay-side intelligence maps natural language to structured device actions
- **Capability negotiation** — surfaces and agents declare what they can render or produce
- **Smart home integration** — conversational layer above Matter, HomeKit, Alexa, Home Assistant

### Reference implementations

Chitin maintains reference implementations of an APP relay, surfaces (iOS, macOS, in-vehicle, kiosk deployments), and a bridge daemon. Downloads and details at [chitin.net](https://chitin.net). Reference implementations are illustrative — the protocol is implementable by any party.

### What you build

Implement a WebSocket connection to the relay. Send and receive JSON messages. That's it.

```javascript
const WebSocket = require('ws');

const AGENT_CARD = {
  protocol_version: '0.4',
  agent: { name: 'My Agent', version: '1.0.0' },
  capabilities: {
    streaming: true,
    emotions: ['neutral', 'happy', 'thinking', 'excited'],
    memory: { read: true, write: true }
  }
};

const ws = new WebSocket(
  `wss://your-relay.example/ws/bridge?token=${process.env.BRIDGE_TOKEN}`
);

ws.on('open', () => {
  // Card Exchange: send the Agent Card first (SPEC §3.3)
  ws.send(JSON.stringify({ type: 'agent_card', card: AGENT_CARD }));
});

ws.on('message', async (raw) => {
  const message = JSON.parse(raw);
  if (message.type !== 'chat_message') return;

  // message.content         = user's text
  // message.messages        = conversation history
  // message.context.surface = "ios_phone", "carplay", etc.
  const response = await yourLLM.chat(message.messages);

  let accumulated = '';
  for await (const chunk of response) {
    accumulated += chunk;
    ws.send(JSON.stringify({
      type: 'chat_stream_chunk', reply_to: message.id,
      delta: chunk, accumulated, timestamp: Date.now()
    }));
  }
  ws.send(JSON.stringify({
    type: 'chat_stream_end', reply_to: message.id,
    content: accumulated, timestamp: Date.now()
  }));
});
```

---

## Protocol Specification

### Message Types

| Type | Direction | Purpose |
|------|-----------|---------|
| `chat_message` | Surface → Agent | User's text or voice input with conversation history |
| `chat_stream_chunk` | Agent → Surface | Streaming response delta + accumulated text |
| `chat_stream_end` | Agent → Surface | Final complete response with metadata |
| `chat_response` | Agent → Surface | Non-streaming complete response |
| `agent_card` | Bidirectional | Identity and capability declaration (§3.3) |
| `agent_notification` | Agent → Surface | Agent-initiated message with declared `warrant` (§13) |
| `aggregator_subscribe` | Aggregator → Relay | Connect-time fleet subscription (§14) |
| `motor_command` | Agent → Device | Physical device directive envelope (device-defined commands) |
| `sensor_event` | Device → Agent/Surface | Physical device sensor data envelope (device-defined readings) |
| `device_action` | Relay → Device | Structured command for headless devices (mapped from natural language) |
| `memory_sync` | Bidirectional | Soul file read/write |
| `presence_update` | Surface → Relay → Ambient | Ambient state broadcast (§12) |
| `error` | Either → Either | `{type, code, message, reply_to?, timestamp}` (§4.9) |
| `system` | Relay → Both | Connection events (connected, agent_online, agent_offline) |

See [SPEC.md §4](./SPEC.md#4-message-types) for the full message-type list.

### Chat Message Format

```json
{
  "type": "chat_message",
  "id": "uuid-v4",
  "content": "Tell me about the weather",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Tell me about the weather"}
  ],
  "context": {
    "surface": "ios_phone",
    "surface_capabilities": {
      "display": true,
      "voice": true,
      "camera": false
    },
    "input_modality": "voice",
    "user_id": "uuid",
    "session_id": "uuid"
  },
  "timestamp": 1774648679638
}
```

`content` is the active message; `messages` is the full conversation context (an industry-standard `{role, content}` array). The two overlap by design — `messages[-1].content` always equals `content`. See SPEC.md §4.1.

### Streaming Response

```json
// Chunk (sent for each delta)
{
  "type": "chat_stream_chunk",
  "reply_to": "message-uuid",
  "delta": "Hey",
  "accumulated": "Hey there",
  "timestamp": 1774648680000
}

// End (sent when response is complete)
{
  "type": "chat_stream_end",
  "reply_to": "message-uuid",
  "content": "Hey there, how can I help you today?",
  "model": "my-agent-v1",
  "finish_reason": "stop",
  "timestamp": 1774648681000
}
```

### Agent Card

Every agent declares its identity and capabilities at connection time:

```json
{
  "protocol_version": "0.4",
  "agent": {
    "name": "My Agent",
    "description": "A helpful AI assistant",
    "version": "1.0.0",
    "author": "Your Name"
  },
  "device": null,
  "capabilities": {
    "streaming": true,
    "emotions": ["neutral", "happy", "sad", "thinking", "excited"],
    "memory": { "read": true, "write": true },
    "voice": { "tts_provider": "client", "stt_provider": "client" },
    "artifacts": false,
    "tools": []
  },
  "auth": {
    "methods": ["bridge_pairing_token"]
  }
}
```

Surfaces adapt their behavior based on declared capabilities. If your agent supports emotions, include emotion tags in responses: `[happy] I'd love to help!`. If it doesn't, surfaces use text-analysis heuristics as a fallback.

Agents that initiate contact (notifications, async messages) can also declare an optional top-level `initiation_profile` describing typical warrants, volume, and urgency, so surfaces can render an informed-consent permission grant UI at install time. See [SPEC.md §13 Initiative](./SPEC.md#13-initiative) for the full negotiation model — `warrant` and `if_unanswered` fields on initiation messages, surface-side `initiation` capability blocks, and relay enforcement.

### Emotion Tags

Embed emotion tags at the start of sentences to drive avatar expressions:

```
[thinking] Let me consider that...
[happy] Great news — I found exactly what you need!
[excited] This is going to be amazing!
```

Supported emotions: `neutral`, `happy`, `sad`, `angry`, `surprised`, `relaxed`, `thinking`, `excited`, `confused`, `love`, `fear`

### Authentication

Six well-known credential methods supported (see [SPEC §7](./SPEC.md#7-authentication-methods) for full details):

- **Bridge pairing token** — obtained during QR code pairing. Simple, proven; used by the reference clients.
- **OAuth 2.0 / OIDC** — for enterprise identity providers.
- **mTLS** — for headless, kiosk, and fleet-deployed scenarios where there's no interactive pairing flow.
- **PSK** (pre-shared key) — for air-gapped deployments and environments with no online IdP.
- **JWT** — short-lived bearer tokens issued by a trusted identity service.
- **API key** — long-lived developer-portal-issued keys for local development.

All connections use WSS (TLS). Optional E2EE layer (ECDH P-256 + AES-256-GCM) encrypts message payloads end-to-end.

### Memory (Soul Files)

Agents can read and write user memory through the relay:

```json
// Read
{ "type": "memory_sync", "action": "get", "avatar_id": "global" }

// Write
{ "type": "memory_sync", "action": "put", "avatar_id": "global", "data": { ... } }
```

The relay stores soul files as opaque JSON blobs keyed by (user_id, avatar_id). The relay never interprets contents.

### Motor Command (Physical Devices)

The protocol defines the message envelope; the device designer defines the command vocabulary.

```json
{
  "type": "motor_command",
  "id": "uuid-v4",
  "command": "move_to",
  "parameters": {
    "location": "lobby_entrance",
    "speed": "normal"
  },
  "timing": {
    "mode": "immediate",
    "sync_to": null
  },
  "safety": {
    "requires_confirmation": false,
    "timeout_ms": 30000
  },
  "reply_to": "session-uuid",
  "timestamp": 1774648679638
}
```

`command` and `parameters` are device-defined — declared in the Agent Card's `available_actions`. Timing modes: `immediate` (now), `queued` (in order), `synchronized` (timed to speech). The protocol carries the envelope; the device interprets the content.

### Sensor Event (Physical Devices)

```json
{
  "type": "sensor_event",
  "id": "uuid-v4",
  "sensor": "harvest_progress",
  "value": {
    "field": "north_40",
    "percent_complete": 73,
    "acres_remaining": 10.8
  },
  "trigger": "periodic",
  "timestamp": 1774648679638
}
```

Trigger modes: `periodic` (regular intervals), `threshold` (value crossed boundary), `event` (discrete occurrence). Sensor names and value schemas are device-defined.

### Device Action (Headless Devices)

For devices with no onboard AI, the relay-side intelligence layer maps natural language to structured commands:

```json
{
  "type": "device_action",
  "id": "uuid-v4",
  "action": "exclude_zone",
  "parameters": {
    "room": "kitchen"
  },
  "source_message": "chat-message-uuid",
  "timestamp": 1774648679638
}
```

`action` must match an entry in the device's Agent Card `available_actions`. The relay validates the action ID and required parameters before sending.

### Audio Streaming (Speech-to-Speech)

For agents that generate audio directly (speech-to-speech models), the protocol supports streaming audio alongside or instead of text. Input and output modalities are declared independently in the Agent Card:

```json
"capabilities": {
  "input_accepts": ["text"],
  "output_modalities": ["text+audio"],
  "audio_format": { "codec": "opus", "sample_rate": 24000, "channels": 1 }
}
```

Output modes: `text` (existing TTS pipeline), `audio` (agent-rendered audio only), `text+audio` (both simultaneously — audio for playback, text for display and emotion extraction).

```json
// Start audio stream
{
  "type": "audio_stream_start",
  "id": "uuid-v4",
  "reply_to": "chat-message-uuid",
  "codec": "opus",
  "sample_rate": 24000,
  "channels": 1
}

// Audio frame (sent continuously)
{
  "type": "audio_chunk",
  "reply_to": "chat-message-uuid",
  "data": "base64-encoded-audio-frame",
  "sequence": 42,
  "duration_ms": 20
}

// End audio stream
{
  "type": "audio_stream_end",
  "reply_to": "chat-message-uuid",
  "total_duration_ms": 3400
}
```

In `text+audio` mode, both `audio_chunk` and `chat_stream_chunk` messages reference the same `reply_to` ID. The surface plays audio immediately and uses the text stream for display and emotion tags.

---

## Getting Started

### 1. Install a WebSocket library

```bash
npm install ws
# or
pip install websockets
```

### 2. Point your agent at a relay

APP routes messages between an agent and a surface through a relay. Two ways to get one:

- **Run the reference relay locally — no signup, no token.** Clone [`chitin-net/app-reference-implementations`](https://github.com/chitin-net/app-reference-implementations) and start the bundled single-file relay; the full agent ↔ relay ↔ surface loop runs on your machine with zero external dependencies. The fastest way to develop against APP.
- **Use any conforming relay.** Point your agent at its bridge endpoint (e.g. `wss://your-relay.example/ws/bridge`). Relays authenticate connections using any of the mechanisms in §3.2 / §7 — bridge pairing token, OAuth/OIDC, mTLS, PSK, JWT, or API key. Credentials are issued by the **relay** through its own pairing or registration flow; there is no central APP sign-up.

### 3. Connect and handle messages

See the code example above. Your `onMessage` handler receives user messages and streams responses back; your client manages the WebSocket lifecycle, heartbeat (§3.4), reconnection (§3.5), and Agent Card exchange (§3.3). The reference implementations show a minimal raw-WebSocket version of each.

### 4. Test with a surface

Pair your agent with any conforming APP surface. The reference implementations include a runnable terminal **surface receiver**, so you can exercise the whole loop locally — no app or account required.

---

## Hosted relay

Chitin plans to operate a hosted reference relay with commercial plans — see [chitin.net/protocol](https://chitin.net/protocol) for status. In the meantime, run the reference relay locally (see Getting Started) or any conforming relay. The protocol itself defines no tiers; operator policies are operator-economic.

---

## Examples

- **[Inbound MCP Endpoint](./examples/mcp-endpoint/)** — Let Claude Code, Cursor, Copilot, or any MCP client drive an APP surface
- **[OpenClaw Bridge](./examples/openclaw/)** — Connect any OpenClaw gateway
- **[LangChain Agent](./examples/langchain/)** — Connect a LangChain agent in 10 lines
- **[Ollama Local](./examples/ollama/)** — Talk to your local Ollama model through your phone
- **[Express Server](./examples/express/)** — Wrap any HTTP API as an APP agent
- **[Device Projection](./examples/device/)** — Project a device's agent to any APP surface
- **[Headless Device](./examples/headless/)** — Give a headless device (or any machine) a conversational interface
- **[Fleet Aggregator](./examples/aggregator/)** — Irrigation Spokesperson worked scenario showing the fan-in agent pattern (§14)

---

## Roadmap

- [x] Protocol specification v0.3 (Draft)
- [x] Physical device schemas (motor_command, sensor_event, device_action)
- [x] Agent Card capability negotiation (§6)
- [x] Artifact delivery (§4.11)
- [x] Initiative model — agent_notification, warrant, if_unanswered (§13)
- [x] Fleet Aggregator — fan-in agent pattern for device fleets (§14)
- [x] Transport rename `/ws/app` → `/ws/surface` with backward-compat alias
- [x] Core SDK (Node.js)
- [x] Core SDK (Python)
- [ ] Relay-side aggregator handler (demand-gated; deferred until first consumer)
- [ ] A2A bridge integration (awaiting upstream Linux Foundation v0.3+ stabilization)

---

## License

The APP specification and core SDKs are licensed under [Apache 2.0](./LICENSE).

The Chitin relay server, iOS/macOS applications, and avatar pipeline are proprietary products of Chitin, LLC. See [chitin.net](https://chitin.net) for details.

---

**Chitin, LLC** · [chitin.net](https://chitin.net) · [support@chitin.net](mailto:support@chitin.net) · [@Chitin_Chat](https://twitter.com/Chitin_Chat)
