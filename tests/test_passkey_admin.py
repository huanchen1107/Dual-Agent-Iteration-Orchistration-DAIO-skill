"""
Unit tests for Provider-Neutral DAIOPasskeyAdminClient and CLI.
"""

import json
from unittest.mock import MagicMock, patch
import pytest

from scripts.daio_closed_loop.adapters.passkey_admin import DAIOPasskeyAdminClient, main


@pytest.fixture
def mock_admin():
    return DAIOPasskeyAdminClient(
        relay_url="https://mock-relay.workers.dev",
        relay_secret="mock-admin-secret-xyz",
        project_id="test-project",
    )


def test_admin_headers_require_secret():
    client = DAIOPasskeyAdminClient(relay_url="https://mock.dev", relay_secret="")
    with pytest.raises(ValueError, match="DAIO_RELAY_SECRET is required"):
        client._headers()


@patch("urllib.request.urlopen")
def test_generate_enrollment_token(mock_urlopen, mock_admin):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "status": "ENROLLMENT_TOKEN_CREATED",
        "enrollment_token": "token-12345",
        "expires_at": "2026-09-26T21:00:00Z",
    }).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value = mock_resp

    res = mock_admin.generate_enrollment_token(owner_label="iPhone 16", ttl_seconds=600)
    assert res["status"] == "ENROLLMENT_TOKEN_CREATED"
    assert res["enrollment_token"] == "token-12345"
    assert "enroll_token=token-12345" in res["enrollment_url"]


@patch("urllib.request.urlopen")
def test_list_credentials(mock_urlopen, mock_admin):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "project_id": "test-project",
        "count": 1,
        "credentials": [
            {"credential_id": "cred_01", "label": "iPhone 16", "enrolled_at": "2026-09-26T20:00:00Z"}
        ]
    }).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value = mock_resp

    creds = mock_admin.list_credentials()
    assert len(creds) == 1
    assert creds[0]["credential_id"] == "cred_01"


@patch("urllib.request.urlopen")
def test_revoke_credential(mock_urlopen, mock_admin):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"status": "REVOKED", "credential_id": "cred_01"}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value = mock_resp

    ok = mock_admin.revoke_credential("cred_01")
    assert ok is True


@patch("urllib.request.urlopen")
def test_reset_all_credentials(mock_urlopen, mock_admin):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"status": "RESET_COMPLETE", "project_id": "test-project"}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value = mock_resp

    ok = mock_admin.reset_all_credentials()
    assert ok is True


@patch.object(DAIOPasskeyAdminClient, "generate_enrollment_token")
def test_cli_enroll(mock_gen, capsys):
    mock_gen.return_value = {
        "status": "ENROLLMENT_TOKEN_CREATED",
        "enrollment_token": "token-abc",
        "expires_at": "2026-09-26T21:00:00Z",
        "enrollment_url": "https://daio-relay.dev/cockpit?enroll_token=token-abc",
    }
    ret = main(["--relay-secret", "secret-123", "enroll", "--label", "TestPhone"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "DAIO OWNER PASSKEY ENROLLMENT TOKEN GENERATED" in captured.out
    assert "token-abc" in captured.out
