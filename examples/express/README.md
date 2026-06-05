# Express Server Wrapper

Wrap any existing HTTP API as an APP agent. If your backend has an API, this pattern gives it an avatar.

## How It Works

```
Your Existing API (any language, any framework)
  ▲
  │  HTTP requests (your existing API format)
  │
Express → APP Bridge (this script)
  │
  │  WSS → APP Relay (any conforming relay)
  ▼
APP Surfaces (any conforming surface)
```

This pattern is for when you already have a backend service and want to add a conversational interface without changing your existing code. The Express server translates between APP messages and your API's request/response format.

## Quick Start

### Install

```bash
npm install ws express
```

### Example: Customer Support Bot

APP is a WebSocket protocol — the agent connects to the relay, sends its
Agent Card, and exchanges JSON messages. This example uses the `ws`
package directly so the wire format is fully visible.

```javascript
const WebSocket = require('ws');
const express = require('express');

const app = express();
app.use(express.json());

// Your existing API — doesn't need to change
app.get('/api/order/:id', async (req, res) => {
  const order = await db.getOrder(req.params.id);
  res.json(order);
});

app.post('/api/support/ticket', async (req, res) => {
  const ticket = await db.createTicket(req.body);
  res.json(ticket);
});

// --- Agent Card (SPEC §5) — the APP agent wraps your API ---------------
const AGENT_CARD = {
  protocol_version: '0.4',
  agent: {
    name: 'Support Assistant',
    description: 'Customer support agent with order lookup',
    version: '1.0.0'
  },
  capabilities: {
    streaming: true,
    emotions: ['neutral', 'happy', 'thinking', 'confused'],
    memory: { read: true, write: true },
    artifacts: true,
    tools: ['order_lookup', 'create_ticket']
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
  // Use an LLM to interpret the user's request and call your API
  const llmResponse = await callLLM({
    messages: message.messages,
    tools: [
      {
        name: 'order_lookup',
        description: 'Look up an order by ID',
        parameters: { order_id: { type: 'string' } }
      },
      {
        name: 'create_ticket',
        description: 'Create a support ticket',
        parameters: {
          subject: { type: 'string' },
          description: { type: 'string' }
        }
      }
    ]
  });

  // If the LLM wants to call a tool, hit your existing API
  if (llmResponse.tool_calls) {
    for (const call of llmResponse.tool_calls) {
      if (call.name === 'order_lookup') {
        const order = await fetch(`http://localhost:3000/api/order/${call.args.order_id}`);
        // Feed result back to LLM for a natural response
      }
      if (call.name === 'create_ticket') {
        await fetch('http://localhost:3000/api/support/ticket', {
          method: 'POST',
          body: JSON.stringify(call.args)
        });
      }
    }
  }

  // Send the final response (SPEC §4.2)
  ws.send(JSON.stringify({
    type: 'chat_stream_end',
    reply_to: message.id,
    content: llmResponse.text,
    timestamp: Date.now()
  }));
}

app.listen(3000);
```

## Example: Simple FAQ Bot (No LLM)

For simple use cases, you don't even need an LLM — pattern match on the user's input:

```javascript
const FAQ = {
  'hours': '[happy] We are open Monday through Friday, 9 AM to 5 PM Central Time.',
  'return': '[neutral] Our return policy allows returns within 30 days of purchase with a receipt.',
  'shipping': '[happy] We offer free shipping on orders over $50. Standard shipping takes 3-5 business days.',
};

async function handleChatMessage(message) {
  const input = message.content.toLowerCase();
  let answer = "[thinking] I'm not sure about that. Let me connect you with a human agent.";

  for (const [keyword, faqAnswer] of Object.entries(FAQ)) {
    if (input.includes(keyword)) { answer = faqAnswer; break; }
  }

  // chat_stream_end carries the full response (SPEC §4.2)
  ws.send(JSON.stringify({
    type: 'chat_stream_end',
    reply_to: message.id,
    content: answer,
    timestamp: Date.now()
  }));
}
```

## Example: Kiosk Check-In

A hotel check-in kiosk where the avatar looks up reservations:

This agent declares `streaming: false` — responses are short, so it
replies with a single `chat_response` (SPEC §4.2) instead of a
`chat_stream_chunk` / `chat_stream_end` sequence.

```javascript
const AGENT_CARD = {
  protocol_version: '0.4',
  agent: { name: 'Concierge', version: '1.0.0' },
  capabilities: {
    streaming: false,  // Responses are short, no need to stream
    emotions: ['neutral', 'happy', 'excited'],
    artifacts: true    // Can show reservation details as an artifact
  }
};

// ...connect and dispatch chat_message as in the first example...

async function handleChatMessage(message) {
  // Check-in flow: look up reservation, display details as an artifact
  const reservation = await pms.findReservation(message.content);

  if (reservation) {
    // artifact_create — rich content rendered alongside the chat (SPEC §4.11)
    ws.send(JSON.stringify({
      type: 'artifact_create',
      id: crypto.randomUUID(),
      reply_to: message.id,
      artifact: {
        artifact_id: crypto.randomUUID(),
        title: 'Your Reservation',
        content_type: 'markdown',
        content: `## Welcome, ${reservation.guest_name}!\n\n` +
                 `**Room:** ${reservation.room}\n` +
                 `**Check-in:** ${reservation.check_in}\n` +
                 `**Check-out:** ${reservation.check_out}\n`
      },
      timestamp: Date.now()
    }));

    // chat_response — non-streaming complete reply (SPEC §4.2)
    ws.send(JSON.stringify({
      type: 'chat_response',
      reply_to: message.id,
      content: `[excited] Welcome, ${reservation.guest_name}! I found your reservation. Your room is ${reservation.room}. Would you like directions?`,
      timestamp: Date.now()
    }));
  } else {
    ws.send(JSON.stringify({
      type: 'chat_response',
      reply_to: message.id,
      content: "[thinking] I couldn't find a reservation with that name. Could you try your confirmation number instead?",
      timestamp: Date.now()
    }));
  }
}
```

## Initiation

The examples above are reactive (request/response). To make an Express wrapper agent-initiating — e.g., a webhook-driven service that pushes alerts to the user — declare an `initiation_profile` (SPEC §13) on the Agent Card describing the alert behavior.

## See Also

- [Main README](../../README.md) — Protocol overview
- [SPEC.md](../../SPEC.md) — Full specification, including artifact delivery (Section 4.11)
- [Device example](../device/) — For connecting physical devices instead of web APIs
