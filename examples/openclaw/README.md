# OpenClaw / NemoClaw Bridge

Connect any OpenClaw or NemoClaw gateway to any APP surface via the relay.

This is the original APP use case — the Chitin Bridge is the reference implementation of this pattern.

## How It Works

```
OpenClaw Gateway (localhost:18789)
  ▲
  │  HTTP POST /v1/chat/completions (or persistent WebSocket)
  │
APP Bridge (this script)
  │
  │  WSS → APP Relay (any conforming relay)
  ▼
APP Surfaces (any conforming surface)
```

The bridge maintains two connections: one to the relay (outbound WSS, persistent) and one to the local OpenClaw gateway. Chat messages arrive from the relay, get forwarded to OpenClaw, and streaming responses flow back.

## Quick Start

### Prerequisites

- OpenClaw gateway running locally (`openclaw gateway` or equivalent)
- Node.js 18+
- A bridge pairing token (obtained via your relay's QR-code pairing flow)

### Install

```bash
npm install ws
```

### Run

APP is a WebSocket protocol — an agent connects to the relay, sends its
Agent Card, and exchanges JSON messages. This example uses the `ws`
package directly so the wire format is fully visible.

```javascript
const WebSocket = require('ws');

// --- Agent Card ---------------------------------------------------------
// Declares identity and capabilities (SPEC §5). The relay stores it and
// forwards it to surfaces during Card Exchange (SPEC §3.3).
const AGENT_CARD = {
  protocol_version: '0.4',
  agent: {
    name: 'My OpenClaw',
    description: 'Local OpenClaw gateway',
    version: '1.0.0'
  },
  capabilities: {
    streaming: true,
    emotions: ['neutral', 'happy', 'sad', 'angry', 'surprised',
               'thinking', 'excited', 'confused'],
    memory: { read: true, write: true }
  },
  initiation_profile: {
    expected_warrants: ['task_decision_required', 'user_authorized', 'external_event'],
    expected_volume_per_day: '1-10',
    typical_urgency: 'medium',
    requires_response_typical: true
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

// --- Handle a chat message ---------------------------------------------
async function handleChatMessage(message) {
  // Forward to OpenClaw's /v1/chat/completions endpoint
  const response = await fetch('http://localhost:18789/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${process.env.OPENCLAW_TOKEN}`
    },
    body: JSON.stringify({
      messages: message.messages,
      model: 'default',
      stream: true
    })
  });

  // Parse SSE and forward each delta as a chat_stream_chunk (SPEC §4.2)
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let accumulated = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const text = decoder.decode(value);
    for (const line of text.split('\n')) {
      if (!line.startsWith('data: ')) continue;
      if (line === 'data: [DONE]') break;

      const json = JSON.parse(line.slice(6));
      const delta = json.choices?.[0]?.delta?.content || '';
      if (delta) {
        accumulated += delta;
        ws.send(JSON.stringify({
          type: 'chat_stream_chunk',
          reply_to: message.id,
          delta,
          accumulated,
          timestamp: Date.now()
        }));
      }
    }
  }

  // chat_stream_end closes the stream (SPEC §4.2)
  ws.send(JSON.stringify({
    type: 'chat_stream_end',
    reply_to: message.id,
    content: accumulated,
    timestamp: Date.now()
  }));
}
```

### Environment Variables

```bash
BRIDGE_TOKEN=your-bridge-token-from-pairing
OPENCLAW_TOKEN=your-gateway-api-token
```

## NemoClaw

NemoClaw and other OpenClaw forks use the same `/v1/chat/completions` API. Change the port if your fork uses a different default:

```javascript
const GATEWAY_URL = process.env.GATEWAY_URL || 'http://localhost:18789';
```

## What Your Users Do

1. Install any conforming APP surface (Chitin's [Avatar](https://apps.apple.com/app/chitin-avatar) and [Phone](https://apps.apple.com/app/chitin-phone) are reference iOS surfaces)
2. Pair the surface to the bridge via QR code
3. Start talking — voice, text, or both

The surface handles user-facing rendering (text, voice, expression, memory) per the protocol's capability negotiation; your OpenClaw gateway handles agent intelligence.

## See Also

- [Main README](../../README.md) — Protocol overview
- [SPEC.md](../../SPEC.md) — Full specification
- [Chitin Bridge](https://chitin.net/downloads/ChitinBridge.dmg) — Pre-built macOS bridge app (no coding required)
