# Architecture Overview

The Agent Presentation Protocol (APP) is a presentation protocol that sits between agent backends and rendering surfaces, with a cloud relay handling routing, authentication, and storage.

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      AGENT BACKENDS                         │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐ │
│  │ OpenClaw │  │LangChain │  │  Sedan    │  │  Vacuum    │ │
│  │ Bridge   │  │  Agent   │  │ Onboard  │  │  Adapter   │ │
│  │          │  │          │  │    AI     │  │ (headless) │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └─────┬──────┘ │
│       │              │              │               │        │
│       │   APP (WSS + JSON)                           │        │
└───────┼──────────────┼──────────────┼───────────────┼────────┘
        │              │              │               │
        ▼              ▼              ▼               ▼
┌─────────────────────────────────────────────────────────────┐
│                APP Relay (any conforming relay)             │
│                                                             │
│  ┌────────────┐ ┌──────────┐ ┌────────────┐ ┌───────────┐ │
│  │  WebSocket │ │ Per-user │ │   E2EE     │ │  Relay    │ │
│  │  Router    │ │ Storage  │ │ Key Mgmt   │ │ Intelli-  │ │
│  │            │ │ (soul    │ │            │ │ gence     │ │
│  │ - Routing  │ │  files,  │ │ - ECDH     │ │           │ │
│  │ - Pairing  │ │  Agent   │ │   P-256    │ │ - NL→     │ │
│  │ - Auth     │ │  Cards,  │ │ - AES-256  │ │   Action  │ │
│  │            │ │  artifacts)│ │ -GCM     │ │ - Headless│ │
│  └────────────┘ └──────────┘ └────────────┘ └───────────┘ │
└───────┬──────────────┬──────────────┬───────────────┬────────┘
        │              │              │               │
        ▼              ▼              ▼               ▼
┌─────────────────────────────────────────────────────────────┐
│            APP Surfaces (any conforming surface)            │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐ │
│  │  Phone   │  │ Desktop  │  │ In-      │  │   Kiosk    │ │
│  │ surface  │  │ surface  │  │ vehicle  │  │  surface   │ │
│  │          │  │          │  │ surface  │  │            │ │
│  └──────────┘  └──────────┘  └──────────┘  └────────────┘ │
│                                                             │
│  Chitin maintains reference surfaces (Avatar, Phone,        │
│  Desktop, OS); see chitin.net.                              │
└─────────────────────────────────────────────────────────────┘
```

## The Relay: Transparent Message Router

A relay is a message router between agents and surfaces. Its core function is simple: forward JSON messages between paired connections via WebSocket. It does not interpret message content.

**What a conforming relay does:**
- Accepts WSS connections from agents (`/ws/bridge?token=`) and surfaces (`/ws/surface?token=`)
- Validates Agent Cards on connection and rejects malformed ones
- Matches agents to surfaces by `(user_id, agent_id)` pairing
- Forwards any JSON message type between paired connections per the routing rules in SPEC §2.3
- MAY persist soul files (opaque JSON keyed by `(user_id, agent_id)`) and artifacts; the relay never interprets soul file contents
- MAY enforce rate limits, connection limits, and authentication requirements per the operator's policy
- Runs the relay-side intelligence layer for headless devices

**What a conforming relay does NOT do:**
- Read or interpret message `content`, `parameters`, `data`, or `value` fields
- Perform LLM inference (except for the headless device intelligence layer)
- Render any UI
- Store conversation history (only soul files and artifacts, per the persistence option above)
- Know or care what kind of agent or surface is connected

Operator-economic constants (specific tier names, rate-limit numbers, retention windows, payload-size caps, persistence backends) are out of scope for the protocol; see the operator's own documentation.

## Message Flow

### Standard Chat (Model 1: Cloud Agent → Surface)

```
User speaks into iPhone
  │
  ▼
Surface: Apple Speech Framework (on-device STT)
  │  Converts speech → text
  ▼
Surface: Sends chat_message { content, messages[], context }
  │
  ▼
Relay: Routes to paired agent
  │
  ▼
Agent: Receives chat_message, runs LLM inference
  │  Generates streaming response with emotion tags
  ▼
Agent: Sends chat_stream_chunk { delta, accumulated }
  │  (repeated for each token group)
  ▼
Relay: Forwards to surface
  │
  ▼
Surface accumulates streaming text and triggers TTS at sentence boundaries
  │  On sentence boundary → fires TTS
  ▼
Surface sends each sentence to TTS for audio playback
  │  Audio plays while next sentence generates
  ▼
Surface: EmotionExtractor strips [emotion] tags, drives avatar expression
  │
  ▼
User hears response and sees avatar react
```

### Device Projection (Model 2: Smart Device → Surface)

```
Device (e.g., an electric vehicle) connects to relay as agent
  │  Sends Agent Card with device metadata + available_actions
  │  Sends periodic sensor_events (battery, location, etc.)
  ▼
Relay: Stores Agent Card, forwards to surface
  │
  ▼
Surface: Renders device status UI (battery indicator, map, action buttons)
  │
User speaks: "Warm up the car"
  │
  ▼
Surface: Sends chat_message to relay → routes to device
  │
  ▼
Device: Onboard AI interprets request, executes climate_start
  │  Sends chat_response: "[ready] Starting climate control. Cabin is at 94°F,
  │  I'll have it comfortable in about 10 minutes."
  ▼
Surface: Displays response, avatar speaks, updates status UI
```

### Headless Device (Model 3: Headless → Relay Intelligence → Surface)

```
Device adapter connects to relay
  │  Sends Agent Card with interaction_model: "headless"
  │  Sends periodic sensor_events (state, battery, progress)
  ▼
Relay: Stores card, notes headless mode
  │
User speaks: "Skip the kitchen today"
  │
  ▼
Surface: Sends chat_message to relay
  │
  ▼
Relay Intelligence Layer:
  │  Reads Agent Card → sees available_actions
  │  Maps "skip the kitchen" → { action: "exclude_zone", params: { room: "kitchen" } }
  │  Sends device_action to adapter
  │  Generates confirmation: "Got it — I'll skip the kitchen for this run."
  │  Sends chat_response to surface
  ▼
Surface: Avatar speaks confirmation
  │
Adapter: Receives device_action, calls device native API
```

## Persistent State

A conforming relay maintains three classes of persistent state, all keyed by the parties involved:

| Class | Scope | Contents |
|-------|-------|----------|
| Credentials and pairings | Per-(agent, surface) | Bridge pairing tokens, JWTs, or other credential material binding an agent to a surface. |
| Soul files | Per-(user, agent) | Opaque JSON memory blobs. The relay stores and retrieves them but never reads, validates, or indexes their contents. |
| Artifacts | Per-(user, artifact) | Opaque rich-content blobs (markdown, code, tables, images). Same opacity rule. |

Storage backend, schema, indexing, and retention policy are implementation-defined.

## Security Model

```
Agent ◄──── E2EE (optional) ────► Surface
  │                                   │
  │  WSS/TLS                          │  WSS/TLS
  ▼                                   ▼
            APP Relay (any conforming relay)
           (sees type + routing metadata)
           (cannot read encrypted content)
```

- **Transport security:** All connections use WSS (TLS). No plaintext connections.
- **Authentication:** Bridge pairing tokens (agents), JWT (surfaces). Tokens scoped to specific pairings.
- **E2EE (optional):** ECDH P-256 key exchange + AES-256-GCM encryption. When enabled, the relay sees message `type` and `id` but cannot read `content` or any payload fields.
- **Relay transparency:** The relay is designed to be unable to read user conversations even if compromised, when E2EE is enabled.

## Capability Negotiation

Both sides declare what they support. Features degrade gracefully:

```
Agent connects → sends Agent Card
  │
  ├── capabilities.streaming: true?
  │     YES → surface uses chat_stream_chunk pipeline
  │     NO  → surface waits for chat_response
  │
  ├── capabilities.emotions: ["happy", ...]?
  │     YES → surface parses [emotion] tags, drives avatar
  │     NO  → surface uses text-analysis heuristics
  │
  ├── capabilities.output_modalities: includes "audio"?
  │     YES → surface plays audio_chunk data directly
  │     NO  → surface runs text through TTS pipeline
  │
  ├── device.interaction_model: "headless"?
  │     YES → relay activates intelligence layer
  │     NO  → relay forwards messages transparently
  │
  └── capabilities.artifacts: true?
        YES → surface renders artifact UI
        NO  → surface ignores artifact messages
```

## Protocol Positioning

```
┌──────────────────────────────────────────────────────────┐
│                    Application Layer                      │
│                                                          │
│  ┌─────────┐  ┌──────────────┐  ┌─────────────────────┐ │
│  │   MCP   │  │     A2A      │  │       APP           │ │
│  │         │  │              │  │                     │ │
│  │  Tool   │  │    Agent     │  │   Presentation +    │ │
│  │ Access  │  │ Coordination │  │ Physical Interaction│ │
│  └─────────┘  └──────────────┘  └─────────────────────┘ │
│                                                          │
│  These protocols compose — a complete agent stack         │
│  uses all of them.                                       │
└──────────────────────────────────────────────────────────┘
```

MCP gives agents tools. A2A lets agents collaborate. APP gives agents a presentation layer — a way to meet users across any conforming surface, including devices that project their own onboard agent.

## See Also

- [SPEC.md](../SPEC.md) — Full protocol specification
- [Authentication](./authentication.md) — Auth methods in detail
- [Physical Devices](./physical-devices.md) — Robotics, IoT, and industrial integration
- [Smart Home](./smart-home.md) — Home Assistant and ecosystem integration
