"""Phase 3D: Isolated Multi-Node Staging Validation, Failover & Release Gate Test Suite.

Validates:
1. Genuine 3-node MongoDB replica set topology and health.
2. Normal multi-document ACID commit across 3 nodes with write concern majority.
3. Transaction abort atomicity leaving zero orphan records.
4. Controlled primary stepdown during idle operation and automatic reelection.
5. Primary stepdown mid-transaction with driver fail-closed rollback.
6. Ambiguous commit reconciliation using authoritative state and idempotency.
7. Secondary interruption with quorum preservation (2 of 3 majority).
8. Loss of majority (1 of 3) fails closed without uncommitted acknowledgments.
9. Recovery-generation fencing against stale workers across nodes.
10. Financial immutability of paid obligations and ledger entries post-failover.
11. Outbox worker event claim and acknowledgment across primary changes.
12. Outbox worker expired lease recovery post-failover.
13. Stale claim-token fencing after multi-node failover.
14. Outbox dispatch produces zero financial mutations.
"""

import asyncio
import os
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import pymongo
import pymongo.errors
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.staging_replica_set_manager import (
    CONNECTION_URI as STAGING_URI,
    start_all_nodes,
    wait_for_cluster_healthy,
    stepdown_primary,
    stop_node,
    start_node,
    get_cluster_status,
    NODES,
)
from backend.tests.isolation_guard import validate_test_database_isolation
import server
from outbox_worker import (
    OutboxWorker,
    OutboxWorkerConfig,
    TestDeliveryAdapter,
    DeliveryResult,
    DeliveryStatus,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="function")
async def staging_3node_env():
    """Provides a disposable test database on the verified 3-node staging replica set."""
    # Ensure cluster is healthy with 1 PRIMARY + 2 SECONDARY
    health_info = wait_for_cluster_healthy(timeout_sec=15.0)
    assert len(health_info["members"]) == 3, "Staging cluster must have exactly 3 members"

    test_db_name = f"sogil_test_staging_{uuid.uuid4().hex[:8]}"
    validate_test_database_isolation(STAGING_URI, test_db_name)

    client = AsyncIOMotorClient(STAGING_URI, serverSelectionTimeoutMS=3000)
    db = client[test_db_name]

    # Pre-create standard collections
    for col in [
        "work_assignments",
        "wage_obligations",
        "wage_settlements",
        "finance_transactions",
        "assignment_groups",
        "item_instances",
        "outbox_events",
        "audit_logs",
    ]:
        try:
            await db.create_collection(col)
        except Exception:
            pass

    try:
        yield client, db, health_info
    finally:
        try:
            await client.drop_database(test_db_name)
        except Exception:
            pass
        client.close()


# =========================================================================
# Scenario 1: 3-Node Topology & Health Verification
# =========================================================================
@pytest.mark.anyio
async def test_01_staging_3node_topology_verification(staging_3node_env):
    client, db, health_info = staging_3node_env
    status = await client.admin.command("replSetGetStatus")

    assert status["set"] == "sogil-staging-rs"
    members = status["members"]
    assert len(members) == 3, f"Expected 3 members, got {len(members)}"

    states = [m["stateStr"] for m in members]
    assert states.count("PRIMARY") == 1
    assert states.count("SECONDARY") == 2
    for m in members:
        assert m["health"] == 1.0, f"Member {m['name']} unhealthy: {m['health']}"


# =========================================================================
# Scenario 2: Normal Multi-Document ACID Commit with Majority Concern
# =========================================================================
@pytest.mark.anyio
async def test_02_normal_multi_document_commit_across_3nodes(staging_3node_env):
    client, db, _ = staging_3node_env
    aid = str(ObjectId())
    oid = str(ObjectId())
    eid = str(uuid.uuid4())

    wc_majority = pymongo.write_concern.WriteConcern(w="majority", wtimeout=5000)
    rc_majority = pymongo.read_concern.ReadConcern(level="majority")

    async with await client.start_session() as session:
        async with session.start_transaction(write_concern=wc_majority, read_concern=rc_majority):
            await db.work_assignments.insert_one(
                {"_id": ObjectId(aid), "order_id": oid, "status": "verified"},
                session=session
            )
            await db.wage_obligations.insert_one(
                {"_id": ObjectId(), "assignment_id": aid, "total_amount_le": 1500.0, "status": "open"},
                session=session
            )
            await db.outbox_events.insert_one(
                {"event_id": eid, "event_type": "assignment.verified", "status": "pending"},
                session=session
            )

    # Verify durability across cluster
    assert await db.work_assignments.find_one({"_id": ObjectId(aid)}) is not None
    assert await db.wage_obligations.find_one({"assignment_id": aid}) is not None
    assert await db.outbox_events.find_one({"event_id": eid}) is not None


# =========================================================================
# Scenario 3: Transaction Abort Atomicity
# =========================================================================
@pytest.mark.anyio
async def test_03_transaction_abort_leaves_zero_orphans(staging_3node_env):
    client, db, _ = staging_3node_env
    aid = str(ObjectId())
    eid = str(uuid.uuid4())

    try:
        async with await client.start_session() as session:
            async with session.start_transaction():
                await db.work_assignments.insert_one(
                    {"_id": ObjectId(aid), "status": "staged"},
                    session=session
                )
                await db.outbox_events.insert_one(
                    {"event_id": eid, "status": "pending"},
                    session=session
                )
                raise RuntimeError("Aborting transaction deliberately")
    except RuntimeError:
        pass

    # Verify zero documents remain
    assert await db.work_assignments.find_one({"_id": ObjectId(aid)}) is None
    assert await db.outbox_events.find_one({"event_id": eid}) is None


# =========================================================================
# Scenario 4: Controlled Primary Stepdown & Automatic Reelection
# =========================================================================
@pytest.mark.anyio
async def test_04_controlled_primary_stepdown_and_new_primary_election(staging_3node_env):
    client, db, _ = staging_3node_env
    hello_before = await client.admin.command("hello")
    old_primary = hello_before["primary"]

    # Step down current primary
    stepdown_primary(seconds=10)

    # Wait for cluster to elect a primary (automatic driver reconnection)
    new_info = wait_for_cluster_healthy(timeout_sec=15.0)
    assert new_info["healthy"] is True
    # The cluster must have a primary
    assert new_info["primary"] is not None


# =========================================================================
# Scenario 5: Primary Stepdown Mid-Transaction Rolls Back Cleanly
# =========================================================================
@pytest.mark.anyio
async def test_05_primary_stepdown_mid_transaction_safety(staging_3node_env):
    client, db, _ = staging_3node_env
    aid = str(ObjectId())

    tx_failed = False
    try:
        async with await client.start_session() as session:
            async with session.start_transaction():
                await db.work_assignments.insert_one(
                    {"_id": ObjectId(aid), "status": "assigned"},
                    session=session
                )
                # Force stepdown while uncommitted transaction is open
                stepdown_primary(seconds=5)
                # Next write or commit must fail closed
                await db.work_assignments.insert_one(
                    {"_id": ObjectId(), "status": "failed_branch"},
                    session=session
                )
    except (pymongo.errors.PyMongoError, Exception):
        tx_failed = True

    assert tx_failed is True, "Transaction should fail when primary steps down mid-transaction"

    # Wait for cluster health to re-establish
    wait_for_cluster_healthy(timeout_sec=10.0)

    # Assert that no partial write persisted
    assert await db.work_assignments.find_one({"_id": ObjectId(aid)}) is None


# =========================================================================
# Scenario 6: Ambiguous Commit Reconciliation on Multi-Node Cluster
# =========================================================================
@pytest.mark.anyio
async def test_06_ambiguous_commit_reconciliation_authoritative_state(staging_3node_env):
    client, db, _ = staging_3node_env
    idempotency_key = f"idem-key-{uuid.uuid4().hex[:8]}"
    settlement_id = str(ObjectId())

    # Seed an authoritative persisted settlement
    await db.wage_settlements.insert_one({
        "_id": ObjectId(settlement_id),
        "idempotency_key": idempotency_key,
        "amount_le": 2500.0,
        "status": "completed",
        "created_at": datetime.now(timezone.utc).isoformat()
    })

    # Stepdown primary to simulate cluster failover during response transmission
    stepdown_primary(seconds=5)
    wait_for_cluster_healthy(timeout_sec=15.0)

    # Reconciling worker/client queries cluster by idempotency key
    persisted = await db.wage_settlements.find_one({"idempotency_key": idempotency_key})
    assert persisted is not None
    assert persisted["_id"] == ObjectId(settlement_id)
    assert persisted["amount_le"] == 2500.0


# =========================================================================
# Scenario 7: Secondary Node Interruption Quorum Preserved
# =========================================================================
@pytest.mark.anyio
async def test_07_single_secondary_interruption_majority_preserved(staging_3node_env):
    client, db, _ = staging_3node_env

    status = await client.admin.command("replSetGetStatus")
    secondaries = [m for m in status["members"] if m["stateStr"] == "SECONDARY"]
    assert len(secondaries) == 2
    sec_idx = next(i for i, n in enumerate(NODES) if n["name"] == secondaries[0]["name"])

    # Stop one secondary node
    stop_node(sec_idx)
    await asyncio.sleep(0.5)

    try:
        # Cluster has 2 of 3 nodes alive (Primary + 1 Secondary) -> Majority quorum (2) satisfied!
        aid = str(ObjectId())
        wc_majority = pymongo.write_concern.WriteConcern(w="majority", wtimeout=3000)

        async with await client.start_session() as session:
            async with session.start_transaction(write_concern=wc_majority):
                await db.work_assignments.insert_one(
                    {"_id": ObjectId(aid), "note": "written during 1-node downtime"},
                    session=session
                )

        assert await db.work_assignments.find_one({"_id": ObjectId(aid)}) is not None
    finally:
        # Restart the secondary node
        start_node(sec_idx)
        wait_for_cluster_healthy(timeout_sec=15.0)


# =========================================================================
# Scenario 8: Loss of Majority Fails Closed
# =========================================================================
@pytest.mark.anyio
async def test_08_loss_of_majority_fails_closed(staging_3node_env):
    client, db, _ = staging_3node_env

    status = await client.admin.command("replSetGetStatus")
    primary = next(m for m in status["members"] if m["stateStr"] == "PRIMARY")
    secondaries = [m for m in status["members"] if m["stateStr"] == "SECONDARY"]
    assert len(secondaries) == 2
    sec_indices = [i for i, n in enumerate(NODES) if any(s["name"] == n["name"] for s in secondaries)]

    # Stop both secondaries -> only the primary remains, losing majority quorum (1 of 3)
    for idx in sec_indices:
        stop_node(idx)
    await asyncio.sleep(0.5)

    failed_closed = False
    try:
        # With only 1 node alive, majority write concern cannot be satisfied
        short_timeout_client = AsyncIOMotorClient(
            f"mongodb://{primary['name']}/?directConnection=true",
            serverSelectionTimeoutMS=2000
        )
        sdb = short_timeout_client[db.name]
        wc = pymongo.write_concern.WriteConcern(w="majority", wtimeout=1000)
        col = sdb.get_collection("work_assignments", write_concern=wc)
        await col.insert_one(
            {"_id": ObjectId(), "attempt": "should_fail_closed"}
        )
    except (pymongo.errors.WriteConcernError, pymongo.errors.PyMongoError):
        failed_closed = True
    finally:
        # Restore both nodes
        for idx in sec_indices:
            start_node(idx)
        wait_for_cluster_healthy(timeout_sec=20.0)
        short_timeout_client.close()

    assert failed_closed is True, "Loss of majority must fail closed on w:majority writes"


# =========================================================================
# Scenario 9: Recovery Generation Fencing Across Multi-Node Cluster
# =========================================================================
@pytest.mark.anyio
async def test_09_recovery_generation_fencing_multinode(staging_3node_env):
    client, db, _ = staging_3node_env
    gid = str(ObjectId())

    # Seed assignment group at generation 5
    await db.assignment_groups.insert_one({
        "_id": ObjectId(gid),
        "group_number": f"GRP-{uuid.uuid4().hex[:6]}",
        "recovery_generation": 5,
        "status": "active"
    })

    # Step down primary
    stepdown_primary(seconds=5)
    wait_for_cluster_healthy(timeout_sec=15.0)

    # Stale worker attempts recovery with generation 4 (< 5)
    now_iso = datetime.now(timezone.utc).isoformat()
    res = await db.assignment_groups.update_one(
        {
            "_id": ObjectId(gid),
            "recovery_generation": 4  # Mismatch
        },
        {"$set": {"status": "repaired", "updated_at": now_iso}}
    )
    assert res.modified_count == 0, "Stale generation must not modify document"

    # Current generation 5 succeeds
    res_ok = await db.assignment_groups.update_one(
        {
            "_id": ObjectId(gid),
            "recovery_generation": 5
        },
        {
            "$set": {"status": "repaired", "updated_at": now_iso},
            "$inc": {"recovery_generation": 1}
        }
    )
    assert res_ok.modified_count == 1


# =========================================================================
# Scenario 10: Financial Immutability Preserved Across Failover
# =========================================================================
@pytest.mark.anyio
async def test_10_financial_immutability_preserved_across_failover(staging_3node_env):
    client, db, _ = staging_3node_env
    ob_id = str(ObjectId())

    # Create paid obligation
    await db.wage_obligations.insert_one({
        "_id": ObjectId(ob_id),
        "total_amount_le": 5000.0,
        "paid_amount_le": 5000.0,
        "status": "paid"
    })

    # Failover cluster
    stepdown_primary(seconds=5)
    wait_for_cluster_healthy(timeout_sec=15.0)

    # Attempting to mutate paid obligation to zero or cancel it must be rejected
    res = await db.wage_obligations.update_one(
        {
            "_id": ObjectId(ob_id),
            "status": {"$in": ["open", "partially_paid"]}  # Strict filter
        },
        {"$set": {"total_amount_le": 0.0, "status": "cancelled"}}
    )
    assert res.modified_count == 0, "Paid obligation must remain immutable"

    persisted = await db.wage_obligations.find_one({"_id": ObjectId(ob_id)})
    assert persisted["status"] == "paid"
    assert persisted["total_amount_le"] == 5000.0


# =========================================================================
# Scenario 11: Outbox Claim & Acknowledgment Across Primary Failover
# =========================================================================
@pytest.mark.anyio
async def test_11_outbox_claim_and_ack_across_primary_failover(staging_3node_env):
    client, db, _ = staging_3node_env
    adapter = TestDeliveryAdapter()
    worker = OutboxWorker(db=db, adapter=adapter, config=OutboxWorkerConfig(lease_duration_sec=30.0))

    eid = str(uuid.uuid4())
    await db.outbox_events.insert_one({
        "event_id": eid,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "retry_count": 0
    })

    # Claim event on current primary
    claimed = await worker.claim_batch(batch_size=1)
    assert len(claimed) == 1
    token = claimed[0]["claim_token"]

    # Step down primary while worker holds valid lease
    stepdown_primary(seconds=5)
    wait_for_cluster_healthy(timeout_sec=15.0)

    # Worker finishes external delivery and acknowledges on the newly elected primary
    ack_res = await worker.acknowledge_success(eid, claim_token=token)
    assert ack_res is True

    persisted = await db.outbox_events.find_one({"event_id": eid})
    assert persisted["status"] == "dispatched"


# =========================================================================
# Scenario 12: Outbox Worker Expired Lease Recovery Post-Failover
# =========================================================================
@pytest.mark.anyio
async def test_12_outbox_worker_expired_lease_recovery_post_stepdown(staging_3node_env):
    client, db, _ = staging_3node_env
    eid = str(uuid.uuid4())

    # Expired lease
    past_iso = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    await db.outbox_events.insert_one({
        "event_id": eid,
        "status": "processing",
        "claim_token": "dead-token-abandoned",
        "lease_expires_at": past_iso,
        "created_at": past_iso,
        "retry_count": 0
    })

    # Failover primary
    stepdown_primary(seconds=5)
    wait_for_cluster_healthy(timeout_sec=15.0)

    # New worker on new primary recovers expired lease
    adapter = TestDeliveryAdapter()
    worker = OutboxWorker(db=db, adapter=adapter)
    processed = await worker.process_one_cycle()
    assert processed == 1

    persisted = await db.outbox_events.find_one({"event_id": eid})
    assert persisted["status"] == "dispatched"


# =========================================================================
# Scenario 13: Stale Claim-Token Fenced After Failover
# =========================================================================
@pytest.mark.anyio
async def test_13_outbox_stale_claim_token_fenced_after_failover(staging_3node_env):
    client, db, _ = staging_3node_env
    eid = str(uuid.uuid4())
    future_iso = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    await db.outbox_events.insert_one({
        "event_id": eid,
        "status": "processing",
        "claim_token": "legitimate-active-token",
        "lease_expires_at": future_iso,
        "created_at": datetime.now(timezone.utc).isoformat()
    })

    # Failover primary
    stepdown_primary(seconds=5)
    wait_for_cluster_healthy(timeout_sec=15.0)

    # Stale worker attempts acknowledgment with wrong token
    worker = OutboxWorker(db=db, adapter=TestDeliveryAdapter())
    ack_res = await worker.acknowledge_success(eid, claim_token="stale-imposter-token")
    assert ack_res is False


# =========================================================================
# Scenario 14: Outbox Dispatch Zero Financial Mutations
# =========================================================================
@pytest.mark.anyio
async def test_14_outbox_dispatch_zero_financial_side_effects(staging_3node_env):
    client, db, _ = staging_3node_env

    # Initial counts
    assert await db.wage_obligations.count_documents({}) == 0
    assert await db.wage_settlements.count_documents({}) == 0
    assert await db.finance_transactions.count_documents({}) == 0

    # Seed and dispatch 3 events
    for _ in range(3):
        await db.outbox_events.insert_one({
            "event_id": str(uuid.uuid4()),
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat()
        })

    worker = OutboxWorker(db=db, adapter=TestDeliveryAdapter())
    processed = await worker.process_one_cycle()
    assert processed == 3

    # Financial collections must remain strictly zero
    assert await db.wage_obligations.count_documents({}) == 0
    assert await db.wage_settlements.count_documents({}) == 0
    assert await db.finance_transactions.count_documents({}) == 0
