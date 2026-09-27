# DAIO Human Channel Router & Notification Failover (Phase B6)

**Contract Standard**: `daio-agent/v1`  
**Milestone**: `PORTABILITY-PHASE-B6`  

---

## 1. Configurable Routing Policy

Channel routing preferences are declared via provider-neutral configuration:

```yaml
human_channels:
  command:
    preferred:
      - chatgpt
      - telegram
      - line
      - messenger

  notification:
    preferred:
      - telegram
      - line
      - messenger
      - cockpit

  authorization:
    preferred:
      - cockpit
```

---

## 2. Notification Dispatch & Delivery Failover

When an interaction (e.g. Human Gate or completion notice) is emitted by DAIO:

```text
HumanInteractionRequest
           │
           ▼
  HumanChannelRouter
           │
           ├─► Attempt 1: Telegram ──► DELIVERY_FAILED (outage)
           │
           └─► Attempt 2: LINE ──────► DELIVERED (success)
```

The router seamlessly fails over across available notification channels without losing request metadata or dropping the interaction.

---

## 3. Decision Delivery vs State Ingestion Separation

$$\begin{aligned}
\text{Delivery Layer} &: \text{Telegram, LINE, Messenger} \quad (\text{Fast Notification}) \\
\text{Authorization Authority} &: \text{iPhone Cockpit / WebAuthn / Passkey} \quad (\text{High-Risk Authorization})
\end{aligned}$$
