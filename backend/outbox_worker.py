"""Phase 3C: Transactional Outbox Relay Worker & Reliable Event Dispatch.

Provides:
- Distributed lease coordination with atomic MongoDB CAS claims.
- Lease renewal, expiration, and abandoned worker recovery.
- Abstract DeliveryAdapter interface with pluggable implementations.
- TestDeliveryAdapter for integration and adversarial test suites.
- Bounded exponential backoff with full jitter.
- Dead-letter state transitions with failure sanitization.
- Safe administrative replay mechanism with durable audit logging.
- Observability metrics for operational health.
"""

import asyncio
import inspect
import json
import logging
import os
import random
import re
import signal
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional, Dict, Any, List, Callable, Union

import pymongo
from pymongo import ReturnDocument

logger = logging.getLogger("outbox_worker")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [OutboxWorker] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Regex to detect sensitive fields that should never be logged
SENSITIVE_KEY_PATTERNS = re.compile(
    r"(password|secret|token|auth|jwt|api_key|access_key|credential)",
    re.IGNORECASE
)


def sanitize_value(val: Any) -> Any:
    """Recursively redacts sensitive keys and values for logging/storage."""
    if isinstance(val, dict):
        return {
            k: ("***REDACTED***" if SENSITIVE_KEY_PATTERNS.search(str(k)) else sanitize_value(v))
            for k, v in val.items()
        }
    elif isinstance(val, list):
        return [sanitize_value(x) for x in val]
    elif isinstance(val, str):
        cleaned = re.sub(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", r"\1***REDACTED***", val)
        cleaned = re.sub(r"([?&](?:token|key|secret|password|auth)=)[^&]+", r"\1***REDACTED***", cleaned)
        return cleaned
    return val


def sanitize_error_message(msg: Optional[str]) -> Optional[str]:
    """Sanitizes error messages before persisting or logging."""
    if not msg:
        return msg
    return str(sanitize_value(msg))


class DeliveryStatus(str, Enum):
    SUCCESS = "success"
    TRANSIENT_FAILURE = "transient_failure"
    PERMANENT_FAILURE = "permanent_failure"
    AMBIGUOUS = "ambiguous"


@dataclass
class DeliveryResult:
    """Outcome of an external delivery attempt."""
    status: DeliveryStatus
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    @property
    def is_success(self) -> bool:
        return self.status == DeliveryStatus.SUCCESS

    @property
    def is_permanent(self) -> bool:
        return self.status == DeliveryStatus.PERMANENT_FAILURE

    @property
    def is_retryable(self) -> bool:
        return self.status in (DeliveryStatus.TRANSIENT_FAILURE, DeliveryStatus.AMBIGUOUS)


class BaseDeliveryAdapter:
    """Abstract interface defining the delivery contract for outbox events.
    External destinations (webhooks, message brokers, queues) must implement this.
    """

    async def deliver(self, event: Dict[str, Any]) -> DeliveryResult:
        raise NotImplementedError("Delivery adapters must implement deliver()")

    def get_adapter_name(self) -> str:
        return self.__class__.__name__


class TestDeliveryAdapter(BaseDeliveryAdapter):
    """Configurable in-memory test delivery adapter for integration & adversarial tests."""
    __test__ = False

    def __init__(self):
        self.delivered_events: List[Dict[str, Any]] = []
        self._next_result: Optional[DeliveryResult] = None
        self._handler: Optional[Callable[[Dict[str, Any]], Union[DeliveryResult, Any]]] = None
        self.call_count: int = 0
        self.last_delivered_event: Optional[Dict[str, Any]] = None

    def set_next_result(self, result: DeliveryResult):
        self._next_result = result

    def set_handler(self, handler: Callable[[Dict[str, Any]], Union[DeliveryResult, Any]]):
        self._handler = handler

    async def deliver(self, event: Dict[str, Any]) -> DeliveryResult:
        self.call_count += 1
        self.last_delivered_event = event

        if self._handler:
            res = self._handler(event)
            if inspect.isawaitable(res):
                res = await res
            if res.is_success:
                self.delivered_events.append(event)
            return res

        if self._next_result is not None:
            res = self._next_result
            self._next_result = None
            if res.is_success:
                self.delivered_events.append(event)
            return res

        # Default success
        self.delivered_events.append(event)
        return DeliveryResult(status=DeliveryStatus.SUCCESS)


class UnconfiguredDeliveryAdapter(BaseDeliveryAdapter):
    """Safe fallback when no external adapter has been configured.
    Fails closed with permanent failure and informs operators to configure a destination adapter.
    """

    async def deliver(self, event: Dict[str, Any]) -> DeliveryResult:
        return DeliveryResult(
            status=DeliveryStatus.PERMANENT_FAILURE,
            error_message=(
                "No external delivery adapter configured. Define an external event sink "
                "(webhook/broker) before enabling outbox dispatch."
            )
        )


@dataclass
class OutboxWorkerConfig:
    """Configuration for the Outbox Relay Worker."""
    poll_interval_sec: float = 1.0
    batch_size: int = 20
    lease_duration_sec: float = 30.0
    max_retries: int = 5
    backoff_base_sec: float = 2.0
    backoff_max_sec: float = 60.0
    backoff_jitter: bool = True
    worker_id: Optional[str] = None

    @classmethod
    def from_env(cls) -> "OutboxWorkerConfig":
        return cls(
            poll_interval_sec=float(os.environ.get("OUTBOX_POLL_INTERVAL_SEC", "1.0")),
            batch_size=int(os.environ.get("OUTBOX_BATCH_SIZE", "20")),
            lease_duration_sec=float(os.environ.get("OUTBOX_LEASE_DURATION_SEC", "30.0")),
            max_retries=int(os.environ.get("OUTBOX_MAX_RETRIES", "5")),
            backoff_base_sec=float(os.environ.get("OUTBOX_BACKOFF_BASE_SEC", "2.0")),
            backoff_max_sec=float(os.environ.get("OUTBOX_BACKOFF_MAX_SEC", "60.0")),
            backoff_jitter=os.environ.get("OUTBOX_BACKOFF_JITTER", "true").lower() in ("true", "1", "yes"),
            worker_id=os.environ.get("OUTBOX_WORKER_ID")
        )


class OutboxWorker:
    """Asynchronous background worker that polls committed outbox events,
    claims them via atomic distributed leases, delivers them via an adapter,
    and handles retries, backoff, and dead-letter states.
    """

    def __init__(
        self,
        db: Any,
        adapter: Optional[BaseDeliveryAdapter] = None,
        config: Optional[OutboxWorkerConfig] = None
    ):
        self.db = db
        self.config = config or OutboxWorkerConfig()
        self.worker_id = self.config.worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.adapter = adapter or UnconfiguredDeliveryAdapter()
        self.is_running = False
        self._stop_requested = False
        self.last_heartbeat = datetime.now(timezone.utc)
        self.stats = {
            "claimed": 0,
            "dispatched": 0,
            "retried": 0,
            "dead_lettered": 0,
            "failed_leases": 0,
        }

    def calculate_backoff(self, retry_count: int) -> float:
        """Calculates bounded exponential backoff delay with optional jitter."""
        base = self.config.backoff_base_sec
        max_d = self.config.backoff_max_sec
        delay = min(base * (2 ** retry_count), max_d)
        if self.config.backoff_jitter:
            jitter_factor = random.uniform(0.5, 1.5)
            delay = min(delay * jitter_factor, max_d)
        return max(0.05, delay)

    async def claim_batch(self, batch_size: Optional[int] = None) -> List[Dict[str, Any]]:
        """Atomically claims a batch of eligible outbox events using MongoDB conditional updates.
        Eligible events are:
        1. status == 'pending' AND (next_retry_at is null OR next_retry_at <= now)
        2. status == 'processing' AND lease_expires_at <= now (abandoned expired lease)
        """
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        lease_expires_iso = (now + timedelta(seconds=self.config.lease_duration_sec)).isoformat()
        limit = batch_size or self.config.batch_size

        # Find eligible candidates
        candidate_filter = {
            "$or": [
                {
                    "status": "pending",
                    "$or": [
                        {"next_retry_at": None},
                        {"next_retry_at": {"$lte": now_iso}}
                    ]
                },
                {
                    "status": "processing",
                    "lease_expires_at": {"$lte": now_iso}
                }
            ]
        }

        candidates = await self.db.outbox_events.find(candidate_filter).sort("created_at", 1).limit(limit).to_list(limit)
        claimed_events: List[Dict[str, Any]] = []

        for candidate in candidates:
            claim_token = str(uuid.uuid4())
            # Atomic CAS update: ensure status and expiration have not changed concurrently
            claimed = await self.db.outbox_events.find_one_and_update(
                {
                    "_id": candidate["_id"],
                    "$or": [
                        {
                            "status": "pending",
                            "$or": [
                                {"next_retry_at": None},
                                {"next_retry_at": {"$lte": now_iso}}
                            ]
                        },
                        {
                            "status": "processing",
                            "lease_expires_at": {"$lte": now_iso}
                        }
                    ]
                },
                {
                    "$set": {
                        "status": "processing",
                        "claim_token": claim_token,
                        "claimed_by_worker": self.worker_id,
                        "claimed_at": now_iso,
                        "lease_expires_at": lease_expires_iso,
                        "updated_at": now_iso
                    }
                },
                return_document=ReturnDocument.AFTER
            )
            if claimed:
                self.stats["claimed"] += 1
                claimed_events.append(claimed)

        return claimed_events

    async def renew_lease(
        self,
        event_id: str,
        claim_token: str,
        additional_seconds: Optional[float] = None
    ) -> bool:
        """Renews an active lease if still held and unexpired."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        duration = additional_seconds or self.config.lease_duration_sec
        new_expires_iso = (now + timedelta(seconds=duration)).isoformat()

        res = await self.db.outbox_events.update_one(
            {
                "event_id": event_id,
                "status": "processing",
                "claim_token": claim_token,
                "lease_expires_at": {"$gt": now_iso}  # Must not already be expired
            },
            {
                "$set": {
                    "lease_expires_at": new_expires_iso,
                    "updated_at": now_iso
                }
            }
        )
        success = res.modified_count > 0
        if not success:
            self.stats["failed_leases"] += 1
        return success

    async def acknowledge_success(self, event_id: str, claim_token: str) -> bool:
        """Transitions claimed event to 'dispatched' conditionally on the claim token."""
        now_iso = datetime.now(timezone.utc).isoformat()
        res = await self.db.outbox_events.update_one(
            {
                "event_id": event_id,
                "status": "processing",
                "claim_token": claim_token
            },
            {
                "$set": {
                    "status": "dispatched",
                    "dispatched_at": now_iso,
                    "claim_token": None,
                    "lease_expires_at": None,
                    "updated_at": now_iso
                }
            }
        )
        if res.modified_count > 0:
            self.stats["dispatched"] += 1
            return True
        self.stats["failed_leases"] += 1
        return False

    async def schedule_retry(
        self,
        event_id: str,
        claim_token: str,
        delay_seconds: float,
        error_message: Optional[str]
    ) -> bool:
        """Transitions claimed event back to 'pending' with next_retry_at backoff."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        next_retry_iso = (now + timedelta(seconds=delay_seconds)).isoformat()
        sanitized_err = sanitize_error_message(error_message)

        res = await self.db.outbox_events.update_one(
            {
                "event_id": event_id,
                "status": "processing",
                "claim_token": claim_token
            },
            {
                "$set": {
                    "status": "pending",
                    "claim_token": None,
                    "lease_expires_at": None,
                    "next_retry_at": next_retry_iso,
                    "last_error": sanitized_err,
                    "updated_at": now_iso
                },
                "$inc": {
                    "retry_count": 1
                }
            }
        )
        if res.modified_count > 0:
            self.stats["retried"] += 1
            return True
        self.stats["failed_leases"] += 1
        return False

    async def dead_letter_event(
        self,
        event_id: str,
        claim_token: str,
        reason: Optional[str]
    ) -> bool:
        """Transitions claimed event to 'dead_letter' conditionally on claim token."""
        now_iso = datetime.now(timezone.utc).isoformat()
        sanitized_err = sanitize_error_message(reason)

        res = await self.db.outbox_events.update_one(
            {
                "event_id": event_id,
                "status": "processing",
                "claim_token": claim_token
            },
            {
                "$set": {
                    "status": "dead_letter",
                    "claim_token": None,
                    "lease_expires_at": None,
                    "last_error": sanitized_err,
                    "dead_letter_at": now_iso,
                    "updated_at": now_iso
                },
                "$inc": {
                    "retry_count": 1
                }
            }
        )
        if res.modified_count > 0:
            self.stats["dead_lettered"] += 1
            return True
        self.stats["failed_leases"] += 1
        return False

    async def process_event(self, event: Dict[str, Any]) -> bool:
        """Processes a single claimed event using the delivery adapter and updates state."""
        event_id = event["event_id"]
        claim_token = event["claim_token"]
        retry_count = int(event.get("retry_count") or 0)

        try:
            delivery_res = await self.adapter.deliver(event)
        except Exception as e:
            logger.warning(f"Unexpected adapter exception delivering event {event_id}: {e}")
            delivery_res = DeliveryResult(
                status=DeliveryStatus.TRANSIENT_FAILURE,
                error_message=f"Unhandled adapter exception: {str(e)}"
            )

        if delivery_res.is_success:
            return await self.acknowledge_success(event_id, claim_token)

        if delivery_res.is_permanent:
            return await self.dead_letter_event(
                event_id, claim_token,
                reason=f"Permanent failure: {delivery_res.error_message}"
            )

        # Transient or ambiguous delivery outcome
        new_attempt = retry_count + 1
        if new_attempt >= self.config.max_retries:
            return await self.dead_letter_event(
                event_id, claim_token,
                reason=f"Exhausted retries ({new_attempt}/{self.config.max_retries}): {delivery_res.error_message}"
            )

        delay = self.calculate_backoff(retry_count)
        return await self.schedule_retry(
            event_id, claim_token,
            delay_seconds=delay,
            error_message=delivery_res.error_message
        )

    async def process_one_cycle(self) -> int:
        """Executes a single processing cycle: claims a batch and processes each event."""
        self.last_heartbeat = datetime.now(timezone.utc)
        events = await self.claim_batch()
        if not events:
            return 0

        processed = 0
        for event in events:
            event_id = event.get("event_id")
            try:
                if not event_id or not event.get("claim_token"):
                    logger.error(f"Malformed event claimed without event_id or claim_token: {event}")
                    if event.get("_id"):
                        await self.db.outbox_events.update_one(
                            {"_id": event["_id"]},
                            {
                                "$set": {
                                    "status": "dead_letter",
                                    "last_error": "Malformed outbox event missing event_id or claim_token"
                                }
                            }
                        )
                    continue

                await self.process_event(event)
                processed += 1
            except Exception as err:
                logger.error(f"Error processing claimed event {event_id}: {err}")
                try:
                    if event_id and event.get("claim_token"):
                        await self.schedule_retry(
                            event_id,
                            event["claim_token"],
                            delay_seconds=10.0,
                            error_message=str(err)
                        )
                except Exception:
                    pass

        return processed

    async def run(self, stop_event: Optional[asyncio.Event] = None):
        """Starts the worker processing loop until stop_event is set or stop() is called."""
        self.is_running = True
        self._stop_requested = False
        logger.info(f"OutboxWorker [{self.worker_id}] started with adapter: {self.adapter.get_adapter_name()}")

        try:
            while self.is_running and not self._stop_requested:
                if stop_event and stop_event.is_set():
                    break

                try:
                    processed = await self.process_one_cycle()
                    if processed == 0:
                        poll_delay = self.config.poll_interval_sec
                        if stop_event:
                            try:
                                await asyncio.wait_for(stop_event.wait(), timeout=poll_delay)
                                break
                            except asyncio.TimeoutError:
                                pass
                        else:
                            await asyncio.sleep(poll_delay)
                except asyncio.CancelledError:
                    break
                except Exception as loop_err:
                    logger.error(f"Unhandled error in worker cycle: {loop_err}")
                    await asyncio.sleep(self.config.poll_interval_sec)
        finally:
            self.is_running = False
            logger.info(f"OutboxWorker [{self.worker_id}] stopped cleanly. Final stats: {self.stats}")

    def stop(self):
        """Requests graceful shutdown of the worker loop."""
        self._stop_requested = True
        self.is_running = False


async def get_outbox_metrics(db: Any) -> Dict[str, Any]:
    """Computes operational observability metrics for the outbox system."""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    pipeline = [
        {
            "$group": {
                "_id": "$status",
                "count": {"$sum": 1},
                "total_retries": {"$sum": "$retry_count"}
            }
        }
    ]
    status_counts = {"pending": 0, "processing": 0, "dispatched": 0, "dead_letter": 0}
    total_retries = 0

    try:
        agg = db.outbox_events.aggregate(pipeline)
        docs = await agg.to_list(100) if hasattr(agg, "to_list") else await agg
        for d in docs:
            st = d.get("_id")
            if st in status_counts:
                status_counts[st] = d.get("count", 0)
            total_retries += d.get("total_retries", 0)
    except Exception as e:
        logger.warning(f"Error computing outbox status aggregate: {e}")

    oldest_pending_age_sec = 0.0
    try:
        oldest = await db.outbox_events.find({"status": "pending"}).sort("created_at", 1).limit(1).to_list(1)
        if oldest and oldest[0].get("created_at"):
            created_dt = datetime.fromisoformat(oldest[0]["created_at"].replace("Z", "+00:00"))
            oldest_pending_age_sec = max(0.0, (now - created_dt).total_seconds())
    except Exception as e:
        logger.warning(f"Error finding oldest pending outbox event: {e}")

    recent_errors = []
    try:
        dead_letters = await db.outbox_events.find(
            {"status": "dead_letter", "last_error": {"$ne": None}}
        ).sort("updated_at", -1).limit(5).to_list(5)
        for dl in dead_letters:
            recent_errors.append({
                "event_id": dl.get("event_id"),
                "event_type": dl.get("event_type"),
                "error": sanitize_error_message(dl.get("last_error")),
                "retry_count": dl.get("retry_count", 0),
                "dead_letter_at": dl.get("dead_letter_at") or dl.get("updated_at")
            })
    except Exception as e:
        logger.warning(f"Error fetching dead letter summaries: {e}")

    return {
        "status_counts": status_counts,
        "total_retries": total_retries,
        "oldest_pending_age_seconds": round(oldest_pending_age_sec, 2),
        "recent_dead_letter_errors": recent_errors,
        "timestamp": now_iso
    }


async def replay_dead_letter_event(
    db: Any,
    event_id: str,
    admin_id: str = "system",
    admin_name: str = "Admin",
    reason: str = ""
) -> Dict[str, Any]:
    """Safely transitions a dead-letter event back to 'pending' for retry.
    Preserves original event identity, payload, and payload hash.
    """
    doc = await db.outbox_events.find_one({"event_id": event_id})
    if not doc:
        return {"success": False, "status_code": 404, "detail": "Outbox event tidak ditemukan"}

    if doc.get("status") != "dead_letter":
        return {
            "success": False,
            "status_code": 400,
            "detail": f"Status event adalah '{doc.get('status')}'; hanya status 'dead_letter' yang dapat di-replay"
        }

    now_iso = datetime.now(timezone.utc).isoformat()
    res = await db.outbox_events.update_one(
        {"event_id": event_id, "status": "dead_letter"},
        {
            "$set": {
                "status": "pending",
                "claim_token": None,
                "lease_expires_at": None,
                "next_retry_at": None,
                "retry_count": 0,
                "previous_retry_count": int(doc.get("retry_count") or 0),
                "replayed_at": now_iso,
                "replayed_by_id": admin_id,
                "replayed_by_name": admin_name,
                "replay_reason": reason or "Administrative replay",
                "updated_at": now_iso
            },
            "$inc": {
                "replay_count": 1
            }
        }
    )
    if res.modified_count == 0:
        return {"success": False, "status_code": 409, "detail": "Event dimodifikasi secara bersamaan"}

    updated = await db.outbox_events.find_one({"event_id": event_id})
    return {"success": True, "event": updated}


async def main():
    """Standalone CLI entry point for running the outbox worker daemon."""
    from motor.motor_asyncio import AsyncIOMotorClient

    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "sogil_furniture")

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    config = OutboxWorkerConfig.from_env()
    adapter = UnconfiguredDeliveryAdapter()
    worker = OutboxWorker(db=db, adapter=adapter, config=config)

    stop_event = asyncio.Event()

    def handle_signal():
        logger.info("Signal received, initiating graceful shutdown...")
        stop_event.set()
        worker.stop()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            pass

    await worker.run(stop_event=stop_event)
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
