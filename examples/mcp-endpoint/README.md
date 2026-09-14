# Chitin Inbound MCP Endpoint

The Chitin Bridge and Chitin Desktop applications expose a local MCP endpoint at
`http://localhost:18790/mcp` that allows external agent frameworks to drive Chitin
surfaces — speak through the user's avatar, display artifacts, show banner
notifications, ring the user, and more.

## Transport

Streamable HTTP per MCP spec 2025-03-26. Session managed via `Mcp-Session-Id`
header. Bearer-token authentication.

## Setup

1. In Chitin Desktop, open Settings > Inbound MCP.
2. Toggle "Accept connections from external agents" on.
3. Copy the API key shown (it's only displayed at generation -- rotate if lost).
4. Configure your MCP client with:
   - Endpoint: `http://localhost:18790/mcp`
   - Header: `Authorization: Bearer <your-key>`

Quick-install snippets for Claude Desktop, Claude Code, Cursor, and Copilot
Studio are in Chitin Desktop > Settings > Inbound MCP > Quick Install.

## Available tools

| Tool | Purpose |
|---|---|
| `chitin.speak` | Speak text through the user's avatar. |
| `chitin.stream_speak` | Stream text progressively for low-latency TTS. |
| `chitin.show_artifact` | Display an artifact in the Desktop Workspace panel. |
| `chitin.notify_user` | Send a notification; optionally ring for high urgency. |
| `chitin.send_message` | Send an async text message (no ring). |
| `chitin.get_connected_surfaces` | Query which Chitin surfaces are online. |
| `chitin.get_user_presence` | Get a coarse presence signal (active/idle/offline). |
| `chitin.set_personality_hint` | Suggest a personality (opt-in). |
| `chitin.read_user_memory` | Read from Chitin memory (Plus, per-agent opt-in). |
| `chitin.write_user_memory` | Add to Chitin memory (Plus, per-agent opt-in). |

## Patterns

### Ring the user, fall back to text

```
result = chitin.notify_user(
    urgency="high",
    warrant="task_decision_required",
    summary="Deploy target ambiguous",
    body="$ENV is unset. Staging or production?",
    require_response=true,
    ring_timeout_seconds=30,
    if_unanswered={"kind": "blocks_until_answered",
                   "blocking_resource": "deploy pipeline"},
    conversation_handoff=true
)

if result.result == "unavailable":
    chitin.send_message(
        body="I tried to reach you about the deploy. $ENV is unset -- "
             "reply 'staging' or 'production' when you're free."
    )
```

### Stream a long response through TTS

```
chitin.stream_speak(stream_id="s1", chunk="Welcome back. ", final=false)
chitin.stream_speak(stream_id="s1", chunk="Here's what I found: ", final=false)
chitin.stream_speak(stream_id="s1", chunk="...", final=false)
chitin.stream_speak(stream_id="s1", chunk="", final=true)
```

### Show a code artifact

```
chitin.show_artifact(
    kind="code",
    title="Proposed refactor",
    content="func refactored() { ... }",
    language="swift"
)
```

## Message types emitted

External agent tool calls map to these APP wire messages sent from Chitin
Bridge/Desktop to the relay and ultimately to surfaces:

- `agent_speak` -> `chat_response` (with `agent_initiated: true`)
- `agent_stream_chunk` -> `chat_stream_chunk`
- `agent_stream_end` -> `chat_stream_end`
- `agent_notification` -> `agent_notification` (carries `warrant` and optional `if_unanswered` per SPEC §13 Initiative)
- `artifact_create` -> `artifact_create`
- `agent_initiated_message` -> `chat_message` (with `agent_initiated: true`)

See the [APP spec](../../SPEC.md) Section 4.13 for full message shapes.
