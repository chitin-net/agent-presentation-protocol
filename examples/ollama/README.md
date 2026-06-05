# Ollama Local LLM

Connect your local Ollama model to any conforming APP surface. Persistent memory is a protocol affordance; the avatar pipeline and voice rendering are surface-side capabilities — Chitin's reference iOS surfaces are one option.

## How It Works

```
Ollama (localhost:11434)
  ▲
  │  HTTP POST /api/chat (streaming)
  │
APP Bridge (this script)
  │
  │  WSS → APP Relay (any conforming relay)
  ▼
APP Surfaces (any conforming surface)
```

Ollama runs on your machine. This script connects it to an APP relay so you can interact through any paired surface from anywhere — same network, different network, doesn't matter. The relay handles routing.

## Quick Start

### Prerequisites

- [Ollama](https://ollama.com) installed and running
- A model pulled (e.g., `ollama pull llama3.1`)
- Node.js 18+
- A bridge pairing token from your relay's pairing flow

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

const OLLAMA_URL = process.env.OLLAMA_URL || 'http://localhost:11434';
const MODEL = process.env.OLLAMA_MODEL || 'llama3.1';

// --- Agent Card (SPEC §5) ----------------------------------------------
// The model name is in the card, so any conforming surface can display
// which model is powering the conversation.
const AGENT_CARD = {
  protocol_version: '0.4',
  agent: {
    name: `Ollama (${MODEL})`,
    description: `Local ${MODEL} via Ollama`,
    version: '1.0.0'
  },
  capabilities: {
    streaming: true,
    emotions: ['neutral', 'happy', 'thinking'],
    memory: { read: false, write: false }
  }
};

// --- Connect to the relay ----------------------------------------------
const ws = new WebSocket(
  `wss://your-relay.example/ws/bridge?token=${process.env.BRIDGE_TOKEN}`
);

ws.on('open', () => {
  // Card Exchange: the Agent Card is the first message sent (SPEC §3.3).
  ws.send(JSON.stringify({ type: 'agent_card', card: AGENT_CARD }));
  console.log(`Connected to relay. Ollama model: ${MODEL}`);
});

ws.on('message', (raw) => {
  const message = JSON.parse(raw);
  if (message.type === 'chat_message') handleChatMessage(message);
});

// Happy-path connection only. For production heartbeat + reconnection,
// see examples/raspberry-pi-zero — it shows a full reconnect loop.

// --- Handle a chat message ---------------------------------------------
async function handleChatMessage(message) {
  const response = await fetch(`${OLLAMA_URL}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: MODEL,
      messages: message.messages,
      stream: true
    })
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let accumulated = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const lines = decoder.decode(value).split('\n').filter(Boolean);
    for (const line of lines) {
      const json = JSON.parse(line);
      const delta = json.message?.content || '';
      if (delta) {
        accumulated += delta;
        // chat_stream_chunk per delta (SPEC §4.2)
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
BRIDGE_TOKEN=your-bridge-token
OLLAMA_URL=http://localhost:11434   # default
OLLAMA_MODEL=llama3.1               # or any pulled model
```

## Adding Emotion Tags

Ollama models can emit emotion tags if you instruct them in the system prompt. Add this to the beginning of your messages array:

```javascript
const SYSTEM_PROMPT = `You are a warm, friendly AI companion.
Start each response with an emotion tag in brackets.
Available: [happy], [thinking], [excited], [neutral], [sad], [surprised].
Example: [thinking] That's an interesting question! Let me consider...
Keep responses to 2-3 sentences for natural conversation.`;

// Prepend to messages before sending to Ollama:
const messages = [
  { role: 'system', content: SYSTEM_PROMPT },
  ...message.messages.filter(m => m.role !== 'system')
];
```

## Using Different Models

Switch models by changing the environment variable:

```bash
OLLAMA_MODEL=mistral        # Fast, good for conversation
OLLAMA_MODEL=llama3.1       # Balanced
OLLAMA_MODEL=codellama      # Code-focused
OLLAMA_MODEL=phi3           # Small, runs on modest hardware
```

The model name appears in the Agent Card, so any conforming surface can display which model is powering the conversation.

## Initiation

The Ollama bridge is reactive only and has no agent-side state to initiate from; declare `initiation_profile` (SPEC §13) in the higher-level agent that wraps it.

## LM Studio

LM Studio exposes an OpenAI-compatible API. Use the same pattern with a different URL:

```javascript
const LM_STUDIO_URL = 'http://localhost:1234/v1/chat/completions';
// Same streaming SSE format as the OpenClaw example
```

## See Also

- [Main README](../../README.md) — Protocol overview
- [OpenClaw example](../openclaw/) — Similar pattern for OpenClaw gateways
- [LangChain example](../langchain/) — a LangChain agent in Python
