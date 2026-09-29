"""Generic repository-optional onboarding contracts; no SMC7S identity is used."""
import subprocess

from scripts.daio_closed_loop.onboarding import (
    AMBIGUOUS_REPOSITORY,
    LOCAL_REPO_ONLY,
    NO_REPOSITORY,
    REMOTE_CANONICAL,
    REPOSITORY_MISMATCH,
    discover_repository,
    validate_repository_evolution,
)


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def make_repo(tmp_path, *remotes):
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init")
    for index, remote in enumerate(remotes):
        git(root, "remote", "add", f"remote{index}", remote)
    return root


def test_verified_single_remote_is_remote_canonical(tmp_path):
    project = make_repo(tmp_path, "https://github.com/example/unique-project.git")
    result = discover_repository(project)
    assert result["repository_state"] == REMOTE_CANONICAL
    assert result["repository_identity"]["remote"].endswith("unique-project.git")


def test_local_git_without_remote_is_ready_candidate(tmp_path):
    result = discover_repository(make_repo(tmp_path))
    assert result["repository_state"] == LOCAL_REPO_ONLY
    assert result["repository_identity"]["git_root"]


def test_no_repository_is_non_mutating_ready_candidate(tmp_path):
    project = tmp_path / "new-project"
    project.mkdir()
    before = sorted(path.relative_to(project) for path in project.rglob("*"))
    result = discover_repository(project)
    after = sorted(path.relative_to(project) for path in project.rglob("*"))
    assert result["repository_state"] == NO_REPOSITORY
    assert before == after == []
    assert not (project / ".git").exists()


def test_multiple_remotes_fail_closed(tmp_path):
    project = make_repo(tmp_path, "https://github.com/example/a.git", "https://github.com/example/b.git")
    result = discover_repository(project)
    assert result["repository_state"] == AMBIGUOUS_REPOSITORY
    assert len(result["candidates"]) == 2


def test_durable_remote_conflict_fails_closed(tmp_path):
    project = make_repo(tmp_path, "https://github.com/example/new.git")
    result = validate_repository_evolution(discover_repository(project), {
        "repository_state": REMOTE_CANONICAL,
        "repository_identity": {"git_root": str(project), "remote": "https://github.com/example/old.git"},
    })
    assert result["repository_state"] == REPOSITORY_MISMATCH


def test_repository_evolution_preserves_project_identity(tmp_path):
    project = tmp_path / "evolving-project"
    project.mkdir()
    no_repo = discover_repository(project)
    assert no_repo["repository_state"] == NO_REPOSITORY
    git(project, "init")
    durable = {"project_id": "stable-daio-project", **no_repo}
    local = validate_repository_evolution(discover_repository(project), durable)
    assert local["repository_state"] == LOCAL_REPO_ONLY
    git(project, "remote", "add", "origin", "https://github.com/example/evolving.git")
    durable = {"project_id": durable["project_id"], **local}
    remote = validate_repository_evolution(discover_repository(project), durable)
    assert remote["repository_state"] == REMOTE_CANONICAL
    assert durable["project_id"] == "stable-daio-project"  # Repository evolution never derives a new DAIO ID.
