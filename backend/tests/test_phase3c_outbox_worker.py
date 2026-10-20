"""Adversarial and Functional Test Suite for Phase 3C: Transactional Outbox Relay Worker.

Validates:
1. Pending event is claimed and processed.
2. Event already acknowledged is not re-processed.
3. Concurrent workers competing for the same event; only one wins lease.
4. Abandoned/crashed worker expired lease recovery.
5. Stale lease holder cannot acknowledge or overwrite newer claims.
6. Lease renewal fails after ownership is lost.
7. Delivery acknowledged only upon adapter success condition.
8. Transient failure schedules retry with exponential backoff.
9. Permanent failure or retry exhaustion moves event to dead-letter state.
10. Malformed events do not block unrelated events in batch.
11. Duplicate delivery attempts preserve stable event identity.
12. Ambiguous outcomes handled via retry with receiver deduplication contract.
13. Dead-letter replay preserves traceability without financial side effects.
14. Concurrent workers cannot corrupt attempt counts or event state.
15. Graceful shutdown halts loop without false acknowledgments.
16. Sensitive payload keys and credentials are fully redacted in logs/errors.
17. Business transactions insert outbox events atomically.
18. Observability metrics and API replay endpoints function as specified.
"""

import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
from bson import ObjectId

import server
from outbox_worker import (
    OutboxWorker,
    OutboxWorkerConfig,
    TestDeliveryAdapter,
    DeliveryResult,
    DeliveryStatus,
    sanitize_value,
    sanitize_error_message,
    get_outbox_metrics,
    replay_dead_letter_event,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_sample_event(
    event_type: str = "assignment.created",
    aggregate_type: str = "work_assignment",
    status: str = "pending",
    retry_count: int = 0,
    payload: dict = None,
    next_retry_at: str = None,
    lease_expires_at: str = None,
    claim_token: str = None
) -> dict:
    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "aggregate_type": aggregate_type,
        "aggregate_id": str(uuid.uuid4()),
        "payload": payload or {"test_key": "test_val", "worker_id": "w1"},
        "payload_hash": "a" * 64,
        "status": status,
        "retry_count": retry_count,
        "created_at": now_iso,
        "dispatched_at": None,
        "last_error": None,
        "next_retry_at": next_retry_at,
        "lease_expires_at": lease_expires_at,
        "claim_token": claim_token,
    }


# =========================================================================
# Scenario 1: Pending event is claimed and processed
# =========================================================================
@pytest.mark.anyio
async def test_01_pending_event_claimed_and_processed(real_replica_set_env):
    client, db = real_replica_set_env
    adapter = TestDeliveryAdapter()
    config = OutboxWorkerConfig(poll_interval_sec=0.05, batch_size=10, lease_duration_sec=10.0)
    worker = OutboxWorker(db=db, adapter=adapter, config=config)

    event_doc = make_sample_event()
    await db.outbox_events.insert_one(event_doc)

    processed_count = await worker.process_one_cycle()
    assert processed_count == 1
    assert len(adapter.delivered_events) == 1
    assert adapter.delivered_events[0]["event_id"] == event_doc["event_id"]

    persisted = await db.outbox_events.find_one({"event_id": event_doc["event_id"]})
    assert persisted["status"] == "dispatched"
    assert persisted["dispatched_at"] is not None
    assert persisted["claim_token"] is None
    assert persisted["lease_expires_at"] is None


# =========================================================================
# Scenario 2: Event already acknowledged is not processed again
# =========================================================================
@pytest.mark.anyio
async def test_02_already_acknowledged_event_not_reprocessed(real_replica_set_env):
    client, db = real_replica_set_env
    adapter = TestDeliveryAdapter()
    worker = OutboxWorker(db=db, adapter=adapter)

    event_doc = make_sample_event(status="dispatched")
    event_doc["dispatched_at"] = datetime.now(timezone.utc).isoformat()
    await db.outbox_events.insert_one(event_doc)

    processed_count = await worker.process_one_cycle()
    assert processed_count == 0
    assert len(adapter.delivered_events) == 0


# =========================================================================
# Scenario 3: Two workers compete for same event; only one wins lease
# =========================================================================
@pytest.mark.anyio
async def test_03_concurrent_workers_compete_single_lease_winner(real_replica_set_env):
    client, db = real_replica_set_env
    worker1 = OutboxWorker(db=db, adapter=TestDeliveryAdapter(), config=OutboxWorkerConfig(worker_id="w1"))
    worker2 = OutboxWorker(db=db, adapter=TestDeliveryAdapter(), config=OutboxWorkerConfig(worker_id="w2"))

    event_doc = make_sample_event()
    await db.outbox_events.insert_one(event_doc)

    # Concurrently attempt claiming
    c1, c2 = await asyncio.gather(
        worker1.claim_batch(batch_size=1),
        worker2.claim_batch(batch_size=1)
    )

    total_claimed = len(c1) + len(c2)
    assert total_claimed == 1, f"Expected exactly 1 claim, got {len(c1)} from w1 and {len(c2)} from w2"
    winner_worker = "w1" if len(c1) == 1 else "w2"

    persisted = await db.outbox_events.find_one({"event_id": event_doc["event_id"]})
    assert persisted["status"] == "processing"
    assert persisted["claimed_by_worker"] == winner_worker


# =========================================================================
# Scenario 4: Worker crashes after claiming; expired lease allows recovery
# =========================================================================
@pytest.mark.anyio
async def test_04_abandoned_expired_lease_safely_recovered(real_replica_set_env):
    client, db = real_replica_set_env
    adapter = TestDeliveryAdapter()
    worker = OutboxWorker(db=db, adapter=adapter, config=OutboxWorkerConfig(worker_id="recovering-worker"))

    past_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    dead_token = str(uuid.uuid4())
    abandoned_doc = make_sample_event(
        status="processing",
        claim_token=dead_token,
        lease_expires_at=past_time
    )
    abandoned_doc["claimed_by_worker"] = "crashed-worker-old"
    await db.outbox_events.insert_one(abandoned_doc)

    processed_count = await worker.process_one_cycle()
    assert processed_count == 1
    assert len(adapter.delivered_events) == 1

    persisted = await db.outbox_events.find_one({"event_id": abandoned_doc["event_id"]})
    assert persisted["status"] == "dispatched"
    assert persisted["claim_token"] is None


# =========================================================================
# Scenario 5: Stale lease holder cannot acknowledge or overwrite newer claims
# =========================================================================
@pytest.mark.anyio
async def test_05_stale_lease_holder_cannot_acknowledge_newer_claim(real_replica_set_env):
    client, db = real_replica_set_env
    worker = OutboxWorker(db=db, adapter=TestDeliveryAdapter())

    stale_token = str(uuid.uuid4())
    fresh_token = str(uuid.uuid4())
    event_id = str(uuid.uuid4())

    future_time = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    # Database currently has the event claimed by a newer worker with fresh_token
    await db.outbox_events.insert_one({
        "event_id": event_id,
        "status": "processing",
        "claim_token": fresh_token,
        "lease_expires_at": future_time,
        "created_at": datetime.now(timezone.utc).isoformat()
    })

    # Stale worker attempts to acknowledge with stale_token
    ack_res = await worker.acknowledge_success(event_id, claim_token=stale_token)
    assert ack_res is False

    # Verify event state was not modified
    doc = await db.outbox_events.find_one({"event_id": event_id})
    assert doc["status"] == "processing"
    assert doc["claim_token"] == fresh_token


# =========================================================================
# Scenario 6: Lease renewal fails after ownership is lost
# =========================================================================
@pytest.mark.anyio
async def test_06_lease_renewal_fails_after_ownership_lost(real_replica_set_env):
    client, db = real_replica_set_env
    worker = OutboxWorker(db=db, adapter=TestDeliveryAdapter())

    my_token = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    past_time = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()

    # Event lease is already expired in DB
    await db.outbox_events.insert_one({
        "event_id": event_id,
        "status": "processing",
        "claim_token": my_token,
        "lease_expires_at": past_time,
        "created_at": past_time
    })

    # Renewal should fail because lease already expired
    renewed = await worker.renew_lease(event_id, claim_token=my_token, additional_seconds=30.0)
    assert renewed is False


# =========================================================================
# Scenario 7: Delivery acknowledged only upon adapter success condition
# =========================================================================
@pytest.mark.anyio
async def test_07_delivery_acknowledged_only_on_adapter_success(real_replica_set_env):
    client, db = real_replica_set_env
    adapter = TestDeliveryAdapter()
    adapter.set_next_result(DeliveryResult(status=DeliveryStatus.TRANSIENT_FAILURE, error_message="Network glitch"))
    worker = OutboxWorker(db=db, adapter=adapter, config=OutboxWorkerConfig(max_retries=3))

    event_doc = make_sample_event()
    await db.outbox_events.insert_one(event_doc)

    await worker.process_one_cycle()

    # Event must NOT be dispatched
    persisted = await db.outbox_events.find_one({"event_id": event_doc["event_id"]})
    assert persisted["status"] != "dispatched"
    assert persisted["status"] == "pending"
    assert persisted["retry_count"] == 1


# =========================================================================
# Scenario 8: Transient delivery failure schedules retry with backoff
# =========================================================================
@pytest.mark.anyio
async def test_08_transient_failure_schedules_backoff_retry(real_replica_set_env):
    client, db = real_replica_set_env
    adapter = TestDeliveryAdapter()
    adapter.set_next_result(DeliveryResult(status=DeliveryStatus.TRANSIENT_FAILURE, error_message="HTTP 503 Service Unavailable"))
    worker = OutboxWorker(db=db, adapter=adapter, config=OutboxWorkerConfig(backoff_base_sec=4.0, backoff_jitter=False))

    event_doc = make_sample_event(retry_count=1)
    await db.outbox_events.insert_one(event_doc)

    before_time = datetime.now(timezone.utc)
    await worker.process_one_cycle()

    persisted = await db.outbox_events.find_one({"event_id": event_doc["event_id"]})
    assert persisted["status"] == "pending"
    assert persisted["retry_count"] == 2
    assert persisted["last_error"] == "HTTP 503 Service Unavailable"
    assert persisted["next_retry_at"] is not None

    retry_dt = datetime.fromisoformat(persisted["next_retry_at"].replace("Z", "+00:00"))
    # Base 4.0 * 2^1 = 8.0s expected backoff delay
    diff = (retry_dt - before_time).total_seconds()
    assert 7.0 <= diff <= 10.0


# =========================================================================
# Scenario 9: Permanent failure or exhausted retries moves to dead-letter
# =========================================================================
@pytest.mark.anyio
async def test_09_permanent_failure_and_exhausted_retries_dead_letter(real_replica_set_env):
    client, db = real_replica_set_env

    # Subcase A: Immediate permanent failure
    adapter_a = TestDeliveryAdapter()
    adapter_a.set_next_result(DeliveryResult(status=DeliveryStatus.PERMANENT_FAILURE, error_message="HTTP 400 Bad Request: Schema unparseable"))
    worker_a = OutboxWorker(db=db, adapter=adapter_a)

    doc_a = make_sample_event()
    await db.outbox_events.insert_one(doc_a)
    await worker_a.process_one_cycle()

    persisted_a = await db.outbox_events.find_one({"event_id": doc_a["event_id"]})
    assert persisted_a["status"] == "dead_letter"
    assert "Permanent failure" in persisted_a["last_error"]

    # Subcase B: Exhausted retries
    adapter_b = TestDeliveryAdapter()
    adapter_b.set_next_result(DeliveryResult(status=DeliveryStatus.TRANSIENT_FAILURE, error_message="Downstream gateway down"))
    worker_b = OutboxWorker(db=db, adapter=adapter_b, config=OutboxWorkerConfig(max_retries=3))

    doc_b = make_sample_event(retry_count=2)  # Attempt 3 will hit max_retries=3
    await db.outbox_events.insert_one(doc_b)
    await worker_b.process_one_cycle()

    persisted_b = await db.outbox_events.find_one({"event_id": doc_b["event_id"]})
    assert persisted_b["status"] == "dead_letter"
    assert persisted_b["retry_count"] == 3
    assert "Exhausted retries" in persisted_b["last_error"]


# =========================================================================
# Scenario 10: Malformed event does not stop unrelated events from processing
# =========================================================================
@pytest.mark.anyio
async def test_10_malformed_event_resilience_unrelated_processed(real_replica_set_env):
    client, db = real_replica_set_env
    adapter = TestDeliveryAdapter()
    worker = OutboxWorker(db=db, adapter=adapter, config=OutboxWorkerConfig(batch_size=10))

    # Event 1: Malformed (missing event_id, empty string)
    bad_doc = {"_id": ObjectId(), "event_id": "", "status": "pending", "created_at": "2026-01-01T00:00:00Z"}
    # Event 2: Valid event
    good_doc = make_sample_event()

    await db.outbox_events.insert_many([bad_doc, good_doc])

    await worker.process_one_cycle()

    # Good doc must be successfully delivered despite bad doc in same batch
    persisted_good = await db.outbox_events.find_one({"event_id": good_doc["event_id"]})
    assert persisted_good["status"] == "dispatched"
    assert len(adapter.delivered_events) == 1
    assert adapter.delivered_events[0]["event_id"] == good_doc["event_id"]


# =========================================================================
# Scenario 11: Duplicate delivery attempts reuse stable event identity
# =========================================================================
@pytest.mark.anyio
async def test_11_duplicate_attempts_reuse_same_stable_event_id(real_replica_set_env):
    client, db = real_replica_set_env
    adapter = TestDeliveryAdapter()
    # First attempt: transient failure; Second attempt: success
    adapter.set_next_result(DeliveryResult(status=DeliveryStatus.TRANSIENT_FAILURE, error_message="Timeout"))
    worker = OutboxWorker(db=db, adapter=adapter, config=OutboxWorkerConfig(backoff_base_sec=0.01))

    doc = make_sample_event()
    await db.outbox_events.insert_one(doc)

    # Attempt 1: Fails transiently
    await worker.process_one_cycle()
    assert adapter.call_count == 1
    assert adapter.last_delivered_event["event_id"] == doc["event_id"]

    # Reset next_retry_at so it's immediately eligible
    await db.outbox_events.update_one({"event_id": doc["event_id"]}, {"$set": {"next_retry_at": None}})

    # Attempt 2: Succeeds
    adapter.set_next_result(DeliveryResult(status=DeliveryStatus.SUCCESS))
    await worker.process_one_cycle()
    assert adapter.call_count == 2
    assert adapter.last_delivered_event["event_id"] == doc["event_id"]
    assert adapter.last_delivered_event["payload_hash"] == doc["payload_hash"]


# =========================================================================
# Scenario 12: Ambiguous delivery outcomes follow documented idempotency
# =========================================================================
@pytest.mark.anyio
async def test_12_ambiguous_delivery_outcome_retried_with_dedup_contract(real_replica_set_env):
    client, db = real_replica_set_env
    adapter = TestDeliveryAdapter()
    adapter.set_next_result(DeliveryResult(status=DeliveryStatus.AMBIGUOUS, error_message="HTTP 504 Gateway Timeout during response"))
    worker = OutboxWorker(db=db, adapter=adapter, config=OutboxWorkerConfig(max_retries=5))

    doc = make_sample_event()
    await db.outbox_events.insert_one(doc)

    await worker.process_one_cycle()

    # Ambiguous outcome must NOT mark as dispatched, but schedule retry
    persisted = await db.outbox_events.find_one({"event_id": doc["event_id"]})
    assert persisted["status"] == "pending"
    assert persisted["retry_count"] == 1
    assert "Gateway Timeout" in persisted["last_error"]


# =========================================================================
# Scenario 13: Dead-letter replay preserves traceability without financial side effects
# =========================================================================
@pytest.mark.anyio
async def test_13_dead_letter_replay_preserves_traceability_no_financial_mutation(real_replica_set_env):
    client, db = real_replica_set_env

    doc = make_sample_event(status="dead_letter", retry_count=5)
    doc["last_error"] = "Exhausted retries"
    await db.outbox_events.insert_one(doc)

    # Initial state of financial collections: zero documents
    assert await db.wage_obligations.count_documents({}) == 0
    assert await db.wage_settlements.count_documents({}) == 0
    assert await db.finance_transactions.count_documents({}) == 0

    # Replay dead-letter event
    replay_res = await replay_dead_letter_event(
        db=db,
        event_id=doc["event_id"],
        admin_id="adm-123",
        admin_name="Lead Auditor",
        reason="Manual retry after third-party API outage resolved"
    )
    assert replay_res["success"] is True

    persisted = await db.outbox_events.find_one({"event_id": doc["event_id"]})
    assert persisted["status"] == "pending"
    assert persisted["next_retry_at"] is None
    assert persisted["replayed_by_id"] == "adm-123"
    assert persisted["replayed_by_name"] == "Lead Auditor"
    assert persisted["replay_reason"] == "Manual retry after third-party API outage resolved"

    # Strict invariant: financial collections must remain untouched
    assert await db.wage_obligations.count_documents({}) == 0
    assert await db.wage_settlements.count_documents({}) == 0
    assert await db.finance_transactions.count_documents({}) == 0


# =========================================================================
# Scenario 14: Concurrent workers cannot corrupt attempt counts or event state
# =========================================================================
@pytest.mark.anyio
async def test_14_concurrent_workers_prevent_state_corruption(real_replica_set_env):
    client, db = real_replica_set_env

    # Create 5 distinct pending events
    events = [make_sample_event() for _ in range(5)]
    await db.outbox_events.insert_many(events)

    # Setup two workers running concurrently
    adapter1 = TestDeliveryAdapter()
    adapter2 = TestDeliveryAdapter()
    w1 = OutboxWorker(db=db, adapter=adapter1, config=OutboxWorkerConfig(worker_id="w1", batch_size=5))
    w2 = OutboxWorker(db=db, adapter=adapter2, config=OutboxWorkerConfig(worker_id="w2", batch_size=5))

    p1, p2 = await asyncio.gather(w1.process_one_cycle(), w2.process_one_cycle())
    assert p1 + p2 == 5

    total_delivered = len(adapter1.delivered_events) + len(adapter2.delivered_events)
    assert total_delivered == 5

    # Check database: all 5 are dispatched exactly once
    dispatched_count = await db.outbox_events.count_documents({"status": "dispatched"})
    assert dispatched_count == 5


# =========================================================================
# Scenario 15: Graceful shutdown halts loop without false acknowledgments
# =========================================================================
@pytest.mark.anyio
async def test_15_graceful_shutdown_halts_loop_cleanly(real_replica_set_env):
    client, db = real_replica_set_env
    adapter = TestDeliveryAdapter()
    config = OutboxWorkerConfig(poll_interval_sec=0.05)
    worker = OutboxWorker(db=db, adapter=adapter, config=config)

    stop_event = asyncio.Event()
    worker_task = asyncio.create_task(worker.run(stop_event=stop_event))

    await asyncio.sleep(0.1)
    assert worker.is_running is True

    # Signal stop
    stop_event.set()
    await asyncio.wait_for(worker_task, timeout=1.0)
    assert worker.is_running is False


# =========================================================================
# Scenario 16: Credentials and sensitive payload contents are not exposed in logs
# =========================================================================
def test_16_sensitive_payload_and_credentials_redacted():
    sensitive_payload = {
        "user_id": "u-123",
        "api_key": "sk_live_998877665544332211",
        "password": "super_secret_admin_pass",
        "nested": {
            "jwt_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.t-IDcSemACt8x4iTmc6Y5uvStErAawPhEiWAvdFsA3Q",
            "auth_header": "Bearer secret_bearer_token_abc"
        }
    }
    sanitized = sanitize_value(sensitive_payload)
    assert sanitized["user_id"] == "u-123"
    assert sanitized["api_key"] == "***REDACTED***"
    assert sanitized["password"] == "***REDACTED***"
    assert sanitized["nested"]["jwt_token"] == "***REDACTED***"
    assert sanitized["nested"]["auth_header"] == "***REDACTED***"

    # Test string pattern redaction (Bearer token & URL query params)
    raw_str = "Authorization: Bearer secret_bearer_token_abc"
    assert sanitize_value(raw_str) == "Authorization: Bearer ***REDACTED***"

    error_str = "Failed connecting to https://api.sink.com/dispatch?token=secret123&auth=pass456"
    sanitized_err = sanitize_error_message(error_str)
    assert "token=***REDACTED***" in sanitized_err
    assert "auth=***REDACTED***" in sanitized_err
    assert "secret123" not in sanitized_err


# =========================================================================
# Scenario 17: Existing event producers continue inserting atomically
# =========================================================================
@pytest.mark.anyio
async def test_17_domain_transaction_producer_atomicity(real_replica_set_env):
    client, db = real_replica_set_env
    # Direct session test ensuring outbox event commits atomically with assignment
    aid = str(ObjectId())
    oid = str(ObjectId())

    async with await client.start_session() as session:
        async with session.start_transaction():
            await db.work_assignments.insert_one(
                {"_id": ObjectId(aid), "order_id": oid, "status": "assigned"},
                session=session
            )
            # Create outbox event in same session
            now_iso = datetime.now(timezone.utc).isoformat()
            await db.outbox_events.insert_one(
                {
                    "event_id": str(uuid.uuid4()),
                    "event_type": "assignment.created",
                    "aggregate_type": "work_assignment",
                    "aggregate_id": aid,
                    "payload": {"assignment_id": aid, "order_id": oid},
                    "status": "pending",
                    "created_at": now_iso,
                },
                session=session
            )

    # Verify both documents exist
    assert await db.work_assignments.find_one({"_id": ObjectId(aid)}) is not None
    assert await db.outbox_events.find_one({"aggregate_id": aid}) is not None


# =========================================================================
# Scenario 18: Observability metrics and API replay endpoint
# =========================================================================
@pytest.mark.anyio
async def test_18_observability_metrics_and_admin_replay_endpoint(real_replica_set_env):
    client, db = real_replica_set_env

    # Seed events with different statuses
    await db.outbox_events.insert_many([
        make_sample_event(status="pending"),
        make_sample_event(status="processing"),
        make_sample_event(status="dispatched"),
        make_sample_event(status="dead_letter", retry_count=5),
    ])

    metrics = await get_outbox_metrics(db)
    assert metrics["status_counts"]["pending"] == 1
    assert metrics["status_counts"]["processing"] == 1
    assert metrics["status_counts"]["dispatched"] == 1
    assert metrics["status_counts"]["dead_letter"] == 1
    assert metrics["total_retries"] >= 5
    assert metrics["oldest_pending_age_seconds"] >= 0.0


# =========================================================================
# Scenario 19: Stale worker retry and dead-letter fencing
# =========================================================================
@pytest.mark.anyio
async def test_19_stale_worker_retry_and_dead_letter_fencing(real_replica_set_env):
    client, db = real_replica_set_env
    worker = OutboxWorker(db=db, adapter=TestDeliveryAdapter())

    stale_token = str(uuid.uuid4())
    fresh_token = str(uuid.uuid4())
    event_id = str(uuid.uuid4())

    future_time = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    await db.outbox_events.insert_one({
        "event_id": event_id,
        "status": "processing",
        "claim_token": fresh_token,
        "lease_expires_at": future_time,
        "retry_count": 1,
        "created_at": datetime.now(timezone.utc).isoformat()
    })

    # Stale worker attempts to schedule retry -> must fail
    retry_res = await worker.schedule_retry(event_id, claim_token=stale_token, delay_seconds=10.0, error_message="stale error")
    assert retry_res is False

    # Stale worker attempts to dead-letter -> must fail
    dl_res = await worker.dead_letter_event(event_id, claim_token=stale_token, reason="stale dead letter")
    assert dl_res is False

    # Verify event remains in processing owned by fresh_token
    persisted = await db.outbox_events.find_one({"event_id": event_id})
    assert persisted["status"] == "processing"
    assert persisted["claim_token"] == fresh_token
    assert persisted["retry_count"] == 1


# =========================================================================
# Scenario 20: Crash after delivery succeeds before DB ack; receiver dedup
# =========================================================================
@pytest.mark.anyio
async def test_20_crash_after_external_delivery_deduplicated_by_consumer(real_replica_set_env):
    client, db = real_replica_set_env

    # Receiver state that tracks received event_ids for idempotency
    received_event_ids = set()
    business_actions_executed = []

    def idempotent_consumer(event: dict) -> DeliveryResult:
        eid = event["event_id"]
        if eid in received_event_ids:
            # Duplicate delivery: return success without repeating business action
            return DeliveryResult(status=DeliveryStatus.SUCCESS, metadata={"deduplicated": True})
        received_event_ids.add(eid)
        business_actions_executed.append(eid)
        return DeliveryResult(status=DeliveryStatus.SUCCESS, metadata={"deduplicated": False})

    adapter = TestDeliveryAdapter()
    adapter.set_handler(idempotent_consumer)

    doc = make_sample_event()
    await db.outbox_events.insert_one(doc)

    worker1 = OutboxWorker(db=db, adapter=adapter, config=OutboxWorkerConfig(lease_duration_sec=0.1))

    # Worker 1 claims event
    claimed = await worker1.claim_batch(batch_size=1)
    assert len(claimed) == 1
    claimed_event = claimed[0]

    # External delivery succeeds
    deliv_res = await adapter.deliver(claimed_event)
    assert deliv_res.is_success is True
    assert len(business_actions_executed) == 1

    # SIMULATE CRASH: Worker 1 crashes BEFORE calling acknowledge_success.
    # The event remains in 'processing' with lease_expires_at.
    # We wait for the lease to expire.
    await asyncio.sleep(0.15)

    # Worker 2 boots up and recovers the abandoned event
    worker2 = OutboxWorker(db=db, adapter=adapter, config=OutboxWorkerConfig(lease_duration_sec=10.0))
    processed = await worker2.process_one_cycle()
    assert processed == 1

    # Business action must NOT have been executed twice
    assert len(business_actions_executed) == 1
    assert adapter.call_count == 2  # Delivered twice across network, but deduplicated

    # DB status must now be dispatched
    persisted = await db.outbox_events.find_one({"event_id": doc["event_id"]})
    assert persisted["status"] == "dispatched"


# =========================================================================
# Scenario 21: Admin endpoint security and audit trail
# =========================================================================
@pytest.mark.anyio
async def test_21_admin_endpoints_authorization_validation_and_audit(real_replica_set_env):
    client, db = real_replica_set_env
    server.client = client
    server.db = db

    admin_finance = {"id": "adm-fin-1", "name": "Finance Admin", "role": "admin", "permissions": {"access_finance": True}}
    admin_unauthorized = {"id": "adm-worker-1", "name": "Factory Worker", "role": "worker", "permissions": {}}

    doc = make_sample_event(status="dead_letter", retry_count=5)
    doc["last_error"] = "Downstream outage"
    await db.outbox_events.insert_one(doc)

    # 1. Unauthorized admin rejected from replay endpoint
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await server.admin_replay_outbox_event_endpoint(
            event_id=doc["event_id"],
            payload=server.OutboxEventReplayInput(reason="Unauthorized attempt"),
            admin=admin_unauthorized
        )
    # require_finance_or_owner dependency raises 403
    # When called directly with mock admin, check permissions check
    # Let's test the endpoint directly with authorized admin
    res = await server.admin_replay_outbox_event_endpoint(
        event_id=doc["event_id"],
        payload=server.OutboxEventReplayInput(reason="Approved replay by finance"),
        admin=admin_finance
    )
    assert res["status"] == "replayed"
    assert res["event"]["status"] == "pending"
    assert res["event"]["retry_count"] == 0
    assert res["event"]["previous_retry_count"] == 5

    # Verify audit log was durably created
    audit = await db.audit_logs.find_one({"action": "outbox_event_replay", "entity_id": doc["event_id"]})
    assert audit is not None
    assert audit["performed_by_id"] == "adm-fin-1"
    assert audit["performed_by_name"] == "Finance Admin"
    assert audit["metadata"]["reason"] == "Approved replay by finance"

    # 2. Replay non-existent event -> 404
    with pytest.raises(HTTPException) as exc_404:
        await server.admin_replay_outbox_event_endpoint(
            event_id=str(uuid.uuid4()),
            payload=server.OutboxEventReplayInput(),
            admin=admin_finance
        )
    assert exc_404.value.status_code == 404

    # 3. Replay event not in dead_letter -> 400
    with pytest.raises(HTTPException) as exc_400:
        await server.admin_replay_outbox_event_endpoint(
            event_id=doc["event_id"],  # Now in 'pending' status
            payload=server.OutboxEventReplayInput(),
            admin=admin_finance
        )
    assert exc_400.value.status_code == 400


# =========================================================================
# Scenario 22: Transaction abort rolls back outbox event atomically
# =========================================================================
@pytest.mark.anyio
async def test_22_transaction_abort_rolls_back_outbox_event(real_replica_set_env):
    client, db = real_replica_set_env
    aid = str(ObjectId())
    outbox_eid = str(uuid.uuid4())

    try:
        async with await client.start_session() as session:
            async with session.start_transaction():
                await db.work_assignments.insert_one(
                    {"_id": ObjectId(aid), "order_id": "ord-1", "status": "assigned"},
                    session=session
                )
                now_iso = datetime.now(timezone.utc).isoformat()
                await db.outbox_events.insert_one(
                    {
                        "event_id": outbox_eid,
                        "event_type": "assignment.created",
                        "aggregate_type": "work_assignment",
                        "aggregate_id": aid,
                        "status": "pending",
                        "created_at": now_iso
                    },
                    session=session
                )
                # Intentionally trigger an error to force transaction abort
                raise RuntimeError("Simulated transaction failure before commit")
    except RuntimeError:
        pass

    # Verify BOTH documents were rolled back: neither exists
    assert await db.work_assignments.find_one({"_id": ObjectId(aid)}) is None
    assert await db.outbox_events.find_one({"event_id": outbox_eid}) is None

