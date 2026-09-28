import enum
import datetime
import sqlite3
import json
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, asdict

class CapacityState(enum.Enum):
    AVAILABLE = "AVAILABLE"
    CAPACITY_EXHAUSTED = "CAPACITY_EXHAUSTED"
    RATE_LIMITED = "RATE_LIMITED"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    INCOMPATIBLE = "INCOMPATIBLE"
    UNKNOWN = "UNKNOWN"

@dataclass
class CapacityObservation:
    provider_id: str
    backend_id: str
    model_id: str
    observed_state: CapacityState
    observed_at: str
    observation_source: str
    sanitized_reason: str
    compatibility_state: str

    def to_dict(self):
        d = asdict(self)
        d['observed_state'] = self.observed_state.value
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]):
        return cls(
            provider_id=d['provider_id'],
            backend_id=d['backend_id'],
            model_id=d['model_id'],
            observed_state=CapacityState(d['observed_state']),
            observed_at=d['observed_at'],
            observation_source=d['observation_source'],
            sanitized_reason=d['sanitized_reason'],
            compatibility_state=d['compatibility_state']
        )

@dataclass
class ExecutionCandidate:
    provider_id: str
    backend_id: str
    model_id: str
    priority: int
    authorized: bool
    requires_safety_contract: str

class CapacityRegistry:
    def __init__(self, db_path: str, stale_seconds: int = 300):
        self.db_path = db_path
        self.stale_seconds = stale_seconds
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS capacity_observations (
                    provider_id TEXT,
                    backend_id TEXT,
                    model_id TEXT,
                    observed_state TEXT,
                    observed_at TEXT,
                    observation_source TEXT,
                    sanitized_reason TEXT,
                    compatibility_state TEXT,
                    PRIMARY KEY (provider_id, backend_id, model_id)
                )
            ''')

    def record_observation(self, obs: CapacityObservation):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT INTO capacity_observations 
                (provider_id, backend_id, model_id, observed_state, observed_at, observation_source, sanitized_reason, compatibility_state)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_id, backend_id, model_id) DO UPDATE SET
                observed_state=excluded.observed_state,
                observed_at=excluded.observed_at,
                observation_source=excluded.observation_source,
                sanitized_reason=excluded.sanitized_reason,
                compatibility_state=excluded.compatibility_state
            ''', (obs.provider_id, obs.backend_id, obs.model_id, obs.observed_state.value, obs.observed_at, obs.observation_source, obs.sanitized_reason, obs.compatibility_state))

    def get_observation(self, provider_id: str, backend_id: str, model_id: str) -> Optional[CapacityObservation]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('''
                SELECT * FROM capacity_observations
                WHERE provider_id = ? AND backend_id = ? AND model_id = ?
            ''', (provider_id, backend_id, model_id))
            row = cursor.fetchone()
            if not row:
                return None
            return CapacityObservation(
                provider_id=row[0],
                backend_id=row[1],
                model_id=row[2],
                observed_state=CapacityState(row[3]),
                observed_at=row[4],
                observation_source=row[5],
                sanitized_reason=row[6],
                compatibility_state=row[7]
            )

    def is_stale(self, obs: CapacityObservation, now: datetime.datetime) -> bool:
        try:
            obs_time = datetime.datetime.fromisoformat(obs.observed_at)
            return (now - obs_time).total_seconds() > self.stale_seconds
        except ValueError:
            return True # malformed

    def select_candidate(self, candidates: List[ExecutionCandidate], required_safety_contract: str, work_compatibility_reqs: List[str], now: datetime.datetime) -> Optional[ExecutionCandidate]:
        eligible = []
        for c in candidates:
            if not c.authorized:
                continue
            if c.requires_safety_contract != required_safety_contract:
                continue
            
            obs = self.get_observation(c.provider_id, c.backend_id, c.model_id)
            if not obs:
                continue
            if self.is_stale(obs, now):
                continue
            if obs.observed_state != CapacityState.AVAILABLE:
                continue
            if obs.compatibility_state not in work_compatibility_reqs and obs.compatibility_state != "FULLY_COMPATIBLE":
                continue
            
            eligible.append(c)

        if not eligible:
            return None
        
        # deterministic priority tie-breaking (highest priority first, then lexicographical by model_id)
        eligible.sort(key=lambda x: (-x.priority, x.model_id))
        return eligible[0]
