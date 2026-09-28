import pytest
import datetime
import sqlite3
from pathlib import Path
from scripts.daio_closed_loop.capacity import (
    CapacityState,
    CapacityObservation,
    ExecutionCandidate,
    CapacityRegistry
)

@pytest.fixture
def registry(tmp_path):
    db_path = str(tmp_path / "capacity.db")
    return CapacityRegistry(db_path=db_path, stale_seconds=300)

@pytest.fixture
def now():
    return datetime.datetime.now(datetime.timezone.utc)

def make_obs(provider, backend, model, state, time_str, compat="FULLY_COMPATIBLE"):
    return CapacityObservation(
        provider_id=provider,
        backend_id=backend,
        model_id=model,
        observed_state=state,
        observed_at=time_str,
        observation_source="test_probe",
        sanitized_reason="test",
        compatibility_state=compat
    )

def test_a_gemini_unavailable_gpt_oss_available(registry, now):
    registry.record_observation(make_obs("Antigravity", "GeminiBackend", "Gemini", CapacityState.WAITING_FOR_EXECUTION_CAPACITY if hasattr(CapacityState, "WAITING_FOR_EXECUTION_CAPACITY") else CapacityState.CAPACITY_EXHAUSTED, now.isoformat()))
    registry.record_observation(make_obs("Antigravity", "GPTBackend", "GPT-OSS-120B", CapacityState.AVAILABLE, now.isoformat()))

    candidates = [
        ExecutionCandidate("Antigravity", "GeminiBackend", "Gemini", 10, True, "DISPOSABLE_SCRATCH"),
        ExecutionCandidate("Antigravity", "GPTBackend", "GPT-OSS-120B", 5, True, "DISPOSABLE_SCRATCH")
    ]
    
    selected = registry.select_candidate(candidates, "DISPOSABLE_SCRATCH", ["FULLY_COMPATIBLE"], now)
    assert selected is not None
    assert selected.model_id == "GPT-OSS-120B"

def test_b_codex_unavailable_gpt_oss_available(registry, now):
    registry.record_observation(make_obs("CodexProvider", "CodexBackend", "CodexModel", CapacityState.CAPACITY_EXHAUSTED, now.isoformat()))
    registry.record_observation(make_obs("Antigravity", "GPTBackend", "GPT-OSS-120B", CapacityState.AVAILABLE, now.isoformat()))

    candidates = [
        ExecutionCandidate("CodexProvider", "CodexBackend", "CodexModel", 10, True, "DISPOSABLE_SCRATCH"),
        ExecutionCandidate("Antigravity", "GPTBackend", "GPT-OSS-120B", 5, True, "DISPOSABLE_SCRATCH")
    ]
    
    selected = registry.select_candidate(candidates, "DISPOSABLE_SCRATCH", ["FULLY_COMPATIBLE"], now)
    assert selected is not None
    assert selected.model_id == "GPT-OSS-120B"

def test_c_all_models_unavailable(registry, now):
    registry.record_observation(make_obs("Antigravity", "GeminiBackend", "Gemini", CapacityState.RATE_LIMITED, now.isoformat()))
    registry.record_observation(make_obs("Antigravity", "GPTBackend", "GPT-OSS-120B", CapacityState.TEMPORARILY_UNAVAILABLE, now.isoformat()))

    candidates = [
        ExecutionCandidate("Antigravity", "GeminiBackend", "Gemini", 10, True, "DISPOSABLE_SCRATCH"),
        ExecutionCandidate("Antigravity", "GPTBackend", "GPT-OSS-120B", 5, True, "DISPOSABLE_SCRATCH")
    ]
    
    selected = registry.select_candidate(candidates, "DISPOSABLE_SCRATCH", ["FULLY_COMPATIBLE"], now)
    assert selected is None

def test_d_stale_capacity_observation(registry, now):
    stale_time = (now - datetime.timedelta(seconds=400)).isoformat()
    registry.record_observation(make_obs("Antigravity", "GPTBackend", "GPT-OSS-120B", CapacityState.AVAILABLE, stale_time))

    candidates = [
        ExecutionCandidate("Antigravity", "GPTBackend", "GPT-OSS-120B", 5, True, "DISPOSABLE_SCRATCH")
    ]
    
    selected = registry.select_candidate(candidates, "DISPOSABLE_SCRATCH", ["FULLY_COMPATIBLE"], now)
    assert selected is None

def test_e_unknown_state_fails_closed(registry, now):
    registry.record_observation(make_obs("Antigravity", "GPTBackend", "GPT-OSS-120B", CapacityState.UNKNOWN, now.isoformat()))

    candidates = [
        ExecutionCandidate("Antigravity", "GPTBackend", "GPT-OSS-120B", 5, True, "DISPOSABLE_SCRATCH")
    ]
    
    selected = registry.select_candidate(candidates, "DISPOSABLE_SCRATCH", ["FULLY_COMPATIBLE"], now)
    assert selected is None

def test_f_authentication_required(registry, now):
    registry.record_observation(make_obs("Antigravity", "GPTBackend", "GPT-OSS-120B", CapacityState.AUTHENTICATION_REQUIRED, now.isoformat()))

    candidates = [
        ExecutionCandidate("Antigravity", "GPTBackend", "GPT-OSS-120B", 5, True, "DISPOSABLE_SCRATCH")
    ]
    
    selected = registry.select_candidate(candidates, "DISPOSABLE_SCRATCH", ["FULLY_COMPATIBLE"], now)
    assert selected is None

def test_g_incompatible_model(registry, now):
    registry.record_observation(make_obs("Antigravity", "GPTBackend", "GPT-OSS-120B", CapacityState.AVAILABLE, now.isoformat(), compat="NEEDS_GPU"))

    candidates = [
        ExecutionCandidate("Antigravity", "GPTBackend", "GPT-OSS-120B", 5, True, "DISPOSABLE_SCRATCH")
    ]
    
    selected = registry.select_candidate(candidates, "DISPOSABLE_SCRATCH", ["CPU_ONLY"], now)
    assert selected is None

def test_h_deterministic_priority(registry, now):
    registry.record_observation(make_obs("Antigravity", "BackendA", "ModelA", CapacityState.AVAILABLE, now.isoformat()))
    registry.record_observation(make_obs("Antigravity", "BackendB", "ModelB", CapacityState.AVAILABLE, now.isoformat()))
    registry.record_observation(make_obs("Antigravity", "BackendC", "ModelC", CapacityState.AVAILABLE, now.isoformat()))

    candidates = [
        ExecutionCandidate("Antigravity", "BackendA", "ModelA", 5, True, "DISPOSABLE_SCRATCH"),
        ExecutionCandidate("Antigravity", "BackendB", "ModelB", 10, True, "DISPOSABLE_SCRATCH"),
        ExecutionCandidate("Antigravity", "BackendC", "ModelC", 10, True, "DISPOSABLE_SCRATCH") # Same priority, ModelB should win lexicographically
    ]
    
    selected = registry.select_candidate(candidates, "DISPOSABLE_SCRATCH", ["FULLY_COMPATIBLE"], now)
    assert selected is not None
    assert selected.model_id == "ModelB"

def test_i_selected_becomes_unavailable(registry, now):
    registry.record_observation(make_obs("Antigravity", "GPTBackend", "GPT-OSS-120B", CapacityState.AVAILABLE, now.isoformat()))

    candidates = [
        ExecutionCandidate("Antigravity", "GPTBackend", "GPT-OSS-120B", 5, True, "DISPOSABLE_SCRATCH")
    ]
    
    selected = registry.select_candidate(candidates, "DISPOSABLE_SCRATCH", ["FULLY_COMPATIBLE"], now)
    assert selected is not None
    
    # Update to unavailable
    registry.record_observation(make_obs("Antigravity", "GPTBackend", "GPT-OSS-120B", CapacityState.CAPACITY_EXHAUSTED, now.isoformat()))
    
    selected_after = registry.select_candidate(candidates, "DISPOSABLE_SCRATCH", ["FULLY_COMPATIBLE"], now)
    assert selected_after is None

def test_j_model_level_failure_does_not_poison_provider(registry, now):
    registry.record_observation(make_obs("Antigravity", "GeminiBackend", "Gemini", CapacityState.CAPACITY_EXHAUSTED, now.isoformat()))
    registry.record_observation(make_obs("Antigravity", "GPTBackend", "GPT-OSS-120B", CapacityState.AVAILABLE, now.isoformat()))

    candidates = [
        ExecutionCandidate("Antigravity", "GeminiBackend", "Gemini", 10, True, "DISPOSABLE_SCRATCH"),
        ExecutionCandidate("Antigravity", "GPTBackend", "GPT-OSS-120B", 5, True, "DISPOSABLE_SCRATCH")
    ]
    
    selected = registry.select_candidate(candidates, "DISPOSABLE_SCRATCH", ["FULLY_COMPATIBLE"], now)
    assert selected is not None
    assert selected.model_id == "GPT-OSS-120B"

def test_k_restart_reconstruction(tmp_path, now):
    db_path = str(tmp_path / "capacity.db")
    r1 = CapacityRegistry(db_path)
    r1.record_observation(make_obs("Antigravity", "GPTBackend", "GPT-OSS-120B", CapacityState.AVAILABLE, now.isoformat()))
    
    r2 = CapacityRegistry(db_path)
    candidates = [
        ExecutionCandidate("Antigravity", "GPTBackend", "GPT-OSS-120B", 5, True, "DISPOSABLE_SCRATCH")
    ]
    selected = r2.select_candidate(candidates, "DISPOSABLE_SCRATCH", ["FULLY_COMPATIBLE"], now)
    assert selected is not None
    assert selected.model_id == "GPT-OSS-120B"

def test_l_malformed_evidence(registry, now):
    # Missing required string for datetime -> raises exception parsing, is_stale returns True
    obs = make_obs("Antigravity", "GPTBackend", "GPT-OSS-120B", CapacityState.AVAILABLE, "not-a-date")
    registry.record_observation(obs)

    candidates = [
        ExecutionCandidate("Antigravity", "GPTBackend", "GPT-OSS-120B", 5, True, "DISPOSABLE_SCRATCH")
    ]
    
    selected = registry.select_candidate(candidates, "DISPOSABLE_SCRATCH", ["FULLY_COMPATIBLE"], now)
    assert selected is None
