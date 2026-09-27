# DAIO Agent Portability: Login-First CLI Architecture & Capability Discovery (Phase B3)

**Contract Standard**: `daio-agent/v1`  
**Milestone**: `PORTABILITY-PHASE-B3`  
**Status**: `APPROVED`  

---

## 1. Architectural Vision: Beyond API Keys

Prior AI agent architectures frequently assumed that agent providers require explicit API keys or cloud credentials configured in environment variables or configuration files.

DAIO v2.1 adopts a **Login-First CLI Model**:
> When a user has already installed and authenticated a local command-line agent tool (e.g., `agy`, `gemini`, `codex`, `opencode`, `claude`), DAIO interacts directly with the local authenticated CLI session rather than demanding external API keys.

```text
               ┌──────────────────────────────────────────────┐
               │                  DAIO Core                   │
               │  (FSM, Supervisor, Work Store, Human Gate)   │
               └──────────────────────┬───────────────────────┘
                                      │ (Zero Vendor Branching)
               ┌──────────────────────▼───────────────────────┐
               │    Provider-Neutral Agent Contract (v1)      │
               └──────────────────────┬───────────────────────┘
                                      │
               ┌──────────────────────▼───────────────────────┐
               │  Capability Discovery & Adapter Registry     │
               └───────┬──────────────┬──────────────┬────────┘
                       │              │              │
         ┌─────────────▼───┐   ┌──────▼──────┐   ┌───▼─────────────┐
         │ Antigravity CLI │   │ Gemini CLI  │   │   Codex CLI     │
         │ (`LOGIN_SESSION`)│  │(`LOGIN_SESSION`)│ (`LOGIN_SESSION`)│
         └─────────────────┘   └─────────────┘   └─────────────────┘
                       │              │
         ┌─────────────▼───┐   ┌──────▼──────────────┐
         │  OpenCode CLI   │   │ Future: Claude Code │
         │(`PROVIDER_DEP`) │   │  (`LOGIN_SESSION`)  │
         └─────────────────┘   └─────────────────────┘
```

---

## 2. Login-First Authentication Model

DAIO formalizes authentication modes via the canonical `AuthMode` enum:

| AuthMode | Semantics | Preference Order | Security Characteristics |
| :--- | :--- | :--- | :--- |
| **`LOGIN_SESSION`** | Authenticated interactive/unattended local session on the host | **1 (Highest)** | Zero API key handling; credentials never leave user's local keychain / session directories. |
| **`LOCAL_CREDENTIAL`**| Host-managed local certificate, socket, or agent daemon | **2** | Secured by local OS file permissions. |
| **`OAUTH`** | OAuth2 user authorization flow | **3** | Dynamic token lifecycle. |
| **`API_KEY`** | Traditional static environment API key | **4** | Fallback mode; requires explicit key provisioning. |
| **`PROVIDER_DEPENDENT`**| Multi-backend CLI (e.g. OpenCode) dynamically delegating auth | **5** | Varies by configured sub-engine. |
| **`UNAVAILABLE`** | Provider not installed or unauthenticated | **N/A** | Gracefully excluded from active candidate list. |

### Non-Destructive Auth Detection
The discovery engine inspects session markers non-destructively:
- **Zero Token Leakage**: No session files or tokens are read, copied, persisted, or logged.
- **Fail-Safe**: If a tool is missing or unauthenticated, the provider status is marked `NOT_INSTALLED` or `DEGRADED`, and DAIO continues normal operation.

---

## 3. Canonical Provider Descriptor

Each discovered or registered provider is described by a canonical `ProviderDescriptor`:

```python
@dataclass
class ProviderDescriptor:
    provider_id: str
    display_name: str
    transport: ProviderTransport          # CLI, API, CDP, SUBPROCESS, IPC
    auth_mode: AuthMode                  # LOGIN_SESSION, API_KEY, etc.
    installation_status: InstallationStatus # INSTALLED, NOT_INSTALLED, UNKNOWN
    auth_status: AuthStatus              # AUTHENTICATED, NOT_AUTHENTICATED, UNKNOWN
    availability: AvailabilityStatus      # AVAILABLE, UNAVAILABLE, DEGRADED
    capabilities: Set[AgentCapability]    # PROPOSE_EDITS, RUN_TESTS, etc.
    supported_roles: Set[AgentRole]       # ENGINEERING_EXECUTION, LEAD_ARCHITECT, etc.
    executable: Optional[str] = None     # Absolute path to binary
    version: Optional[str] = None        # Extracted version string
    supports_non_interactive: bool = True
    supports_structured_output: bool = True
    supports_sandbox: bool = True
    supports_unattended: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
```

---

## 4. Capability Matching & Discovery Workflow

When an orchestration turn requires an agent for a specific role (e.g., `ENGINEERING_EXECUTION`):

1. **Discovery**: `CLIProviderDiscovery.discover_all_cli_providers()` queries the host for known CLI binaries.
2. **Registry Indexing**: `AgentAdapterRegistry.register_descriptor()` updates provider catalog.
3. **Capability Matching**:
   ```python
   matches = registry.find_matching_descriptors(
       required_capabilities={AgentCapability.PROPOSE_EDITS, AgentCapability.RUN_TESTS},
       preferred_auth_mode=AuthMode.LOGIN_SESSION,
       preferred_transport=ProviderTransport.CLI,
       role=AgentRole.ENGINEERING_EXECUTION,
       only_installed=True,
   )
   ```
4. **Ranking Rule**:
   - `LOGIN_SESSION` CLI tools are prioritized over `API_KEY` backends.
   - `AVAILABLE` (installed & authenticated) tools rank ahead of `DEGRADED` tools.

---

## 5. Human Communication Channels — Architectural Extension

DAIO maintains a strict separation between **Human Decision Authority** and **Human Communication Transport**:

```text
            ┌─────────────────────────────────────────┐
            │          DAIO Human Gate Core           │
            │  (Authoritative Decision Ingress, FSM)  │
            └────────────────────┬────────────────────┘
                                 │
            ┌────────────────────▼────────────────────┐
            │       Canonical HumanDecisionEnvelope   │
            │     (WebAuthn / Passkey Auth Proof)     │
            └────────────────────┬────────────────────┘
                                 │
            ┌────────────────────▼────────────────────┐
            │         HumanChannelAdapter             │
            └───────┬────────────┬────────────┬───────┘
                    │            │            │
            ┌───────▼───┐ ┌──────▼───┐ ┌──────▼─────┐
            │Web Cockpit│ │LINE Bot  │ │Telegram Bot│
            └───────────┘ └──────────┘ └────────────┘
```

### Security Invariants:
1. **Zero Authorization Dilution**: External chat channels (LINE, Telegram, Messenger) act solely as notification delivery and decision intake channels.
2. **Canonical Decision Envelope**: Decisions must arrive packed in a `HumanDecisionEnvelope` with cryptographic or ticket-verified `auth_proof`.
3. **No Alternative Authorities**: Third-party messaging platforms cannot bypass Passkey / Face ID verification or mutate SQLite state outside the atomic DAIO Work Store.
