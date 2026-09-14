# LangChain Agent

Connect a LangChain agent to any APP surface.

## How It Works

```
LangChain Agent (your code)
  │
  │  raw WebSocket (the `websockets` library)
  ▼
APP Relay → APP Surfaces
```

Your LangChain agent runs wherever you want — your laptop, a cloud server, a Jupyter notebook. It opens a WebSocket to the relay, sends an Agent Card, and exchanges JSON messages. You implement the handler; the wire format is plain JSON (SPEC §4).

## Quick Start

### Install

```bash
pip install websockets langchain langchain-openai
```

### The agent

APP is a WebSocket protocol — the agent connects to the relay, sends its
Agent Card, and exchanges JSON messages. This example uses the
`websockets` library directly so the wire format is fully visible.

```python
import asyncio
import json
import os
import time
import websockets
from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage

# --- Agent Card (SPEC §5) ----------------------------------------------
AGENT_CARD = {
    "protocol_version": "0.4",
    "agent": {"name": "My LangChain Agent", "version": "1.0.0"},
    "capabilities": {
        "streaming": True,
        "emotions": ["neutral", "happy", "thinking", "excited"],
    },
    "initiation_profile": {
        "expected_warrants": ["task_decision_required", "user_authorized"],
        "expected_volume_per_day": "1-5",
        "typical_urgency": "medium",
        "requires_response_typical": True,
    },
}

llm = ChatOpenAI(model="gpt-4o", streaming=True)


# --- Handle a chat message ---------------------------------------------
async def handle(ws, message):
    messages = [
        SystemMessage(content=message["messages"][0]["content"]),
        *[HumanMessage(content=m["content"]) if m["role"] == "user"
          else SystemMessage(content=m["content"])
          for m in message["messages"][1:]]
    ]
    accumulated = ""
    async for chunk in llm.astream(messages):
        accumulated += chunk.content
        # chat_stream_chunk per delta (SPEC §4.2)
        await ws.send(json.dumps({
            "type": "chat_stream_chunk",
            "reply_to": message["id"],
            "delta": chunk.content,
            "accumulated": accumulated,
            "timestamp": int(time.time() * 1000),
        }))
    # chat_stream_end closes the stream (SPEC §4.2)
    await ws.send(json.dumps({
        "type": "chat_stream_end",
        "reply_to": message["id"],
        "content": accumulated,
        "timestamp": int(time.time() * 1000),
    }))


# --- Connect to the relay ----------------------------------------------
async def main():
    url = f"wss://your-relay.example/ws/bridge?token={os.environ['BRIDGE_TOKEN']}"
    async with websockets.connect(url) as ws:
        # Card Exchange: the Agent Card is the first message sent (SPEC §3.3).
        await ws.send(json.dumps({"type": "agent_card", "card": AGENT_CARD}))
        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("type") == "chat_message":
                await handle(ws, msg)


# Happy-path connection only. For production heartbeat + reconnection,
# see examples/raspberry-pi-zero — it shows a full reconnect loop.
asyncio.run(main())
```

That's it. Your LangChain agent is now accessible through every paired APP surface.

The sections below show variations on the `handle` function — the
connection scaffold above stays the same.

## With Emotion Tags

Add emotion tags to make the avatar react:

```python
SYSTEM_PROMPT = """You are a friendly AI companion. Express your emotions
by starting sentences with emotion tags like [happy], [thinking], [excited].
Keep responses conversational — 2-3 sentences for voice, longer for text.
Available emotions: neutral, happy, sad, angry, surprised, thinking, excited, confused."""

async def handle(ws, message):
    messages = [SystemMessage(content=SYSTEM_PROMPT)]
    for m in message["messages"][1:]:
        if m["role"] == "user":
            messages.append(HumanMessage(content=m["content"]))
    # ... then stream chat_stream_chunk / chat_stream_end as in the main example
```

## Surface-Aware Responses

Adapt response length based on which surface the user is on:

```python
async def handle(ws, message):
    surface = message.get("context", {}).get("surface", "unknown")

    if surface == "carplay":
        length_instruction = "Keep responses to 1-2 sentences maximum."
    elif surface == "ios_phone":
        length_instruction = "Keep responses to 2-3 sentences."
    else:
        length_instruction = "Respond at whatever length is appropriate."

    system = f"{BASE_PROMPT}\n\n{length_instruction}"
    # ... build messages and stream
```

## With LangChain Tools

LangChain tools work normally — the agent processes tool calls locally and returns the final response through the APP relay:

```python
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.tools import tool

@tool
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"It's 72°F and sunny in {city}."

agent_executor = AgentExecutor(
    agent=create_openai_tools_agent(llm, [get_weather], prompt),
    tools=[get_weather]
)

async def handle(ws, message):
    result = await agent_executor.ainvoke({"input": message["content"]})
    # Tool agents can't stream token-by-token — send the whole response
    # as a single chat_stream_end (SPEC §4.2).
    await ws.send(json.dumps({
        "type": "chat_stream_end",
        "reply_to": message["id"],
        "content": result["output"],
        "timestamp": int(time.time() * 1000),
    }))
```

Note: Tool-based agents typically can't stream token-by-token since they need to process tool calls internally. Send a single `chat_stream_end` for the final response.

## With Memory

Read the user's soul file to personalize responses:

```python
import uuid

# Soul file memory is read and written with memory_sync messages (SPEC §4.4).
# A `get` request is answered asynchronously by a `get_response` carrying the
# SoulFile JSON in `data`; correlate it by `reply_to` in your dispatch loop,
# alongside the `chat_message` branch in main().

# Request the user's memory:
await ws.send(json.dumps({
    "type": "memory_sync",
    "action": "get",
    "avatar_id": "global",
    "id": str(uuid.uuid4()),
}))

# When the get_response arrives, inject the stored facts into the prompt:
#   facts = soul_file.get("relationship", {}).get("facts", [])
#   system = f"{BASE_PROMPT}\n\nWhat you know about the user: " + "; ".join(facts)

# After generating a response and extracting new facts, write it back:
await ws.send(json.dumps({
    "type": "memory_sync",
    "action": "put",
    "avatar_id": "global",
    "data": updated_soul_file,
    "id": str(uuid.uuid4()),
}))
```

## Environment Variables

```bash
BRIDGE_TOKEN=your-bridge-token
OPENAI_API_KEY=your-openai-key
```

## See Also

- [Main README](../../README.md) — Protocol overview
- [SPEC.md](../../SPEC.md) — Full specification
- [Ollama example](../ollama/) — Same pattern with a local model instead of OpenAI
