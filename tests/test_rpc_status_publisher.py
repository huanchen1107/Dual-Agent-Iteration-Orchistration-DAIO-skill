"""
Automated Test Suite for DAIO RPC-1 Status Publisher.
"""

import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import threading
from typing import List, Tuple
import pytest

from scripts.daio_closed_loop.adapters.rpc_status_collector import DAIOStatusCollector
from scripts.daio_closed_loop.adapters.rpc_status_publisher import DAIOStatusPublisher


class MockRelayHandler(BaseHTTPRequestHandler):
    valid_token = "valid-secret-token"
    received_requests: List[Tuple[str, dict, str]] = []

    def do_POST(self):
        auth_header = self.headers.get("Authorization", "")
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else ""

        if self.path == "/api/v1/publish":
            if auth_header == f"Bearer {self.valid_token}":
                try:
                    payload = json.loads(body)
                    MockRelayHandler.received_requests.append((self.path, payload, auth_header))
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"status": "PUBLISHED", "timestamp": "2026-09-25T12:00:00Z"}')
                except Exception as e:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(str(e).encode())
            else:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": "Unauthorized"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Quiet during testing


@pytest.fixture
def mock_relay_server():
    MockRelayHandler.received_requests = []
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

    success, detail = publisher.publish_once()
    assert success is True
    assert "200" in detail
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

    success, detail = publisher.publish_once()
    assert success is False
    assert "401" in detail


def test_publisher_network_failure_resilience():
    collector = DAIOStatusCollector(project_root=".")
    # Port 59999 unlikely to be open
    publisher = DAIOStatusPublisher(
        collector=collector,
        relay_url="http://127.0.0.1:59999",
        publish_token="token",
        timeout_seconds=0.5,
    )

    success, detail = publisher.publish_once()
    assert success is False
    assert "error" in detail.lower() or "connection" in detail.lower()


def test_publisher_run_loop_graceful_stop(mock_relay_server):
    async def _async_test():
        collector = DAIOStatusCollector(project_root=".")
        publisher = DAIOStatusPublisher(
            collector=collector,
            relay_url=mock_relay_server,
            publish_token="valid-secret-token",
            interval_seconds=5,
            timeout_seconds=2.0,
        )

        stop_event = asyncio.Event()

        async def trigger_stop_later():
            await asyncio.sleep(0.1)
            stop_event.set()

        asyncio.create_task(trigger_stop_later())
        await publisher.run_loop(stop_event=stop_event)

        assert len(MockRelayHandler.received_requests) >= 1

    asyncio.run(_async_test())

