"""
Automated Test Suite for DAIO RPC-1 Status Publisher and Relay Security Contract.
"""

import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import threading
from typing import List, Optional, Tuple
import pytest

from scripts.daio_closed_loop.adapters.rpc_status_collector import DAIOStatusCollector
from scripts.daio_closed_loop.adapters.rpc_status_publisher import DAIOStatusPublisher


class MockRelayHandler(BaseHTTPRequestHandler):
    configured_secret: Optional[str] = "valid-secret-token"
    received_requests: List[Tuple[str, dict, str]] = []

    def do_POST(self):
        auth_header = self.headers.get("Authorization", "")
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else ""

        if self.path == "/api/v1/publish":
            # 1. Fail closed if relay secret is not configured
            if not MockRelayHandler.configured_secret:
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": "Server Configuration Error: DAIO_RPC_PUBLISH_TOKEN not configured (fail-closed)."}')
                return

            # 2. Enforce Bearer authentication
            if not auth_header.startswith("Bearer "):
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": "Unauthorized: Missing Bearer token."}')
                return

            token = auth_header.replace("Bearer ", "").strip()
            if token != MockRelayHandler.configured_secret:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": "Unauthorized: Invalid publisher token."}')
                return

            try:
                payload = json.loads(body)
                MockRelayHandler.received_requests.append((self.path, payload, auth_header))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status": "PUBLISHED", "timestamp": "2026-09-25T12:00:00Z"}')
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(str(e).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Quiet during testing


@pytest.fixture
def mock_relay_server():
    MockRelayHandler.received_requests = []
    MockRelayHandler.configured_secret = "valid-secret-token"
    server = HTTPServer(("127.0.0.1", 0), MockRelayHandler)
    port = server.server_address[1]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


def test_publisher_successful_publish(mock_relay_server):
    collector = DAIOStatusCollector(project_root=".")
    publisher = DAIOStatusPublisher(
        collector=collector,
        relay_url=mock_relay_server,
        publish_token="valid-secret-token",
        timeout_seconds=2.0,
    )

    success, detail, status_resp = publisher.publish_once()
    assert success is True
    assert "200" in detail
    assert status_resp is not None
    assert len(MockRelayHandler.received_requests) == 1

    path, payload, auth = MockRelayHandler.received_requests[0]
    assert path == "/api/v1/publish"
    assert "live_plane" in payload
    assert "durable_plane" in payload
    assert auth == "Bearer valid-secret-token"


def test_publisher_unauthorized_token_rejection(mock_relay_server):
    collector = DAIOStatusCollector(project_root=".")
    publisher = DAIOStatusPublisher(
        collector=collector,
        relay_url=mock_relay_server,
        publish_token="invalid-wrong-token",
        timeout_seconds=2.0,
    )

    success, detail, status_resp = publisher.publish_once()
    assert success is False
    assert "401" in detail


def test_publisher_missing_relay_secret_fails_closed(mock_relay_server):
    # Simulate unconfigured Cloudflare Worker environment secret
    MockRelayHandler.configured_secret = None

    collector = DAIOStatusCollector(project_root=".")
    publisher = DAIOStatusPublisher(
        collector=collector,
        relay_url=mock_relay_server,
        publish_token="valid-secret-token",
        timeout_seconds=2.0,
    )

    success, detail, status_resp = publisher.publish_once()
    assert success is False
    assert "503" in detail
    assert len(MockRelayHandler.received_requests) == 0


def test_publisher_network_failure_resilience():
    collector = DAIOStatusCollector(project_root=".")
    # Port 59999 unlikely to be open
    publisher = DAIOStatusPublisher(
        collector=collector,
        relay_url="http://127.0.0.1:59999",
        publish_token="token",
        timeout_seconds=0.5,
    )

    success, detail, status_resp = publisher.publish_once()
    assert success is False
    assert "error" in detail.lower() or "connection" in detail.lower()


def test_publisher_continuous_multi_cycle_loop(mock_relay_server):
    """Proves that loop mode performs multiple independent cycles and updates collected_at on each cycle."""
    async def _async_test():
        collector = DAIOStatusCollector(project_root=".")
        published_records = []

        def record_cb(count, success, detail, resp):
            if success and resp:
                published_records.append((count, resp.provenance.get("collected_at")))

        publisher = DAIOStatusPublisher(
            collector=collector,
            relay_url=mock_relay_server,
            publish_token="valid-secret-token",
            interval_seconds=1,
            timeout_seconds=2.0,
            on_publish=record_cb,
        )

        # Run for 3 iterations
        await publisher.run_loop(max_iterations=3)

        assert len(MockRelayHandler.received_requests) == 3
        assert len(published_records) == 3

        # Prove each iteration produced a distinct collected_at timestamp
        timestamps = [r[1] for r in published_records]
        assert len(set(timestamps)) == 3, f"Expected 3 distinct timestamps, got: {timestamps}"

    asyncio.run(_async_test())

