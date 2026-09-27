# DAIO Human Channel Security Model

## 1. Zero-Trust Identity Boundary

DAIO enforces strict allowlisting for all incoming human channel requests:
- Unlisted `external_user_id` or `chat_id` requests are rejected with status `REJECTED` and audited.
- Telegram identities are bounded strictly to `CHANNEL_AUTHENTICATED` level.
- Hardware-backed `STRONG_AUTHENTICATED` level is exclusively granted via iPhone Cockpit WebAuthn / Passkey / Face ID verification.

---

## 2. Strong Authorization Handshake

```text
Telegram User sends: /approve CHANGE_052
                      │
                      ▼
        TelegramHumanChannelAdapter
     (Interception: STRONG_AUTH_REQUIRED)
                      │
                      ▼
      Returns Secure Deep Link to Telegram:
      https://cockpit.awin.internal/gate?work_id=CHANGE_052&ticket=ticket-xxx
                      │
                      ▼
            User clicks Deep Link
                      │
                      ▼
          DAIO iPhone Cockpit UI
                      │
                      ▼
         Hardware Passkey / Face ID
                      │
                      ▼
      Cloudflare Worker Relay (/rpc/decision)
                      │
                      ▼
            DAIO Persistent Supervisor
             (Atomic SQLite WorkStore)
                      │
                      ▼
          Autonomous Continuation
                      │
                      ▼
      Telegram Resumption Notification:
         "Approved — execution resumed"
```

---

## 3. Secret Protection Invariants

1. **Zero Secret Leakage**: Bot tokens, bearer tokens, relay secrets, and encryption keys are never written to audit logs, traces, exception messages, or mobile responses.
2. **Audit Trail Completeness**: Every incoming command generates a `HumanChannelAuditRecord` with `timestamp`, `channel`, `external_user_id`, `project_id`, `command`, `authorization_class`, `accepted`, `reason`, `correlation_id`, and `work_id`.
