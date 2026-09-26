"""
Provider-Neutral DAIO Passkey Admin Client & CLI.
Manages WebAuthn Passkey enrollment tokens, registered credentials, and revocations
against the Cloudflare DAIO Unified Relay Edge without requiring any local browser secrets.
"""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional


class DAIOPasskeyAdminClient:
    """
    Client for managing Owner Passkeys on Cloudflare Unified Relay.
    Strictly domain-neutral: zero dependencies on specific LLM or Agent providers.
    """

    def __init__(
        self,
        relay_url: Optional[str] = None,
        relay_secret: Optional[str] = None,
        project_id: str = "awin-fintech",
    ) -> None:
        self.relay_url = (relay_url or os.environ.get("DAIO_RELAY_URL") or "https://daio-relay.huanchen1107.workers.dev").rstrip("/")
        self.relay_secret = (relay_secret or os.environ.get("DAIO_RELAY_SECRET") or "").strip()
        self.project_id = project_id

    def _headers(self) -> Dict[str, str]:
        if not self.relay_secret:
            raise ValueError("DAIO_RELAY_SECRET is required for administrative passkey operations.")
        return {
            "Authorization": f"Bearer {self.relay_secret}",
            "Content-Type": "application/json",
            "User-Agent": "DAIO-PasskeyAdmin/1.0",
        }

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.relay_url}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            try:
                err_json = json.loads(err_body)
                raise RuntimeError(f"HTTP {e.code}: {err_json.get('reason', err_body)}")
            except Exception:
                raise RuntimeError(f"HTTP {e.code}: {err_body}")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to relay at {url}: {e}")

    def generate_enrollment_token(self, owner_label: str = "iPhone Owner", ttl_seconds: int = 600) -> Dict[str, Any]:
        """
        Requests a single-use passkey enrollment token from the Cloudflare Relay.
        Token is valid for 10 minutes (600s default) and single-use.
        """
        payload = {
            "project_id": self.project_id,
            "owner_label": owner_label,
            "ttl_seconds": ttl_seconds,
        }
        res = self._request("POST", "/api/v1/auth/enroll/token", payload)
        enrollment_url = f"{self.relay_url}/cockpit?enroll_token={res.get('enrollment_token', '')}&project_id={self.project_id}"
        res["enrollment_url"] = enrollment_url
        return res

    def list_credentials(self) -> List[Dict[str, Any]]:
        """Lists all registered Passkey public credentials for the project."""
        res = self._request("GET", f"/api/v1/auth/credentials?project_id={self.project_id}")
        return res.get("credentials", [])

    def revoke_credential(self, credential_id: str) -> bool:
        """Revokes a specific registered Passkey by credential ID."""
        payload = {"project_id": self.project_id}
        res = self._request("POST", f"/api/v1/auth/credentials/{credential_id}/revoke", payload)
        return res.get("status") in ("REVOKED", "NOT_FOUND")

    def reset_all_credentials(self) -> bool:
        """Purges all registered credentials and active action tickets for the project."""
        payload = {"project_id": self.project_id}
        res = self._request("POST", "/api/v1/auth/reset", payload)
        return res.get("status") == "RESET_COMPLETE"


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint for DAIO Passkey Admin."""
    parser = argparse.ArgumentParser(description="DAIO Passkey Administrative Tool (Provider-Neutral)")
    parser.add_argument("--project-id", default="awin-fintech", help="DAIO project ID")
    parser.add_argument("--relay-url", default=None, help="Cloudflare Unified Relay URL")
    parser.add_argument("--relay-secret", default=None, help="DAIO Relay Secret (defaults to env DAIO_RELAY_SECRET)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # enroll
    enroll_parser = subparsers.add_parser("enroll", help="Generate a single-use passkey enrollment token and URL")
    enroll_parser.add_argument("--label", default="iPhone Owner", help="Label for the enrolled device")
    enroll_parser.add_argument("--ttl", type=int, default=600, help="Token TTL in seconds (default 600)")

    # list
    subparsers.add_parser("list", help="List registered passkey credentials")

    # revoke
    revoke_parser = subparsers.add_parser("revoke", help="Revoke a registered passkey by credential ID")
    revoke_parser.add_argument("--cred-id", required=True, help="Credential ID to revoke")

    # reset-all
    subparsers.add_parser("reset-all", help="Purge all registered passkeys and tickets for project")

    args = parser.parse_args(argv)

    client = DAIOPasskeyAdminClient(
        relay_url=args.relay_url,
        relay_secret=args.relay_secret,
        project_id=args.project_id,
    )

    try:
        if args.command == "enroll":
            res = client.generate_enrollment_token(owner_label=args.label, ttl_seconds=args.ttl)
            print("=================================================================")
            print("🔑 DAIO OWNER PASSKEY ENROLLMENT TOKEN GENERATED")
            print("=================================================================")
            print(f"Project ID       : {args.project_id}")
            print(f"Owner Label      : {args.label}")
            print(f"Token TTL        : {args.ttl}s")
            print(f"Enrollment Token : {res.get('enrollment_token')}")
            print(f"Expires At       : {res.get('expires_at')}")
            print("-----------------------------------------------------------------")
            print("📱 Open this URL in iPhone Safari to enroll Face ID / Passkey:")
            print(res.get("enrollment_url"))
            print("=================================================================")
            return 0

        elif args.command == "list":
            creds = client.list_credentials()
            print(f"Registered Passkeys for project '{args.project_id}': ({len(creds)} found)")
            for i, c in enumerate(creds, 1):
                print(f" [{i}] Credential ID: {c.get('credential_id')} | Label: {c.get('label')} | Enrolled: {c.get('enrolled_at')}")
            return 0

        elif args.command == "revoke":
            ok = client.revoke_credential(args.cred_id)
            if ok:
                print(f"✓ Successfully revoked credential '{args.cred_id}'")
                return 0
            else:
                print(f"✗ Failed to revoke credential '{args.cred_id}'")
                return 1

        elif args.command == "reset-all":
            ok = client.reset_all_credentials()
            if ok:
                print(f"✓ Successfully reset all passkeys and tickets for project '{args.project_id}'")
                return 0
            else:
                print(f"✗ Failed to reset credentials for project '{args.project_id}'")
                return 1

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
