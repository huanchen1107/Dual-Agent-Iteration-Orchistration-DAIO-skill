"""
Generic DAIO RPC Status Publisher (Outbound HTTPS Relay Adapter).
Publishes collected Two-Plane project state to authenticated Cloudflare Relay.
"""

from __future__ import annotations
import asyncio
import datetime
import hashlib
import json
import logging
import time
from typing import Any, Callable, Dict, Optional, Tuple
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
        interval_seconds: int = 300,
        timeout_seconds: float = 5.0,
        observation_interval_seconds: float = 2.0,
        backoff_base_seconds: float = 30.0,
        backoff_max_seconds: float = 900.0,
        on_publish: Optional[Callable[[int, bool, str, Optional[DAIOProjectStatusResponse]], None]] = None,
    ) -> None:
        self.collector = collector
        self.relay_url = relay_url.rstrip("/")
        self.publish_token = publish_token.strip() if publish_token else ""
        # KV is a snapshot/status store, not a heartbeat stream. Keep normal
        # refreshes in the 2--5 minute range while observing locally more often
        # so material state changes can publish immediately.
        self.interval_seconds = max(120.0, min(300.0, float(interval_seconds)))
        self.timeout_seconds = timeout_seconds
        self.observation_interval_seconds = max(0.1, float(observation_interval_seconds))
        self.backoff_base_seconds = max(1.0, float(backoff_base_seconds))
        self.backoff_max_seconds = max(self.backoff_base_seconds, float(backoff_max_seconds))
        self.on_publish = on_publish
        self.publish_count = 0
        self.attempt_count = 0
        self._last_material_fingerprint: Optional[str] = None
        self._last_publish_monotonic: Optional[float] = None
        self._next_attempt_monotonic = 0.0
        self._consecutive_failures = 0
        self.remote_status_degraded = False
        self.last_failure_detail: Optional[str] = None

    @staticmethod
    def _material_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Remove observation timestamps that must not defeat suppression."""
        material = json.loads(json.dumps(payload, sort_keys=True))
        live = material.get("live_plane")
        if isinstance(live, dict):
            live.pop("heartbeat_age_seconds", None)
            live.pop("last_heartbeat_timestamp", None)
        provenance = material.get("provenance")
        if isinstance(provenance, dict):
            provenance.pop("server_timestamp", None)
        return material

    @classmethod
    def _fingerprint(cls, status_response: DAIOProjectStatusResponse) -> str:
        material = cls._material_payload(status_response.to_dict())
        return hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def _in_backoff(self, now_monotonic: float) -> bool:
        return now_monotonic < self._next_attempt_monotonic

    def _record_failure(self, detail: str, now_monotonic: float) -> None:
        self._consecutive_failures += 1
        delay = min(
            self.backoff_max_seconds,
            self.backoff_base_seconds * (2 ** (self._consecutive_failures - 1)),
        )
        self._next_attempt_monotonic = now_monotonic + delay
        self.remote_status_degraded = True
        self.last_failure_detail = detail

    def _record_success(self, fingerprint: str, now_monotonic: float) -> None:
        self._last_material_fingerprint = fingerprint
        self._last_publish_monotonic = now_monotonic
        self._next_attempt_monotonic = now_monotonic
        self._consecutive_failures = 0
        self.remote_status_degraded = False
        self.last_failure_detail = None

    def publish_once(
        self,
        force: bool = False,
        now_monotonic: Optional[float] = None,
    ) -> Tuple[bool, str, Optional[DAIOProjectStatusResponse]]:
        """
        Gathers real DAIO status and sends an authenticated POST request to the Relay.
        Returns (success: bool, detail: str, status_response: Optional[DAIOProjectStatusResponse]).
        """
        if not self.relay_url or not self.publish_token:
            return False, "Missing relay_url or publish_token", None

        now_mono = time.monotonic() if now_monotonic is None else now_monotonic
        status_response = None
        try:
            status_response = self.collector.collect_status()
            fingerprint = self._fingerprint(status_response)
            heartbeat_due = (
                self._last_publish_monotonic is None
                or now_mono - self._last_publish_monotonic >= self.interval_seconds
            )
            changed = fingerprint != self._last_material_fingerprint
            if not force and not changed and not heartbeat_due:
                return False, "Suppressed unchanged status (heartbeat not due)", status_response
            if self._in_backoff(now_mono):
                remaining = max(0.0, self._next_attempt_monotonic - now_mono)
                return False, f"Remote status backoff active ({remaining:.1f}s remaining)", status_response

            endpoint = f"{self.relay_url}/api/v1/publish"
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
                    self._record_success(fingerprint, now_mono)
                    self.publish_count += 1
                    return True, f"HTTP {status_code}: {body[:120]}", status_response
                detail = f"HTTP {status_code}: {body[:120]}"
                self._record_failure(detail, now_mono)
                return False, detail, status_response

        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
            msg = f"HTTP {e.code} ({e.reason}): {err_body[:120]}"
            logger.warning(f"Publication failed: {msg}")
            self._record_failure(msg, now_mono)
            return False, msg, status_response
        except urllib.error.URLError as e:
            msg = f"Network URL error: {e.reason}"
            logger.warning(f"Publication network error: {msg}")
            self._record_failure(msg, now_mono)
            return False, msg, status_response
        except Exception as e:
            msg = f"Unexpected publication error: {e}"
            logger.error(f"Publication unexpected error: {msg}")
            self._record_failure(msg, now_mono)
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
        logger.info(
            "Starting DAIO RPC Status Publisher loop -> %s (heartbeat: %.0fs, observation: %.1fs)",
            self.relay_url,
            self.interval_seconds,
            self.observation_interval_seconds,
        )
        while stop_event is None or not stop_event.is_set():
            if max_iterations is not None and self.attempt_count >= max_iterations:
                break

            self.attempt_count += 1
            now_str = datetime.datetime.now().strftime("%H:%M:%S")

            success, detail, status_resp = self.publish_once()

            if success:
                proj = status_resp.live_plane.project_name if status_resp else "unknown"
                sha = (status_resp.durable_plane.local_head_sha[:7]) if (status_resp and status_resp.durable_plane.local_head_sha) else "?"
                freshness = status_resp.live_plane.freshness.value if status_resp else "?"
                print(f"[RPC-1] #{self.attempt_count}  HTTP 200  PUBLISHED  ({now_str} | {proj} | {freshness} | {sha})", flush=True)
            else:
                print(f"[RPC-1] #{self.attempt_count}  HTTP SUPPRESSED/FAILED  ({now_str} | {detail})", flush=True)

            if self.on_publish:
                try:
                    self.on_publish(self.attempt_count, success, detail, status_resp)
                except Exception as cb_err:
                    logger.warning(f"on_publish callback error: {cb_err}")

            if max_iterations is not None and self.attempt_count >= max_iterations:
                break

            try:
                if stop_event:
                    await asyncio.wait_for(stop_event.wait(), timeout=self.observation_interval_seconds)
                    break
                else:
                    await asyncio.sleep(self.observation_interval_seconds)
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                break
