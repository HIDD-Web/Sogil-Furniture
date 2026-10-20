"""
Real MongoDB Replica-Set Integration Test Suite for Phase 3.F.3.
Target: Sogil Furniture Worker Wage Obligations & Settlement.

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
from decimal import Decimal
import pytest
import pymongo
import pymongo.errors
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from unittest.mock import patch, AsyncMock

import server
from server import (
    admin_create_wage_settlement,
    admin_void_wage_settlement,
    admin_verify_work_assignment,
    WageSettlementCreateInput,
    WageSettlementAllocationItem,
    WageSettlementVoidInput,
    WorkAssignmentVerifyInput,
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
TEST_DB_NAME = os.environ.get("TEST_MONGO_DB_NAME", "sogil_test_disposable_replica").strip()

# Check whether test replica set is configured
IS_REPLICA_SET_CONFIGURED = bool(TEST_URI)


@pytest.fixture(scope="function")
async def real_replica_set_env():
    """Provisions a disposable database on a real MongoDB replica set.
    Performs isolation check, provisions indexes, seeds test users, and drops database on teardown.
    """
    if not IS_REPLICA_SET_CONFIGURED:
        pytest.skip(
            "BLOCKED: TEST_MONGO_REPLICA_SET_URI not configured. "
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

    # Seed admin, owner, and worker
    admin_user = {
        "_id": ObjectId("660000000000000000000001"),
        "id": "660000000000000000000001",
        "name": "Finance Admin",
        "email": "finance.test@sogil.com",
        "role": "admin",
        "permissions": {"access_finance": True, "manage_orders": True},
    }
    owner_user = {
        "_id": ObjectId("660000000000000000000002"),
        "id": "660000000000000000000002",
        "name": "Owner Sogil",
        "email": "owner.test@sogil.com",
        "role": "owner",
        "permissions": {},
    }
    worker_user = {
        "_id": ObjectId("660000000000000000000003"),
        "id": "660000000000000000000003",
        "name": "Tukang Kayu Ahmed",
        "email": "ahmed.test@sogil.com",
        "role": "worker",
        "permissions": {},
    }
    await db.admins.insert_many([admin_user, owner_user, worker_user])

    # Patch server globals to point to this isolated test replica set
    with patch.object(server, "client", client), \
         patch.object(server, "db", db), \
         patch("server.is_standalone_fallback_permitted", return_value=False):
        # Run real index initialization
        await server.seed()
        yield db, client, admin_user, owner_user, worker_user

    # Teardown: drop disposable test database
    await client.drop_database(TEST_DB_NAME)
    client.close()


# --------------------------------------------------------------------------
# TC-RS-01: Atomic Multi-Document Commit on Real Replica Set
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_tc_rs_01_atomic_commit(real_replica_set_env):
    db, client, admin_user, owner_user, worker_user = real_replica_set_env
    wid = str(worker_user["_id"])

    # Create obligation
    ob_id = ObjectId("66aaaa000000000000000001")
    ob_doc = {
        "_id": ob_id,
        "obligation_number": "WOB-202610-0001",
        "accrual_event_key": "acc_66aaaa000000000000000001",
        "work_assignment_id": "assign_001",
        "worker_id": wid,
        "worker_name": worker_user["name"],
        "order_id": "ord_100",
        "order_number": "ORD-100",
        "order_item_id": "item_1",
        "task_category": "frame",
        "pricing_basis": "per_unit",
        "rate_le": 100.0,
        "accepted_quantity": 2,
        "total_amount_le": 200.0,
        "currency": "EGP",
        "status": "accrued",
        "paid_amount_le": 0.0,
        "settlement_allocations": [],
        "created_at": "2026-10-14T00:00:00Z",
    }
    await db.wage_obligations.insert_one(ob_doc)

    # Execute settlement of 200 LE
    payload = WageSettlementCreateInput(
        worker_id=wid,
        amount_le=200.0,
        payment_method="cash",
        idempotency_key="rs_idem_001",
    )
    settle_res = await admin_create_wage_settlement(payload, admin=admin_user)
    assert settle_res["amount_le"] == 200.0
    st_num = settle_res["settlement_number"]

    # Verify exact records committed in real MongoDB
    st_db = await db.wage_settlements.find_one({"settlement_number": st_num})
    assert st_db is not None
    assert st_db["status"] == "recorded"
    assert st_db["amount_le"] == 200.0

    # Finance transaction committed
    txn_id = st_db["finance_transaction_id"]
    txn = await db.finance_transactions.find_one({"_id": ObjectId(txn_id)})
    assert txn is not None
    assert txn["type"] == "expense"
    assert txn["category"] == "Pekerja"
    assert txn["amount"] == 200.0
    assert txn["classification"] == "cost"
    assert txn["wage_settlement_id"] == str(st_db["_id"])

    # Employee wages mirror committed
    ew = await db.employee_wages.find_one({"transaction_id": txn_id})
    assert ew is not None
    assert ew["amount"] == 200.0
    assert ew["employee_id"] == wid

    # Wage obligation fully paid
    ob_after = await db.wage_obligations.find_one({"_id": ob_id})
    assert ob_after["paid_amount_le"] == 200.0
    assert ob_after["status"] == "paid"
    assert len(ob_after["settlement_allocations"]) == 1
    assert ob_after["settlement_allocations"][0]["settlement_number"] == st_num


# --------------------------------------------------------------------------
# TC-RS-02: Real Transaction Abort Rollback
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_tc_rs_02_transaction_abort(real_replica_set_env):
    db, client, admin_user, owner_user, worker_user = real_replica_set_env
    wid = str(worker_user["_id"])

    ob_id = ObjectId("66aaaa000000000000000002")
    ob_doc = {
        "_id": ob_id,
        "obligation_number": "WOB-202610-0002",
        "accrual_event_key": "acc_66aaaa000000000000000002",
        "worker_id": wid,
        "worker_name": worker_user["name"],
        "total_amount_le": 150.0,
        "paid_amount_le": 0.0,
        "status": "accrued",
        "settlement_allocations": [],
        "created_at": "2026-10-14T00:00:00Z",
    }
    await db.wage_obligations.insert_one(ob_doc)

    # Fault injection: patch AsyncIOMotorCollection.update_one to fail inside the transaction
    from motor.motor_asyncio import AsyncIOMotorCollection
    original_update_one = AsyncIOMotorCollection.update_one

    async def _failing_update_one(self, *args, **kwargs):
        # Allow initial setup, but fail inside transaction on wage_obligations collection
        if kwargs.get("session") is not None and getattr(self, "name", "") == "wage_obligations":
            raise RuntimeError("FAULT INJECTION: Simulating network crash before transaction commit")
        return await original_update_one(self, *args, **kwargs)

    payload = WageSettlementCreateInput(
        worker_id=wid,
        amount_le=150.0,
        payment_method="cash",
        idempotency_key="rs_idem_abort_002",
    )

    with patch.object(AsyncIOMotorCollection, "update_one", _failing_update_one):
        with pytest.raises(Exception):
            await admin_create_wage_settlement(payload, admin=admin_user)

    # VERIFY ZERO PARTIAL WRITES SURVIVED IN REAL MONGODB
    # 1. No wage settlements created
    st_count = await db.wage_settlements.count_documents({"worker_id": wid})
    assert st_count == 0

    # 2. No finance transactions created
    txn_count = await db.finance_transactions.count_documents({"recipient_employee_id": wid})
    assert txn_count == 0

    # 3. No employee wages mirror created
    ew_count = await db.employee_wages.count_documents({"employee_id": wid})
    assert ew_count == 0

    # 4. Wage obligation remains completely intact at accrued (0 paid)
    ob_intact = await db.wage_obligations.find_one({"_id": ob_id})
    assert ob_intact["paid_amount_le"] == 0.0
    assert ob_intact["status"] == "accrued"
    assert len(ob_intact.get("settlement_allocations", [])) == 0


# --------------------------------------------------------------------------
# TC-RS-03: Real Parallel Concurrency Against Same Obligation
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_tc_rs_03_concurrent_settlement(real_replica_set_env):
    db, client, admin_user, owner_user, worker_user = real_replica_set_env
    wid = str(worker_user["_id"])

    ob_id = ObjectId("66aaaa000000000000000003")
    ob_doc = {
        "_id": ob_id,
        "obligation_number": "WOB-202610-0003",
        "accrual_event_key": "acc_66aaaa000000000000000003",
        "worker_id": wid,
        "worker_name": worker_user["name"],
        "total_amount_le": 100.0,
        "paid_amount_le": 0.0,
        "status": "accrued",
        "settlement_allocations": [],
        "created_at": "2026-10-14T00:00:00Z",
    }
    await db.wage_obligations.insert_one(ob_doc)

    # Two concurrent settlement requests for 100 LE with DIFFERENT idempotency keys
    p1 = WageSettlementCreateInput(worker_id=wid, amount_le=100.0, idempotency_key="race_key_1")
    p2 = WageSettlementCreateInput(worker_id=wid, amount_le=100.0, idempotency_key="race_key_2")

    results = await asyncio.gather(
        admin_create_wage_settlement(p1, admin=admin_user),
        admin_create_wage_settlement(p2, admin=admin_user),
        return_exceptions=True
    )

    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]

    # Exactly one request must win; the other must fail (HTTP 409 or 422)
    assert len(successes) == 1
    assert len(failures) == 1

    # Verify obligation is NOT overpaid
    ob_final = await db.wage_obligations.find_one({"_id": ob_id})
    assert ob_final["paid_amount_le"] == 100.0
    assert ob_final["status"] == "paid"

    # Exactly one finance transaction exists
    txn_count = await db.finance_transactions.count_documents({"recipient_employee_id": wid})
    assert txn_count == 1


# --------------------------------------------------------------------------
# TC-RS-04: Real Concurrent Idempotency Race (Same Key)
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_tc_rs_04_idempotency_race(real_replica_set_env):
    db, client, admin_user, owner_user, worker_user = real_replica_set_env
    wid = str(worker_user["_id"])

    ob_id = ObjectId("66aaaa000000000000000004")
    ob_doc = {
        "_id": ob_id,
        "obligation_number": "WOB-202610-0004",
        "accrual_event_key": "acc_66aaaa000000000000000004",
        "worker_id": wid,
        "worker_name": worker_user["name"],
        "total_amount_le": 100.0,
        "paid_amount_le": 0.0,
        "status": "accrued",
        "settlement_allocations": [],
        "created_at": "2026-10-14T00:00:00Z",
    }
    await db.wage_obligations.insert_one(ob_doc)

    same_key = "race_identical_key_004"
    p1 = WageSettlementCreateInput(worker_id=wid, amount_le=100.0, idempotency_key=same_key)
    p2 = WageSettlementCreateInput(worker_id=wid, amount_le=100.0, idempotency_key=same_key)

    results = await asyncio.gather(
        admin_create_wage_settlement(p1, admin=admin_user),
        admin_create_wage_settlement(p2, admin=admin_user),
        return_exceptions=True
    )

    # Both requests must conclude safely (either returning winning settlement doc or handled cleanly)
    non_err = [r for r in results if not isinstance(r, Exception)]
    assert len(non_err) >= 1

    # Exactly ONE settlement document in db
    st_count = await db.wage_settlements.count_documents({"worker_id": wid})
    assert st_count == 1

    # Exactly ONE finance transaction in db
    txn_count = await db.finance_transactions.count_documents({"recipient_employee_id": wid})
    assert txn_count == 1

    # Obligation paid 100 LE
    ob_final = await db.wage_obligations.find_one({"_id": ob_id})
    assert ob_final["paid_amount_le"] == 100.0


# --------------------------------------------------------------------------
# TC-RS-05: Real Unique Index Enforcement & Fail-Closed Gate
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_tc_rs_05_index_and_fail_closed(real_replica_set_env):
    db, client, admin_user, owner_user, worker_user = real_replica_set_env

    # 1. Real MongoDB unique index constraint verification on settlement_number
    await db.wage_settlements.insert_one({
        "settlement_number": "WST-UNIQUE-TEST",
        "worker_id": "w_1",
        "amount_le": 50.0,
        "created_at": "2026-10-14T00:00:00Z"
    })

    with pytest.raises(pymongo.errors.DuplicateKeyError):
        await db.wage_settlements.insert_one({
            "settlement_number": "WST-UNIQUE-TEST",
            "worker_id": "w_2",
            "amount_le": 100.0,
            "created_at": "2026-10-14T00:00:00Z"
        })

    # 2. Real MongoDB partial unique index constraint on idempotency_key
    await db.wage_settlements.insert_one({
        "settlement_number": "WST-IDEM-TEST-1",
        "idempotency_key": "unique_idem_key_005",
        "worker_id": "w_1",
        "amount_le": 50.0,
        "created_at": "2026-10-14T00:00:00Z"
    })

    with pytest.raises(pymongo.errors.DuplicateKeyError):
        await db.wage_settlements.insert_one({
            "settlement_number": "WST-IDEM-TEST-2",
            "idempotency_key": "unique_idem_key_005",
            "worker_id": "w_2",
            "amount_le": 75.0,
            "created_at": "2026-10-14T00:00:00Z"
        })
