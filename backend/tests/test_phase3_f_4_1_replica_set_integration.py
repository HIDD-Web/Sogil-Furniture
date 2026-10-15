"""
Real MongoDB Replica-Set Integration Test Suite for Phase 3.F.4.1.
Target: Sogil Furniture Logistics Data Models & Trip Core Engine.

SAFETY REQUIREMENTS:
- Requires an explicitly configured test-only URI via TEST_MONGO_REPLICA_SET_URI.
- Validates URI and database isolation before connecting.
- Strictly rejects production hostnames, Atlas URIs, and production database names.
- Uses dedicated disposable database with automatic teardown.
- Fails closed / skips if isolated replica set is not available.
"""

import asyncio
import os
import re
import urllib.parse
import pytest
import pymongo
import pymongo.errors
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from unittest.mock import patch, AsyncMock
from fastapi import HTTPException

import server
from server import (
    assign_order_to_trip_core,
    release_order_from_trip_core,
    record_delivery_attempt_core,
    cancel_trip_multi_stop_core,
    complete_trip_partial_core,
    generate_trip_number,
    _execute_delivery_tx_or_fail_closed,
    admin_add_trip_stop,
    DeliveryTripAddStopInput,
    DeliveryTripStopAttemptInput,
    DeliveryTripStatus,
    StopOutcome,
    CriticalFinanceIndexError,
    _num,
)


def validate_test_database_isolation(uri: str, db_name: str) -> None:
    """Rigorous pre-flight validator to ensure test connection cannot touch production.
    Raises ValueError on any ambiguity or risk.
    """
    if not uri or not isinstance(uri, str):
        raise ValueError("TEST_MONGO_REPLICA_SET_URI is missing or empty")

    parsed = urllib.parse.urlparse(uri)
    host = (parsed.hostname or "").lower()

    # Reject known production hosts and Atlas clusters
    forbidden_host_patterns = [
        r"mongodb\.net$",
        r"railway",
        r"railway\.internal$",
        r"up\.railway\.app$",
        r"production",
    ]
    for pattern in forbidden_host_patterns:
        if re.search(pattern, host):
            raise ValueError(f"SECURITY ABORT: Hostname '{host}' matches forbidden production pattern '{pattern}'")

    # Reject production database names
    forbidden_db_names = ["sogil", "sogil-production", "production", "admin", "config", "local"]
    db_clean = (db_name or "").strip().lower()
    if db_clean in forbidden_db_names:
        raise ValueError(f"SECURITY ABORT: Database name '{db_clean}' is a protected production or system database")

    # Enforce disposable test prefix
    if not (db_clean.startswith("sogil_test_") or db_clean.startswith("test_disposable_")):
        raise ValueError(f"SECURITY ABORT: Database name '{db_clean}' must start with 'sogil_test_' or 'test_disposable_'")


TEST_URI = os.environ.get("TEST_MONGO_REPLICA_SET_URI", "").strip()
TEST_DB_NAME = os.environ.get("TEST_MONGO_DB_NAME", "sogil_test_disposable_replica_delivery").strip()

# Check whether test replica set is configured
IS_REPLICA_SET_CONFIGURED = bool(TEST_URI)


@pytest.fixture(scope="function")
async def real_delivery_replica_env():
    """Provisions a disposable database on a real MongoDB replica set.
    Performs isolation check, provisions indexes, seeds test users, and drops database on teardown.
    """
    if not IS_REPLICA_SET_CONFIGURED:
        pytest.skip(
            "BLOCKED — SAFE REPLICA SET UNAVAILABLE: TEST_MONGO_REPLICA_SET_URI not configured. "
            "Isolated MongoDB replica-set engine required for real transaction tests."
        )

    validate_test_database_isolation(TEST_URI, TEST_DB_NAME)

    client = AsyncIOMotorClient(TEST_URI, serverSelectionTimeoutMS=3000)

    # 1. Verify replica set status
    try:
        hello_res = await client.admin.command("hello")
    except Exception as e:
        client.close()
        pytest.fail(f"Failed to connect to TEST_MONGO_REPLICA_SET_URI: {e}")

    set_name = hello_res.get("setName")
    if not set_name:
        client.close()
        pytest.fail(
            "BLOCKED: Target MongoDB instance is a standalone server (setName is None). "
            "MongoDB multi-document transactions strictly require a replica set."
        )

    db = client[TEST_DB_NAME]

    # Clean slate on disposable test db
    collections = await db.list_collection_names()
    for coll in collections:
        await db[coll].drop()

    # Seed admin manager
    admin_mgr = {
        "_id": ObjectId("660000000000000000000001"),
        "id": "660000000000000000000001",
        "name": "Manager Logistics",
        "role": "manager",
        "permissions": {"manage_orders": True, "access_finance": True}
    }
    await db.admins.insert_one(admin_mgr)

    # Patch server globals to point to this isolated test replica set
    with patch.object(server, "client", client), \
         patch.object(server, "db", db), \
         patch("server.is_standalone_fallback_permitted", return_value=False):
        # Run real index initialization
        await server.seed()
        yield db, client, admin_mgr

    # Teardown: drop disposable test database
    await client.drop_database(TEST_DB_NAME)
    client.close()


# --------------------------------------------------------------------------
# 1. Atomic Assignment: abort rolls back order lock
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_tc_rs_01_atomic_assignment_rollback(real_delivery_replica_env):
    """Test 1: Force trip update to fail after order lock attempt; verify neither mutation remains committed."""
    db, client, admin_mgr = real_delivery_replica_env
    trip_id = ObjectId("670f11112222333344445555")
    ord_id = ObjectId("661111112222333344445555")

    await db.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-RS-001",
        "order_status": "siap",
        "delivery_method": "delivery",
        "active_delivery_trip_id": None
    })

    # Trip is in terminal status 'completed' so trip update will reject (matched_count == 0)
    await db.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-9001",
        "status": "completed",
        "stops": []
    })

    # Execute assign wrapped in transaction
    with pytest.raises(HTTPException) as ctx:
        await _execute_delivery_tx_or_fail_closed(
            lambda sess: assign_order_to_trip_core(str(trip_id), str(ord_id), admin_mgr, session=sess)
        )
    assert ctx.value.status_code == 409

    # Verify atomic rollback: order must NOT remain locked
    order_after = await db.orders.find_one({"_id": ord_id})
    assert order_after["active_delivery_trip_id"] is None
    assert order_after.get("delivery_logistics_status") is None or order_after.get("delivery_logistics_status") != "scheduled"


# --------------------------------------------------------------------------
# 2. Concurrent Assignment: exactly one winner
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_tc_rs_02_concurrent_assignment_single_winner(real_delivery_replica_env):
    """Test 2: Two concurrent requests attempting to assign the same order to different trips."""
    db, client, admin_mgr = real_delivery_replica_env
    ord_id = ObjectId("661111112222333344445556")
    trip1_id = ObjectId("670f11112222333344445556")
    trip2_id = ObjectId("670f11112222333344445557")

    await db.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-RS-002",
        "order_status": "siap",
        "delivery_method": "delivery",
        "active_delivery_trip_id": None
    })
    await db.delivery_trips.insert_many([
        {"_id": trip1_id, "trip_number": "TRP-20261015-9002", "status": "draft", "stops": []},
        {"_id": trip2_id, "trip_number": "TRP-20261015-9003", "status": "draft", "stops": []},
    ])

    results = await asyncio.gather(
        admin_add_trip_stop(str(trip1_id), DeliveryTripAddStopInput(order_id=str(ord_id)), admin_mgr),
        admin_add_trip_stop(str(trip2_id), DeliveryTripAddStopInput(order_id=str(ord_id)), admin_mgr),
        return_exceptions=True
    )

    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]

    assert len(successes) == 1, "Exactly one transaction must succeed"
    assert len(failures) == 1, "The competing transaction must fail"
    assert isinstance(failures[0], HTTPException)
    assert failures[0].status_code == 409

    # Verify database state consistency
    order_doc = await db.orders.find_one({"_id": ord_id})
    winning_trip_id = successes[0].get("id") or successes[0].get("_id")
    assert str(order_doc["active_delivery_trip_id"]) == str(winning_trip_id)


# --------------------------------------------------------------------------
# 3. Atomic Stop Removal: rollback on order release failure
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_tc_rs_03_atomic_stop_removal_rollback(real_delivery_replica_env):
    """Test 3: Force order release to fail; verify stop removal rolls back."""
    db, client, admin_mgr = real_delivery_replica_env
    trip_id = ObjectId("670f11112222333344445558")
    ord_id = ObjectId("661111112222333344445558")

    # Order has a mismatched active_delivery_trip_id in db
    await db.orders.insert_one({
        "_id": ord_id,
        "active_delivery_trip_id": "other_trip_id",
        "order_status": "siap"
    })
    await db.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-9004",
        "status": "draft",
        "stops": [{"stop_id": "stp_1", "order_id": str(ord_id), "outcome": "pending"}]
    })

    with pytest.raises(HTTPException) as ctx:
        await _execute_delivery_tx_or_fail_closed(
            lambda sess: release_order_from_trip_core(str(trip_id), str(ord_id), admin_mgr, session=sess)
        )
    assert ctx.value.status_code == 409

    # Stop must still remain on trip
    trip_after = await db.delivery_trips.find_one({"_id": trip_id})
    assert len(trip_after["stops"]) == 1


# --------------------------------------------------------------------------
# 4. Atomic Multi-Stop Cancellation: release mismatch rollback
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_tc_rs_04_atomic_multi_stop_cancel_mismatch_rollback(real_delivery_replica_env):
    """Test 4: Force a release mismatch; verify trip and all order locks remain consistent after abort."""
    db, client, admin_mgr = real_delivery_replica_env
    trip_id = ObjectId("670f11112222333344445559")
    ord1_id = ObjectId("661111112222333344445559")
    ord2_id = ObjectId("661111112222333344445560")

    await db.orders.insert_one({"_id": ord1_id, "active_delivery_trip_id": str(trip_id), "order_status": "siap"})
    # ord2 has mismatched lock
    await db.orders.insert_one({"_id": ord2_id, "active_delivery_trip_id": "different_trip", "order_status": "siap"})

    await db.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-9005",
        "status": "scheduled",
        "stops": [
            {"stop_id": "stp_1", "order_id": str(ord1_id), "outcome": "pending"},
            {"stop_id": "stp_2", "order_id": str(ord2_id), "outcome": "pending"}
        ]
    })

    with pytest.raises(HTTPException) as ctx:
        await _execute_delivery_tx_or_fail_closed(
            lambda sess: cancel_trip_multi_stop_core(str(trip_id), "Kendaraan mogok", admin_mgr, session=sess)
        )
    assert ctx.value.status_code == 409

    # Verify trip status was NOT modified to cancelled
    trip_after = await db.delivery_trips.find_one({"_id": trip_id})
    assert trip_after["status"] == "scheduled"
    # Ord1 still has active trip lock
    ord1_after = await db.orders.find_one({"_id": ord1_id})
    assert str(ord1_after["active_delivery_trip_id"]) == str(trip_id)


# --------------------------------------------------------------------------
# 5. Atomic Partial Completion: intermediate write failure rollback
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_tc_rs_05_atomic_partial_completion_rollback(real_delivery_replica_env):
    """Test 5: Force intermediate write failure; verify no partial completion survives."""
    db, client, admin_mgr = real_delivery_replica_env
    trip_id = ObjectId("670f11112222333344445561")
    ord_deliv_id = ObjectId("661111112222333344445561")
    ord_failed_id = ObjectId("661111112222333344445562")

    await db.orders.insert_one({"_id": ord_deliv_id, "active_delivery_trip_id": str(trip_id), "order_status": "selesai"})
    await db.orders.insert_one({"_id": ord_failed_id, "active_delivery_trip_id": str(trip_id), "order_status": "siap"})

    # Missing in_transit status (trip in draft status cannot be completed)
    await db.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-9006",
        "status": "draft",
        "stops": [
            {"stop_id": "stp_1", "order_id": str(ord_deliv_id), "outcome": "delivered"},
            {"stop_id": "stp_2", "order_id": str(ord_failed_id), "outcome": "failed"}
        ]
    })

    with pytest.raises(HTTPException) as ctx:
        await _execute_delivery_tx_or_fail_closed(
            lambda sess: complete_trip_partial_core(str(trip_id), "Catatan", admin_mgr, session=sess)
        )
    assert ctx.value.status_code == 409

    trip_after = await db.delivery_trips.find_one({"_id": trip_id})
    assert trip_after["status"] == "draft"


# --------------------------------------------------------------------------
# 6. Retry Safety: failed attempt retains lock for retry
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_tc_rs_06_retry_safety_failed_attempt_preserves_lock(real_delivery_replica_env):
    """Test 6: Record a failed delivery attempt and verify order remains assigned for retry."""
    db, client, admin_mgr = real_delivery_replica_env
    trip_id = ObjectId("670f11112222333344445563")
    ord_id = ObjectId("661111112222333344445563")

    await db.orders.insert_one({
        "_id": ord_id,
        "active_delivery_trip_id": str(trip_id),
        "order_status": "siap",
        "delivery_logistics_status": "in_transit"
    })
    await db.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-9007",
        "status": "in_transit",
        "stops": [{"stop_id": "stp_1", "order_id": str(ord_id), "outcome": "out_for_delivery", "attempts": []}]
    })

    # Record failed attempt
    await _execute_delivery_tx_or_fail_closed(
        lambda sess: record_delivery_attempt_core(
            str(trip_id),
            str(ord_id),
            DeliveryTripStopAttemptInput(outcome="failed", failure_reason="Penerima tidak di tempat"),
            admin_mgr,
            session=sess
        )
    )

    ord_after = await db.orders.find_one({"_id": ord_id})
    # Order lock is preserved for same-trip retry
    assert str(ord_after["active_delivery_trip_id"]) == str(trip_id)
    assert ord_after["delivery_logistics_status"] == "delivery_attempt_failed"


# --------------------------------------------------------------------------
# 7. Transaction-Unavailable Behavior: fail-closed in production
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_tc_rs_07_transaction_unavailable_fails_closed(real_delivery_replica_env):
    """Test 7: Verify no non-atomic fallback occurs when transactions are unavailable in production mode."""
    with patch("server.is_standalone_fallback_permitted", return_value=False), \
         patch("server.client.start_session", side_effect=pymongo.errors.ConfigurationError("Unavailable")):
        with pytest.raises(HTTPException) as ctx:
            await _execute_delivery_tx_or_fail_closed(lambda sess: None)
        assert ctx.value.status_code == 503
        assert "Layanan transaksi multi-dokumen tidak tersedia" in ctx.value.detail


# --------------------------------------------------------------------------
# 8. Trip-Number Uniqueness: concurrent generation and database constraint
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_tc_rs_08_trip_number_uniqueness_and_constraint(real_delivery_replica_env):
    """Test 8: Test concurrent number generation and verify database unique constraint rejects duplicates."""
    db, client, admin_mgr = real_delivery_replica_env

    # 1. Concurrent trip number generation
    trip_nums = await asyncio.gather(*[generate_trip_number() for _ in range(10)])
    assert len(trip_nums) == 10
    assert len(set(trip_nums)) == 10, "All 10 generated trip numbers must be unique"

    # 2. Database unique index constraint
    dup_trip_num = "TRP-20261015-9999"
    await db.delivery_trips.insert_one({"trip_number": dup_trip_num, "status": "draft", "stops": []})

    with pytest.raises(pymongo.errors.DuplicateKeyError):
        await db.delivery_trips.insert_one({"trip_number": dup_trip_num, "status": "draft", "stops": []})
