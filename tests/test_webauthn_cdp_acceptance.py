"""Verifier-backed WebAuthn acceptance using the canonical DAIO CDP client.

This is deliberately an opt-in integration test.  It uses Chrome's CDP
``WebAuthn`` test domain only for a disposable localhost Worker page, and it
never enumerates or routes to a ChatGPT tab.  The production bridge remains
unchanged: the harness imports :class:`UniversalCDPClient` rather than adding a
second CDP transport.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request
from copy import deepcopy
import uuid

import pytest

from scripts.daio_bridge import UniversalCDPClient


REPO = Path(__file__).resolve().parents[1]
RELAY_DIR = REPO / "cloudflare"
RUN_ACCEPTANCE = os.getenv("DAIO_WEBAUTHN_CDP_ACCEPTANCE") == "1"


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _http_json(url: str, *, method: str = "GET", body: dict | None = None, headers: dict | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode())


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _browser_ws_url() -> str:
    with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=3) as response:
        return json.loads(response.read().decode())["webSocketDebuggerUrl"]


async def _create_disposable_target(browser: UniversalCDPClient, url: str) -> tuple[UniversalCDPClient, str]:
    result = await browser.send_cdp_command("Target.createTarget", {"url": url})
    target_id = result["targetId"]
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=3) as response:
            tabs = json.loads(response.read().decode())
        for tab in tabs:
            if tab.get("id") == target_id and tab.get("webSocketDebuggerUrl"):
                client = UniversalCDPClient(tab["webSocketDebuggerUrl"])
                await client.connect()
                return client, target_id
        await asyncio.sleep(0.1)
    raise RuntimeError("Disposable WebAuthn target did not become available")


async def _evaluate(client: UniversalCDPClient, source: str) -> dict:
    value = await client.evaluate(source)
    assert isinstance(value, dict), value
    return value


@pytest.mark.skipif(not RUN_ACCEPTANCE, reason="set DAIO_WEBAUTHN_CDP_ACCEPTANCE=1 for local verifier acceptance")
def test_real_webauthn_registration_and_assertion_through_relay() -> None:
    """Run real SimpleWebAuthn verifier paths with Chrome virtual passkey data."""
    port = _free_port()
    origin = f"http://localhost:{port}"
    # Wrangler's local KV state may persist between test runs; isolate every
    # ceremony so a prior credential cannot affect this acceptance result.
    project_id = f"webauthn-cdp-acceptance-{uuid.uuid4().hex}"
    admin_secret = "test-relay-admin-secret"
    worker = subprocess.Popen(
        ["npx", "wrangler", "dev", "--local", "--port", str(port), "--var", f"DAIO_RELAY_SECRET:{admin_secret}"],
        cwd=RELAY_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    browser: UniversalCDPClient | None = None
    page: UniversalCDPClient | None = None
    target_id: str | None = None
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                status, _ = _http_json(f"{origin}/api/v1/status")
                if status == 200:
                    break
            except Exception:
                time.sleep(0.15)
        else:
            raise RuntimeError("local relay failed to start")

        status, enrollment = _http_json(
            f"{origin}/api/v1/auth/enroll/token",
            method="POST",
            body={"project_id": project_id, "ttl_seconds": 120},
            headers={"Authorization": f"Bearer {admin_secret}"},
        )
        assert status == 200, enrollment
        token = enrollment["enrollment_token"]

        async def ceremony() -> None:
            nonlocal browser, page, target_id
            browser = UniversalCDPClient(_browser_ws_url())
            await browser.connect()
            page, target_id = await _create_disposable_target(browser, f"{origin}/?project_id={project_id}")
            await page.send_cdp_command("WebAuthn.enable", {"enableUI": False})
            virtual_authenticator = await page.send_cdp_command("WebAuthn.addVirtualAuthenticator", {"options": {
                "protocol": "ctap2", "ctap2Version": "ctap2_1", "transport": "internal",
                "hasResidentKey": True, "hasUserVerification": True, "isUserVerified": True,
                "automaticPresenceSimulation": True,
            }})
            registration = await _evaluate(page, f"""(async () => {{
                const token = {json.dumps(token)}; const projectId = {json.dumps(project_id)};
                const b64 = s => Uint8Array.from(atob(s.replace(/-/g,'+').replace(/_/g,'/')), c => c.charCodeAt(0));
                const enc = b => btoa(String.fromCharCode(...new Uint8Array(b))).replace(/=/g,'').replace(/\\+/g,'-').replace(/\\//g,'_');
                const c = await fetch('/api/v1/auth/enroll/challenge?project_id=' + encodeURIComponent(projectId) + '&enrollment_token=' + encodeURIComponent(token)).then(r => r.json());
                const credential = await navigator.credentials.create({{publicKey: {{challenge:b64(c.challenge), rp:{{name:'DAIO test',id:'localhost'}}, user:{{id:new Uint8Array(16).fill(7),name:'test-owner',displayName:'Test Owner'}}, pubKeyCredParams:[{{type:'public-key',alg:-7}}], authenticatorSelection:{{userVerification:'required',residentKey:'preferred'}}, attestation:'none'}}}});
                return {{credential_id:credential.id, raw_id:enc(credential.rawId), response:{{client_data_json:enc(credential.response.clientDataJSON),attestation_object:enc(credential.response.attestationObject)}}}};
            }})()""")
            malformed_registration = deepcopy(registration)
            malformed_registration["response"]["attestation_object"] = "not-an-attestation"
            status, rejected_registration = _http_json(
                f"{origin}/api/v1/auth/enroll/verify", method="POST",
                body={"project_id": project_id, "enrollment_token": token, **malformed_registration},
            )
            assert status in {400, 401}, rejected_registration
            status, before_registration = _http_json(
                f"{origin}/api/v1/auth/credentials?project_id={project_id}",
                headers={"Authorization": f"Bearer {admin_secret}"},
            )
            assert status == 200 and before_registration["count"] == 0
            assertion = await _evaluate(page, f"""(async () => {{
                const projectId = {json.dumps(project_id)};
                const b64 = s => Uint8Array.from(atob(s.replace(/-/g,'+').replace(/_/g,'/')), c => c.charCodeAt(0));
                const enc = b => btoa(String.fromCharCode(...new Uint8Array(b))).replace(/=/g,'').replace(/\\+/g,'-').replace(/\\//g,'_');
                const c = await fetch('/api/v1/auth/challenge', {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{project_id:projectId,work_id:'webauthn-test-work'}})}}).then(r => r.json());
                const assertion = await navigator.credentials.get({{publicKey:{{challenge:b64(c.challenge),rpId:'localhost',userVerification:'required'}}}});
                return {{challenge:c.challenge,credential_id:assertion.id,raw_id:enc(assertion.rawId),authenticator_data:enc(assertion.response.authenticatorData),client_data_json:enc(assertion.response.clientDataJSON),signature:enc(assertion.response.signature)}};
            }})()""")
            status, registered = _http_json(f"{origin}/api/v1/auth/enroll/verify", method="POST", body={"project_id": project_id, "enrollment_token": token, **registration})
            assert status == 201, registered
            assert registered["credential_id"] == registration["credential_id"]

            verification_body = {"project_id": project_id, "work_id": "webauthn-test-work", "gate_id": "TEST_GATE", "current_phase": "TEST", "decision": "APPROVE", "action": "RUN", "instruction": "test", **assertion}
            wrong_challenge = deepcopy(verification_body)
            wrong_challenge["challenge"] = _b64url(os.urandom(32))
            status, rejected_challenge = _http_json(f"{origin}/api/v1/auth/verify", method="POST", body=wrong_challenge)
            assert status == 401, rejected_challenge
            unknown_credential = deepcopy(verification_body)
            unknown_credential["credential_id"] = _b64url(os.urandom(32))
            status, rejected_unknown = _http_json(f"{origin}/api/v1/auth/verify", method="POST", body=unknown_credential)
            assert status == 401, rejected_unknown
            malformed_authenticator = deepcopy(verification_body)
            malformed_authenticator["authenticator_data"] = "not-authenticator-data"
            status, rejected_malformed = _http_json(f"{origin}/api/v1/auth/verify", method="POST", body=malformed_authenticator)
            assert status in {400, 401}, rejected_malformed
            # The received request URL is the canonical verifier origin. A
            # localhost assertion presented through 127.0.0.1 must fail both
            # expected-origin and RP-ID verification.
            status, rejected_origin_rp = _http_json(f"http://127.0.0.1:{port}/api/v1/auth/verify", method="POST", body=verification_body)
            assert status == 401, rejected_origin_rp
            invalid_signature = deepcopy(verification_body)
            invalid_signature["signature"] = ("A" if invalid_signature["signature"][0] != "A" else "B") + invalid_signature["signature"][1:]
            status, rejected_signature = _http_json(f"{origin}/api/v1/auth/verify", method="POST", body=invalid_signature)
            assert status == 401, rejected_signature
            status, authenticated = _http_json(f"{origin}/api/v1/auth/verify", method="POST", body=verification_body)
            assert status == 200, authenticated
            assert authenticated["status"] == "AUTHORIZED"
            status, credential_state = _http_json(
                f"{origin}/api/v1/auth/credentials?project_id={project_id}",
                headers={"Authorization": f"Bearer {admin_secret}"},
            )
            assert status == 200 and credential_state["credentials"][0]["counter"] > 0

            # Regress the virtual authenticator's sign counter below the
            # server-persisted counter. Chrome creates the next assertion with
            # that regressed instance state; SimpleWebAuthn must reject it.
            virtual_credentials = await page.send_cdp_command(
                "WebAuthn.getCredentials", {"authenticatorId": virtual_authenticator["authenticatorId"]}
            )
            assert len(virtual_credentials["credentials"]) == 1
            regressed = dict(virtual_credentials["credentials"][0])
            regressed["signCount"] = 0
            # Chrome 153 does not expose setCredential. Reinstall the same
            # private-key credential with a lower signCount through the
            # supported remove/add virtual-authenticator protocol instead.
            await page.send_cdp_command("WebAuthn.removeCredential", {
                "authenticatorId": virtual_authenticator["authenticatorId"],
                "credentialId": regressed["credentialId"],
            })
            await page.send_cdp_command("WebAuthn.addCredential", {
                "authenticatorId": virtual_authenticator["authenticatorId"],
                "credential": regressed,
            })

            counter_challenge = await _evaluate(page, f"""(async () => {{
                const r = await fetch('/api/v1/auth/challenge', {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{project_id:{json.dumps(project_id)},work_id:'webauthn-test-work'}})}});
                return await r.json();
            }})()""")
            counter_assertion = await _evaluate(page, f"""(async () => {{
                const b64 = s => Uint8Array.from(atob(s.replace(/-/g,'+').replace(/_/g,'/')), c => c.charCodeAt(0));
                const enc = b => btoa(String.fromCharCode(...new Uint8Array(b))).replace(/=/g,'').replace(/\\+/g,'-').replace(/\\//g,'_');
                const assertion = await navigator.credentials.get({{publicKey:{{challenge:b64({json.dumps(counter_challenge['challenge'])}),rpId:'localhost',userVerification:'required'}}}});
                return {{challenge:{json.dumps(counter_challenge['challenge'])},credential_id:assertion.id,raw_id:enc(assertion.rawId),authenticator_data:enc(assertion.response.authenticatorData),client_data_json:enc(assertion.response.clientDataJSON),signature:enc(assertion.response.signature)}};
            }})()""")
            status, rejected_counter = _http_json(
                f"{origin}/api/v1/auth/verify", method="POST",
                body={"project_id": project_id, "work_id": "webauthn-test-work", "gate_id": "TEST_GATE", "current_phase": "TEST", "decision": "APPROVE", "action": "RUN", "instruction": "test", **counter_assertion},
            )
            assert status == 401, rejected_counter

            # Same assertion/challenge cannot produce a second action.
            status, replay = _http_json(f"{origin}/api/v1/auth/verify", method="POST", body=verification_body)
            assert status == 401, replay

            # Revocation is a durable state, not an alias for an unknown ID.
            status, revoked = _http_json(
                f"{origin}/api/v1/auth/credentials/{registration['credential_id']}/revoke",
                method="POST", body={"project_id": project_id},
                headers={"Authorization": f"Bearer {admin_secret}"},
            )
            assert status == 200, revoked
            status, rejected_revoked = _http_json(f"{origin}/api/v1/auth/verify", method="POST", body=verification_body)
            assert status == 401, rejected_revoked

        asyncio.run(ceremony())
    finally:
        async def cleanup() -> None:
            if browser and target_id:
                await browser.send_cdp_command("Target.closeTarget", {"targetId": target_id})
            if page:
                await page.close()
            if browser:
                await browser.close()
        # The CDP websocket is owned by the event loop which ran ceremony.
        # Close only the disposable page through the browser HTTP endpoint if
        # the ceremony reached target creation; this avoids touching any other
        # page target, including ChatGPT routing targets.
        if target_id:
            request = urllib.request.Request(
                f"http://127.0.0.1:9222/json/close/{target_id}", method="PUT"
            )
            try:
                urllib.request.urlopen(request, timeout=3).read()
            except Exception:
                pass
        worker.terminate()
        try:
            worker.wait(timeout=8)
        except subprocess.TimeoutExpired:
            worker.kill()
