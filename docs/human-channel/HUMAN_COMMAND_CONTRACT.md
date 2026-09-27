# DAIO Human Command Contract & Normalization (Phase B6)

**Contract Standard**: `daio-agent/v1`  
**Milestone**: `PORTABILITY-PHASE-B6`  

---

## 1. HumanCommand Schema

```python
@dataclass
class HumanCommand:
    command_id: str
    actor_id: str = "project_owner"
    project_id: str = "default"
    source_channel: HumanChannelType = HumanChannelType.CHATGPT
    conversation_reference: Optional[str] = None
    intent: HumanCommandIntent = HumanCommandIntent.GET_STATUS
    target_work_id: Optional[str] = None
    target_change_id: Optional[str] = None
    requested_action: Optional[str] = None
    constraints: List[str] = field(default_factory=list)
    preferred_provider: Optional[str] = None
    stop_condition: Optional[str] = None
    risk_class: HumanRiskClass = HumanRiskClass.ROUTINE_ENGINEERING
    requires_strong_auth: bool = False
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    expires_at: Optional[str] = None
    provenance: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

---

## 2. Command Intent Taxonomy (`HumanCommandIntent`)

| Intent | Description | Default Risk Class |
| :--- | :--- | :--- |
| `START_WORK` | Initiates a new Change or work stream | `ROUTINE_ENGINEERING` |
| `CONTINUE_WORK` | Resumes active Change until stop condition / Human Gate | `ROUTINE_ENGINEERING` |
| `PAUSE_WORK` | Temporarily suspends execution | `WORKFLOW_CONTROL` |
| `RESUME_WORK` | Resumes paused execution | `ROUTINE_ENGINEERING` |
| `STOP_WORK` | Terminates active execution cycle | `WORKFLOW_CONTROL` |
| `GET_STATUS` | Queries live supervisor / queue / gate status | `READ_ONLY` |
| `GET_EVIDENCE` | Queries test results, diffs, and evidence | `READ_ONLY` |
| `GET_BLOCKERS` | Explains why work is blocked or at Human Gate | `READ_ONLY` |
| `SELECT_PROVIDER` | Directs task to specific CLI provider | `ROUTINE_ENGINEERING` |
| `RETRY_PROVIDER` | Forces retry with candidate provider | `ROUTINE_ENGINEERING` |
| `APPROVE` | Submits approval decision | `WORKFLOW_CONTROL` / `SECURITY_SENSITIVE` |
| `REVISE` | Submits revision instruction | `ROUTINE_ENGINEERING` |
| `REJECT` | Rejects proposed work | `WORKFLOW_CONTROL` |
| `ACKNOWLEDGE` | Acknowledges receipt of notification | `READ_ONLY` |

---

## 3. Natural Language Normalization Boundary

```text
ChatGPT / Telegram / LINE / Messenger (Free Text)
                 │
                 ▼
       HumanCommandNormalizer
  (Rule-based & heuristic intent parser)
                 │
                 ▼
            HumanCommand
                 │
                 ▼
        DAIO Command Gateway
```

Natural-language parsing executes strictly **ABOVE** DAIO Core. DAIO Core consumes canonical `HumanCommand` representations only.
