# DAIO Human Interaction Contract (Phase B6)

**Contract Standard**: `daio-agent/v1`  
**Milestone**: `PORTABILITY-PHASE-B6`  

---

## 1. HumanInteractionRequest Schema

```python
@dataclass
class HumanInteractionRequest:
    interaction_id: str
    work_id: str
    project_id: str = "default"
    change_id: Optional[str] = None
    interaction_type: HumanInteractionType = HumanInteractionType.APPROVAL
    requested_action: str = ""
    reason: str = ""
    summary: str = ""
    allowed_actions: List[str] = field(default_factory=lambda: ["APPROVE", "REVISE", "REJECT"])
    risk_class: HumanRiskClass = HumanRiskClass.SECURITY_SENSITIVE
    requires_strong_auth: bool = True
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    expires_at: Optional[str] = None
    evidence_refs: List[str] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

---

## 2. HumanInteractionResponse Schema

```python
@dataclass
class HumanInteractionResponse:
    interaction_id: str
    decision_id: str
    actor_id: str
    channel_id: HumanChannelType
    action: str  # "APPROVE", "REVISE", "REJECT", "ACKNOWLEDGE", "STOP", "RESUME"
    selected_option: Optional[str] = None
    comment: Optional[str] = None
    authentication_level: HumanAuthLevel = HumanAuthLevel.CHANNEL_AUTHENTICATED
    authenticated_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    received_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    channel_message_id: Optional[str] = None
    raw_channel_reference: Optional[str] = None
    idempotency_key: Optional[str] = None
    auth_proof: Dict[str, Any] = field(default_factory=dict)
    provenance: Dict[str, Any] = field(default_factory=dict)
```

---

## 3. Interaction Types & Delivery Lifecycles

### Interaction Types (`HumanInteractionType`):
- `APPROVAL`: Human Gate decision (APPROVE / REVISE / REJECT).
- `REJECTION`: Explicit rejection or cancellation request.
- `CHOICE`: Multi-option design or provider selection.
- `ACKNOWLEDGEMENT`: Informational notification requiring acknowledgment.
- `INFORMATION`: Read-only push notification.

### Delivery States vs Decision States:
$$\text{DELIVERY\_PENDING} \rightarrow \text{DELIVERED} \rightarrow \text{DECISION\_PENDING} \rightarrow \text{DECISION\_VERIFIED} \rightarrow \text{DECISION\_APPLIED}$$
A delivered message does **NOT** equal a decision.
