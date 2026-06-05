# Notification with structured options

Golden trace for `agent_notification.options` + `agent_notification_response.chosen_option` (SPEC §4.13).

Mirrors the whitepaper build-monitor vignette: an agent reports a failed build and offers three discrete
choices (Retry / Roll back / Investigate); the user selects one and the surface returns the chosen `id`.

`app.expected.jsonl`:

1. `agent_notification` carrying an `options` array.
2. `agent_notification_response` with `result: "answered"` and `chosen_option: "rollback"`.

Validated by `scripts/validate.py` against `schemas/messages.schema.json`. `options` is non-blocking:
a surface that cannot render it still delivers the notification and answers via free-text `user_response`.
