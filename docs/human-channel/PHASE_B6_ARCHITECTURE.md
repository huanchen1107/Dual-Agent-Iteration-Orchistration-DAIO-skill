# DAIO Portability: Human Command, Interaction & Channel Federation (Phase B6)

**Contract Standard**: `daio-agent/v1`  
**Milestone**: `PORTABILITY-PHASE-B6`  
**Status**: `APPROVED`  

---

## 1. Executive Summary & Dual-Federation Architecture

Generic DAIO establishes **Two Orthogonal Federation Axes**:

```text
                  HUMAN
                    │
       ┌────────────┼─────────────┐
       │            │             │
    ChatGPT      Telegram        LINE
       │            │             │
       │         Messenger        │
       └────────────┼─────────────┘
                    │
                    ▼
       Human Interaction Gateway
                    │
        ┌───────────┴───────────┐
        │                       │
   Human Command          Human Interaction
  (Human -> DAIO)          (DAIO -> Human)
        │                       │
        └───────────┬───────────┘
                    ▼
             Canonical DAIO
                    │
          ┌─────────┴─────────┐
          │                   │
   Provider Router        HUMAN_GATE
          │                   │
 ┌────────┼────────┐          │
 │        │        │          │
AGY    Gemini    Codex      Passkey
 │        │        │        Face ID
OpenCode │   (future Claude)
          │
          ▼
     Engineering /
     Architecture
```

The system strictly decouples:
$$\text{Agent Provider Federation} \quad\times\quad \text{Human Channel Federation}$$

---

## 2. Separation of Core Concepts

The architecture enforces strict separation between:

1. **Human Command (`HumanCommand`)**: Human $\rightarrow$ DAIO. Unsolicited directives (e.g. *"Continue Change 052 until next Human Gate"*, *"Pause DAIO"*, *"Use Codex"*).
2. **Human Interaction (`HumanInteractionRequest` / `HumanInteractionResponse`)**: DAIO $\rightarrow$ Human $\rightarrow$ DAIO. Contextual notifications, choices, and Human Gate approvals.
3. **Authorization ($\neq$ Communication)**: Receiving an `"APPROVE"` message from Telegram/LINE/ChatGPT does **NOT** equal authorized mutation. High-risk actions strictly require Strong Authentication upgrade via Cockpit WebAuthn / Passkey / Face ID.

$$\text{COMMAND} \neq \text{INTERACTION} \neq \text{AUTHORIZATION}$$
