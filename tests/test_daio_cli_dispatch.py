import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_dispatch_submits_to_canonical_inbox(tmp_path):
    config_dir = tmp_path / "_daio"
    config_dir.mkdir()
    (config_dir / "daio_config.json").write_text(json.dumps({
        "project_name": "disposable-project",
        "allowed_scope": ["tests/probe/**"],
        "architect_endpoint": {
            "provider": "CHATGPT_WEB",
            "conversation_id": "conversation-test",
        },
    }), encoding="utf-8")

    result = subprocess.run([
        sys.executable,
        str(REPO_ROOT / "daio"),
        "dispatch",
        "-C", str(tmp_path),
        "--request-id", "hello-connectivity-test",
        "--change-id", "HELLO_E2E",
        "--requested-action", 'Execute print("Hello")',
    ], cwd=REPO_ROOT, capture_output=True, text=True, check=True)

    response = json.loads(result.stdout)
    assert response["status"] == "SUBMITTED"
    assert response["work_id"] == "daio-root-hello-connectivity-test"

    payload_path = tmp_path / "_daio" / "inbox" / "hello-connectivity-test.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "daio-root-work/v1"
    assert payload["requested_action"] == 'Execute print("Hello")'
    assert payload["allowed_scope"] == ["tests/probe/**"]
    assert payload["architect_endpoint"]["conversation_id"] == "conversation-test"
    assert payload["metadata"]["dispatch_source"] == "daio-cli"


def test_create_work_is_dispatch_alias(tmp_path):
    result = subprocess.run([
        sys.executable,
        str(REPO_ROOT / "daio"),
        "create-work",
        "-C", str(tmp_path),
        "--request-id", "alias-test",
        "--change-id", "HELLO_E2E",
        "--requested-action", 'Execute print("Hello")',
        "--allow", "tests/probe/**",
    ], cwd=REPO_ROOT, capture_output=True, text=True, check=True)

    response = json.loads(result.stdout)
    assert response["work_id"] == "daio-root-alias-test"
    assert (tmp_path / "_daio" / "inbox" / "alias-test.json").exists()
