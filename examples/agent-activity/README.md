# Agent working state: start / progress / clear

Golden trace for `agent_activity` (SPEC §19) — an agent's own working-state indicator, distinct from
`presence`/`presence_update`, which describe the user's state, not the agent's.

An agent begins reading a batch of files in response to a turn, tags the activity with a `task_id`
correlating it back to the originating `chat_message` (`reply_to`) and a `ttl_seconds` self-expiry
floor, sends a `progress` update partway through with a refreshed label (and a refreshed `ttl_seconds`,
per §19.2.1's ttl-refresh rule) and no other fields, then clears it on completion.

`app.expected.jsonl`:

1. `agent_activity` with `event: "start"`, `task_id: "task-9f2c5e10"`, `label`, `kind: "tool_call"`,
   `reply_to`, and `ttl_seconds: 120`.
2. `agent_activity` with `event: "progress"`, the same `task_id`, and an updated `label`
   (`"Reading 40 files in src/ (18/40)"`) — no `kind`, `reply_to`, or `reason`, since none of those
   are meaningful on `progress` (§19.2.1).
3. `agent_activity` with `event: "clear"`, the same `task_id`, and `reason: "completed"`.

Validated by `scripts/validate.py` against `schemas/messages.schema.json`. See SPEC.md §19.4 for the
full clear-on-finish contract, including the relay's disconnect-triggered fallback and the surface-side
`ttl_seconds` floor for the case where the agent never gets to send the `clear` itself, and §19.2.1 for
the `progress` event's shape, its unknown-`task_id` handling, its rate-limiting/coalescing rules, and
why it needs no new capability flag.
