"""Durable, non-mutating repository discovery for Generic DAIO takeover."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any, Dict, Optional


REMOTE_CANONICAL = "REMOTE_CANONICAL"
LOCAL_REPO_ONLY = "LOCAL_REPO_ONLY"
NO_REPOSITORY = "NO_REPOSITORY"
AMBIGUOUS_REPOSITORY = "AMBIGUOUS_REPOSITORY"
REPOSITORY_MISMATCH = "REPOSITORY_MISMATCH"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def discover_repository(project_root: str | Path) -> Dict[str, Any]:
    """Classify only the repository already present at ``project_root``.

    This intentionally never initializes Git, scans sibling directories, reaches
    a network remote, or infers identity from a similar project name.
    """
    root = Path(project_root).resolve()
    inside = _git(root, "rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or inside.stdout.strip().lower() != "true":
        return {"repository_state": NO_REPOSITORY, "project_root": str(root), "repository_identity": None}

    git_root_result = _git(root, "rev-parse", "--show-toplevel")
    if git_root_result.returncode != 0:
        return {"repository_state": NO_REPOSITORY, "project_root": str(root), "repository_identity": None}
    git_root = str(Path(git_root_result.stdout.strip()).resolve())
    head_result = _git(root, "rev-parse", "HEAD")
    head = head_result.stdout.strip() if head_result.returncode == 0 else None

    remotes_result = _git(root, "config", "--get-regexp", r"^remote\..*\.url$")
    remotes = []
    if remotes_result.returncode == 0:
        for line in remotes_result.stdout.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2:
                remotes.append(parts[1].strip())
    unique_remotes = sorted(set(remote for remote in remotes if remote))
    identity: Dict[str, Any] = {"git_root": git_root, "head": head}
    if len(unique_remotes) == 0:
        return {"repository_state": LOCAL_REPO_ONLY, "project_root": str(root), "repository_identity": identity}
    if len(unique_remotes) == 1:
        identity["remote"] = unique_remotes[0]
        return {"repository_state": REMOTE_CANONICAL, "project_root": str(root), "repository_identity": identity}
    return {
        "repository_state": AMBIGUOUS_REPOSITORY,
        "project_root": str(root),
        "repository_identity": identity,
        "candidates": unique_remotes,
    }


def validate_repository_evolution(discovered: Dict[str, Any], prior_onboarding: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Permit NO_REPOSITORY → LOCAL → REMOTE without changing DAIO identity."""
    if not prior_onboarding:
        return discovered
    prior_state = prior_onboarding.get("repository_state")
    prior_identity = prior_onboarding.get("repository_identity") or {}
    current_state = discovered["repository_state"]
    current_identity = discovered.get("repository_identity") or {}
    if current_state == AMBIGUOUS_REPOSITORY:
        return discovered

    # A bound remote may not silently become a different remote or disappear.
    prior_remote = prior_identity.get("remote")
    current_remote = current_identity.get("remote")
    if prior_remote and prior_remote != current_remote:
        return {**discovered, "repository_state": REPOSITORY_MISMATCH,
                "mismatch": "durable canonical remote conflicts with discovered repository"}
    # A durable local root cannot silently point at a different repository.
    prior_root = prior_identity.get("git_root")
    current_root = current_identity.get("git_root")
    if prior_root and current_root and prior_root != current_root:
        return {**discovered, "repository_state": REPOSITORY_MISMATCH,
                "mismatch": "durable repository root conflicts with discovered repository"}
    # Absence can evolve to a newly created local repository, then to one remote.
    return discovered


def read_onboarding_state(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, json.JSONDecodeError):
        raise RuntimeError("Existing DAIO onboarding state is unreadable; fail closed")
