# Fleet Aggregator — Irrigation Spokesperson

Reference walkthrough of an APP **fleet aggregator** (fan-in agent) consuming a population of irrigation controllers and presenting itself to the user's surfaces as a single conversational agent. See [SPEC.md §14](../../SPEC.md) for the protocol semantics this example illustrates.

> **⚠️ Illustrative only.** No runnable adapter is shipped with v0.3 — the directory carries an Agent Card / subscription / fanned-event trace pattern to validate the wire shape. A Python or Node reference aggregator is a candidate for a later revision.

## Scenario

A farm operator runs **300 RainMachine Pro** irrigation controllers — one per zone. Each is an APP headless bridge (`device.interaction_model: "headless"`) declaring `device.fleet_tags: ["irrigation"]`. Without an aggregator, the operator's surfaces list 300 separate entries in `agent_list_response` and the operator addresses each controller by `target_agent`.

The operator deploys an **Irrigation Spokesperson** aggregator. It connects on `/ws/bridge` with `agent_role: "aggregator"` declared on its Agent Card, then issues an `aggregator_subscribe` for `fleet_tags: ["irrigation"]`. The relay fans `sensor_event`, `agent_card`, `bridge_online`, and `bridge_offline` from every matching controller to the aggregator. Surfaces render the aggregator's `aggregates` block as **"Irrigation Spokesperson — 247 of 300 controllers online."** The operator asks the aggregator natural-language questions about the fleet; the aggregator composes fleet-wide responses; when conditions warrant, the aggregator emits `agent_notification` with `warrant: "external_event"`. To act on a single controller the aggregator dispatches `device_action` with `target_agent` set to that controller's bridge ID.

## Architecture

```
Bridge-1..Bridge-300         Relay              Aggregator              Surface(s)
       │                       │                     │                       │
       ├─/ws/bridge connect───►│                     │                       │
       ├─agent_card───────────►│ (store + fan to     │                       │
       │  fleet_tags:          │  surfaces and       │                       │
       │   ["irrigation"]      │  matching aggregators)                      │
       │                       │                     │                       │
       │                       │◄────/ws/bridge──────┤ agent_role:aggregator │
       │                       │◄────agent_card──────┤                       │
       │                       │◄────aggregator_subscribe                    │
       │                       │ (validate + begin fan-out per §2.3 rule 6)  │
       │                       │                     │                       │
       │                       │ (aggregator's card fanned to surfaces)      │
       │                       ├──────────────agent_card────────────────────►│
       │                       │                     │                       │
       ├─sensor_event─────────►│                     │                       │
       │                       ├──sensor_event──────►│                       │
       │                       │                     │                       │
       │                       │◄──agent_notification─┤ (warrant:           │
       │                       │  external_event)    │                       │
       │                       ├──────agent_notification────────────────────►│
       │                       │                     │                       │
       │                       │◄──device_action─────┤  (target_agent:       │
       │                       │                     │   B-047)              │
       │                       ├──device_action─────►│                       │
       │  (to B-047 only)      │                     │                       │
```

## Wire traces

The `app.expected.jsonl` file in this directory carries three validated traces — the aggregator's Agent Card, the `aggregator_subscribe` it sends immediately after, and one inbound `sensor_event` it receives via fan-in. The traces parallel the per-example `app.expected.jsonl` discipline introduced by the v2 Prompt 1 corpus (e.g., [examples/raspberry-pi-zero/app.expected.jsonl](../raspberry-pi-zero/app.expected.jsonl)).

### Bridge-side Agent Card (one of 300 controllers)

```json
{
  "protocol_version": "0.4",
  "agent": {
    "name": "RainMachine Pro — Zone 47",
    "version": "2.4.0"
  },
  "device": {
    "type": "appliance",
    "manufacturer": "RainMachine",
    "model": "Pro",
    "interaction_model": "headless",
    "fleet_tags": ["irrigation", "farm-north"],
    "available_actions": [
      {
        "id": "irrigate_zone",
        "name": "Water a zone",
        "params": [
          {"name": "zone", "type": "string"},
          {"name": "duration_minutes", "type": "integer"}
        ]
      },
      {
        "id": "skip_zone",
        "name": "Skip zone in next cycle",
        "params": [
          {"name": "zone", "type": "string"},
          {"name": "reason", "type": "string"}
        ]
      }
    ]
  },
  "capabilities": {
    "streaming": false,
    "sensor_events": ["soil_moisture", "flow_rate", "zone_complete", "freeze_warning"]
  }
}
```

The only delta from the existing `examples/headless/README.md` irrigation snippet is `device.fleet_tags`. See [`examples/headless/README.md`](../headless/README.md) for the bridge-side controller pattern.

### Aggregator-side Agent Card

```json
{
  "protocol_version": "0.4",
  "agent": {
    "name": "Irrigation Spokesperson",
    "version": "1.0.0",
    "author": "Chitin, LLC"
  },
  "agent_role": "aggregator",
  "aggregates": {
    "fleet_tags": ["irrigation"],
    "members_total": 300,
    "members_online": 247,
    "last_member_change_at": "2026-05-14T09:14:00Z"
  },
  "capabilities": {
    "streaming": true,
    "emotions": ["neutral", "alert", "thinking"],
    "input_accepts": ["text", "audio"],
    "output_modalities": ["text", "audio"],
    "sensor_events": ["fleet_summary", "zone_anomaly"]
  },
  "initiation_profile": {
    "expected_warrants": ["external_event", "user_authorized"],
    "expected_volume_per_day": "5-50",
    "typical_urgency": "medium",
    "requires_response_typical": false
  },
  "auth": {
    "methods": ["bridge_pairing_token"]
  }
}
```

### `aggregator_subscribe` (sent immediately after the aggregator's card)

```json
{
  "type": "aggregator_subscribe",
  "id": "1f8a3c50-2b9d-4e7f-8c11-9e6f3a2b1d04",
  "fleet_tags": ["irrigation"],
  "timestamp": 1779235200000
}
```

Per [SPEC §14.4](../../SPEC.md), the aggregator MUST send this message immediately after the relay acknowledges its Agent Card and before any other traffic. Subscriptions are immutable for the life of the connection in v0.3.

### Inbound fanned `sensor_event` (from one of the 300 controllers)

```json
{
  "type": "sensor_event",
  "id": "9c4f12a8-5e7d-4b1c-9a3f-2d8e1c0b5f47",
  "sensor": "soil_moisture",
  "value": {
    "zone": "north-row-12",
    "moisture_pct": 11.4,
    "threshold_pct": 18.0
  },
  "trigger": "threshold",
  "timestamp": 1779235260418
}
```

The relay fans this event to subscribed aggregators per [SPEC §2.3 rule 6](../../SPEC.md). The same event continues to flow to surfaces and to the relay's per-device intelligence layer; aggregator delivery does not replace or filter existing routes.

### Outbound aggregator-emitted `agent_notification`

After observing low moisture across 23 zones in a 30-minute window, the aggregator initiates:

```json
{
  "type": "agent_notification",
  "message_id": "b3e9a721-04ef-4f3d-9c61-12fa78b35d92",
  "agent_id": "aggregator-irrigation-001",
  "urgency": "medium",
  "warrant": "external_event",
  "if_unanswered": {"kind": "safe_to_ignore"},
  "summary": "23 zones below moisture threshold (north field)",
  "body": "Soil moisture has crossed the configured threshold in 23 of 247 active zones over the last 30 minutes. Concentrated in the north field. No action required; flagging for awareness.",
  "require_response": false,
  "target_surface": "auto",
  "timestamp": "2026-05-14T09:48:00Z"
}
```

`warrant` and `if_unanswered` semantics follow [§13 Initiative](../../SPEC.md). The relay validates `warrant` against the aggregator's permission tier per §13.4 with no aggregator-specific path.

### Outbound aggregator-emitted `device_action` (to a single member)

```json
{
  "type": "device_action",
  "id": "7a2c3b14-9d5e-4f08-b6c2-3e8f1a9d2c41",
  "action": "irrigate_zone",
  "parameters": {
    "zone": "north-row-12",
    "duration_minutes": 25
  },
  "target_agent": "bridge-rainmachine-047",
  "source_message": "aggregator-decision-uuid",
  "timestamp": 1779235620000
}
```

`target_agent` (§4.12) is the existing addressing primitive; no new field is needed to route aggregator-emitted actions to a specific fleet member.

## Implementation notes

- **Illustrative only.** No runnable code is shipped with v0.3. The traces in `app.expected.jsonl` are validated wire-format samples, not the output of a live adapter. A reference Python or Node aggregator is a candidate for a later revision.
- **Subscription is immutable in v0.3.** An aggregator that needs to change its `fleet_tags` set must disconnect and reconnect with a new subscription. Mutation via `aggregator_subscribe_update` is deferred to v0.4. See [SPEC §14.4](../../SPEC.md).
- **Per-user scope.** All subscriptions are scoped to the same user. Cross-user / cross-tenant aggregation is out of scope for v0.3. See [SPEC §14.9](../../SPEC.md).
- **Operator-economic rate limits.** Per-aggregator notification throughput, sensor-event ingest cap, and subscription cardinality are operator-side concerns, not SPEC-normative. Operators codify these in their runbooks.

## See also

- [SPEC.md §14 Fleet Aggregator](../../SPEC.md) — the normative section this example illustrates.
- [SPEC.md §13 Initiative](../../SPEC.md) — `warrant` / `if_unanswered` semantics used by aggregator-emitted notifications.
- [examples/headless/README.md](../headless/README.md) — the per-controller bridge pattern (irrigation snippet around line 194).
