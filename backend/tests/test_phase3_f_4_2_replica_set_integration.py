"""
Real MongoDB Replica-Set Integration Test Suite for Phase 3.F.4.2A.
Target: Delivery Wage Policy Settings, Handover Transaction & Obligation Accrual.

SAFETY REQUIREMENTS:
- Requires an explicitly configured test-only URI via TEST_MONGO_REPLICA_SET_URI.
- Validates URI and database isolation before connecting.
- Strictly rejects production hostnames, Atlas URIs, and production database names.
- Uses dedicated disposable database with automatic teardown.
- Fails closed / skips safely if isolated replica set is not available.
"""

import asyncio
import os
import re
import urllib.parse
from datetime import datetime, timezone
import pytest
import pymongo
import pymongo.errors
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from unittest.mock import patch
from fastapi import HTTPException

import server
from server import (
    record_delivery_stop_handover_core,
    admin_deliver_trip_stop,
    admin_update_delivery_trip_status,
    admin_update_delivery_wage_policy,
    DeliveryStopHandoverInput,
    DeliveryTripStatusUpdateInput,
    DeliveryWagePolicyInput,
    _execute_delivery_tx_or_fail_closed,
    build_delivery_accrual_event_key,
    DeliveryTripStatus,
    StopOutcome,
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

    # Enforce localhost/127.0.0.1 only
    if host not in ("localhost", "127.0.0.1"):
        raise ValueError(f"SECURITY ABORT: Hostname '{host}' is not strictly localhost or 127.0.0.1")

    # Reject production database names
    forbidden_db_names = ["sogil", "sogil-production", "production", "admin", "config", "local"]
    db_clean = (db_name or "").strip().lower()
    if db_clean in forbidden_db_names:
        raise ValueError(f"SECURITY ABORT: Database name '{db_clean}' is a protected production or system database")

    # Enforce disposable test prefix
    if not (db_clean.startswith("sogil_test_") or db_clean.startswith("test_disposable_")):
        raise ValueError(f"SECURITY ABORT: Database name '{db_clean}' must start with 'sogil_test_' or 'test_disposable_'")


TEST_URI = os.environ.get("TEST_MONGO_REPLICA_SET_URI", "").strip()
TEST_DB_NAME = os.environ.get("TEST_MONGO_DB_NAME", "sogil_test_disposable_replica_delivery_wage").strip()

IS_REPLICA_SET_CONFIGURED = bool(TEST_URI)


@pytest.fixture(scope="function")
async def real_delivery_wage_replica_env():
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
        "email": "manager@sogil.local",
        "role": "manager",
        "permissions": {"manage_orders": True, "access_finance": True}
    }
    owner_user = {
        "_id": ObjectId("660000000000000000000002"),
        "id": "660000000000000000000002",
        "name": "Owner Sogil",
        "email": "owner@sogil.local",
        "role": "owner",
        "permissions": {"manage_orders": True, "access_finance": True, "manage_settings": True}
    }
    helper_1 = {
        "_id": ObjectId("660000000000000000000011"),
        "id": "660000000000000000000011",
        "name": "Helper Joko",
        "email": "helper1@sogil.local",
        "role": "helper"
    }
    helper_2 = {
        "_id": ObjectId("660000000000000000000012"),
        "id": "660000000000000000000012",
        "name": "Helper Budi",
        "email": "helper2@sogil.local",
        "role": "helper"
    }
    await db.admins.insert_many([admin_mgr, owner_user, helper_1, helper_2])

    # Seed wage policy settings with cap
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.settings.insert_one({
        "key": "delivery_wage_policy",
        "value": {
            "base_wage_per_order_le": 50.0,
            "unusual_amount_threshold_le": 500.0,
            "max_helper_wage_per_order_le": 500.0,
            "currency": "EGP",
            "rounding_policy": "piastre_round_half_up",
            "updated_at": now_iso
        }
    })

    # Patch server globals to point to this isolated test replica set
    with patch.object(server, "client", client), \
         patch.object(server, "db", db), \
         patch("server.is_standalone_fallback_permitted", return_value=False):
        # Run real index initialization
        await server.seed()
        yield db, client, admin_mgr, owner_user, [helper_1, helper_2]

    # Teardown: drop disposable test database
    await client.drop_database(TEST_DB_NAME)
    client.close()


# --------------------------------------------------------------------------
# 1. Successful Handover: multi-document transaction commits atomically
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_tc_rs_01_successful_handover_multi_doc_transaction(real_delivery_wage_replica_env):
    """Test 1: Successful handover commits mutations atomically across orders, delivery_trips, and wage_obligations."""
    db, client, admin_mgr, _, helpers = real_delivery_wage_replica_env
    trip_id = ObjectId("670f00000000000000000101")
    ord_id = ObjectId("660f00000000000000000101")

    await db.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-RS-101",
        "order_status": "siap",
        "delivery_method": "delivery",
        "active_delivery_trip_id": str(trip_id),
        "total_le": 1500.0
    })

    await db.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-RS-101",
        "status": "in_transit",
        "trip_wage_rate_le": 50.0,
        "rate_policy_snapshot": {
            "applied_rate_le": 50.0,
            "is_custom_rate": False,
            "max_cap_at_dispatch_le": 500.0,
            "unusual_amount_threshold_le": 500.0,
            "currency": "EGP",
            "rounding_policy": "piastre_round_half_up"
        },
        "helpers": [
            {"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]},
            {"helper_id": str(helpers[1]["_id"]), "helper_name": helpers[1]["name"]}
        ],
        "stops": [{"order_id": str(ord_id), "outcome": "out_for_delivery"}],
        "delivered_stops_count": 0
    })

    # Execute handover via transaction wrapper
    res = await _execute_delivery_tx_or_fail_closed(
        lambda sess: record_delivery_stop_handover_core(
            trip_id=str(trip_id),
            order_id=str(ord_id),
            payload=DeliveryStopHandoverInput(recipient_name="Penerima RS", handover_notes="Aman dan mulus", helper_confirmed=True),
            admin=admin_mgr,
            session=sess
        )
    )
    assert res["ok"] is True

    # 1. Assert order committed
    order_after = await db.orders.find_one({"_id": ord_id})
    assert order_after["order_status"] == "selesai"
    assert order_after["delivery_logistics_status"] == "delivered"
    assert order_after["recognized_revenue_le"] == 1500.0

    # 2. Assert trip committed
    trip_after = await db.delivery_trips.find_one({"_id": trip_id})
    assert trip_after["stops"][0]["outcome"] == "delivered"
    assert trip_after["delivered_stops_count"] == 1
    assert len(trip_after["stops"][0]["wage_allocation_snapshot"]) == 2

    # 3. Assert wage obligations committed
    wobs = await db.wage_obligations.find({"order_id": str(ord_id)}).to_list(10)
    assert len(wobs) == 2
    assert sum(w["total_amount_le"] for w in wobs) == 50.0
    assert sum(w["amount_piastres"] for w in wobs) == 5000

    # 4. Assert zero finance cash transactions created on accrual
    fin_tx_count = await db.finance_transactions.count_documents({})
    assert fin_tx_count == 0


# --------------------------------------------------------------------------
# 2. Injected Failure Rollback: abort restores all documents to pre-tx state
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_tc_rs_02_transactional_rollback_on_injected_failure(real_delivery_wage_replica_env):
    """Test 2: Deliberately injected failure after partial mutations rolls back all changes across orders, trips, and obligations."""
    db, client, admin_mgr, _, helpers = real_delivery_wage_replica_env
    trip_id = ObjectId("670f00000000000000000102")
    ord_id = ObjectId("660f00000000000000000102")

    await db.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-RS-102",
        "order_status": "siap",
        "delivery_method": "delivery",
        "active_delivery_trip_id": str(trip_id),
        "total_le": 1500.0
    })

    await db.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-RS-102",
        "status": "in_transit",
        "trip_wage_rate_le": 50.0,
        "rate_policy_snapshot": {
            "applied_rate_le": 50.0,
            "is_custom_rate": False,
            "max_cap_at_dispatch_le": 500.0,
            "unusual_amount_threshold_le": 500.0
        },
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": "out_for_delivery"}],
        "delivered_stops_count": 0
    })

    # Failure injection: simulate crash during obligation number generation inside the transaction
    with patch("server.generate_obligation_number", side_effect=RuntimeError("INJECTED_ABORT_AFTER_ORDER_AND_TRIP_MUTATION")):
        with pytest.raises(RuntimeError) as ctx:
            await _execute_delivery_tx_or_fail_closed(
                lambda sess: record_delivery_stop_handover_core(
                    trip_id=str(trip_id),
                    order_id=str(ord_id),
                    payload=DeliveryStopHandoverInput(recipient_name="Penerima Rollback", helper_confirmed=True),
                    admin=admin_mgr,
                    session=sess
                )
            )
        assert "INJECTED_ABORT_AFTER_ORDER_AND_TRIP_MUTATION" in str(ctx.value)

    # DIRECT DATABASE QUERY: verify entire transaction rolled back cleanly!
    order_after = await db.orders.find_one({"_id": ord_id})
    assert order_after["order_status"] == "siap"
    assert order_after.get("delivery_logistics_status") != "delivered"
    assert order_after.get("delivered_trip_id") is None

    trip_after = await db.delivery_trips.find_one({"_id": trip_id})
    assert trip_after["stops"][0]["outcome"] == "out_for_delivery"
    assert trip_after["delivered_stops_count"] == 0

    wobs_count = await db.wage_obligations.count_documents({"order_id": str(ord_id)})
    assert wobs_count == 0


# --------------------------------------------------------------------------
# 3. Repeated Handover Idempotency: no duplicate wage obligations
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_tc_rs_03_repeated_handover_idempotency(real_delivery_wage_replica_env):
    """Test 3: Calling deliver twice on a real replica set returns already_delivered and creates zero duplicate obligations."""
    db, client, admin_mgr, _, helpers = real_delivery_wage_replica_env
    trip_id = ObjectId("670f00000000000000000103")
    ord_id = ObjectId("660f00000000000000000103")

    await db.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-RS-103",
        "order_status": "siap",
        "delivery_method": "delivery",
        "active_delivery_trip_id": str(trip_id),
        "total_le": 1000.0
    })

    await db.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-RS-103",
        "status": "in_transit",
        "trip_wage_rate_le": 50.0,
        "rate_policy_snapshot": {"applied_rate_le": 50.0},
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": "out_for_delivery"}],
        "delivered_stops_count": 0
    })

    # Call 1
    res1 = await _execute_delivery_tx_or_fail_closed(
        lambda sess: record_delivery_stop_handover_core(
            str(trip_id), str(ord_id),
            DeliveryStopHandoverInput(recipient_name="Penerima Idempotent", helper_confirmed=True),
            admin_mgr, session=sess
        )
    )
    assert res1["ok"] is True

    # Call 2
    res2 = await _execute_delivery_tx_or_fail_closed(
        lambda sess: record_delivery_stop_handover_core(
            str(trip_id), str(ord_id),
            DeliveryStopHandoverInput(recipient_name="Penerima Idempotent", helper_confirmed=True),
            admin_mgr, session=sess
        )
    )
    assert res2["ok"] is True
    assert res2.get("already_delivered") is True

    # Direct DB assertion: exactly 1 obligation exists
    wobs = await db.wage_obligations.find({"order_id": str(ord_id)}).to_list(10)
    assert len(wobs) == 1


# --------------------------------------------------------------------------
# 4. Unique Index Rejection: duplicate entitlement insertion aborted by DB
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_tc_rs_04_unique_index_prevents_duplicate_entitlements(real_delivery_wage_replica_env):
    """Test 4: Real MongoDB unique index uniq_wage_obligation_accrual_event rejects duplicate entitlement key."""
    db, client, admin_mgr, _, helpers = real_delivery_wage_replica_env
    order_id = "660f00000000000000000104"
    worker_id = str(helpers[0]["_id"])
    event_key = build_delivery_accrual_event_key(order_id, worker_id)

    # Insert obligation 1
    await db.wage_obligations.insert_one({
        "obligation_number": "OBL-RS-TEST-0001",
        "accrual_event_key": event_key,
        "order_id": order_id,
        "worker_id": worker_id,
        "task_category": "delivery",
        "total_amount_le": 50.0,
        "amount_piastres": 5000,
        "status": "accrued"
    })

    # Insert obligation 2 with duplicate entitlement key -> must raise DuplicateKeyError from MongoDB
    with pytest.raises(pymongo.errors.DuplicateKeyError):
        await db.wage_obligations.insert_one({
            "obligation_number": "OBL-RS-TEST-0002",
            "accrual_event_key": event_key,
            "order_id": order_id,
            "worker_id": worker_id,
            "task_category": "delivery",
            "total_amount_le": 50.0,
            "amount_piastres": 5000,
            "status": "accrued"
        })


# --------------------------------------------------------------------------
# 5. Dispatch-Time Snapshot Authoritative after Policy Update
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_tc_rs_05_dispatch_snapshot_authoritative_after_policy_change(real_delivery_wage_replica_env):
    """Test 5: Live replica set verifies dispatch snapshot remains strictly authoritative after Owner policy change."""
    db, client, admin_mgr, owner_user, helpers = real_delivery_wage_replica_env
    trip_id = ObjectId("670f00000000000000000105")
    ord_id = ObjectId("660f00000000000000000105")

    await db.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-RS-105",
        "order_status": "siap",
        "delivery_method": "delivery",
        "active_delivery_trip_id": str(trip_id),
        "total_le": 1000.0
    })

    # Trip scheduled with 0.0 trip rate -> dispatch must capture 50.0 LE active policy
    await db.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-RS-105",
        "status": "scheduled",
        "trip_wage_rate_le": 0.0,
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": "pending"}]
    })

    # 1. Dispatch trip
    await admin_update_delivery_trip_status(
        trip_id=str(trip_id),
        payload=DeliveryTripStatusUpdateInput(target_status="in_transit"),
        admin=owner_user
    )

    # 2. Owner changes policy in db.settings to 85.0 LE
    await admin_update_delivery_wage_policy(
        payload=DeliveryWagePolicyInput(base_wage_per_order_le=85.0, unusual_amount_threshold_le=600.0),
        admin=owner_user
    )

    # 3. Handover running trip without custom_wage_le
    res = await _execute_delivery_tx_or_fail_closed(
        lambda sess: record_delivery_stop_handover_core(
            trip_id=str(trip_id),
            order_id=str(ord_id),
            payload=DeliveryStopHandoverInput(recipient_name="Penerima Snapshot", helper_confirmed=True),
            admin=admin_mgr,
            session=sess
        )
    )
    assert res["ok"] is True

    # 4. Direct DB assertion: wage obligation is 50.0 LE (dispatch snapshot rate), NOT 85.0 LE!
    wob = await db.wage_obligations.find_one({"order_id": str(ord_id)})
    assert wob["total_amount_le"] == 50.0
    assert wob["amount_piastres"] == 5000


# --------------------------------------------------------------------------
# 6. Transaction Unavailability Fails Closed
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_tc_rs_06_transaction_unavailability_fails_closed(real_delivery_wage_replica_env):
    """Test 6: In fail-closed mode, unavailability of transactions rejects operation with HTTP 503 and zero mutations."""
    db, client, admin_mgr, _, helpers = real_delivery_wage_replica_env
    trip_id = ObjectId("670f00000000000000000106")
    ord_id = ObjectId("660f00000000000000000106")

    await db.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-RS-106",
        "order_status": "siap",
        "delivery_method": "delivery",
        "active_delivery_trip_id": str(trip_id),
        "total_le": 1000.0
    })

    await db.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-RS-106",
        "status": "in_transit",
        "rate_policy_snapshot": {"applied_rate_le": 50.0},
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": "out_for_delivery"}]
    })

    # Simulate transaction capability failure with standalone fallback forbidden
    with patch.object(client, "start_session", side_effect=pymongo.errors.ConfigurationError("Cluster not replica set")), \
         patch("server.is_standalone_fallback_permitted", return_value=False):
        with pytest.raises(HTTPException) as ctx:
            await _execute_delivery_tx_or_fail_closed(
                lambda sess: record_delivery_stop_handover_core(
                    str(trip_id), str(ord_id),
                    DeliveryStopHandoverInput(recipient_name="Penerima FailClosed", helper_confirmed=True),
                    admin_mgr, session=sess
                )
            )
        assert ctx.value.status_code == 503
        assert "Fail-Closed" in ctx.value.detail

    # Direct DB assertion: order remains uncompleted
    order_after = await db.orders.find_one({"_id": ord_id})
    assert order_after["order_status"] == "siap"
    assert await db.wage_obligations.count_documents({"order_id": str(ord_id)}) == 0
