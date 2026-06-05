# Agent Presentation Protocol (APP) — Specification

**Version:** 0.4 (Draft)
**Status:** Private Draft — Not yet published
**Date:** March 2026
**Author:** Chitin, LLC
**License:** Apache 2.0

---

## 1. Overview

The Agent Presentation Protocol (APP) defines the wire contract between an **agent backend** and a **presentation surface**. APP enables any AI agent, intelligent device, or headless machine to project itself through any conforming surface — phones, desktops, watches, in-vehicle HMIs (Apple CarPlay, Android Auto, and others), kiosk displays, embedded systems, and custom OS shells. The protocol is implementable by any party; Chitin maintains reference surfaces and a reference relay (see `chitin.net`).

The protocol covers five layers:

1. **Transport** — WebSocket connections through a cloud relay
2. **Authentication** — Bridge pairing tokens, OAuth 2.0 / OIDC, mTLS, PSK, JWT, API keys
3. **Discovery** — Agent Cards declaring identity, capabilities, and device metadata
4. **Messaging** — Structured JSON messages for chat, streaming, device control, and audio
5. **Lifecycle** — Connection management, heartbeat, reconnection, capability negotiation

### 1.1 Design Principles

- **Envelope, not vocabulary.** The protocol defines message structure; domain-specific content (device commands, sensor readings, action parameters) is defined by the agent or device designer.
- **Surface-agnostic.** The protocol does not assume any specific rendering surface. An iPhone, a kiosk, a humanoid robot, and a headless vacuum cleaner are all valid endpoints.
- **Capability-negotiated.** Both sides declare what they support. Features degrade gracefully when capabilities don't match.
- **Backward-compatible.** New message types and capability fields can be added without breaking existing implementations. Unknown message types are silently ignored.
- **Relay-transparent.** The relay routes messages without interpreting content. It sees message `type` and routing metadata (tokens, user IDs) but never reads `content`, `parameters`, or `data` fields.

### 1.2 Terminology

| Term | Definition |
|------|-----------|
| **Agent** | The backend system that generates responses. Can be a cloud LLM, a local gateway, an onboard device AI, or a headless device adapter. |
| **Surface** | Any user-facing client that conforms to this specification and renders agent output. Examples include phones, desktops, watches, in-vehicle HMIs (CarPlay extensions and others), kiosks, embedded displays, and custom OS shells. Chitin Avatar (iOS), Chitin Phone (iOS), Chitin Desktop (macOS), and Chitin OS are reference implementations. |
| **Relay** | A message router between agents and surfaces, forwarding messages without interpreting content. Chitin operates a reference relay at `relay.chitin.chat`; conforming relays MAY be operated by any party. |
| **Bridge** | An agent implementation that connects a local system (e.g., an OpenClaw gateway) to the relay. The Chitin Bridge is the reference implementation. |
| **Agent Card** | A JSON document declaring an agent's identity, capabilities, device metadata, and authentication methods. |
| **Soul File** | An opaque JSON blob storing persistent user memory, keyed by (user_id, avatar_id). |

---

## 2. Transport

### 2.1 WebSocket Connection

All communication uses **WebSocket Secure (WSS)** connections to the relay server.

**Agent endpoint:**
```
wss://<relay-host>/ws/bridge?token=<BRIDGE_TOKEN>
```

**Surface endpoint:**
```
wss://<relay-host>/ws/surface?token=<JWT>
```

`<relay-host>` is the hostname of the conforming relay the implementation targets. For Chitin's reference relay, `<relay-host>` is `relay.chitin.chat`.

**Backward compatibility.** The route `/ws/app` is supported as a deprecated alias for `/ws/surface` for the duration of one minor-version release cycle following v0.3. Relay implementations MUST accept connections on both routes during this window and SHOULD log a deprecation warning for connections that arrive on `/ws/app`. Surfaces SHOULD migrate to `/ws/surface`; new surface implementations MUST use `/ws/surface`. After the deprecation window, `/ws/app` MAY be removed.

Both connections are outbound from the client — no port forwarding, firewall configuration, or inbound connection acceptance is required on either side.

### 2.2 Message Framing

All messages are UTF-8 encoded JSON objects sent as WebSocket text frames. Every message MUST include a `type` field.

```json
{
  "type": "message_type",
  ...additional fields per type...
}
```

Binary WebSocket frames are reserved for future audio streaming optimization but are not used in protocol version 0.3. Audio data is base64-encoded within JSON text frames.

### 2.3 Relay Routing

The relay is a transparent message router. Its routing rules are:

1. Messages from a **surface** are forwarded to the paired **agent** (matched by bridge pairing token / pairing relationship).
2. Messages from an **agent** are forwarded to all connected **surfaces** paired to that agent, except as refined by rule 3.
3. When an agent message includes a `target_surface` field, the relay filters delivery by surface class: only surfaces whose declared `surface_class` (§5.4) matches the target string receive the message. The reserved value `all` broadcasts to every paired surface (the default rule-2 behavior); the reserved value `auto` defers to relay routing logic, which selects based on surfaces' declared capabilities and most recent presence signal.
4. The relay reads only: `type` (for system event handling), `appUserId` (for multi-user routing), `target_surface` (for the rule-3 filter), and envelope metadata. It never reads `content`, `messages`, `parameters`, `data`, or `value` fields.
5. Messages with unknown `type` values are forwarded without interpretation. This enables protocol extensions without relay changes.
6. When an aggregator is connected on `/ws/bridge` with `agent_role: "aggregator"` (§14.3) and has issued a validated `aggregator_subscribe` (§14.4), the relay forwards `sensor_event`, `agent_card`, `bridge_online`, and `bridge_offline` from every matching bridge under the same user to that aggregator. Matching is by `fleet_tags` intersection or `bridge_ids` membership; subscriptions specifying both compose as union. A bridge MAY be matched by multiple aggregator subscriptions and is fanned to each. Aggregator delivery is in addition to existing surface and relay-intelligence routing; it does not replace or filter rules 1–3.

---

## 3. Connection Lifecycle

### 3.1 Connection Sequence

```
Agent                        Relay                        Surface
  │                            │                            │
  ├──WSS connect──────────────►│                            │
  │                            │◄──────────────WSS connect──┤
  │                            │                            │
  │◄─────system: connected─────┤────system: connected──────►│
  │                            │                            │
  ├──agent_card───────────────►│────agent_card─────────────►│
  │                            │                            │
  │◄────agent_card─────────────┤◄───────────────agent_card──┤
  │                            │                            │
  │        (ready for messages)│                            │
```

1. Agent opens WSS connection to `/ws/bridge?token=<BRIDGE_TOKEN>`.
2. Surface opens WSS connection to `/ws/surface?token=<JWT>`.
3. Relay sends `system: connected` event to both sides with connection metadata, including the relay's own protocol version (`protocol_version`).
4. Agent sends its Agent Card. Relay stores the card and forwards it to all connected surfaces.
5. Surface sends its Agent Card. Relay stores the card and forwards it to the connected agent.
6. Both sides are now ready for message exchange, having received each other's capability declarations.

### 3.2 Authentication

Authentication happens at the WebSocket connection level. The protocol supports multiple credential mechanisms so that implementations can match deployment context — consumer pairing, enterprise IdP, headless and fleet-deployed surfaces, and air-gapped scenarios all have viable paths. Either role (agent or surface) MAY use any of the mechanisms below; the choice is implementation-driven.

**Acceptable credential types:**

- **Bridge pairing token** — issued by the relay during a pairing flow (typically QR-based, see §7.1). Persistent, scoped to a specific (agent, surface) pairing. Used by the reference clients.
- **OAuth 2.0 / OIDC** — federated identity via an enterprise identity provider. The relay validates tokens against the configured IdP. Suits SSO, web-based pairing, and enterprise-managed deployments. See §7.2.
- **mTLS** — mutual TLS at the WebSocket handshake. Suits headless, kiosk, fleet-deployed, and CAC/PIV-derived-credential scenarios where there is no interactive pairing flow. See §7.4.
- **Pre-shared key (PSK)** — symmetric key passed at handshake. Suits air-gapped deployments and environments where no online identity provider is available. See §7.5.
- **JWT** — short-lived bearer token issued by an identity service the relay trusts. Common for surface registration in consumer flows; usable for either role. See §7.6.
- **API key** — long-lived developer-portal-issued key for local development and testing. Not recommended for production. See §7.3.

Credential transport at the WebSocket layer is mechanism-dependent and out of scope for v0.2. The reference relay accepts `?token=<TOKEN>` for bearer-style credentials (bridge pairing token, JWT, OAuth access token) and uses TLS client certificates for mTLS. Future spec versions MAY normatively specify URL patterns per mechanism.

All mechanisms MUST bind the credential to a specific (agent, surface) tuple at issuance. Credentials MUST be persisted using platform-appropriate secure storage:

- Apple platforms: Keychain
- Windows: Credential Manager (DPAPI)
- Linux: Secret Service / kwallet (TPM-backed where available)
- Embedded, fleet, and HSM-backed devices: TPM, secure element, or hardware security module per platform best practice

The reference applications use the bridge pairing token flow described in §7.1. Other mechanisms are equally conforming.

### 3.3 Card Exchange

After connection is established, both agents and surfaces MUST send an `agent_card` message within 10 seconds. Each side uses the other's Agent Card to adapt its behavior — surfaces adapt their rendering to the agent's declared capabilities (streaming, emotions, output modalities, artifacts, etc.), and agents adapt their output to the connected surfaces' declared capabilities (modality, urgency choices, `target_surface` selection, initiation handling per `capabilities.initiation`).

The Agent Card schema (§5) is role-neutral: most fields apply to either role. Surface-only fields (`surface_class`, `capabilities.initiation`, `capabilities.supports_presence`) are populated by surfaces; agent-only fields (`initiation_profile`, `capabilities.tools`, `capabilities.sensor_events`, `device`) are populated by agents. Aggregator-only fields (`agent_role: "aggregator"`, `aggregates`) are populated by fleet aggregators (§14); bridge-side `device.fleet_tags` is populated by bridges that participate in a fleet.

If a side does not send its card within 10 seconds, the other side assumes default capabilities (streaming: true, emotions: full set, memory: enabled, surface_class: unspecified). This ensures backward compatibility with implementations that predate the Agent Card system, or that predate the bidirectional-emission rule.

Either side can request the other's current Agent Card at any time:

```json
// Either side sends:
{"type": "agent_card_request", "id": "uuid"}

// Relay responds with the stored card from the other side:
{"type": "agent_card", "card": { ... }}
```

`agent_card_request` fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"agent_card_request"` |
| `id` | string | Yes | UUID v4 for this request. |

`agent_card` fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"agent_card"` |
| `card` | object | Yes | The full Agent Card document — see §5 for the card structure. |

**Capability declaration vs. per-message context.** The Agent Card mechanism described above is canonical for declaring a surface's *static* or *foundational* capabilities — what classes of message it can render, what input modalities it accepts, whether it supports presence broadcasting, what voice providers it uses. It is the basis for capability negotiation at connection time and for routing decisions throughout the session.

A separate per-message mechanism, `chat_message.context.surface_capabilities` (§4.1), carries *current-moment* context refinements: which capabilities are momentarily available, what the user just did, what's currently muted or dimmed. The two mechanisms are complementary. The Agent Card declares "this surface fundamentally supports voice"; per-message `surface_capabilities` may indicate "the user is currently muted." Implementations should populate the Agent Card with stable capability declarations and use per-message `surface_capabilities` for context that varies within a session.

**Aggregator connect-time subscription.** Bridges declaring `agent_role: "aggregator"` (§14.3) MUST send an `aggregator_subscribe` message (§14.4) immediately after the relay acknowledges the Agent Card and before any other traffic. The relay MUST NOT begin fan-out routing (§2.3 rule 6) until the subscription is received and validated. Subscriptions are immutable for the life of the connection in v0.3; reconnects produce a new subscription declaration.

### 3.4 Heartbeat

Both agents and surfaces send WebSocket ping frames every **30 seconds**. The relay closes connections that fail to respond with a pong within **60 seconds**.

The 30-second ping interval provides adequate margin against the 60-second timeout. Implementations SHOULD NOT reduce the ping interval below 15 seconds to avoid unnecessary relay load.

### 3.5 Reconnection

On unexpected disconnection, both agents and surfaces MUST implement automatic reconnection with **exponential backoff**:

- Initial delay: **1 second**
- Multiplier: **2x** per attempt
- Maximum delay: **60 seconds**
- Jitter: Add random 0–500ms to each delay to prevent thundering herd

Reconnection MUST re-send the reconnecting side's own Agent Card after the new WSS handshake completes (agents re-send the agent's card; surfaces re-send the surface's card). The relay treats each new WebSocket connection as a fresh session and replaces the stored card for that connection.

User-initiated disconnection (e.g., user disables the bridge) MUST NOT trigger automatic reconnection.

---

## 4. Message Types

### 4.1 Chat Messages

#### chat_message (Surface → Agent)

User's text or voice input with conversation history.

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
  "appUserId": "uuid",
  "timestamp": 1774648679638
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"chat_message"` |
| `id` | string | Yes | UUID v4. Used as `reply_to` in responses. |
| `content` | string | Yes | The user's message text (from speech recognition or text input). The active message — see the `content` vs `messages` note below. |
| `messages` | array | Yes | An industry-standard message array (a list of `{role, content}` turns; the same general shape used by OpenAI, Anthropic, Google, and Mistral chat APIs) carrying conversation history, including the system prompt. Surfaces SHOULD include the last 30 messages. See the `content` vs `messages` note below. |
| `context` | object | No | Surface metadata. See Context Object below. |
| `appUserId` | string | No | Relay-assigned user ID for multi-user routing. |
| `timestamp` | integer | Yes | Unix epoch milliseconds. |

**`content` vs `messages`.** These two fields overlap by design. `content` is the *active message* — the single user utterance this `chat_message` delivers. `messages` is the *full conversation context* the agent should condition on, including the system prompt and all prior turns. The active message is always the last element of `messages`, so the invariant **`messages[-1].content` MUST equal `content`** holds for every `chat_message`. Surfaces populate both fields. An agent that only needs the latest user turn MAY read `content` directly; an agent that needs history reads `messages`.

#### Context Object

```json
{
  "surface": "ios_phone",
  "surface_capabilities": {
    "display": true,
    "voice": true,
    "camera": false,
    "locomotion": false,
    "manipulation": false
  },
  "input_modality": "voice",
  "user_id": "uuid",
  "session_id": "uuid"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `surface` | string | Human-readable surface identifier: `ios_avatar`, `ios_phone`, `macos_desktop`, `carplay`, `kiosk`, `chitin_os`, or device-defined. |
| `surface_capabilities` | object | Open-ended dictionary of boolean or object capabilities, carrying *per-message* context refinements (e.g., "currently muted", "user just switched to voice input"). The surface's *foundational* capabilities are declared via the Agent Card mechanism (§3.3); this field is for moment-to-moment refinements, not the canonical capability set. Not enumerated — new capabilities can be added by any surface without protocol revision. |
| `input_modality` | string | How the user provided input: `"text"`, `"voice"`, `"touch"`, `"gesture"`. |
| `user_id` | string | User identifier (from JWT or anonymous registration). |
| `session_id` | string | Session identifier for grouping related messages. |

### 4.2 Streaming Responses

#### chat_stream_chunk (Agent → Surface)

Incremental streaming response. Sent for each token or group of tokens as the agent generates them.

```json
{
  "type": "chat_stream_chunk",
  "reply_to": "chat-message-uuid",
  "delta": "Hey",
  "accumulated": "Hey there",
  "appUserId": "uuid",
  "timestamp": 1774648680000
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"chat_stream_chunk"` |
| `reply_to` | string | Yes | The `id` of the originating `chat_message`. |
| `delta` | string | Yes | New text since the last chunk. |
| `accumulated` | string | Yes | Full response text accumulated so far. This is critical — it means the surface does not need to reconstruct the response from deltas, eliminating ordering bugs. |
| `appUserId` | string | No | Echoed from the originating message for relay routing. |
| `timestamp` | integer | Yes | Unix epoch milliseconds. |

#### chat_stream_end (Agent → Surface)

Final message indicating the response is complete.

```json
{
  "type": "chat_stream_end",
  "reply_to": "chat-message-uuid",
  "content": "Hey there, how's your evening going?",
  "model": "agent-model-id",
  "finish_reason": "stop",
  "appUserId": "uuid",
  "timestamp": 1774648681000
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"chat_stream_end"` |
| `reply_to` | string | Yes | The `id` of the originating `chat_message`. |
| `content` | string | Yes | Complete final response text. |
| `model` | string | No | Identifier of the model that generated the response. |
| `finish_reason` | string | No | Why generation stopped: `"stop"`, `"length"`, `"error"`. |
| `appUserId` | string | No | Echoed for routing. |
| `timestamp` | integer | Yes | Unix epoch milliseconds. |

#### chat_response (Agent → Surface)

Non-streaming complete response. Used by agents that do not support streaming. Surfaces MUST support both streaming and non-streaming responses.

```json
{
  "type": "chat_response",
  "reply_to": "chat-message-uuid",
  "content": "Complete response text.",
  "model": "agent-model-id",
  "appUserId": "uuid",
  "timestamp": 1774648681000
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"chat_response"` |
| `reply_to` | string | Yes | The `id` of the originating `chat_message`. |
| `content` | string | Yes | Complete response text. |
| `model` | string | No | Identifier of the model that generated the response. |
| `appUserId` | string | No | Echoed for routing. |
| `timestamp` | integer | Yes | Unix epoch milliseconds. |

### 4.3 System Events

#### system (Relay → Both)

Connection lifecycle events sent by the relay.

```json
{"type": "system", "event": "connected", "protocol_version": "0.4", "bridgesOnline": 1}
{"type": "system", "event": "bridge_online", "bridgeName": "Home Mac mini"}
{"type": "system", "event": "bridge_offline", "bridgeName": "Home Mac mini"}
{"type": "system", "event": "replaced"}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"system"` |
| `event` | string | Yes | One of `connected`, `bridge_online`, `bridge_offline`, `replaced`. Determines which event-specific fields are present. |

**Event-specific fields:**

| Field | Type | Event | Description |
|-------|------|-------|-------------|
| `protocol_version` | string | `connected` | The relay's own protocol version, e.g. `0.4`. See §10.3. |
| `bridgesOnline` | integer | `connected` | Count of bridges online, included for surfaces. |
| `bridgeName` | string | `bridge_online`, `bridge_offline` | Name of the bridge. |

| Event | Sent To | Description |
|-------|---------|-------------|
| `connected` | Both | Initial connection acknowledgment. Carries the relay's own protocol version in `protocol_version` (§10.3), and a `bridgesOnline` count for surfaces. |
| `bridge_online` | Surface | An agent/bridge came online. Includes `bridgeName`. |
| `bridge_offline` | Surface | An agent/bridge went offline. |
| `replaced` | Agent or Surface | This connection was replaced by a newer connection from the same client (duplicate connection detected). The recipient should not reconnect. |

The `protocol_version` field on the `connected` event is the relay's protocol-version declaration. The relay mediates every message but sends no Agent Card, so this is where it states its version. It uses the same field name as the Agent Card (§5) so that version vocabulary is uniform across all APP-aware parties. See §10.3 for how version information is used.

### 4.4 Memory Sync

#### memory_sync (Bidirectional)

Read and write soul file memory through the relay.

```json
// Read request
{
  "type": "memory_sync",
  "action": "get",
  "avatar_id": "global",
  "id": "uuid"
}

// Read response
{
  "type": "memory_sync",
  "action": "get_response",
  "avatar_id": "global",
  "data": { /* SoulFile JSON */ },
  "reply_to": "uuid"
}

// Write request
{
  "type": "memory_sync",
  "action": "put",
  "avatar_id": "global",
  "data": { /* SoulFile JSON */ },
  "id": "uuid"
}

// Write confirmation
{
  "type": "memory_sync",
  "action": "put_response",
  "avatar_id": "global",
  "success": true,
  "reply_to": "uuid"
}

// Delete request
{
  "type": "memory_sync",
  "action": "delete",
  "avatar_id": "global",
  "id": "uuid"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"memory_sync"` |
| `action` | string | Yes | One of `get`, `get_response`, `put`, `put_response`, `delete`. Determines which additional fields are present — see Action variants below. |

**Action variants:**

| `action` | Direction | Additional required fields | Description |
|----------|-----------|----------------------------|-------------|
| `get` | Surface/Agent → Relay | `avatar_id`, `id` | Read request. |
| `get_response` | Relay → requester | `avatar_id`, `data`, `reply_to` | Read response carrying the SoulFile JSON. |
| `put` | Surface/Agent → Relay | `avatar_id`, `data`, `id` | Write request. |
| `put_response` | Relay → requester | `avatar_id`, `success`, `reply_to` | Write confirmation. |
| `delete` | Surface/Agent → Relay | `avatar_id`, `id` | Delete request. |

**Variant fields:**

| Field | Type | Required for | Description |
|-------|------|--------------|-------------|
| `avatar_id` | string | all variants | Memory scope. `global` is shared across all characters; character-specific IDs scope to one personality. |
| `id` | string | `get`, `put`, `delete` | UUID v4 request identifier. |
| `data` | object | `get_response`, `put` | The SoulFile JSON. Opaque to the relay. |
| `reply_to` | string | `get_response`, `put_response` | The `id` of the originating request. |
| `success` | boolean | `put_response` | Whether the write succeeded. |

The relay stores soul files as **opaque JSON blobs** keyed by `(user_id, avatar_id)`. It never validates, interprets, or indexes the contents of the `data` field. The `avatar_id` of `"global"` indicates shared memory across all characters; character-specific IDs scope memory to a single personality.

### 4.5 Motor Commands

#### motor_command (Agent → Surface)

Physical surface directive envelope. The protocol defines the message structure; the device designer defines the command vocabulary and parameters.

```json
{
  "type": "motor_command",
  "id": "uuid-v4",
  "command": "move_to",
  "parameters": {
    "location": "lobby_entrance",
    "speed": "normal",
    "avoid_obstacles": true
  },
  "timing": {
    "mode": "immediate",
    "delay_ms": 0,
    "sync_to": null
  },
  "safety": {
    "requires_confirmation": false,
    "timeout_ms": 30000,
    "abort_on_error": true
  },
  "reply_to": "session-uuid",
  "timestamp": 1774648679638
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"motor_command"` |
| `id` | string | Yes | UUID v4 for this command. |
| `command` | string | Yes | Device-defined command identifier. MUST match an entry in the device's Agent Card `available_actions`. |
| `parameters` | object | No | Device-defined parameters. Schema declared in Agent Card per action. |
| `timing` | object | No | Execution timing. See below. |
| `safety` | object | No | Safety constraints. See below. |
| `reply_to` | string | No | Session or message context. |
| `timestamp` | integer | Yes | Unix epoch milliseconds. |

**Timing modes:**

| Mode | Description |
|------|-------------|
| `immediate` | Execute now (default). |
| `queued` | Add to device's command queue. Execute in order. |
| `synchronized` | Execute in sync with a chat message referenced by `sync_to`. Enables coordinated speech-and-movement. |

**Safety object:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `requires_confirmation` | boolean | false | If true, device sends confirmation request to surface before executing. |
| `timeout_ms` | number | 30000 | Time to wait for command completion before reporting failure. |
| `abort_on_error` | boolean | true | Whether to halt the command queue if this command fails. |

**Inline tagged commands:**

For coordinated speech-and-movement, motor directives can also be embedded in the response text stream using tag syntax:

```
[gesture:wave] Welcome to the Hilton! [move:approach]
I see you have luggage. [gesture:point_elevator]
```

The surface parses these tags, generates `motor_command` messages with `timing.mode: "synchronized"`, and coordinates physical execution with TTS playback. The tag format is `[category:action_name]`.

### 4.6 Sensor Events

#### sensor_event (Surface/Device → Agent)

Physical surface or device sensor data envelope. The protocol defines the message structure; the device designer defines sensor types and value schemas.

```json
{
  "type": "sensor_event",
  "id": "uuid-v4",
  "sensor": "harvest_progress",
  "value": {
    "field": "north_40",
    "percent_complete": 73,
    "acres_remaining": 10.8,
    "yield_bushels_per_acre": 185
  },
  "trigger": "periodic",
  "device_timestamp": 1774648679000,
  "timestamp": 1774648679638
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"sensor_event"` |
| `id` | string | Yes | UUID v4. |
| `sensor` | string | Yes | Device-defined sensor identifier. MUST match a declared sensor in the Agent Card. |
| `value` | any | Yes | Sensor reading. Schema is device-defined. Can be a number, string, boolean, or object. |
| `trigger` | string | Yes | Why this event was sent: `"periodic"`, `"threshold"`, `"event"`. |
| `device_timestamp` | integer | No | Timestamp from the device's own clock (may differ from relay time). |
| `timestamp` | integer | Yes | Unix epoch milliseconds (relay time). |

**Trigger modes:**

| Mode | Description |
|------|-------------|
| `periodic` | Sent at regular device-defined intervals (e.g., battery every 60s, GPS every 5s). |
| `threshold` | Sent when a value crosses a boundary (e.g., battery below 20%, temperature above limit). |
| `event` | Sent when a discrete occurrence happens (e.g., task complete, error, person detected). |

### 4.7 Device Actions

#### device_action (Relay → Device)

Structured command for headless devices. Generated by the relay-side intelligence layer from natural language input. The device never receives natural language — only structured actions.

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

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"device_action"` |
| `id` | string | Yes | UUID v4. |
| `action` | string | Yes | Action identifier. MUST match an entry in the device's Agent Card `available_actions`. |
| `parameters` | object | No | Action parameters. Schema defined per action in Agent Card. |
| `source_message` | string | No | The `chat_message` ID that triggered this action (for audit trail). |
| `timestamp` | integer | Yes | Unix epoch milliseconds. |

The relay validates that `action` matches a declared `available_actions` entry and that required parameters are present before forwarding to the device.

### 4.8 Audio Streaming

#### audio_stream_start (Bidirectional)

Signals the start of an audio stream with codec metadata.

```json
{
  "type": "audio_stream_start",
  "id": "uuid-v4",
  "reply_to": "chat-message-uuid",
  "codec": "opus",
  "sample_rate": 24000,
  "channels": 1,
  "timestamp": 1774648679638
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"audio_stream_start"` |
| `id` | string | Yes | UUID v4 stream identifier. |
| `reply_to` | string | No | The `id` of the originating `chat_message`, when the stream is a response. Omitted for surface-originated audio input. |
| `codec` | string | Yes | Audio codec, e.g. `opus`. |
| `sample_rate` | integer | Yes | Sample rate in Hz, e.g. 24000. |
| `channels` | integer | Yes | Channel count, e.g. 1 for mono. |
| `timestamp` | integer | Yes | Unix epoch milliseconds. |

#### audio_chunk (Bidirectional)

A single frame of streaming audio data.

```json
{
  "type": "audio_chunk",
  "reply_to": "chat-message-uuid",
  "data": "base64-encoded-audio-frame",
  "sequence": 42,
  "duration_ms": 20,
  "timestamp": 1774648679658
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"audio_chunk"` |
| `reply_to` | string | No | The `id` of the originating `chat_message`. |
| `data` | string | Yes | Base64-encoded audio frame. |
| `sequence` | integer | Yes | Monotonically increasing frame number. Enables out-of-order detection. |
| `duration_ms` | integer | Yes | Duration this frame represents in milliseconds. Used for playback buffer management. |
| `timestamp` | integer | No | Unix epoch milliseconds. |

#### audio_stream_end (Bidirectional)

Signals the end of an audio stream.

```json
{
  "type": "audio_stream_end",
  "reply_to": "chat-message-uuid",
  "total_duration_ms": 3400,
  "timestamp": 1774648683038
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"audio_stream_end"` |
| `reply_to` | string | No | The `id` of the originating `chat_message`. |
| `total_duration_ms` | integer | Yes | Total duration of the completed stream in milliseconds. |
| `timestamp` | integer | Yes | Unix epoch milliseconds. |

**Output modality interaction:**

When an agent sends `text+audio` output, both `audio_chunk` and `chat_stream_chunk` messages reference the same `reply_to` ID. The surface plays audio immediately and uses the concurrent text stream for display and emotion tag extraction. If either stream is absent, the surface degrades gracefully.

### 4.9 Error Messages

#### error (Agent → Surface, or Relay → either side)

```json
{
  "type": "error",
  "code": "provider_error",
  "message": "Upstream LLM returned: model not found",
  "reply_to": "originating-message-uuid",
  "timestamp": 1774648681000
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"error"`. |
| `code` | string | Yes | One of the standard codes below, or an implementation-specific extension code. |
| `message` | string | Yes | Human-readable error description suitable for surface display. |
| `reply_to` | string | Optional; SHOULD be included when the error is a response to a specific message | UUID of the originating message that this error responds to (e.g., the `id` of the `chat_message` whose processing failed). Omitted when the error is not a response to a specific message (e.g., connection-level relay errors). |
| `timestamp` | integer | Yes | Unix epoch milliseconds. |

Additional implementation-specific fields MAY be included (e.g., a relay's `connection_limit_exceeded` error may include `current`, `limit`, `upgrade_url`; see §9.2). Consumers MUST ignore unknown fields per §10.2.

Standard error codes:

| Code | Description |
|------|-------------|
| `provider_error` | The upstream LLM or service returned an error. |
| `timeout` | The request timed out. |
| `rate_limited` | The agent or relay is rate-limiting requests. |
| `connection_limit_exceeded` | The relay's per-account connection limit (operator-defined) has been reached. |
| `authentication_failed` | Token is invalid or expired. |
| `not_paired` | No paired agent/surface found. |
| `unsupported_capability` | Requested feature not supported by this agent. |

### 4.10 Presence

#### presence (Bidirectional)

Typing indicators and attention state.

```json
{
  "type": "presence",
  "state": "typing",
  "timestamp": 1774648679638
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"presence"` |
| `state` | string | Yes | Current attention state. One of `typing`, `idle`, `listening`, `processing`, `speaking`. |
| `timestamp` | integer | Yes | Unix epoch milliseconds. |

### 4.11 Artifacts

#### artifact_create (Agent → Surface)

Delivers a rich content artifact — a document, code block, table, image, or structured data — that the surface renders alongside conversation. Artifacts are persistent objects stored on the relay and accessible across surfaces.

```json
{
  "type": "artifact_create",
  "id": "uuid-v4",
  "reply_to": "chat-message-uuid",
  "artifact": {
    "artifact_id": "uuid-v4",
    "title": "Weekly Meal Plan",
    "content_type": "markdown",
    "content": "## Monday\n- Breakfast: Oatmeal...",
    "metadata": {
      "created_at": 1774648679638,
      "version": 1
    }
  },
  "timestamp": 1774648679638
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"artifact_create"` |
| `id` | string | Yes | UUID v4 for this message. |
| `reply_to` | string | No | The `id` of the originating `chat_message`. |
| `artifact` | object | Yes | The artifact payload. See Artifact object below. |
| `timestamp` | integer | Yes | Unix epoch milliseconds. |

**Artifact object:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `artifact_id` | string | Yes | Persistent ID for this artifact. Used for updates and cross-surface access. |
| `title` | string | Yes | Display title for the artifact. |
| `content_type` | string | Yes | MIME-like type: `"markdown"`, `"code"`, `"table"`, `"image"`, `"html"`, `"json"`. |
| `content` | string | Yes | The artifact body. For `code`, includes language in metadata. For `image`, a URL or base64 data. For `table`, JSON array of rows. |
| `metadata` | object | No | Additional metadata: `language` (for code), `version` (for updates), `created_at`. |

#### artifact_update (Agent → Surface)

Updates an existing artifact. The surface replaces the artifact content in-place.

```json
{
  "type": "artifact_update",
  "id": "uuid-v4",
  "artifact_id": "existing-artifact-uuid",
  "changes": {
    "content": "## Monday\n- Breakfast: Yogurt parfait...",
    "metadata": { "version": 2 }
  },
  "timestamp": 1774648680000
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"artifact_update"` |
| `id` | string | Yes | UUID v4 for this message. |
| `artifact_id` | string | Yes | ID of the existing artifact to update. |
| `changes` | object | Yes | The fields to replace on the artifact. Typically `content` (replacement body) and/or `metadata` (replacement or merged metadata, e.g. an incremented `version`). |
| `timestamp` | integer | Yes | Unix epoch milliseconds. |

#### artifact_request (Surface → Agent or Relay)

Surface requests a previously created artifact by ID. Used when a surface connects mid-session or when the user navigates to an artifact referenced in conversation history.

```json
{
  "type": "artifact_request",
  "id": "uuid-v4",
  "artifact_id": "target-artifact-uuid"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"artifact_request"` |
| `id` | string | Yes | UUID v4 for this message. |
| `artifact_id` | string | Yes | ID of the artifact being requested. |

`artifact_request` carries no `timestamp` — it is a request/query message, not an event-class message.

**Relay storage:** Artifacts are stored on the relay alongside soul files, keyed by `(user_id, artifact_id)`. The relay stores artifacts as opaque blobs — it does not interpret `content_type` or `content`. Surfaces render artifacts based on `content_type`: markdown is rendered as rich text, code gets syntax highlighting, tables get column/row rendering, images are displayed inline.

**Subscription gating:** Artifact persistence on the relay may be gated by subscription tier. Surfaces should handle the case where artifact storage requests are rejected by the relay due to tier limitations, and fall back to session-only artifact storage.

### 4.12 Multi-Agent Messages

When a user has multiple agents connected (personal assistant, vehicle, home devices), the surface needs to list, select, and address specific agents.

#### agent_list_request (Surface → Relay)

Requests the list of all agents currently online for this user.

```json
{
  "type": "agent_list_request",
  "id": "uuid-v4"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"agent_list_request"` |
| `id` | string | Yes | UUID v4 for this request. |

#### agent_list_response (Relay → Surface)

Returns all online agents with their Agent Cards.

```json
{
  "type": "agent_list_response",
  "reply_to": "uuid",
  "agents": [
    {
      "bridge_id": "uuid",
      "bridge_name": "Home Mac mini",
      "online": true,
      "agent_card": { /* full Agent Card */ }
    },
    {
      "bridge_id": "uuid",
      "bridge_name": "Electric Vehicle",
      "online": true,
      "agent_card": { /* full Agent Card */ }
    },
    {
      "bridge_id": "uuid",
      "bridge_name": "Robot Vacuum",
      "online": true,
      "agent_card": { /* full Agent Card */ }
    }
  ]
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"agent_list_response"` |
| `reply_to` | string | Yes | The `id` of the originating `agent_list_request`. |
| `agents` | array | Yes | Online agents for this user. Each element is an object with `bridge_id` (string), `bridge_name` (string), `online` (boolean), and `agent_card` (the agent's full Agent Card, §5). |

#### Targeted messages

When multiple agents are online, a `chat_message` can target a specific agent by including a `target_agent` field:

```json
{
  "type": "chat_message",
  "id": "uuid-v4",
  "content": "What's your battery at?",
  "target_agent": "bridge-id-of-vacuum",
  "messages": [...],
  "timestamp": 1774648679638
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `target_agent` | string | No | Bridge ID of the intended recipient. If omitted, the relay delivers to the user's default/primary agent. If specified, the relay delivers only to that agent. |

The surface is responsible for providing a UI that lets the user select which agent to address. The relay routes based on `target_agent` when present; surfaces without multi-agent UI simply omit the field and messages go to the default agent.

**Default agent selection:** When no `target_agent` is specified and multiple agents are online, the relay delivers to the agent that connected first (oldest active connection). Users can change their default agent through the developer portal or surface settings.

### 4.13 Agent Notifications

Messages in this section are agent-initiated. Their `warrant` (why the agent is reaching out) and optional `if_unanswered` (structured stakes) semantics are defined in §13 Initiative.

#### agent_notification (Bridge/Desktop → Relay → Surface)

An external agent asks to reach the user. Routed by the relay based on urgency and target surface.

```json
{
  "type": "agent_notification",
  "message_id": "uuid",
  "agent_id": "external-agent-id",
  "urgency": "low | medium | high",
  "summary": "Short summary (max 140 chars)",
  "body": "Optional longer body (max 1000 chars)",
  "require_response": true,
  "ring_timeout_seconds": 30,
  "target_surface": "phone",
  "conversation_handoff": false,
  "timestamp": "ISO-8601"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"agent_notification"` |
| `message_id` | string | Yes | UUID identifying this notification. Echoed by `agent_notification_response`. |
| `agent_id` | string | Yes | Identifier of the agent reaching out. |
| `urgency` | string | Yes | One of `low`, `medium`, `high`. Rendering hint — see Urgency behaviors below. |
| `summary` | string | Yes | Short summary (max 140 chars). |
| `body` | string | No | Optional longer body (max 1000 chars). |
| `require_response` | boolean | No | Whether the agent expects a user response. |
| `ring_timeout_seconds` | integer | No | For high-urgency ring-through, how long to ring before timing out. |
| `warrant` | string | No | Why the agent is reaching out: `user_authorized`, `task_decision_required`, `external_event`, or `unspecified` (default). SHOULD be declared on every agent-initiated message. `urgency` is a rendering hint; `warrant` is the structured reason. See §13. |
| `if_unanswered` | object | No | Structured stakes if the notification goes unanswered. See §13.1. |
| `conversation_handoff` | boolean | No | Whether answering should hand off into a full conversation. |
| `timestamp` | string | No | ISO-8601 timestamp. Note: `agent_notification` uses an ISO-8601 string timestamp, unlike the epoch-millis integer `timestamp` used by most APP messages. |
| `target_surface` | string | No | Class identifier for the target surface. See the `target_surface` note below. |
| `options` | array | No | Structured response choices the surface MAY render as discrete selectable actions. Each element has `id` (string, required — stable machine-readable identifier, echoed back in `agent_notification_response.chosen_option`) and `label` (string, required — human-readable text the surface displays or speaks). Additional per-option fields are reserved for future additive extension (§10.2) and MUST be ignored if unrecognized. |

**Urgency behaviors:**
- `low` — Silent banner in-app if foreground; notification center entry if background. Respects DND.
- `medium` — Notification with sound. Respects DND.
- `high` — Ring-through UI. Bypasses DND.

**`target_surface`** is a string identifying the *class* of surface to receive the notification. Well-known values include `phone`, `tablet`, `watch`, `desktop`, `car` (in-vehicle surfaces — Apple CarPlay, Android Auto, in-vehicle infotainment systems, aftermarket head units), `smart_speaker`, `kiosk`, and `ambient`. Two reserved values direct routing behavior rather than naming a specific class: `auto` (the agent has no preference; the relay routes based on presence and surface capability) and `all` (broadcast to every connected surface paired to this agent). Surfaces declare their class in their Agent Card via the top-level `surface_class` field (§5.4); the relay routes by string match. Implementations may use additional class names — new surface categories do not require protocol changes. Surfaces should pick class names that describe the *category of interaction* (`thermostat`, `headset`) rather than a specific product (`nest_thermostat_v3`, `carplay`).

All agent-initiated messages should declare a `warrant` and may declare `if_unanswered` stakes — see §13 Initiative for full semantics. `urgency` is a rendering hint; `warrant` is the structured reason. Both can be carried on the same message and play complementary roles.

**Structured options.** When `options` is present:

- A surface that supports structured choices **SHOULD** render each option as a discrete selectable action.
- A surface that cannot render structured choices (e.g. voice-only or ambient surfaces) **MAY** ignore `options`; it **MUST** still deliver the notification and remain answerable via free-text `user_response`. The presence of `options` **MUST NOT** make a notification undeliverable or unanswerable on any surface.
- A voice surface **MAY** enumerate option `label`s aloud.
- Surfaces **SHOULD** render as many options as their form factor allows and **MAY** overflow excess options to a secondary affordance. The protocol does not constrain the number of options.
- When a user answers by selecting an option, the surface **MUST** set `result` to `answered` and `chosen_option` to that option's `id`.
- An agent **MUST NOT** assume a `chosen_option` will be returned. A user may reply in free text, the surface may not support options, or the notification may go unanswered. Agents **MUST** handle every `result` value and a possibly-absent `chosen_option` regardless of whether `options` was sent.

The `result` enum is unchanged. Unanswered, timeout, decline, and error semantics — and the `if_unanswered` / `ring_timeout_seconds` machinery — are unchanged; `chosen_option` is simply absent in those outcomes.

#### agent_notification_response (Surface → Relay → Bridge/Desktop)

Surface replies to an `agent_notification`. Relay forwards to the originating Bridge/Desktop.

```json
{
  "type": "agent_notification_response",
  "message_id": "matching id",
  "result": "answered | declined | dismissed | unavailable | error",
  "user_response": "If answered with text/speech, the user's reply",
  "conversation_id": "If conversation_handoff was true and user answered",
  "reason": "Present if result=error"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"agent_notification_response"` |
| `message_id` | string | Yes | The `message_id` of the `agent_notification` being answered. |
| `result` | string | Yes | Outcome: `answered`, `declined`, `dismissed`, `unavailable`, or `error`. |
| `user_response` | string | No | The user's reply. Present when `result` is `answered` with a text or speech reply. |
| `conversation_id` | string | No | Conversation identifier. Present when `conversation_handoff` was requested and the user answered. |
| `reason` | string | No | Human-readable failure detail. Present when `result` is `error`. |
| `chosen_option` | string | No | The `id` of the selected option, present only when `result` is `answered` and the answer came from an option selection. Absent for free-text answers, declines, dismissals, timeouts, and errors. `user_response` MAY accompany it but is not required. |

#### agent_initiated_message (Bridge/Desktop → Relay → Surface)

A non-interruptive async message from an agent. Routed to all online surfaces as a regular `chat_message` with `agent_initiated: true` set.

```json
{
  "type": "agent_initiated_message",
  "message_id": "uuid",
  "agent_id": "agent-id",
  "body": "Full message text",
  "thread_id": "Optional thread for conversation continuation"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"agent_initiated_message"` |
| `message_id` | string | Yes | UUID identifying this message. |
| `agent_id` | string | Yes | Identifier of the agent sending the message. |
| `body` | string | Yes | Full message text. |
| `thread_id` | string | No | Optional thread identifier for conversation continuation. |

#### set_dnd (Surface or Bridge → Relay)

Surface or Bridge tells relay whether the user is in Do Not Disturb. Relay uses this to filter low/medium urgency notifications.

```json
{ "type": "set_dnd", "enabled": true }
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"set_dnd"` |
| `enabled` | boolean | Yes | Whether Do Not Disturb is active. |

---

## 5. Agent Card Schema

The Agent Card is a JSON document declaring an agent's identity, capabilities, device metadata, and authentication methods. It is sent by the agent immediately after connection and stored by the relay for delivery to surfaces.

```json
{
  "protocol_version": "0.4",
  "agent": {
    "name": "My Agent",
    "description": "A helpful AI assistant",
    "version": "1.0.0",
    "author": "Developer Name"
  },
  "device": null,
  "capabilities": {
    "streaming": true,
    "emotions": ["neutral", "happy", "sad", "angry", "surprised",
                 "relaxed", "thinking", "excited", "confused", "love", "fear"],
    "memory": { "read": true, "write": true },
    "voice": { "tts_provider": "client", "stt_provider": "client" },
    "input_accepts": ["text"],
    "output_modalities": ["text"],
    "audio_format": null,
    "artifacts": false,
    "tools": [],
    "sensor_events": []
  },
  "initiation_profile": {
    "expected_warrants": ["task_decision_required", "user_authorized"],
    "expected_volume_per_day": "1-5",
    "typical_urgency": "medium",
    "requires_response_typical": true
  },
  "surface_class": null,
  "auth": {
    "methods": ["bridge_pairing_token"]
  }
}
```

`protocol_version` declares the protocol version this card conforms to (§10.1) — for example `"0.4"`. The relay declares its own protocol version the same way, in the `system: connected` event (§4.3).

`initiation_profile` is optional. When present, surfaces use it to render an informed-consent permission grant UI at install time. See §13 Initiative for full semantics.

`surface_class` is `null` for agents (which are message senders, not message receivers). Surfaces participating in the protocol declare their class here so agents can target initiations by class string — see §5.4 and §4.13.

Fleet aggregators (§14) add two top-level fields to the above shape: `agent_role: "aggregator"` and an `aggregates` block describing the fleet they cover. Bridges that participate in a fleet add `device.fleet_tags` (§14.5). See §14 for the aggregator-side Agent Card example and the full field semantics.

### 5.1 Agent Object (required)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Display name shown to users. |
| `description` | string | No | Brief description of the agent. |
| `version` | string | No | Semantic version of the agent. |
| `author` | string | No | Developer or organization name. |

### 5.2 Device Object (optional)

For devices projecting outward or headless machines. Null for cloud agents.

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Device category: `"vehicle"`, `"robot"`, `"appliance"`, `"sensor"`, `"hub"`, or custom. |
| `manufacturer` | string | Device manufacturer name. |
| `model` | string | Device model name/number. |
| `interaction_model` | string | `"standard"` (has onboard AI) or `"headless"` (no onboard AI, relay intelligence handles NL). |
| `status` | object | Open-ended device status (battery, location, mode, etc.). Updated via `agent_card` resend or `sensor_event` messages. |
| `available_actions` | array | Actions the device supports. Each entry declares `id`, `name`, `params` (with name, type, and optional `options` for enums). |
| `fleet_tags` | array | Optional fleet-membership tags for this bridge. Open taxonomy. Used by aggregators to subscribe to fleets via tag intersection — see §14.5. |

### 5.3 Capabilities Object (required)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `streaming` | boolean | true | Whether the agent supports streaming responses. |
| `emotions` | array | [] | List of supported emotion tags. Empty = no emotion support. |
| `memory` | object | {read: false, write: false} | Whether the agent reads/writes soul file memory. |
| `voice` | object | null | TTS/STT provider declarations. |
| `input_accepts` | array | ["text"] | What input the agent accepts: `"text"`, `"audio"`. |
| `output_modalities` | array | ["text"] | What the agent can output: `"text"`, `"audio"`, `"text+audio"`. |
| `audio_format` | object | null | If audio is supported: `codec`, `sample_rate`, `channels`. |
| `artifacts` | boolean | false | Whether the agent generates rich artifacts (documents, code, tables). If true, the surface renders artifact UI and the relay stores artifacts for cross-surface access. |
| `tools` | array | [] | Tool identifiers the agent can use (informational). |
| `sensor_events` | array | [] | Sensor event types the device will emit. |
| `initiation` | object | omitted | Surface-side initiation handling (interruption modes, whether `warrant` and `if_unanswered` are honored, whether structured notification options are supported, max concurrent pings). See §13 Initiative for schema. |

### 5.4 Surface Class (optional)

Surfaces declare their class identifier as the top-level `surface_class` field on their Agent Card. Agents reference this string when targeting an initiation via `agent_notification.target_surface` (§4.13).

Well-known surface classes: `phone`, `tablet`, `watch`, `desktop`, `car` (in-vehicle surfaces — Apple CarPlay, Android Auto, in-vehicle infotainment, aftermarket head units), `smart_speaker`, `kiosk`, `ambient`. Implementations may use additional class names. The taxonomy is open — new surface categories do not require protocol changes. Surfaces should pick names that describe the category of interaction (`car`, `headset`), not a specific product (`carplay`, `nest_thermostat_v3`).

`surface_class` is `null` (or omitted) for agents, which send rather than receive initiations.

---

## 6. Capability Negotiation

Capability negotiation is implicit through the Agent Card and runs in both directions. When either side receives the other's Agent Card, it adapts its behavior. Surfaces adapt their rendering to the agent's declared output capabilities, supported modalities, and initiation profile. Agents adapt their output to the surface's declared rendering capabilities, surface class, and initiation handling.

**Surface adapts to agent's card:**

| Agent Capability | If Declared | If Not Declared |
|------------------|-------------|-----------------|
| `streaming` | Surface handles `chat_stream_chunk` + `chat_stream_end` | Surface waits for `chat_response` |
| `emotions` | Surface parses `[emotion]` tags from response text, drives avatar expressions | Surface uses text-analysis heuristics for expression |
| `memory` | Surface loads and saves soul files, injects memory into system prompts | Surface skips memory operations |
| `output_modalities: audio` | Surface plays `audio_chunk` data directly | Surface runs text through TTS pipeline |
| `output_modalities: text+audio` | Surface plays audio AND displays text, extracts emotions from text | Surface falls back to whichever lower mode is supported (typically `text`) |
| `sensor_events` | Surface subscribes to declared sensor types, renders status UI | Surface shows chat-only interface |
| `artifacts` | Surface renders `artifact_create` content in dedicated UI panel, stores on relay | Surface ignores artifact messages, chat-only |
| `initiation_profile` | Surface renders informed-consent permission grant UI at install time using declared warrants, volume, urgency | Surface uses generic permission UI or grants Async-only by default |

**Agent adapts to surface's card:**

| Surface Capability | If Declared | If Not Declared |
|--------------------|-------------|-----------------|
| `surface_class` | Agent may target this class via `target_surface`; relay routes by string match (§2.3 rule 3) | Agent treats the surface as eligible only for `all` / `auto` routing |
| `capabilities.initiation.modes` | Agent honors the surface's interruption taxonomy — sends `negotiated`-mode initiations only when surface declares `negotiated` | Agent uses `immediate` semantics, falls back to `agent_initiated_message` for non-urgent contact |
| `capabilities.initiation.respects_warrant` | Agent assumes the surface will render `warrant`-aware UI (resume-task affordances for `task_decision_required`, etc.) | Agent assumes warrant is a hint only |
| `capabilities.initiation.respects_if_unanswered` | Agent assumes the surface may render countdowns or escalation UI based on `if_unanswered` | Agent treats `if_unanswered` as an end-to-end signal it must enforce itself |
| `capabilities.initiation.supports_structured_options` | Agent MAY send `agent_notification.options` and expect the surface to render discrete selectable choices, returning `chosen_option` | Agent assumes free-text response only; it MAY still send `options` (non-blocking) but should not rely on `chosen_option` coming back |
| `capabilities.supports_presence` | Agent expects `presence_update` messages and may use them for routing decisions | Agent does not rely on real-time presence signals from this surface |

**Text is the universal floor.** If `output_modalities` is undeclared (or empty), surfaces and agents MUST treat the implicit value as `["text"]`. Audio, video, haptic, and any other non-text modality requires explicit declaration via capability negotiation. The text floor lets every conforming surface render every conforming agent at minimum, regardless of richer capabilities either side may also declare.

### 6.1 Runtime Capability Updates

If either side's capabilities change during a session (e.g., an agent gains a new tool, or a surface's user enables a previously-disabled modality), that side resends its full Agent Card. The other side MUST handle mid-session Agent Card updates by re-evaluating capabilities.

---

## 7. Authentication Methods

APP supports several credential mechanisms (§3.2). This section details each. Implementations MAY support any subset; the well-known method strings (`bridge_pairing_token`, `oauth2`, `oidc`, `mtls`, `psk`, `jwt`, `api_key`) appear in the Agent Card's `auth.methods` array.

The well-known method strings listed here are a soft taxonomy — implementations MAY define additional method strings for mechanisms not listed, mirroring the open `surface_class` pattern. Conforming implementations should prefer the well-known strings where the mechanism matches.

### 7.1 Bridge Pairing Token

The primary authentication method used by reference clients. Obtained during a pairing flow (typically QR-based):

1. Agent generates a pairing code via the relay REST API (`POST /api/pair`).
2. Surface scans the QR code containing `{"type": "chitin-bridge", "relay": "wss://relay.chitin.chat", "bridge": "name", "bridgeId": "uuid"}`.
3. Surface claims the pairing code via the relay.
4. Relay issues a bridge pairing token to the agent.
5. Both sides store their credentials (agent stores its bridge pairing token; surface stores its JWT or other surface-side credential).

Bridge pairing tokens are persistent and non-expiring unless explicitly revoked. The token is bound to a specific (agent, surface) pairing at issuance.

The token discriminator string in `auth.methods` is `"bridge_pairing_token"`.

### 7.2 OAuth 2.0 / OIDC

For enterprise deployments and federated identity scenarios. The relay validates tokens against a configured identity provider (Azure AD, Okta, Auth0, Google Workspace, or any OIDC-compliant IdP). Configuration is per-developer-account in the relay developer portal.

Suits SSO, web-based pairing flows, and deployments where the organization has an existing IdP. Token scoping can be used to grant different agents or surfaces different permission levels.

The discriminator strings in `auth.methods` are `"oauth2"` and `"oidc"`.

### 7.3 API Key

For local development and testing. The developer includes an API key in the WebSocket connection URL. Long-lived but visible in connection logs and URL parameters; not recommended for production.

The discriminator string in `auth.methods` is `"api_key"`.

### 7.4 mTLS

For headless, kiosk, fleet-deployed, and CAC/PIV-derived-credential scenarios where there is no interactive pairing flow. Both sides present X.509 certificates at the WebSocket TLS handshake; the relay validates the surface or agent against a configured trust anchor (typically a tenant CA or a smart-card-derived chain).

mTLS suits deployments that already manage a PKI — defense, healthcare, regulated industrial, fleet operators — and that need machine-to-machine credential bootstrapping without a user pairing step.

Implementations using mTLS MUST validate the full certificate chain to a configured trust anchor and MUST reject connections whose presented certificate cannot be bound to a specific (agent, surface) tuple via the relay's identity mapping.

The discriminator string in `auth.methods` is `"mtls"`.

### 7.5 Pre-Shared Key (PSK)

For air-gapped deployments and environments where no online identity provider is available. A symmetric key is provisioned out of band to both the surface (or agent) and the relay; the credential is presented at connection time.

PSK suits closed deployments that need offline operation. Implementations using PSK MUST rotate keys on a schedule the deployer chooses and MUST treat each PSK as scoped to a specific (agent, surface) tuple.

The discriminator string in `auth.methods` is `"psk"`.

### 7.6 JWT

Short-lived bearer token issued by an identity service the relay trusts. Common for surface registration in consumer flows; usable for either role.

In consumer flows, JWTs are issued at user registration (anonymous device-generated UUID or email/password) and refreshed via the relay's REST API. In enterprise flows, JWTs may be issued by the IdP under §7.2.

The discriminator string in `auth.methods` is `"jwt"`.

### 7.7 Credential Storage

All credential types MUST be persisted using platform-appropriate secure storage. Implementations SHOULD prefer hardware-backed storage where available.

| Platform | Recommended storage |
|----------|---------------------|
| Apple platforms (iOS, macOS) | Keychain (`kSecAttrAccessibleAfterFirstUnlock` or stricter) |
| Windows | Credential Manager (DPAPI-protected) |
| Linux (desktop) | Secret Service (GNOME Keyring, KWallet) |
| Linux (server) | Deployment-specific; common patterns include systemd-creds, HashiCorp Vault, Kubernetes Secrets with appropriate RBAC, and TPM-backed storage via tpm2-tss. Implementers SHOULD follow their organization's existing secrets management practice. |
| Android | Android Keystore |
| Embedded / IoT | TPM, secure element, or vendor-provided secure storage |
| Fleet / industrial | HSM, TPM, or vendor-provided secure storage |

Credentials MUST NOT be stored in plaintext configuration files in production deployments. Development credentials (e.g., API keys for local testing) are exempt from the hardware-backed-storage SHOULD but still MUST NOT be committed to version control.

---

## 8. Encryption (E2EE)

End-to-end encryption is optional and layered on top of the base protocol. When enabled, the relay cannot read message content.

### 8.1 Key Exchange

Uses **ECDH P-256** (Elliptic Curve Diffie-Hellman) for key agreement:

1. Both sides generate ephemeral P-256 key pairs.
2. Public keys are exchanged during the connection handshake (included in the `system: connected` response and Agent Card).
3. Both sides derive a shared secret using ECDH.
4. Shared secret is used to derive AES-256-GCM encryption keys.

### 8.2 Message Encryption

Encrypted messages use **AES-256-GCM**:

- The `type` and `id` fields remain visible (the relay needs `type` for routing).
- All other fields are encrypted into a single `encrypted_payload` field.
- Each message uses a unique 96-bit IV (initialization vector).
- The authentication tag is appended to the ciphertext.

```json
{
  "type": "chat_stream_chunk",
  "id": "uuid",
  "encrypted_payload": "base64(iv + ciphertext + tag)",
  "e2ee": true
}
```

### 8.3 Relay Transparency

With E2EE enabled, the relay sees message type, ID, and routing metadata but cannot read content, parameters, or any payload data. This is verified by the encryption module's self-test (tamper detection, key isolation).

---

## 9. Error Handling

### 9.1 Agent Errors

When an agent encounters an error processing a request, it MUST send an `error` message with `reply_to` set to the originating message's `id`. The surface displays the error to the user.

Agents MUST NOT silently swallow errors. If the upstream LLM fails, the network times out, or any processing step fails, an error message must be sent.

### 9.2 Relay Errors

The relay sends errors for connection-level issues. These use the §4.9 `error` envelope, omitting `reply_to` (since they are not responses to a specific message) and including implementation-specific extension fields where useful:

```json
{
  "type": "error",
  "code": "connection_limit_exceeded",
  "message": "Your plan allows 5 concurrent connections. Upgrade at chitin.net/connect",
  "current": 5,
  "limit": 5,
  "upgrade_url": "https://chitin.net/connect/dashboard/billing",
  "timestamp": 1779235260000
}
```

### 9.3 Surface Error Display

Surfaces MUST display error messages to the user in a non-disruptive way (e.g., inline in the chat, not a modal alert). The error message text from the agent should be shown as-is — agents are responsible for writing user-friendly error messages.

---

## 10. Versioning

### 10.1 Protocol Version

The protocol version is declared in the Agent Card's `protocol_version` field (e.g., `"0.4"`). Semantic versioning:

- **Major version** (1.x → 2.x): Breaking changes. Surfaces and agents on different major versions may not be compatible.
- **Minor version** (0.2 → 0.3): New message types or fields. Backward-compatible. Unknown types/fields are silently ignored.
- **Patch version** (0.2.0 → 0.2.1): Clarifications, typos, no behavioral changes.

### 10.2 Backward Compatibility

New message types can be added in minor versions. Implementations MUST silently ignore unknown message types rather than disconnecting or throwing errors. This ensures that a v0.2 agent can communicate with a v0.1 surface — the surface simply ignores message types it doesn't recognize.

New fields can be added to existing message types. Implementations MUST ignore unknown fields.

### 10.3 Version Handling and Feature Detection

**The protocol version is exchanged, not negotiated.** Every APP-aware party declares its protocol version in a `protocol_version` field — agents and surfaces in their Agent Cards (§5), the relay in its `system: connected` event (§4.3). After Card Exchange (§3.3), every party knows every other party's declared version. APP deliberately stops there: there is no negotiation step, no version-based handshake, and no mandated version-gated behavior. The exchanged version is available for logging and diagnostics, and an implementation MAY use it for its own compatibility decisions, but the protocol requires none.

**Why no handshake.** APP evolves additively. Minor versions add message types and fields; §10.2 requires implementations to silently ignore unknown types and fields, so a newer peer and an older peer interoperate without either needing to act on the other's version. Compatibility is therefore a property of *capabilities*, not of *version numbers* — and capabilities are detected directly. Surfaces SHOULD check the Agent Card's declared capabilities rather than the protocol version to determine feature support: a v0.1 agent that supports audio streaming declares it in capabilities; a v0.2 agent that doesn't support it omits it. Capability detection (§6) is more reliable than version checking because it reports what a peer can actually do, not what its version number implies it might do.

**Major versions.** A major-version increment (1.x → 2.x) signals changes that are *not* additive — wire formats an older peer cannot parse by ignoring unknown content. APP v0.3 defines no version-negotiation mechanism because it introduces no such changes. If a future major version introduces a genuinely wire-incompatible format, that version will define an explicit negotiation mechanism at the same time, designed against the specific incompatibilities it introduces. Until then, adding negotiation machinery would be speculative.

See §6 for the capability-detection model and §5 for the `protocol_version` field.

---

## 11. Physical Surfaces and Device Integration

This section explains how APP extends beyond screen-based surfaces to physical devices — robots, vehicles, industrial machines, and IoT endpoints. The protocol's message types (`motor_command`, `sensor_event`, `device_action`) and the Agent Card's device metadata are designed to serve this entire continuum without requiring protocol revisions for each new device category.

### 11.1 The Envelope Principle

APP defines the **message envelope** — the JSON structure, required fields, timing semantics, and safety constraints. The **device designer** fills in the vocabulary — what commands exist, what parameters they take, what sensors report, and what values mean.

This separation is deliberate. The protocol does not encode domain expertise in agriculture, mining, warehouse logistics, or humanoid locomotion. The protocol provides the transport and interaction framework; surface and device implementers provide the domain knowledge.

| APP Defines | Device Designer Defines |
|------------------------|------------------------|
| `motor_command` structure: type, id, command, parameters, timing, safety | What commands the device supports: `move_to`, `harvest_row`, `weld_seam`, `dock` |
| `sensor_event` structure: type, id, sensor, value, trigger | What sensors exist: GPS, battery, yield rate, bin level, weld quality, proximity |
| `device_action` structure: type, id, action, parameters | What actions users can trigger: start, stop, change mode, skip zone, set schedule |
| Agent Card schema for declaring all of the above | The actual capability list, parameter schemas, value ranges, and safety flags |
| Timing modes (immediate, queued, synchronized) | Which commands support which timing modes on this hardware |
| Safety constraints (confirmation, timeout, abort) | Which commands are safety-critical and require user confirmation |

A robotics company integrates with APP by reading this spec, declaring their device's commands and sensors in an Agent Card, and writing a thin adapter that translates between APP messages and their hardware API. They bring domain expertise; the protocol provides transport, surface conventions, relay intelligence, and the human interaction layer.

### 11.2 The Surface Continuum

Physical surface integration is a continuum, not a binary. Each stage adds capability types to the surface declaration without changing the core protocol:

**Stage 1 — Stationary screen.** An iPad or monitor running an APP avatar surface. Fixed position, no physical actuation. Optional camera for presence detection. No `motor_command` support needed.

**Stage 2 — Motorized display.** A screen on a motorized mount that tilts toward customers, rotates to follow them, or adjusts height. Adds a small set of motor commands (`pan`, `tilt`, `height`). Minimal hardware integration.

**Stage 3 — Mobile screen robot.** A tablet mounted on a mobile base (like retail robots from Bear Robotics or Pudu). Adds locomotion commands (`go_to`, `follow_user`, `return_to_station`). The avatar is still on a screen; the robot provides mobility.

**Stage 4 — Humanoid with display.** A humanoid robot with a screen face displaying a VRM avatar. Combines physical gesture and locomotion with the protocol's avatar rendering vocabulary. The avatar's on-screen expressions synchronize with the robot's physical gestures via `timing.mode: "synchronized"`.

**Stage 5 — Full humanoid embodiment.** A humanoid robot where the agent controls physical expression directly — no screen. The protocol's emotion tags map to physical actuators: `[happy]` drives servo positions for a smile, `[thinking]` tilts the head and pauses movement.

An agent built for Stage 1 still works at Stage 5. The robot surface ignores capabilities the agent doesn't use; the agent ignores capabilities it doesn't understand. Graceful degradation is built into capability negotiation.

### 11.3 Device Projection — Smart Devices as Agents

Devices with onboard intelligence can connect to the relay as agents and project their presence to any APP surface. The device runs the agent; APP surfaces are additional presentation endpoints it can reach.

**Use cases:**

- **Vehicle → phone.** A connected vehicle projects to the owner's phone. The owner asks about charge status, starts climate control, or initiates summon — through a conversational interface. The car's onboard AI processes requests; responses flow back through the relay.
- **Robot → supervisor kiosk.** A warehouse robot projects to a control room kiosk. The supervisor interacts conversationally rather than walking to the robot. The robot sends `sensor_event` messages with status; the supervisor sends commands.
- **Smart home hub → every screen.** A home agent running locally projects to the kitchen kiosk, living room TV, and the family's phones. Same agent, same memory, multiple surfaces.
- **Cross-surface continuity.** A conversation starts on one surface and continues on another. Memory persists through the relay's soul file storage.

Example device Agent Card (vehicle):

```json
{
  "protocol_version": "0.4",
  "agent": {
    "name": "Electric Vehicle",
    "description": "Owner's electric vehicle",
    "version": "2026.8.1"
  },
  "device": {
    "type": "vehicle",
    "manufacturer": "Acme Motors",
    "model": "EV Sedan 2024",
    "interaction_model": "standard",
    "status": {
      "battery_percent": 72,
      "charging": false,
      "location": {"lat": 34.73, "lng": -86.59},
      "cabin_temp_f": 94,
      "security_mode": true
    },
    "available_actions": [
      {"id": "climate_start", "name": "Start climate", "params": []},
      {"id": "lock", "name": "Lock doors", "params": []},
      {"id": "unlock", "name": "Unlock doors", "params": []},
      {"id": "summon", "name": "Summon vehicle", "params": [
        {"name": "direction", "type": "string", "options": ["forward", "reverse"]}
      ]}
    ]
  },
  "capabilities": {
    "streaming": true,
    "emotions": ["neutral", "alert", "ready"],
    "memory": {"read": true, "write": false},
    "sensor_events": ["location", "battery", "security_alert", "charge_complete"]
  }
}
```

### 11.4 Headless Devices — Machines Without Screens, AI, or Voice

The largest category of potential APP endpoints is machines that have no screen, no speaker, no onboard AI, and no reason to have any of these. A combine harvester. A CNC machine. A welding robot. A warehouse AGV. A robot vacuum. An irrigation controller. These are purpose-built machines where human interaction is incidental to their purpose.

APP makes these machines conversationally accessible through a thin adapter and the relay-side intelligence layer.

**How it works:**

1. A thin adapter connects to the relay and publishes an Agent Card with `device.interaction_model: "headless"`.
2. The adapter sends periodic `sensor_event` messages with device state.
3. When a user sends a `chat_message` ("skip the kitchen today"), the relay-side intelligence layer reads the Agent Card's `available_actions` and maps natural language to a structured `device_action`.
4. The relay sends the `device_action` to the adapter; the adapter translates to the machine's native API.
5. The intelligence layer generates a natural language confirmation for the surface.

The device never sees natural language. It receives structured JSON commands and reports state.

Example headless device Agent Card (robot vacuum):

```json
{
  "protocol_version": "0.4",
  "agent": {
    "name": "Robot Vacuum",
    "description": "Living room robot vacuum",
    "version": "4.2.1"
  },
  "device": {
    "type": "appliance",
    "manufacturer": "Acme Robotics",
    "model": "RV-200",
    "interaction_model": "headless",
    "status": {
      "battery_percent": 64,
      "state": "cleaning",
      "current_zone": "master_bedroom",
      "bin_full": false,
      "zones_completed": ["living_room", "kitchen"],
      "zones_remaining": ["hallway", "office"]
    },
    "available_actions": [
      {"id": "start", "name": "Start cleaning", "params": []},
      {"id": "stop", "name": "Stop and stay", "params": []},
      {"id": "dock", "name": "Return to dock", "params": []},
      {"id": "clean_room", "name": "Clean specific room", "params": [
        {"name": "room", "type": "string",
         "options": ["living_room", "kitchen", "master_bedroom", "hallway", "office"]}
      ]},
      {"id": "exclude_zone", "name": "Skip a room", "params": [
        {"name": "room", "type": "string"}
      ]}
    ]
  },
  "capabilities": {
    "streaming": false,
    "emotions": [],
    "memory": {"read": false, "write": false},
    "sensor_events": ["state_change", "error", "zone_complete", "bin_full"]
  }
}
```

**Industrial examples:**

- **Combine harvester.** Sensors: `harvest_progress`, `fuel_level`, `position`. Actions: `start_row`, `end_row`, `return_to_start`, `set_speed`. A farmer asks "how's the north field?" through their phone and gets a synthesized status report.
- **CNC machine.** Sensors: `job_progress`, `tool_wear`, `coolant_level`. Actions: `pause`, `resume`, `abort_job`. A machinist asks "is the batch done yet?" from across the shop floor.
- **Warehouse AGV fleet.** Each AGV publishes its own Agent Card. A supervisor interacts with individual robots or asks fleet-level questions through a kiosk.
- **Irrigation controller.** Sensors: `soil_moisture`, `flow_rate`. Actions: `irrigate_zone`, `skip_zone`, `set_schedule`. "Don't water the east field tomorrow, it's going to rain."

The barrier to integration is intentionally low. A 50-line adapter script that reads a device's local API and publishes an Agent Card is all that's needed. The device manufacturer doesn't need to change anything.

### 11.5 Smart Home Ecosystem Integration

APP does not replace Matter, Zigbee, Z-Wave, Alexa, Google Home, or HomeKit. It sits above them as a conversational interaction layer.

| Layer | Examples | APP's Role |
|-------|----------|----------------------|
| Local radio protocol | Matter, Zigbee, Z-Wave, BLE, Thread | Not involved. |
| Smart home controller | Alexa, Google Home, Apple Home, Home Assistant | Not replaced. An APP smart home bridge integrates with these via their APIs. |
| Conversational interaction | **APP** | The gap no existing platform fills. |

An APP smart home bridge reads devices from an existing controller (most likely Home Assistant), generates Agent Cards, and connects to the relay. The entire home becomes conversationally accessible:

```
Home Assistant / Matter / HomeKit / Alexa
         │  Local API
         ▼
APP Smart Home Bridge (any conforming bridge)
         │  APP (WSS)
         ▼
APP Relay → APP Surfaces
```

This adds three things no smart home controller provides: conversational depth ("I'm going to bed" becomes a personalized sequence of actions), cross-device memory (the relay remembers preferences Alexa forgets), and aggregate intelligence ("Is the house secure?" synthesizes status across all devices in one response).

---

## 12. Ambient Surfaces

Ambient surfaces (Menu Bar Live, Watch, Lights Bridge, widgets) subscribe to continuous PresenceState broadcasts without participating in chat. They consume the emitted state from whichever active surface is driving the conversation.

### 12.1 Active surfaces emit PresenceState

Every active surface (e.g., phone, desktop, in-vehicle surfaces) SHOULD emit `presence_update` messages on state transitions (attention, mood, activity, urgency) and on new messages. Emission rate is coalesced by the client: debounce 250ms on rapid changes, force-emit on attention transitions, heartbeat every 30s if no changes.

Emission flows through the existing `/ws/surface` connection — no separate channel from the active surface side.

### 12.2 Ambient surfaces consume via `/ws/ambient`

New WebSocket route: `/ws/ambient`. Authenticated with the same bearer token as `/ws/surface` (query parameter `?token=…`). Receives ONLY `presence_update` messages — no chat, no TTS, no device actions. Lighter footprint than `/ws/surface`.

On connection: the relay immediately sends the user's latest cached PresenceState (if any). Subsequent updates stream in real-time.

### 12.3 Message type: `presence_update`

Shape:

```json
{
  "type": "presence_update",
  "agent_id": "bridge-id-abc123",
  "source_surface_id": "desktop-m1-mini",
  "presence": {
    "mood": "curious",
    "attention": "listening",
    "activity": null,
    "urgency": "none",
    "last_message": null,
    "personality_id": "warm_supportive",
    "agent_id": "bridge-id-abc123",
    "timestamp": "2026-04-18T14:23:00Z"
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Always `"presence_update"` |
| `agent_id` | string | Yes | Bridge/agent identifier this presence relates to. |
| `source_surface_id` | string | Yes | Identifier of the active surface that emitted this presence. |
| `presence` | object | Yes | The PresenceState payload — see `schemas/presence_state.json`. |

### 12.4 Throttling and fairness

The relay SHOULD throttle per-user broadcast to approximately **2 broadcasts per second** as a recommended default; operators MAY tune the rate based on relay capacity and deployment characteristics. Rapid client emissions are coalesced to the latest state — there is no replay buffer. Clients that need high-frequency internal updates should coalesce before emission. (Numeric rate limits are operator-tunable; the recommended default exists to anchor first-time implementations.)

### 12.5 Default-idle fallback

If the emitting active surface disconnects AND no other active surface emits within 60 seconds, the relay emits a synthetic `presence_update` with `{attention: "idle", mood: "neutral", activity: null, urgency: "none", last_message: null}` to all ambient subscribers for that user. This prevents ambient surfaces from stuck "speaking" or "thinking" states when all active surfaces go offline.

### 12.6 E2EE handling

`last_message.encrypted_snippet` is an opaque base64 string to the relay. The relay MUST NOT decrypt, parse, inspect, or log the plaintext. Only surfaces holding the user's ECDH-derived key can decrypt.

### 12.7 Agent Card capability flag

Bridges that support PresenceState advertise:

```json
{
  "capabilities": {
    "supports_presence": true
  }
}
```

Absence of this flag means the bridge does not emit PresenceState; ambient surfaces connected to that user will rely on the default-idle fallback.

---

## 13. Initiative

APP treats initiative as a negotiated property of the agent–surface relationship, not a fixed property of the channel. Either party may initiate contact when warranted, subject to the user's standing permissions and the receiving surface's declared capabilities.

This is a deliberate departure from earlier assumptions in the human-AI interaction literature. Panfili et al. (2021), studying voice assistants, proposed an additional Gricean maxim of "Priority" — that human initiative takes precedence in human-AI interactions because "humans and AIs are not (yet?) conversational equals." This holds for request-response appliances. It does not hold for delegated agents operating on a user's behalf. An agent that has been asked to monitor a build, watch a market, or coordinate a deploy is uncooperative if it withholds relevant observations until queried — it is violating the maxim of Quantity, not respecting Priority.

APP therefore expresses initiation as a structured negotiation between four parties: the agent (which has context and intent), the user (who grants standing authority), the surface (which renders the message, collects user response, and contributes presence awareness), and the relay (which enforces policy).

### 13.1 What initiation messages must declare

Every agent-initiated message — `agent_notification`, `agent_initiated_message`, or future initiation types — carries the fields below in addition to the urgency and routing fields documented elsewhere.

#### `warrant` (required)

Why the agent is reaching out. One of:

- `user_authorized` — the agent is following a standing instruction the user gave it ("ping me when the build finishes," "remind me about my 2pm"). The user has pre-consented to this category of contact.
- `task_decision_required` — the agent is paused inside a delegated task and needs input to proceed. The initiation is a resumption point; the agent is waiting and the task state is held.
- `external_event` — something in the world changed that the agent judges the user wants to know about (deadline approaching, threshold crossed, message arrived from a watched source). No reply is required.
- `unspecified` — backward-compatible default. Surfaces should treat as `external_event` for rendering purposes but may surface a warning to the user that the agent did not declare a warrant.

Surfaces use `warrant` to render meaningful UI. A `task_decision_required` ping deserves a "resume task" affordance and should suppress dismissal-without-response patterns. An `external_event` ping is informational and dismissable.

#### `if_unanswered` (optional)

Structured stakes. Tells the surface (and through it, the user) what happens if the initiation goes unaddressed. Mutually exclusive options:

```json
{
  "if_unanswered": {
    "kind": "proceeds_with_default",
    "default": "staging",
    "after_seconds": 240
  }
}
```

```json
{
  "if_unanswered": {
    "kind": "blocks_until_answered",
    "blocking_resource": "deploy pipeline"
  }
}
```

```json
{
  "if_unanswered": {
    "kind": "safe_to_ignore"
  }
}
```

```json
{
  "if_unanswered": {
    "kind": "reverts_at",
    "deadline": "2026-04-30T15:00:00Z"
  }
}
```

Surfaces that understand `if_unanswered` may render a countdown, display the consequence inline, or escalate urgency as the deadline approaches. Surfaces that do not understand the field ignore it without error. Agents should never rely on the surface to enforce the consequence — the agent itself is the source of truth for what happens next.

### 13.2 What surfaces declare

Surfaces extend their existing Agent Card capability block with an `initiation` object describing how they handle inbound initiation:

```json
{
  "capabilities": {
    "supports_presence": true,
    "initiation": {
      "modes": ["immediate", "negotiated", "scheduled"],
      "respects_warrant": true,
      "respects_if_unanswered": true,
      "max_concurrent_pings": 1
    }
  }
}
```

`modes` corresponds to McFarlane's interruption taxonomy. A surface that declares `negotiated` will hold non-`high` initiations until a suitable PresenceState attention transition (typically `aware → engaged`). A surface that declares only `immediate` delivers on receipt or not at all. A `scheduled` surface batches into digests at user-defined intervals.

Surfaces are not required to support all modes. A watch surface may declare `["immediate"]` only. A car surface may declare `["scheduled"]` only while in motion. A desktop surface typically supports all three.

### 13.3 What agents declare

Agents extend their Agent Card with an `initiation_profile` so users can grant informed consent at install time rather than discover behavior on the third notification:

```json
{
  "initiation_profile": {
    "expected_warrants": ["task_decision_required", "user_authorized"],
    "expected_volume_per_day": "1-5",
    "typical_urgency": "medium",
    "requires_response_typical": true
  }
}
```

Surfaces use this to render a meaningful permission grant UI. Permission tiers (None / Async only / Urgent only / All) operate independently of and on top of `initiation_profile` — the profile is disclosure, not authorization. (Per-agent permission tiers are surface-side authorization state, defined and enforced by individual surface implementations and the relay's policy layer; they are not part of the wire protocol but interact with `initiation_profile` to drive informed-consent UI.)

### 13.4 How the relay enforces

The relay validates `warrant` against the agent's permission tier before routing. `task_decision_required` and `user_authorized` warrants from agents granted "Async only" or higher are routed. `external_event` warrants count against rate limits more aggressively, since they are unsolicited by definition. The relay does not interpret `if_unanswered` — it is end-to-end information between agent and surface.

### 13.5 Why this matters

The protocol's stance on initiative is the difference between a notification system and a coworker-grade interaction model. Tool-call and request-response framings dominate today's agent protocols; APP takes the position that as agents take on delegated work, the surface must be able to render their initiative as legibly as it renders their responses. Initiation with declared warrant and stakes is what distinguishes "an agent doing its job" from "an app pestering you."

---

## 14. Fleet Aggregator

### 14.1 Overview

A **Fleet Aggregator** is an APP agent that fan-ins events from many bridges under the same user and presents itself to that user's surfaces as a single conversational agent — an interpreter and spokesperson for its fleet. The aggregator lets one agent subscribe to "all bridges tagged `irrigation` under this user," consume their `sensor_event` (§4.6) streams, dispatch `device_action` (§4.7) to specific members by `target_agent` (§4.12), and initiate to the user with `agent_notification` (§4.13) when the fleet collectively warrants attention.

The aggregator is related to but distinct from §13 Initiative. §13 defines the agent-initiation half of the pattern; §14 adds the **fan-in subscription** half. Aggregators are heavy senders of the `external_event` warrant — that is, in initiative terms, what an aggregator is — but the aggregator is not itself an initiation construct. It is the consumption side: an agent that takes a population of bridges as input and exposes a single conversational interface as output.

### 14.2 Pattern definition

The three interaction models in Appendix B (`"standard"` / `"headless"` / cloud-agent) are device-shaped — they describe whether the agent's intelligence lives on the device, in the cloud, or in the relay. The aggregator is a **fourth interaction shape**, orthogonal to the existing three: it describes how the agent *consumes* events, not where its intelligence lives. A bridge is simultaneously one of the three device-shaped models and either a fleet member or not; an aggregator can subscribe to a mix of Model-2 and Model-3 members. The fourth shape is declared on the agent (via `agent_role`), not on the device (via `device.interaction_model`).

Members remain first-class APP agents. A surface that connects directly to a fleet member sees it as a normal headless or standard bridge. The aggregator is an opt-in lens over fleet membership, not a replacement for it.

### 14.3 Agent role declaration

Connections to `/ws/bridge` declare their role via the top-level `agent_role` field on the Agent Card:

| Value | Meaning |
|---|---|
| `"bridge"` | Default. Provides events to the relay (today's behavior — surfaces and surface-targeted routing). Omitting the field is equivalent to declaring `"bridge"`. |
| `"aggregator"` | Consumes bridge events via subscription (§14.4). Aggregators MAY also provide their own `agent_notification` and `chat_response` traffic; the role declaration governs subscription eligibility, not message-emission rights. |

The field lives alongside `agent`, `device`, `capabilities`, and `available_actions` at the top level of the Agent Card. Aggregators connect on the existing `/ws/bridge` endpoint (§2.1) — no new transport route is introduced. The field's absence preserves today's behavior for every existing bridge; this is a backward-compatible addition.

The well-known values are open. Future roles MAY be added without protocol changes, matching the `surface_class` (§5.4) and `auth.methods` (§7) discipline.

### 14.4 Subscription

A connection declaring `agent_role: "aggregator"` MUST send an `aggregator_subscribe` message immediately after the relay acknowledges its Agent Card, and before any other traffic. The relay MUST NOT begin fan-out routing to that aggregator until the subscription is received and validated.

Wire format:

```json
{
  "type": "aggregator_subscribe",
  "id": "1f8a3c50-2b9d-4e7f-8c11-9e6f3a2b1d04",
  "fleet_tags": ["irrigation"],
  "timestamp": 1779235200000
}
```

At least one of `fleet_tags` or `bridge_ids` MUST be present. Both MAY be present; matches compose by union (a bridge is subscribed if it matches either specifier).

| Field | Type | Required | Description |
|---|---|---|---|
| `fleet_tags` | array<string> | At least one of `fleet_tags` / `bridge_ids` | Subscribe to bridges whose `device.fleet_tags` (§14.5) intersects this set. |
| `bridge_ids` | array<string> | At least one of `fleet_tags` / `bridge_ids` | Subscribe to specific bridges by ID. Fallback for narrow, debugging, or non-fleet integrations. |

**Mutability.** Subscriptions are **immutable for the life of the connection in v0.3.** An aggregator that needs to change its subscription MUST disconnect, reconnect, and re-issue `aggregator_subscribe` with the new set. The relay MUST NOT persist subscriptions across reconnects. Mutation via a separate `aggregator_subscribe_update` message is deferred to v0.4.

**Scope.** All subscriptions are per-user. The relay only fans events from bridges under the same user as the aggregator. Cross-user / cross-tenant aggregation is out of scope for v0.3 (see §14.9).

### 14.5 `device.fleet_tags`

Bridges declare fleet membership via the optional `device.fleet_tags` array on their Agent Card:

```json
{
  "device": {
    "type": "appliance",
    "manufacturer": "RainMachine",
    "model": "Pro",
    "interaction_model": "headless",
    "fleet_tags": ["irrigation", "farm-north"],
    "available_actions": []
  }
}
```

`fleet_tags` is `array<string>` and OPTIONAL. Empty or omitted means the bridge is not in any fleet — the default for existing bridges, preserving non-breaking behavior. A bridge MAY belong to multiple fleets simultaneously, which is why the field is an array rather than a single string: a smart-light bridge can be both `"smart-home"` and `"lighting"`; a delivery van can be both `"vehicles"` and `"fleet-west"`. Aggregator subscriptions match by set intersection.

**Taxonomy.** Open free-text. Implementations MAY use any tag strings. The well-known starter list is documented alongside `surface_class` (§5.4) and `auth.methods` discipline: `"irrigation"`, `"hvac"`, `"lighting"`, `"security"`, `"vehicles"`, `"sensors"`, `"meters"`. Operators and integrators define additional strings as their deployments require.

**Why on `device` and not on `agent`.** Fleet tags describe the bridge's place in a population of physical or logical assets — conceptually a device cohort. Putting `fleet_tags` on `agent` would mis-frame it for cloud-agent (non-device) bridges where `device: null` is correct. For cloud-agent fleets, a future revision MAY lift `fleet_tags` to top-level; v0.3 ships the device-side shape.

### 14.6 `aggregates` block

The aggregator-side Agent Card carries an `aggregates` block giving surfaces the fleet-context they need to render meaningful UI. The block is REQUIRED when `agent_role: "aggregator"` and absent otherwise:

```json
{
  "protocol_version": "0.4",
  "agent": { "name": "Irrigation Spokesperson", "version": "1.0.0" },
  "agent_role": "aggregator",
  "aggregates": {
    "fleet_tags": ["irrigation"],
    "members_total": 300,
    "members_online": 247,
    "last_member_change_at": "2026-05-14T09:14:00Z"
  },
  "capabilities": { "streaming": true }
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `fleet_tags` | array<string> | Yes | The tags this aggregator covers. Mirrors the subscription declaration (§14.4). |
| `members_total` | integer | Yes | Total fleet size including offline members. |
| `members_online` | integer | Yes | Currently online members. |
| `last_member_change_at` | string (ISO-8601) | No | Timestamp of the most recent fleet roster change (`bridge_online` or `bridge_offline` observed by the aggregator). Surfaces use this for stale-indicator UI. |

Surfaces use this block to render fleet-context affordances ("Irrigation Spokesperson — 247 of 300 controllers online") instead of treating the aggregator as a single anonymous agent. Per-member affordances continue to flow through `agent_list_request` / `agent_list_response` (§4.12); the `aggregates` block is for the headline view, not the roster.

**Refresh.** The aggregator re-sends its full Agent Card via §6.1 Runtime Capability Updates when the fleet roster changes. Aggregators SHOULD debounce roster changes to avoid card-storm: coalesce changes on a window of ~30s. Fine-grained member-transition events (one per `bridge_online` / `bridge_offline`) are out of scope for v0.3.

### 14.7 Routing

A sixth routing rule (§2.3) governs aggregator fan-in. Restated here for reference: when an aggregator is subscribed, the relay forwards `sensor_event`, `agent_card`, `bridge_online`, and `bridge_offline` from every matching bridge to that aggregator, in addition to existing surface and relay-intelligence routing. The aggregator's subscription does not replace or filter any existing rule.

**Why these four message types.** Aggregators consume telemetry (`sensor_event`), capability-or-status updates (`agent_card`), and roster (`bridge_online` / `bridge_offline`). Surface-bound chat traffic (`chat_response`, `chat_stream_chunk`) is not aggregator-relevant. `device_action` flows surface→bridge and is not aggregator input — aggregators dispatch `device_action` *out*, addressed by `target_agent`, but do not consume them.

**Multiple subscribers.** A bridge MAY be matched by more than one aggregator subscription. The relay fans each event to every matching aggregator. The relay does not arbitrate or partition; that is an aggregator-side concern.

### 14.8 Throttling and caching

Aggregator fan-in is throttled and cached using the same primitives as §12 PresenceState fan-out:

- **Latest-only caching for `agent_card`.** On subscribe, the relay sends the current cached card for each matching member (one card per online member). Subsequent card updates stream as they arrive.
- **Throttled fan-out for `sensor_event`.** The relay applies the same per-user throttling discipline as §12.4 (no replay buffer; coalesce to latest where possible). Aggregators that need higher-frequency telemetry MAY opt in via subscription parameters in a future revision; v0.3 ships with the default.
- **Roster events (`bridge_online` / `bridge_offline`)** are not throttled but are coarsely emitted (relay emits once per transition, not per heartbeat).

**Aggregator rate limits beyond throttling are operator-economic, not protocol-level.** As an operator-economic matter, per-aggregator notification throughput, sensor-event ingest cap, and subscription cardinality are operator-side concerns codified in operator runbooks. The SPEC defines what an aggregator can do; the operator defines how much.

### 14.9 What is NOT in v0.3

Surfaced explicitly to prevent scope drift:

- **Subscription mutation.** Subscriptions are connect-time only. Mutation via `aggregator_subscribe_update` is deferred to v0.4.
- **Cross-user / cross-tenant aggregation.** A v0.3 aggregator only sees bridges under the same user. Cross-user fleets (e.g., a utility company aggregating customer-owned solar inverters) raise privacy and authorization questions that are out of scope.
- **Payload-content filtering at subscription time.** Aggregators subscribe to bridges, not to event predicates. Filtering by sensor-event payload contents (e.g., "only `soil_moisture` events with `value < 15`") is an aggregator-side concern.
- **Bulk-action primitive.** Aggregators that want to act on N members emit N `device_action` messages with distinct `target_agent` values. There is no single "fan-out action" envelope in v0.3.
- **Cross-device query language.** Surfaces ask aggregators questions in natural language; aggregators compose responses. There is no protocol-level query primitive that operates over Cards or event streams.
- **Aggregator-of-aggregators recursion.** An aggregator subscribing to other aggregators raises composition-cycle and authority-layering questions that v0.3 does not decide.
- **Per-aggregator authentication beyond existing bridge pairing.** Aggregators use the same `auth.methods` as any other `/ws/bridge` connection.
- **Member-change events to surfaces.** Surfaces see fleet roster changes only as `aggregates.members_online` / `aggregates.members_total` deltas on the aggregator's Agent Card refresh. A `member_change_event` system message for fine-grained transitions is a v0.4+ candidate.

### 14.10 Initiative interaction

Aggregators interact with §13 Initiative without exception. An aggregator's `initiation_profile` typically declares `expected_warrants: ["external_event"]`, sometimes also `task_decision_required` for fleet-wide decisions. The distinguishing characteristic of aggregator initiation is sustained higher volume than single-device agents — a single irrigation controller might send 1–5 `agent_notification` per day; an irrigation aggregator over 300 controllers might send 10–50.

The relay's §13.4 enforcement applies to aggregators with no change. Aggregator rate limits — as distinct from §13's per-warrant policy — are operator-economic (§14.8) and live in operator runbooks, not in the SPEC.

### 14.11 Worked example

The canonical worked example is `examples/aggregator/`. The scenario is an Irrigation Spokesperson over 300 `RainMachine Pro` controllers. Each controller declares `device.fleet_tags: ["irrigation"]`; the aggregator declares `agent_role: "aggregator"` and subscribes to `fleet_tags: ["irrigation"]`. Surfaces render the `aggregates` block as "247 of 300 controllers online." A user asks "how are the fields?" → the aggregator composes a fleet-wide summary. When three zones lose pressure simultaneously, the aggregator emits `agent_notification` with `warrant: "external_event"` (§13.1) and `if_unanswered: { "kind": "safe_to_ignore" }`.

The example directory includes the bridge-side card, the aggregator-side card, the subscription message, an inbound `sensor_event`, an outbound `agent_notification`, and an outbound `device_action` dispatched to one specific member. See `examples/aggregator/README.md` for the full trace and `examples/aggregator/app.expected.jsonl` for the validated golden traces.

---

## Appendix A: Emotion Tags

Emotion tags are embedded in response text to drive avatar expressions on surfaces that support them.

**Format:** `[emotion_name]` at the start of a sentence.

```
[thinking] Let me consider that...
[happy] Great news — I found exactly what you need!
[excited] This is going to be amazing!
```

**Standard emotions:**

| Tag | Description |
|-----|-------------|
| `[neutral]` | Default state. No specific emotion. |
| `[happy]` | Joy, satisfaction, friendliness. |
| `[sad]` | Sympathy, disappointment, concern. |
| `[angry]` | Frustration, displeasure. |
| `[surprised]` | Unexpected information, astonishment. |
| `[relaxed]` | Calm, ease, comfort. |
| `[thinking]` | Consideration, processing, uncertainty. |
| `[excited]` | Enthusiasm, eagerness, high energy. |
| `[confused]` | Puzzlement, clarification needed. |
| `[love]` | Affection, warmth, deep care. |
| `[fear]` | Worry, anxiety, caution. |
| `[alert]` | Attention, notification, urgency (commonly used by device agents). |
| `[ready]` | Prepared, standing by (commonly used by device agents). |

Surfaces parse emotion tags using an `EmotionExtractor` that strips the tag before passing text to TTS. The emotion is interpreted by the surface in its own way — blend shapes on a VRM avatar, servo positions on a robot face, LED patterns on a simple device, or ignored entirely on a text-only surface.

Agents that do not support emotions simply omit the tags. Agents MAY use custom emotion tags beyond the standard set; surfaces SHOULD fall back to `[neutral]` for unrecognized tags.

---

## Appendix B: The Four Interaction Models

APP supports four distinct interaction architectures. The first three are device-shaped (they describe whether the agent's intelligence lives on the device, in the cloud, or in the relay); the fourth is consumption-shaped (it describes how an agent consumes events from many bridges).

**Model 1: Cloud Agent → Surface.** A cloud or local LLM agent connects to the relay and projects to any APP surface. The agent handles natural language. The surface renders.

**Model 2: Smart Device → Surface.** A device with onboard AI (car, robot, smart hub) connects as an agent and projects to surfaces. The device handles natural language locally.

**Model 3: Headless Device → Relay Intelligence → Surface.** A device with no AI connects via a thin adapter. The relay-side intelligence layer interprets natural language and maps it to the device's declared `available_actions`. The device receives structured `device_action` commands only.

**Model 4: Fleet Aggregator (cross-cutting).** An agent that consumes events from many bridges under the same user and presents to surfaces as a single conversational agent. Declared via `agent_role: "aggregator"` on the agent's Agent Card (§14.3). Members can be Model-1, Model-2, or Model-3 bridges; the aggregator is a consumption lens over a fleet, not a replacement for the underlying device-shaped model. See §14 for the full description.

The first three models are declared in the Agent Card's `device.interaction_model` field: `"standard"` for Models 1 and 2, `"headless"` for Model 3. When the relay sees `"headless"`, it activates the intelligence layer for that connection. Model 4 is declared via the top-level `agent_role` field (`"aggregator"`).

---

*This specification is a working draft. Version 0.4 (in draft) defines the core protocol including chat, streaming, physical device interaction, audio streaming, artifact delivery, multi-agent switching, the Initiative model (§13), and the Fleet Aggregator pattern (§14). Future minor versions will add A2A (Agent-to-Agent) bridge integration when the A2A protocol (currently v0.3, governed by the Linux Foundation) stabilizes sufficiently for committed integration.*

*Copyright 2026 Chitin, LLC. Licensed under Apache 2.0.*
