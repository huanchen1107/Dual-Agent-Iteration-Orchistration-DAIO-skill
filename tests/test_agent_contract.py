import asyncio
import pytest
from scripts.daio_closed_loop.adapters.agent_contract import (
    AgentTaskRequest,
    AgentTaskProposal,
    ProposedFileEdit,
    MockEngineeringAgentAdapter
)

def test_agent_contract_request_and_proposal():
    async def _run():
        mock_adapter = MockEngineeringAgentAdapter(canned_proposals=[
            AgentTaskProposal(
                work_id="work-test-01",
                success=True,
                backend_identity="TEST_BACKEND",
                model_name="test-llm-v1",
                proposed_edits=[
                    ProposedFileEdit(
                        file_path="src/calculator.py",
                        new_content="def add(a, b): return a + b\n",
                        description="Implement addition function"
                    )
                ]
            )
        ])
        
        req = AgentTaskRequest(
            work_id="work-test-01",
            change_id="CHG-01",
            requested_action="Implement add function in src/calculator.py",
            project_root="/tmp/test_project",
            allowed_scope=["src/*", "tests/*"],
            frozen_paths=["src/frozen/*"]
        )
        
        proposal = await mock_adapter.propose_task_solution(req)
        assert proposal.success is True
        assert proposal.work_id == "work-test-01"
        assert proposal.backend_identity == "TEST_BACKEND"
        assert len(proposal.proposed_edits) == 1
        assert proposal.proposed_edits[0].file_path == "src/calculator.py"
        assert len(mock_adapter.invocations) == 1
        assert mock_adapter.invocations[0].requested_action == req.requested_action

    asyncio.run(_run())
