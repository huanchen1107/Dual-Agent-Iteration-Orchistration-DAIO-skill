"""C1.4 v1: manual, proposal-only durable handoff contracts.

No authentication material or provider output belongs in these records.
Authorization and quiescence receipts are supplied by the trusted controller,
never inferred from model prose. Native IDE and CLI lifecycles are distinct.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import re

CONTRACT_VERSION = "daio-handoff/v1"
CHECKPOINT_VERSION = "daio-checkpoint/v1"


class Outcome(str, Enum):
    SUCCESS = "SUCCESS"
    ENGINEERING_FAILURE = "ENGINEERING_FAILURE"
    TEST_FAILURE = "TEST_FAILURE"
    BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    CAPACITY_EXHAUSTED = "CAPACITY_EXHAUSTED"
    RATE_LIMITED = "RATE_LIMITED"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    INCOMPATIBLE = "INCOMPATIBLE"
    HUMAN_GATE_REQUIRED = "HUMAN_GATE_REQUIRED"
    STALE_EXECUTION = "STALE_EXECUTION"
    SUPERSEDED_WORK = "SUPERSEDED_WORK"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class TestStatus(str, Enum):
    __test__ = False
    NOT_RUN = "NOT_RUN"
    PASSED = "PASSED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


CAPACITY_OUTCOMES = frozenset({
    Outcome.BACKEND_UNAVAILABLE,
    Outcome.QUOTA_EXHAUSTED,
    Outcome.CAPACITY_EXHAUSTED,
    Outcome.RATE_LIMITED,
    Outcome.TEMPORARILY_UNAVAILABLE,
    Outcome.AUTHENTICATION_REQUIRED,
})


class SafetyError(RuntimeError):
    pass


class StaleExecution(SafetyError):
    pass


def value(x):
    return x.value if isinstance(x, Enum) else x


def admission_reason(work):
    """Recognize explicit durable state, not incidental words in instructions."""
    metadata = work.metadata or {}
    status = value(work.status)
    if status in {"COMPLETED", "FROZEN", "SUPERSEDED", "STOP", "STOPPED", "HUMAN_GATE_REQUIRED"}:
        return status
    if value(work.current_gate) == "HUMAN_GATE" or work.human_gate_reason:
        return "HUMAN_GATE_REQUIRED"
    if work.last_decision in {"STOP", "REJECT"}:
        return "STOP"
    if metadata.get("frozen") or metadata.get("milestone_state") == "FROZEN":
        return "FROZEN"
    if metadata.get("superseded_by") or metadata.get("superseded"):
        return "SUPERSEDED_WORK"
    if metadata.get("stopped"):
        return "STOP"
    return None


def require_admission(work):
    reason = admission_reason(work)
    if reason:
        raise SafetyError("Execution admission denied: " + reason)


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(data):
    return hashlib.sha256(canonical(data).encode()).hexdigest()


def identifier(text):
    if not isinstance(text, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", text):
        raise SafetyError("Expected bounded non-secret identifier")
    return text


def hash_value(text):
    if not isinstance(text, str) or not re.fullmatch(r"[0-9a-f]{64}", text):
        raise SafetyError("Expected SHA-256 digest")
    return text


@dataclass(frozen=True)
class PublicationToken:
    work_id: str
    work_revision: int
    event_sequence: int
    execution_attempt_id: str | None
    fencing_token: int


@dataclass(frozen=True)
class BackendIdentity:
    backend_id: str
    adapter: str
    adapter_version: str
    transport: str
    execution_mode: str = "PROPOSAL_ONLY"

    def validate(self):
        expected = {"antigravity_cli": ("AntigravityCLIAdapter", "CLI"),
                    "codex_cli": ("CodexCLIAdapter", "CLI"),
                    "codex_ide_manual": ("CodexIDEManual", "MANUAL")}
        if self.backend_id not in expected or (self.adapter, self.transport) != expected[self.backend_id]:
            raise SafetyError("Unrecognized backend identity or transport")
        identifier(self.adapter_version)
        if self.execution_mode != "PROPOSAL_ONLY":
            raise SafetyError("Only proposal execution is authorized")


@dataclass(frozen=True)
class Reconstruction:
    """Exact, independently measured manifest; hashes refer only to allowed material."""
    repository_id: str
    head_sha: str
    workspace_sha256: str
    policy_sha256: str
    scope_sha256: str
    frozen_sha256: str
    evidence_sha256: str
    completed_steps: tuple[str, ...]
    next_step: str

    def validate(self):
        identifier(self.repository_id)
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", self.head_sha):
            raise SafetyError("Expected Git object ID")
        for field in (self.workspace_sha256, self.policy_sha256, self.scope_sha256,
                      self.frozen_sha256, self.evidence_sha256):
            hash_value(field)
        identifier(self.next_step)
        if len(set(self.completed_steps)) != len(self.completed_steps) or self.next_step in self.completed_steps:
            raise SafetyError("Completed step cannot be replayed")
        for step in self.completed_steps:
            identifier(step)

    def manifest(self):
        self.validate()
        return json.loads(canonical(asdict(self)))


@dataclass(frozen=True)
class ReconstructionAck:
    token: PublicationToken
    checkpoint_id: str
    checkpoint_sha256: str
    manifest_sha256: str


@dataclass(frozen=True)
class QuiescenceReceipt:
    execution_attempt_id: str
    state: str
    receipt_id: str
    method: str

    def validate(self, attempt):
        if self.execution_attempt_id != attempt or self.state != 'TERMINATED':
            raise SafetyError("Prior termination is UNKNOWN or belongs to another attempt")
        if self.method not in {'PROCESS_GROUP_EXITED', 'VERIFIED_NOT_STARTED', 'ISOLATION_REVOKED'}:
            raise SafetyError("Unverified termination method")
        identifier(self.receipt_id)


@dataclass(frozen=True)
class ExecutionOutcome:
    outcome: Outcome
    tests: TestStatus = TestStatus.NOT_RUN

    def validate(self):
        if not isinstance(self.outcome, Outcome) or not isinstance(self.tests, TestStatus):
            raise SafetyError("Typed outcome and test status required")
        if self.outcome in CAPACITY_OUTCOMES and self.tests != TestStatus.NOT_RUN:
            raise SafetyError("Capacity interruption cannot report test execution")
        if (self.outcome == Outcome.TEST_FAILURE) != (self.tests == TestStatus.FAILED):
            raise SafetyError("TEST_FAILURE requires actual failed tests")
        if self.outcome == Outcome.SUCCESS and self.tests == TestStatus.UNKNOWN:
            raise SafetyError("Unknown tests cannot establish success")
