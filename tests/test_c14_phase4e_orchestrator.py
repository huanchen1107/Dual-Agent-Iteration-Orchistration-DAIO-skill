import os
import sqlite3
import pytest
import asyncio
from typing import List
import json
import datetime
from scripts.daio_closed_loop.orchestrator import DAIOClosedLoopOrchestrator
from scripts.daio_closed_loop.store import SqliteDAIOWorkStore
from scripts.daio_closed_loop.adapters.executor import EngineeringExecutorAdapter, ExecutionResult
from scripts.daio_closed_loop.handoff_contract import Outcome, TestStatus, CHECKPOINT_VERSION, digest
from scripts.daio_closed_loop.capacity import CapacityRegistry, CapacityObservation, CapacityState, ExecutionCandidate
from scripts.daio_closed_loop.capacity_handoff_v2 import CapacityHandoffController

class MockCapacityExecutor(EngineeringExecutorAdapter):
    def __init__(self, outcomes: List[Outcome]):
        self.outcomes = outcomes
        self.calls = 0

    def execute_task(self, work, command=None, test_command=None, commit_message=None):
        raise NotImplementedError

    async def execute_task_async(self, work, command=None, test_command=None, commit_message=None):
        outcome = self.outcomes[self.calls] if self.calls < len(self.outcomes) else Outcome.SUCCESS
        self.calls += 1
        res = ExecutionResult(
            success=(outcome == Outcome.SUCCESS),
            test_passed=(outcome == Outcome.SUCCESS),
            outcome=outcome,
            test_status=TestStatus.PASSED if outcome == Outcome.SUCCESS else TestStatus.NOT_RUN
        )
        res.backend_id = "provider:backend:modelA"
        return res

def test_4e_orchestrator_capacity_handoff_integration(tmp_path):
    asyncio.run(run_4e_orchestrator_capacity_handoff_integration(tmp_path))

async def run_4e_orchestrator_capacity_handoff_integration(tmp_path):
    db_path = str(tmp_path / "daio_test.db")
    store = SqliteDAIOWorkStore(db_path)
    registry = CapacityRegistry(db_path)
    
    registry.record_observation(CapacityObservation(
        provider_id="prov", backend_id="back", model_id="modelB",
        observed_state=CapacityState.AVAILABLE,
        observed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        observation_source="test", sanitized_reason="ok", compatibility_state="FULLY_COMPATIBLE"
    ))
    
    candidates = [ExecutionCandidate(
        provider_id="prov", backend_id="back", model_id="modelB", priority=10, authorized=True, requires_safety_contract="C1.4"
    )]
    
    controller = CapacityHandoffController(registry, db_path)
    executor = MockCapacityExecutor([Outcome.QUOTA_EXHAUSTED, Outcome.SUCCESS])
    
    orchestrator = DAIOClosedLoopOrchestrator(
        store=store,
        executor=executor,
        max_rounds=5
    )
    orchestrator.handoff_controller = controller
    orchestrator.execution_candidates = candidates
    
    work = orchestrator.create_work_item("STAGE_1", "/tmp", "action")
    work.handoff_contract = "C1.4"
    from scripts.daio_closed_loop.models import DAIORole, DAIOStatus
    work.assigned_role = DAIORole.ENGINEERING_EXECUTION
    store.save_work_item(work)
    
    from scripts.daio_closed_loop.capacity_handoff_v2 import HandoffPhase, HandoffResult
    original_verify = controller.verify_checkpoint_and_authorize_handoff
    
    def fake_verify(w_id, conn):
        st = controller._load(w_id)
        st.phase = HandoffPhase.CHECKPOINT_VERIFIED
        controller._save(st)
        return HandoffResult(success=True, phase=HandoffPhase.CHECKPOINT_VERIFIED, reason="MOCK_VERIFIED")
        
    controller.verify_checkpoint_and_authorize_handoff = fake_verify
    
    final_work = await orchestrator.run_autonomous_loop(work.work_id)
    
    assert executor.calls == 2
    # Should have continued to SUCCESS
    # But wait, work might not go to COMPLETED if not approved by Architect.
    # It routes back to Architect Review!
    assert final_work.status == DAIOStatus.COMPLETED
    assert final_work.assigned_role == DAIORole.LEAD_ARCHITECT_REVIEW
    
    st = controller.get_state(work.work_id)
    assert st is not None
    assert st.phase == HandoffPhase.BACKEND_B_EXECUTING or st.phase == HandoffPhase.COMPLETED
