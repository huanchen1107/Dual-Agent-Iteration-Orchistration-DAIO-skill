# DAIO Human Authorization & Strong Authentication Upgrade Model (Phase B6)

**Contract Standard**: `daio-agent/v1`  
**Milestone**: `PORTABILITY-PHASE-B6`  

---

## 1. Normalized Authentication Levels (`HumanAuthLevel`)

1. **`UNVERIFIED`**: Anonymous or unauthenticated web/webhook payload.
2. **`CHANNEL_AUTHENTICATED`**: Authenticated by platform identity (e.g. Telegram User ID, LINE User ID, ChatGPT OAuth).
3. **`ACCOUNT_AUTHENTICATED`**: Bound to project owner account via pre-shared signature or token.
4. **`STRONG_AUTHENTICATED`**: Authenticated via Hardware / FIDO2 / WebAuthn Passkey (Apple Face ID / Touch ID / YubiKey) and Action Ticket.

---

## 2. Risk Classification Matrix (`HumanRiskClass`)

| Risk Class | Example Actions | Permitted Auth Level |
| :--- | :--- | :--- |
| `READ_ONLY` | `"Show status"`, `"Get blockers"`, `"View test evidence"` | `CHANNEL_AUTHENTICATED` |
| `ROUTINE_ENGINEERING` | `"Continue Change 052"`, `"Fix typos"`, `"Acknowledge"` | `CHANNEL_AUTHENTICATED` |
| `WORKFLOW_CONTROL` | `"Pause DAIO"`, `"Stop DAIO"`, `"Select Codex"` | `CHANNEL_AUTHENTICATED` / `ACCOUNT_AUTHENTICATED` |
| `SECURITY_SENSITIVE` | `"Human Gate APPROVE"`, `"Modify credentials"` | `STRONG_AUTHENTICATED` ONLY |
| `FINANCIAL_OR_PRODUCTION` | `"Live deployment"`, `"Production trading execution"` | `STRONG_AUTHENTICATED` ONLY |

---

## 3. Strong Authentication Upgrade Flow

```text
Telegram / LINE / ChatGPT
          │
          │ "APPROVE"
          ▼
HumanInteractionResponse (CHANNEL_AUTHENTICATED)
          │
          ▼
    Risk / Auth Policy
  (requires_strong_auth = TRUE)
          │
          ▼
  DECISION_REJECTED (STRONG_AUTH_REQUIRED)
          │
          ▼
  Secure Cockpit Deep Link
  https://cockpit.awin.internal/gate?interaction_id=...&ticket=...
          │
          ▼
   Apple Face ID / Passkey
          │
          ▼
  STRONG_AUTHENTICATED Decision
          │
          ▼
     DAIO Core
```
