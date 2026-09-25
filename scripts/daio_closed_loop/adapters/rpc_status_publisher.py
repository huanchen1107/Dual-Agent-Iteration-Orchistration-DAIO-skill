"""
Generic DAIO RPC Status Publisher (Outbound HTTPS Relay Adapter).
Publishes collected Two-Plane project state to authenticated Cloudflare Relay.
"""

from __future__ import annotations
import asyncio
import datetime
import json
import logging
import sys
from typing import Callable, Optional, Tuple
import urllib.error
import urllib.request

from ..models import DAIOProjectStatusResponse
from .rpc_status_collector import DAIOStatusCollector

logger = logging.getLogger("DAIOStatusPublisher")


class DAIOStatusPublisher:
    """
    Outbound HTTPS Status Publisher for DAIO Remote Project Cockpit (RPC-1).
    Periodically transmits real Two-Plane status to Cloudflare Relay with Bearer auth.
    """

    def __init__(
        self,
        collector: DAIOStatusCollector,
        relay_url: str,
        publish_token: str,
        interval_seconds: int = 15,
        timeout_seconds: float = 5.0,
        on_publish: Optional[Callable[[int, bool, str, Optional[DAIOProjectStatusResponse]], None]] = None,
    ) -> None:
        self.collector = collector
        self.relay_url = relay_url.rstrip("/")
        self.publish_token = publish_token.strip() if publish_token else ""
        self.interval_seconds = max(1, interval_seconds)
        self.timeout_seconds = timeout_seconds
        self.on_publish = on_publish
        self.publish_count = 0

    def publish_once(self) -> Tuple[bool, str, Optional[DAIOProjectStatusResponse]]:
        """
        Gathers real DAIO status and sends an authenticated POST request to the Relay.
        Returns (success: bool, detail: str, status_response: Optional[DAIOProjectStatusResponse]).
        """
        if not self.relay_url or not self.publish_token:
            return False, "Missing relay_url or publish_token", None

        endpoint = f"{self.relay_url}/api/v1/publish"
        status_response = None
        try:
            status_response = self.collector.collect_status()
            payload_data = status_response.to_dict()
            json_bytes = json.dumps(payload_data).encode("utf-8")

            req = urllib.request.Request(
                url=endpoint,
                data=json_bytes,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Connection": "close",
                    "Authorization": f"Bearer {self.publish_token}",
                    "User-Agent": "DAIO-RPC-Publisher/1.0",
                },
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                status_code = resp.getcode()
                body = resp.read().decode("utf-8")
                if 200 <= status_code < 300:
                    return True, f"HTTP {status_code}: {body[:120]}", status_response
                return False, f"HTTP {status_code}: {body[:120]}", status_response

        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
            msg = f"HTTP {e.code} ({e.reason}): {err_body[:120]}"
            logger.warning(f"Publication failed: {msg}")
            return False, msg, status_response
        except urllib.error.URLError as e:
            msg = f"Network URL error: {e.reason}"
            logger.warning(f"Publication network error: {msg}")
            return False, msg, status_response
        except Exception as e:
            msg = f"Unexpected publication error: {e}"
            logger.error(f"Publication unexpected error: {msg}")
            return False, msg, status_response

    async def run_loop(
        self,
        stop_event: Optional[asyncio.Event] = None,
        max_iterations: Optional[int] = None,
    ) -> None:
        """
        Asynchronous publishing loop that runs continuously until stop_event is triggered
        or max_iterations is reached. Provides interactive visibility on each cycle.
        """
        logger.info(f"Starting DAIO RPC Status Publisher loop -> {self.relay_url} (interval: {self.interval_seconds}s)")
        while stop_event is None or not stop_event.is_set():
            if max_iterations is not None and self.publish_count >= max_iterations:
                break

            self.publish_count += 1
            now_str = datetime.datetime.now().strftime("%H:%M:%S")

            success, detail, status_resp = self.publish_once()

            if success:
                proj = status_resp.live_plane.project_name if status_resp else "unknown"
                sha = (status_resp.durable_plane.local_head_sha[:7]) if (status_resp and status_resp.durable_plane.local_head_sha) else "?"
                freshness = status_resp.live_plane.freshness.value if status_resp else "?"
                print(f"[RPC-1] publish #{self.publish_count} ({now_str}) → ✅ HTTP 200 PUBLISHED ({proj} | {freshness} | {sha})", flush=True)
            else:
                print(f"[RPC-1] publish #{self.publish_count} ({now_str}) → ❌ FAILED: {detail}", flush=True)

            if self.on_publish:
                try:
                    self.on_publish(self.publish_count, success, detail, status_resp)
                except Exception as cb_err:
                    logger.warning(f"on_publish callback error: {cb_err}")

            if max_iterations is not None and self.publish_count >= max_iterations:
                break

            try:
                if stop_event:
                    await asyncio.wait_for(stop_event.wait(), timeout=self.interval_seconds)
                    break
                else:
                    await asyncio.sleep(self.interval_seconds)
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                break
