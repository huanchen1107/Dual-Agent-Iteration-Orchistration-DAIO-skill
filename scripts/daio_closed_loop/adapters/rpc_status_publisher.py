"""
Generic DAIO RPC Status Publisher (Outbound HTTPS Relay Adapter).
Publishes collected Two-Plane project state to authenticated Cloudflare Relay.
"""

from __future__ import annotations
import asyncio
import json
import logging
from typing import Optional, Tuple
import urllib.error
import urllib.request

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
    ) -> None:
        self.collector = collector
        self.relay_url = relay_url.rstrip("/")
        self.publish_token = publish_token
        self.interval_seconds = max(5, interval_seconds)
        self.timeout_seconds = timeout_seconds

    def publish_once(self) -> Tuple[bool, str]:
        """
        Gathers real DAIO status and sends an authenticated POST request to the Relay.
        Returns (success: bool, detail: str).
        """
        if not self.relay_url or not self.publish_token:
            return False, "Missing relay_url or publish_token"

        endpoint = f"{self.relay_url}/api/v1/publish"
        try:
            status_response = self.collector.collect_status()
            payload_data = status_response.to_dict()
            json_bytes = json.dumps(payload_data).encode("utf-8")

            req = urllib.request.Request(
                url=endpoint,
                data=json_bytes,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.publish_token}",
                    "User-Agent": "DAIO-RPC-Publisher/1.0",
                },
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                status_code = resp.getcode()
                body = resp.read().decode("utf-8")
                if 200 <= status_code < 300:
                    return True, f"HTTP {status_code}: {body[:100]}"
                return False, f"HTTP {status_code}: {body[:100]}"

        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
            msg = f"HTTP {e.code} ({e.reason}): {err_body[:100]}"
            logger.warning(f"Publication failed: {msg}")
            return False, msg
        except urllib.error.URLError as e:
            msg = f"Network URL error: {e.reason}"
            logger.warning(f"Publication network error: {msg}")
            return False, msg
        except Exception as e:
            msg = f"Unexpected publication error: {e}"
            logger.error(f"Publication unexpected error: {msg}")
            return False, msg

    async def run_loop(self, stop_event: Optional[asyncio.Event] = None) -> None:
        """
        Asynchronous publishing loop that runs continuously until stop_event is triggered.
        """
        logger.info(f"Starting DAIO RPC Status Publisher loop -> {self.relay_url} (interval: {self.interval_seconds}s)")
        while stop_event is None or not stop_event.is_set():
            success, detail = self.publish_once()
            if success:
                logger.debug(f"RPC Status published successfully: {detail}")
            else:
                logger.warning(f"RPC Status publication failure: {detail}")

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
