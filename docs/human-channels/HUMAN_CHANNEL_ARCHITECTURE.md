# DAIO Human Channel Federation Architecture

## 1. Overview & Core Federation Principles

Generic DAIO establishes two strictly orthogonal federation axes:

```text
                 ┌────────────────────────────────┐
                 │       ChatGPT (Architect)      │
                 │   High-Level Reasoning / Plan   │
                 └───────────────┬────────────────┘
                                 │
                                 ▼
                 ┌────────────────────────────────┐
                 │           DAIO Core            │
                 │ Orchestrator / FSM / WorkStore │
                 └───┬────────────────────────┬───┘
                     │                        │
                     ▼                        ▼
      ┌──────────────────────────┐   ┌──────────────────────────┐
      │  Agent Provider Router   │   │  Human Channel Router    │
      │  (Execution Federation)  │   │ (Interaction Federation) │
      └──────────────┬───────────┘   └────────────┬─────────────┘
                     │                            │
      ┌──────────────┼─────────────┐   ┌──────────┼──────────────┐
      ▼              ▼             ▼   ▼          ▼              ▼
     AGY          Gemini         Codex Telegram  LINE (Future) Cockpit
     CLI            CLI           CLI  Adapter   Messenger     (WebAuthn)
      │
   OpenCode / Claude Code (Future)
```

### Separation of Responsibilities

1. **ChatGPT**: Architect / reasoning / command origin.
2. **Telegram**: Human notification delivery + remote operational convenience command channel.
3. **DAIO Cockpit + Passkey / Face ID**: Hardware-backed strong human authorization.
4. **DAIO Core**: Canonical orchestration, state machine, work lease management, watchdog, atomic SQLite work store.
5. **AGY / Gemini / Codex / OpenCode / Claude Code**: Replaceable execution providers.

---

## 2. Invariants

### `DAIO-PORTABILITY-INVARIANT-001`
> Zero vendor-specific modifications or vendor branching (`if telegram`, `if line`, `if messenger`) in DAIO Core. All channel-specific code is isolated strictly in `scripts/daio_closed_loop/adapters/`.

### `DAIO-HUMAN-AUTH-INVARIANT-001`
> Notification channels and convenience command channels may request or initiate authorization, but they cannot substitute for strong authorization when the applicable DAIO policy requires hardware-backed Passkey / Face ID.

---

## 3. Human Channel Contract (`human_contract.py`)

The contract defines provider-neutral abstractions:

- `HumanChannelEvent`: Proactive notification envelope dispatched by DAIO.
- `HumanChannelCommand`: Normalized command structure received from human channels.
- `HumanChannelResponse`: Structured result returned to human channels.
- `HumanChannelIdentity`: Identity descriptor for allowlisting and access control.
- `HumanChannelAuditRecord`: Immutable audit envelope containing zero secrets.
- `HumanChannelAdapter`: Abstract base class implementing:
  - `send_notification(event: HumanChannelEvent) -> DeliveryStatus`
  - `receive_command(command: HumanChannelCommand) -> HumanChannelResponse`
  - `send_response(response: HumanChannelResponse) -> bool`
  - `health_check() -> HumanChannelState`
