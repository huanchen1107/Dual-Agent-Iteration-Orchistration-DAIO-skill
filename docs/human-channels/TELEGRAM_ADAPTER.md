# Telegram Human Channel Adapter Specification

## 1. Scope & Purpose

`TelegramHumanChannelAdapter` enables DAIO to:
1. Dispatch proactive, mobile-friendly notifications on significant lifecycle events.
2. Accept read-only and low-risk operational commands from allowlisted Telegram users.
3. Intercept sensitive commands (`/approve`, `/revise`, `/stop`) and redirect to hardware-backed Cockpit Passkey / Face ID verification.
4. Maintain strict failure isolation: Telegram downtime or API errors will degrade adapter health without interrupting DAIO supervisor operations.

---

## 2. Command Set

| Command | Classification | Behavior |
|---|---|---|
| `/status` | `READ_ONLY` | Returns current DAIO supervisor health, active work item, and active agent provider. |
| `/queue` | `READ_ONLY` | Returns list of currently queued and in-progress work items. |
| `/current` | `READ_ONLY` | Returns detailed status and stage of active work item. |
| `/history` | `READ_ONLY` | Returns recent work execution results. |
| `/help` | `READ_ONLY` | Displays available command set and usage guidelines. |
| `/pause` | `OPERATIONAL_LOW_RISK` | Safely suspends queue processing without corrupting active work leases. |
| `/resume` | `OPERATIONAL_LOW_RISK` | Resumes queue processing (fails closed if active work is blocked on `HUMAN_GATE`). |
| `/approve` | `STRONG_AUTH_REQUIRED` | Intercepted! Returns Cockpit deep link for Passkey / Face ID verification. |
| `/revise` | `STRONG_AUTH_REQUIRED` | Intercepted! Returns Cockpit deep link for Passkey / Face ID verification. |
| `/stop` | `STRONG_AUTH_REQUIRED` | Intercepted! Returns Cockpit deep link for Passkey / Face ID verification. |

---

## 3. Notification Events

- `WORK_STARTED`: Triggered when DAIO begins execution on a new work item.
- `WORK_COMPLETED`: Triggered on successful verification and `GATE_PASS`.
- `WORK_FAILED`: Triggered on unrecoverable failure or stall.
- `HUMAN_GATE_REQUIRED`: Dispatches alert with `[Open Secure Cockpit]` deep link.
- `PROVIDER_FAILOVER`: Notifies when ProviderRouter transitions execution to a fallback CLI.
- `SUPERVISOR_DEGRADED`: Alerts if supervisor heartbeat or provider probes degrade.
- `SUPERVISOR_RECOVERED`: Notifies when healthy state is restored.

---

## 4. Notification Deduplication

To prevent Telegram spam during repeated supervisor ticks:
- Notifications are deduplicated by `(work_id, gate, recovery_epoch, event_type)`.
- Re-dispatch occurs only when a material state change occurs (e.g. recovery epoch increment or gate change).

---

## 5. Configuration & Environment Variables

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot API token issued by Telegram BotFather (never logged or committed). |
| `TELEGRAM_ALLOWED_USER_IDS` | Comma-separated allowlist of Telegram user IDs. |
| `TELEGRAM_ALLOWED_CHAT_IDS` | Comma-separated allowlist of Telegram group/direct chat IDs. |
| `TELEGRAM_COCKPIT_URL` | Base URL for iPhone Cockpit deep links (default: `https://cockpit.awin.internal`). |
