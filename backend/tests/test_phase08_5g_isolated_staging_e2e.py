"""Phase 08.5G — Isolated Staging End-to-End Execution Test Suite.
Sogil Furniture | Admin Wage Activation System | Isolated Replica Set Testing

Validates runtime behavior against a verified 3-node MongoDB Replica Set (sogil-staging-rs):
A. Completion and payment ordering (Scenarios 1-5)
B. Activation lifecycle (Scenarios 6-11)
C. Financial integrity (Scenarios 12-15)
D. Order-state integrity (Scenarios 16-18)
E. Transaction and recovery (Scenarios 19-23)
"""

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List

import pytest
import pymongo
import pymongo.errors
from motor.motor_asyncio import AsyncIOMotorClient

# Setup module paths
BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
for p in [str(REPO_ROOT), str(BACKEND_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.staging_replica_set_manager import (
    CONNECTION_URI as STAGING_URI,
    wait_for_cluster_healthy,
)
from backend.tests.isolation_guard import validate_test_database_isolation
import backend.index_provisioner as ip
import backend.server as server
from backend.server import (
    build_admin_wage_accrual_event_key,
    is_order_completed,
    is_order_fully_paid,
    is_order_excluded_from_admin_wage,
    is_order_historical_unreconciled,
    evaluate_and_process_order_admin_wage_accrual,
    process_order_admin_wage_accrual,
    execute_transaction_with_safety,
    get_order_admin_wage_eligibility,
    get_active_admin_wage_policy,
)


@pytest.fixture(scope="session")
def staging_cluster():
    """Verifies that the isolated 3-node staging replica set is up and healthy."""
    health = wait_for_cluster_healthy(timeout_sec=10.0)
    assert health["healthy"] is True
    assert health["set"] == "sogil-staging-rs"
    assert len(health["secondaries"]) == 2
    return health


@pytest.fixture(scope="function")
async def staging_db(staging_cluster):
    """Provisions an isolated, disposable database with required indexes on the replica set."""
    db_name = f"sogil_test_staging_085g_{uuid.uuid4().hex[:8]}"
    validate_test_database_isolation(STAGING_URI, db_name)

    client = AsyncIOMotorClient(STAGING_URI, serverSelectionTimeoutMS=3000)
    db = client[db_name]

    # Provision all required indexes
    await ip.provision_indexes(db, dry_run=False, target_uri=STAGING_URI, db_name=db_name)

    # Patch server globals to point to isolated staging DB
    orig_client = server.client
    orig_db = server.db
    server.client = client
    server.db = db

    # Seed synthetic admin actor
    admin_id = "admin_synthetic_01"
    admin_doc = {
        "_id": admin_id,
        "id": admin_id,
        "name": "Sarah Administrasi Synthetic",
        "email": "sarah.synthetic@sogil.local",
        "role": "admin",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.admins.insert_one(admin_doc)

    try:
        yield client, db, admin_doc
    finally:
        server.client = orig_client
        server.db = orig_db
        try:
            await client.drop_database(db_name)
        except Exception:
            pass
        client.close()


async def set_staging_admin_wage_policy(
    db,
    enabled: bool = True,
    default_wage: float = 50.0,
    max_wage: float = 100.0,
    admin_id: str = "admin_synthetic_01",
    admin_name: str = "Sarah Administrasi Synthetic",
    cycles: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    now_iso = datetime.now(timezone.utc).isoformat()
    if cycles is None:
        if enabled:
            cycles = [
                {
                    "cycle_id": "cycle_synth_01",
                    "enabled_at": now_iso,
                    "disabled_at": None,
                    "opened_by_id": admin_id,
                    "opened_by_name": admin_name,
                }
            ]
        else:
            cycles = [
                {
                    "cycle_id": "cycle_synth_00",
                    "enabled_at": "2026-10-01T00:00:00Z",
                    "disabled_at": now_iso,
                    "opened_by_id": admin_id,
                    "opened_by_name": admin_name,
                }
            ]

    val = {
        "enabled": enabled,
        "is_configured": True,
        "default_wage_per_order_le": default_wage,
        "default_recipient_id": admin_id,
        "default_recipient_name": admin_name,
        "unusual_amount_threshold_le": 80.0,
        "max_wage_per_order_le": max_wage,
        "currency": "EGP",
        "current_cycle_id": "cycle_synth_01" if enabled else None,
        "activation_cycles": cycles,
        "updated_at": now_iso,
        "updated_by_id": admin_id,
        "updated_by_name": admin_name,
    }
    await db.settings.update_one(
        {"key": "admin_wage_policy"},
        {"$set": {"key": "admin_wage_policy", "value": val}},
        upsert=True,
    )
    return val


# =========================================================================
# GROUP A: COMPLETION AND PAYMENT ORDERING
# =========================================================================

@pytest.mark.anyio
async def test_01_completion_before_full_payment_sequence_a(staging_db):
    """Scenario 1: Sequence A (Completed first, fully paid later)."""
    client, db, admin = staging_db
    await set_staging_admin_wage_policy(db, enabled=True, admin_id=admin["id"], admin_name=admin["name"])
    order_id = "SYNTH-A01-001"

    # 1. Order completed but unpaid
    order_doc = {
        "_id": order_id,
        "order_number": "ORD-A01",
        "order_status": "selesai",
        "payment_status": "belum_dibayar",
        "total_le": 500.0,
        "paid_amount_le": 0.0,
        "outstanding_amount_le": 500.0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.orders.insert_one(order_doc)

    # Initial check: zero obligations
    assert await db.wage_obligations.count_documents({"order_id": order_id}) == 0

    # Step A: Evaluate before payment
    res_a = await evaluate_and_process_order_admin_wage_accrual(order_doc, admin, lifecycle_event="order_completed")
    assert res_a["status"] == "skipped_payment_not_lunas"
    assert await db.wage_obligations.count_documents({"order_id": order_id}) == 0

    # Step B: Customer payment arrives (transition to lunas)
    payment_summary = {
        "payment_status": "lunas",
        "paid_amount_le": 500.0,
        "outstanding_amount_le": 0.0,
        "total_le": 500.0,
        "payment_date": datetime.now(timezone.utc).isoformat(),
    }
    order_doc.update(payment_summary)

    async def tx_fn(sess):
        return await evaluate_and_process_order_admin_wage_accrual(
            order_doc, admin, session=sess, payment_summary=payment_summary, lifecycle_event="payment_lunas"
        )

    res_b = await execute_transaction_with_safety(client, tx_fn)
    assert res_b["status"] == "accrued"
    assert res_b["obligation"]["amount_le"] == 50.0

    # After state DB assertions
    wob = await db.wage_obligations.find_one({"order_id": order_id})
    assert wob is not None
    assert wob["accrual_event_key"] == f"admin_wage:{order_id}"
    assert wob["total_amount_le"] == 50.0
    assert wob["status"] == "accrued"
    assert wob["worker_id"] == admin["id"]
    assert await db.wage_obligations.count_documents({"order_id": order_id}) == 1


@pytest.mark.anyio
async def test_02_full_payment_before_completion_sequence_b(staging_db):
    """Scenario 2: Sequence B (Fully paid first, completed later)."""
    client, db, admin = staging_db
    await set_staging_admin_wage_policy(db, enabled=True, admin_id=admin["id"], admin_name=admin["name"])
    order_id = "SYNTH-A02-002"

    # 1. Order in progress but fully paid
    order_doc = {
        "_id": order_id,
        "order_number": "ORD-A02",
        "order_status": "diproses",
        "payment_status": "lunas",
        "total_le": 750.0,
        "paid_amount_le": 750.0,
        "outstanding_amount_le": 0.0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.orders.insert_one(order_doc)

    # Step A: Evaluate while not completed
    res_a = await evaluate_and_process_order_admin_wage_accrual(order_doc, admin, lifecycle_event="order_completed")
    assert res_a["status"] == "skipped_order_not_completed"
    assert await db.wage_obligations.count_documents({"order_id": order_id}) == 0

    # Step B: Order transitions to selesai
    order_doc["order_status"] = "selesai"
    order_doc["completed_at"] = datetime.now(timezone.utc).isoformat()

    async def tx_fn(sess):
        return await evaluate_and_process_order_admin_wage_accrual(order_doc, admin, session=sess, lifecycle_event="order_completed")

    res_b = await execute_transaction_with_safety(client, tx_fn)
    assert res_b["status"] == "accrued"

    # Database assertion
    wob = await db.wage_obligations.find_one({"order_id": order_id})
    assert wob is not None
    assert wob["accrual_event_key"] == f"admin_wage:{order_id}"
    assert wob["total_amount_le"] == 50.0
    assert await db.wage_obligations.count_documents({"order_id": order_id}) == 1


@pytest.mark.anyio
async def test_03_completion_and_full_payment_while_automation_enabled(staging_db):
    """Scenario 3: Completion & payment while automation is enabled."""
    client, db, admin = staging_db
    await set_staging_admin_wage_policy(db, enabled=True, admin_id=admin["id"], admin_name=admin["name"])
    order_id = "SYNTH-A03-003"

    order_doc = {
        "_id": order_id,
        "order_number": "ORD-A03",
        "order_status": "diproses",
        "payment_status": "lunas",
        "total_le": 300.0,
        "paid_amount_le": 300.0,
        "outstanding_amount_le": 0.0,
    }
    await db.orders.insert_one(order_doc)

    order_doc["order_status"] = "selesai"
    order_doc["completed_at"] = datetime.now(timezone.utc).isoformat()

    async def tx_fn(sess):
        return await evaluate_and_process_order_admin_wage_accrual(order_doc, admin, session=sess, lifecycle_event="order_completed")

    res = await execute_transaction_with_safety(client, tx_fn)
    assert res["status"] == "accrued"
    assert res["eligibility"]["scope_status"] == "accrued"
    assert res["eligibility"]["in_active_cycle_at_maturity"] is True

    wob = await db.wage_obligations.find_one({"order_id": order_id})
    assert wob is not None
    assert wob["total_amount_le"] == 50.0


@pytest.mark.anyio
async def test_04_completion_and_full_payment_while_automation_disabled(staging_db):
    """Scenario 4: Completion & payment while automation is disabled."""
    client, db, admin = staging_db
    await set_staging_admin_wage_policy(db, enabled=False, admin_id=admin["id"], admin_name=admin["name"])
    order_id = "SYNTH-A04-004"

    order_doc = {
        "_id": order_id,
        "order_number": "ORD-A04",
        "order_status": "selesai",
        "payment_status": "lunas",
        "total_le": 450.0,
        "paid_amount_le": 450.0,
        "outstanding_amount_le": 0.0,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.orders.insert_one(order_doc)

    # Accrual evaluation under disabled policy
    res = await evaluate_and_process_order_admin_wage_accrual(order_doc, admin, lifecycle_event="order_completed")
    assert res["status"] == "skipped_policy_disabled"
    assert res["eligibility"]["scope_status"] == "skipped_disabled_window"
    assert res["eligibility"]["in_active_cycle_at_maturity"] is False

    # Persist the skipped state on order
    await db.orders.update_one(
        {"_id": order_id},
        {"$set": {
            "admin_wage_skipped": res["skipped"],
            "admin_wage_eligibility": res["eligibility"]
        }}
    )

    # Zero obligations in database
    assert await db.wage_obligations.count_documents({"order_id": order_id}) == 0
    saved = await db.orders.find_one({"_id": order_id})
    assert saved["admin_wage_eligibility"]["scope_status"] == "skipped_disabled_window"


@pytest.mark.anyio
async def test_05_order_incomplete_or_unpaid_across_disable_reenable_cycle(staging_db):
    """Scenario 5: Order pending across disable/re-enable cycle accrues in new active cycle."""
    client, db, admin = staging_db
    # Policy initially disabled
    await set_staging_admin_wage_policy(db, enabled=False, admin_id=admin["id"], admin_name=admin["name"])
    order_id = "SYNTH-A05-005"

    # Order created while disabled, but remained incomplete and unpaid
    order_doc = {
        "_id": order_id,
        "order_number": "ORD-A05",
        "order_status": "diproses",
        "payment_status": "belum_dibayar",
        "total_le": 800.0,
        "paid_amount_le": 0.0,
        "outstanding_amount_le": 800.0,
        "created_at": "2026-10-15T10:00:00Z",
    }
    await db.orders.insert_one(order_doc)

    # Verify eligibility is in_scope_pending (not skipped)
    el = get_order_admin_wage_eligibility(order_doc)
    assert el["scope_status"] == "in_scope_pending"

    # Now policy is re-enabled, and order completes and pays in the new active cycle
    await set_staging_admin_wage_policy(db, enabled=True, admin_id=admin["id"], admin_name=admin["name"])
    now_iso = datetime.now(timezone.utc).isoformat()
    order_doc["order_status"] = "selesai"
    order_doc["payment_status"] = "lunas"
    order_doc["paid_amount_le"] = 800.0
    order_doc["outstanding_amount_le"] = 0.0
    order_doc["completed_at"] = now_iso

    async def tx_fn(sess):
        return await evaluate_and_process_order_admin_wage_accrual(order_doc, admin, session=sess, lifecycle_event="order_completed")

    res = await execute_transaction_with_safety(client, tx_fn)
    assert res["status"] == "accrued"
    assert await db.wage_obligations.count_documents({"order_id": order_id}) == 1


# =========================================================================
# GROUP B: ACTIVATION LIFECYCLE
# =========================================================================

@pytest.mark.anyio
async def test_06_disabled_window_skip_remains_permanent(staging_db):
    """Scenario 6: Disabled-window skip is persisted permanently."""
    client, db, admin = staging_db
    await set_staging_admin_wage_policy(db, enabled=False, admin_id=admin["id"], admin_name=admin["name"])
    order_id = "SYNTH-B06-006"
    now_iso = datetime.now(timezone.utc).isoformat()

    order_doc = {
        "_id": order_id,
        "order_number": "ORD-B06",
        "order_status": "selesai",
        "payment_status": "lunas",
        "total_le": 400.0,
        "paid_amount_le": 400.0,
        "outstanding_amount_le": 0.0,
        "completed_at": now_iso,
        "admin_wage_skipped": {
            "status": "skipped_disabled_window",
            "reason": "Pesanan diselesaikan saat otomatisasi OFF",
            "skipped_at": now_iso
        },
        "admin_wage_eligibility": {
            "scope_status": "skipped_disabled_window",
            "governance_mode": "automatic",
            "evaluated_at": now_iso,
            "version": 1
        }
    }
    await db.orders.insert_one(order_doc)

    saved = await db.orders.find_one({"_id": order_id})
    assert saved["admin_wage_eligibility"]["scope_status"] == "skipped_disabled_window"
    assert await db.wage_obligations.count_documents({"order_id": order_id}) == 0


@pytest.mark.anyio
async def test_07_reenabling_automation_does_not_retroactively_accrue(staging_db):
    """Scenario 7: Re-enabling automation does not retroactively accrue skipped order."""
    client, db, admin = staging_db
    # Policy re-enabled
    await set_staging_admin_wage_policy(db, enabled=True, admin_id=admin["id"], admin_name=admin["name"])
    order_id = "SYNTH-B07-007"
    now_iso = datetime.now(timezone.utc).isoformat()

    order_doc = {
        "_id": order_id,
        "order_number": "ORD-B07",
        "order_status": "selesai",
        "payment_status": "lunas",
        "total_le": 400.0,
        "paid_amount_le": 400.0,
        "outstanding_amount_le": 0.0,
        "completed_at": now_iso,
        "admin_wage_skipped": {
            "status": "skipped_disabled_window",
            "reason": "Pesanan selesai saat otomatisasi OFF",
            "skipped_at": now_iso
        },
        "admin_wage_eligibility": {
            "scope_status": "skipped_disabled_window",
            "governance_mode": "automatic",
            "evaluated_at": now_iso,
            "version": 1
        }
    }
    await db.orders.insert_one(order_doc)

    # Re-evaluation under active policy
    res = await evaluate_and_process_order_admin_wage_accrual(order_doc, admin, lifecycle_event="order_completed")
    assert res["status"] == "skipped_disabled_window_matured"
    assert res["eligibility"]["scope_status"] == "skipped_disabled_window"

    # Zero obligations created
    assert await db.wage_obligations.count_documents({"order_id": order_id}) == 0


@pytest.mark.anyio
async def test_08_order_still_pending_at_reactivation_becomes_eligible(staging_db):
    """Scenario 8: Order still incomplete/unpaid at reactivation accrues post-reactivation."""
    client, db, admin = staging_db
    await set_staging_admin_wage_policy(db, enabled=True, admin_id=admin["id"], admin_name=admin["name"])
    order_id = "SYNTH-B08-008"

    order_doc = {
        "_id": order_id,
        "order_number": "ORD-B08",
        "order_status": "diproses",
        "payment_status": "belum_dibayar",
        "total_le": 600.0,
        "paid_amount_le": 0.0,
        "outstanding_amount_le": 600.0,
        "created_at": "2026-10-20T00:00:00Z",
    }
    await db.orders.insert_one(order_doc)

    # Now completed and paid
    order_doc["order_status"] = "selesai"
    order_doc["payment_status"] = "lunas"
    order_doc["paid_amount_le"] = 600.0
    order_doc["outstanding_amount_le"] = 0.0
    order_doc["completed_at"] = datetime.now(timezone.utc).isoformat()

    async def tx_fn(sess):
        return await evaluate_and_process_order_admin_wage_accrual(order_doc, admin, session=sess, lifecycle_event="order_completed")

    res = await execute_transaction_with_safety(client, tx_fn)
    assert res["status"] == "accrued"
    assert await db.wage_obligations.count_documents({"order_id": order_id}) == 1


@pytest.mark.anyio
async def test_09_repeated_events_and_concurrency_idempotency(staging_db):
    """Scenario 9: Repeated evaluation returns already_accrued without duplicating."""
    client, db, admin = staging_db
    await set_staging_admin_wage_policy(db, enabled=True, admin_id=admin["id"], admin_name=admin["name"])
    order_id = "SYNTH-B09-009"

    order_doc = {
        "_id": order_id,
        "order_number": "ORD-B09",
        "order_status": "diproses",
        "payment_status": "lunas",
        "total_le": 500.0,
        "paid_amount_le": 500.0,
        "outstanding_amount_le": 0.0,
    }
    await db.orders.insert_one(order_doc)

    order_doc["order_status"] = "selesai"
    order_doc["completed_at"] = datetime.now(timezone.utc).isoformat()

    # First call
    res1 = await evaluate_and_process_order_admin_wage_accrual(order_doc, admin, lifecycle_event="order_completed")
    assert res1["status"] == "accrued"
    assert await db.wage_obligations.count_documents({"order_id": order_id}) == 1

    # Second call (repeat trigger)
    res2 = await evaluate_and_process_order_admin_wage_accrual(order_doc, admin, lifecycle_event="order_completed")
    assert res2["status"] == "already_accrued"
    assert await db.wage_obligations.count_documents({"order_id": order_id}) == 1


@pytest.mark.anyio
async def test_10_valid_manual_override_honored_independently_of_global_toggle(staging_db):
    """Scenario 10: Manual override succeeds even when global toggle is OFF."""
    client, db, admin = staging_db
    await set_staging_admin_wage_policy(db, enabled=False, admin_id=admin["id"], admin_name=admin["name"])
    order_id = "SYNTH-B10-010"

    order_doc = {
        "_id": order_id,
        "order_number": "ORD-B10",
        "order_status": "selesai",
        "payment_status": "lunas",
        "total_le": 900.0,
        "paid_amount_le": 900.0,
        "outstanding_amount_le": 0.0,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "admin_wage_override": {
            "is_override": True,
            "amount_le": 65.0,
            "recipient_id": admin["id"],
            "recipient_name": admin["name"],
            "override_reason": "Negosiasi pesanan khusus",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    }
    await db.orders.insert_one(order_doc)

    # Process with disabled policy in DB
    res = await evaluate_and_process_order_admin_wage_accrual(order_doc, admin, lifecycle_event="order_completed")
    assert res["status"] == "accrued"
    assert res["obligation"]["amount_le"] == 65.0
    assert res["obligation"]["is_override"] is True

    wob = await db.wage_obligations.find_one({"order_id": order_id})
    assert wob is not None
    assert wob["total_amount_le"] == 65.0
    assert wob["is_override"] is True


@pytest.mark.anyio
async def test_11_global_defaults_do_not_silently_overwrite_per_order_override(staging_db):
    """Scenario 11: Updating global policy default does not alter per-order override."""
    client, db, admin = staging_db
    await set_staging_admin_wage_policy(db, enabled=True, default_wage=50.0, admin_id=admin["id"], admin_name=admin["name"])
    order_id = "SYNTH-B11-011"

    order_doc = {
        "_id": order_id,
        "order_number": "ORD-B11",
        "order_status": "selesai",
        "payment_status": "lunas",
        "total_le": 1000.0,
        "paid_amount_le": 1000.0,
        "outstanding_amount_le": 0.0,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "admin_wage_override": {
            "is_override": True,
            "amount_le": 75.0,
            "recipient_id": admin["id"],
            "recipient_name": admin["name"],
            "override_reason": "Order kustom",
        }
    }
    await db.orders.insert_one(order_doc)

    res = await evaluate_and_process_order_admin_wage_accrual(order_doc, admin, lifecycle_event="order_completed")
    assert res["status"] == "accrued"
    assert res["obligation"]["amount_le"] == 75.0

    # Simulate global policy default changed to 90.0 LE in DB
    await set_staging_admin_wage_policy(db, enabled=True, default_wage=90.0, admin_id=admin["id"], admin_name=admin["name"])

    # Repeat check
    wob = await db.wage_obligations.find_one({"order_id": order_id})
    assert wob["total_amount_le"] == 75.0  # unchanged
    saved_ord = await db.orders.find_one({"_id": order_id})
    assert saved_ord["admin_wage_override"]["amount_le"] == 75.0  # unchanged


# =========================================================================
# GROUP C: FINANCIAL INTEGRITY
# =========================================================================

@pytest.mark.anyio
async def test_12_invalid_numeric_values_negative_nan_infinity_fail_closed(staging_db):
    """Scenario 12: Corrupt, negative, NaN, Inf numbers fail closed safely."""
    client, db, admin = staging_db
    await set_staging_admin_wage_policy(db, enabled=True, admin_id=admin["id"], admin_name=admin["name"])

    malformed_cases = [
        {"paid_amount_le": -100.0, "total_le": 500.0, "outstanding_amount_le": 600.0},
        {"paid_amount_le": "NaN", "total_le": 500.0, "outstanding_amount_le": 0.0},
        {"paid_amount_le": float("nan"), "total_le": 500.0, "outstanding_amount_le": 0.0},
        {"paid_amount_le": "Infinity", "total_le": 500.0, "outstanding_amount_le": 0.0},
        {"paid_amount_le": float("inf"), "total_le": 500.0, "outstanding_amount_le": 0.0},
        {"paid_amount_le": "N/A", "total_le": 500.0, "outstanding_amount_le": 0.0},
        {"paid_amount_le": False, "total_le": 500.0, "outstanding_amount_le": 0.0},
    ]

    for idx, c in enumerate(malformed_cases):
        order_id = f"SYNTH-C12-{idx}"
        order_doc = {
            "_id": order_id,
            "order_number": f"ORD-C12-{idx}",
            "order_status": "selesai",
            "payment_status": "lunas",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            **c
        }
        await db.orders.insert_one(order_doc)

        assert is_order_fully_paid(order_doc) is False
        res = await evaluate_and_process_order_admin_wage_accrual(order_doc, admin, lifecycle_event="order_completed")
        assert res["status"] == "skipped_payment_not_lunas"
        assert await db.wage_obligations.count_documents({"order_id": order_id}) == 0


@pytest.mark.anyio
async def test_13_hard_cap_conflict_blocks_accrual_without_clamping(staging_db):
    """Scenario 13: Override exceeding hard-cap blocks accrual without clamping amount."""
    client, db, admin = staging_db
    # Set hard cap to 100.0 LE in DB
    await set_staging_admin_wage_policy(db, enabled=True, max_wage=100.0, admin_id=admin["id"], admin_name=admin["name"])
    order_id = "SYNTH-C13-013"

    order_doc = {
        "_id": order_id,
        "order_number": "ORD-C13",
        "order_status": "selesai",
        "payment_status": "lunas",
        "total_le": 2000.0,
        "paid_amount_le": 2000.0,
        "outstanding_amount_le": 0.0,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "admin_wage_override": {
            "is_override": True,
            "amount_le": 150.0,  # Exceeds 100.0 hard cap
            "recipient_id": admin["id"],
            "recipient_name": admin["name"],
        }
    }
    await db.orders.insert_one(order_doc)

    res = await evaluate_and_process_order_admin_wage_accrual(order_doc, admin, lifecycle_event="order_completed")
    assert res["status"] == "blocked_hard_cap_conflict"
    assert res["blocked"]["attempted_amount_le"] == 150.0
    assert res["blocked"]["max_wage_per_order_le"] == 100.0

    # Zero obligations created (not clamped to 100.0)
    assert await db.wage_obligations.count_documents({"order_id": order_id}) == 0


@pytest.mark.anyio
async def test_14_blocked_accrual_produces_auditable_outcome(staging_db):
    """Scenario 14: Blocked accrual records blocked subdocument and eligibility."""
    client, db, admin = staging_db
    # Set hard cap to 100.0 LE in DB
    await set_staging_admin_wage_policy(db, enabled=True, max_wage=100.0, admin_id=admin["id"], admin_name=admin["name"])
    order_id = "SYNTH-C14-014"

    order_doc = {
        "_id": order_id,
        "order_number": "ORD-C14",
        "order_status": "selesai",
        "payment_status": "lunas",
        "total_le": 1000.0,
        "paid_amount_le": 1000.0,
        "outstanding_amount_le": 0.0,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "admin_wage_override": {
            "is_override": True,
            "amount_le": 200.0,
            "recipient_id": admin["id"],
            "recipient_name": admin["name"],
        }
    }
    await db.orders.insert_one(order_doc)

    res = await evaluate_and_process_order_admin_wage_accrual(order_doc, admin, lifecycle_event="order_completed")
    assert res["status"] == "blocked_hard_cap_conflict"

    # Persist blocked outcome
    await db.orders.update_one(
        {"_id": order_id},
        {"$set": {
            "admin_wage_blocked": res["blocked"],
            "admin_wage_eligibility": res["eligibility"]
        }}
    )

    saved = await db.orders.find_one({"_id": order_id})
    assert saved["admin_wage_blocked"]["status"] == "blocked_hard_cap_conflict"
    assert saved["admin_wage_eligibility"]["scope_status"] == "blocked"


@pytest.mark.anyio
async def test_15_previously_voided_obligation_blocks_automatic_reaccrual(staging_db):
    """Scenario 15: Prior voided obligation triggers quarantine, blocking duplicate re-accrual."""
    client, db, admin = staging_db
    await set_staging_admin_wage_policy(db, enabled=True, admin_id=admin["id"], admin_name=admin["name"])
    order_id = "SYNTH-C15-015"
    accrual_key = build_admin_wage_accrual_event_key(order_id)
    now_iso = datetime.now(timezone.utc).isoformat()

    # Pre-existing obligation in voided status
    wob_void = {
        "obligation_number": "WOB-VOID-0001",
        "accrual_event_key": accrual_key,
        "task_category": "admin",
        "order_id": order_id,
        "total_amount_le": 50.0,
        "status": "void",
        "created_at": now_iso,
    }
    await db.wage_obligations.insert_one(wob_void)

    order_doc = {
        "_id": order_id,
        "order_number": "ORD-C15",
        "order_status": "selesai",
        "payment_status": "lunas",
        "total_le": 500.0,
        "paid_amount_le": 500.0,
        "outstanding_amount_le": 0.0,
        "completed_at": now_iso,
    }
    await db.orders.insert_one(order_doc)

    res = await evaluate_and_process_order_admin_wage_accrual(order_doc, admin, lifecycle_event="order_completed")
    assert res["status"] == "blocked_prior_voided_obligation"
    assert res["blocked"]["owner_review_required"] is True

    # Still exactly 1 obligation, unchanged status void
    wobs = await db.wage_obligations.find({"order_id": order_id}).to_list(10)
    assert len(wobs) == 1
    assert wobs[0]["status"] == "void"


# =========================================================================
# GROUP D: ORDER-STATE INTEGRITY
# =========================================================================

@pytest.mark.anyio
async def test_16_cancelled_or_void_order_cannot_accrue_despite_completed_at(staging_db):
    """Scenario 16: Cancelled/void order cannot qualify as completed merely because completed_at exists."""
    client, db, admin = staging_db
    await set_staging_admin_wage_policy(db, enabled=True, admin_id=admin["id"], admin_name=admin["name"])
    order_id = "SYNTH-D16-016"

    order_doc = {
        "_id": order_id,
        "order_number": "ORD-D16",
        "order_status": "dibatalkan",
        "payment_status": "lunas",
        "total_le": 500.0,
        "paid_amount_le": 500.0,
        "outstanding_amount_le": 0.0,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "cancellation_reason": "Dibatalkan pelanggan",
    }
    await db.orders.insert_one(order_doc)

    assert is_order_completed(order_doc) is False
    res = await evaluate_and_process_order_admin_wage_accrual(order_doc, admin, lifecycle_event="order_completed")
    assert res["status"] == "skipped_order_not_completed"
    assert await db.wage_obligations.count_documents({"order_id": order_id}) == 0


@pytest.mark.anyio
async def test_17_partial_payments_cannot_be_mistaken_for_full_payment(staging_db):
    """Scenario 17: Partial payment with outstanding balance > 0 fails closed."""
    client, db, admin = staging_db
    await set_staging_admin_wage_policy(db, enabled=True, admin_id=admin["id"], admin_name=admin["name"])
    order_id = "SYNTH-D17-017"

    order_doc = {
        "_id": order_id,
        "order_number": "ORD-D17",
        "order_status": "selesai",
        "payment_status": "dp_dibayar",
        "total_le": 1000.0,
        "paid_amount_le": 400.0,
        "outstanding_amount_le": 600.0,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.orders.insert_one(order_doc)

    assert is_order_fully_paid(order_doc) is False
    res = await evaluate_and_process_order_admin_wage_accrual(order_doc, admin, lifecycle_event="order_completed")
    assert res["status"] == "skipped_payment_not_lunas"
    assert await db.wage_obligations.count_documents({"order_id": order_id}) == 0


@pytest.mark.anyio
async def test_18_historical_exclusion_guards(staging_db):
    """Scenario 18: Historical orders marked legacy/reconciled are strictly excluded."""
    client, db, admin = staging_db
    await set_staging_admin_wage_policy(db, enabled=True, admin_id=admin["id"], admin_name=admin["name"])
    order_id = "SYNTH-D18-018"

    order_doc = {
        "_id": order_id,
        "order_number": "ORD-D18",
        "order_status": "selesai",
        "payment_status": "lunas",
        "total_le": 1500.0,
        "paid_amount_le": 1500.0,
        "outstanding_amount_le": 0.0,
        "completed_at": "2026-10-01T00:00:00Z",
        "admin_wage_legacy_reconciled": True,
    }
    await db.orders.insert_one(order_doc)

    assert is_order_excluded_from_admin_wage(order_doc) is True
    res = await evaluate_and_process_order_admin_wage_accrual(order_doc, admin, lifecycle_event="order_completed")
    assert res["status"] == "skipped_legacy_reconciled"
    assert res["eligibility"]["scope_status"] == "excluded_historical"
    assert await db.wage_obligations.count_documents({"order_id": order_id}) == 0


# =========================================================================
# GROUP E: TRANSACTION AND RECOVERY
# =========================================================================

@pytest.mark.anyio
async def test_19_injected_failure_during_multidoc_operation_rolls_back_on_replica_set(staging_db):
    """Scenario 19: Injected error in multi-document transaction rolls back on replica set."""
    client, db, admin = staging_db
    policy_doc = await set_staging_admin_wage_policy(db, enabled=True, admin_id=admin["id"], admin_name=admin["name"])
    order_id = "SYNTH-E19-019"

    order_doc = {
        "_id": order_id,
        "order_number": "ORD-E19",
        "order_status": "diproses",
        "payment_status": "lunas",
        "total_le": 600.0,
        "paid_amount_le": 600.0,
        "outstanding_amount_le": 0.0,
    }
    await db.orders.insert_one(order_doc)

    order_doc["order_status"] = "selesai"
    order_doc["completed_at"] = datetime.now(timezone.utc).isoformat()

    # Execute transaction that fails after inserting wage obligation
    async def failing_tx(sess):
        # Step 1: Accrual inserts obligation in session
        res = await process_order_admin_wage_accrual(order_doc, admin, session=sess, policy=policy_doc, lifecycle_event="order_completed")
        assert res["status"] == "accrued"
        # Step 2: Inject crash before commit
        raise RuntimeError("SIMULATED CRASH MID-TRANSACTION BEFORE ORDER UPDATE COMMIT")

    with pytest.raises(RuntimeError, match="SIMULATED CRASH"):
        async with await client.start_session() as sess:
            async with sess.start_transaction():
                await failing_tx(sess)

    # Database verification: zero obligations survived rollback!
    assert await db.wage_obligations.count_documents({"order_id": order_id}) == 0
    assert await db.audit_logs.count_documents({"entity_id": order_id}) == 0


@pytest.mark.anyio
async def test_20_retry_after_transient_failure_verifies_final_state(staging_db):
    """Scenario 20: TransientTransactionError retried and completed cleanly."""
    client, db, admin = staging_db
    policy_doc = await set_staging_admin_wage_policy(db, enabled=True, admin_id=admin["id"], admin_name=admin["name"])
    order_id = "SYNTH-E20-020"

    order_doc = {
        "_id": order_id,
        "order_number": "ORD-E20",
        "order_status": "diproses",
        "payment_status": "lunas",
        "total_le": 700.0,
        "paid_amount_le": 700.0,
        "outstanding_amount_le": 0.0,
    }
    await db.orders.insert_one(order_doc)

    order_doc["order_status"] = "selesai"
    order_doc["completed_at"] = datetime.now(timezone.utc).isoformat()

    attempts = 0

    async def transient_fail_then_succeed(sess):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            # Simulate a transient write conflict or network hiccup labeled TransientTransactionError
            err = pymongo.errors.PyMongoError("Simulated write conflict on attempt 1")
            err._error_labels = {"TransientTransactionError"}
            raise err
        # Attempt 2: normal execution
        return await process_order_admin_wage_accrual(order_doc, admin, session=sess, policy=policy_doc, lifecycle_event="order_completed")

    res = await execute_transaction_with_safety(client, transient_fail_then_succeed)
    assert res["status"] == "accrued"
    assert attempts == 2  # Proves retry occurred!

    # Exactly 1 obligation in DB
    assert await db.wage_obligations.count_documents({"order_id": order_id}) == 1
    wob = await db.wage_obligations.find_one({"order_id": order_id})
    assert wob["total_amount_le"] == 50.0


@pytest.mark.anyio
async def test_21_concurrent_accrual_attempts_on_replica_set_exact_one_canonical_obligation(staging_db):
    """Scenario 21: 5 concurrent accrual tasks produce exactly ONE canonical obligation."""
    client, db, admin = staging_db
    policy_doc = await set_staging_admin_wage_policy(db, enabled=True, admin_id=admin["id"], admin_name=admin["name"])
    order_id = "SYNTH-E21-021"

    order_doc = {
        "_id": order_id,
        "order_number": "ORD-E21",
        "order_status": "diproses",
        "payment_status": "lunas",
        "total_le": 850.0,
        "paid_amount_le": 850.0,
        "outstanding_amount_le": 0.0,
    }
    await db.orders.insert_one(order_doc)

    order_doc["order_status"] = "selesai"
    order_doc["completed_at"] = datetime.now(timezone.utc).isoformat()

    # 5 concurrent tasks competing to accrue for the same order
    async def worker_accrue():
        return await process_order_admin_wage_accrual(order_doc, admin, session=None, policy=policy_doc, lifecycle_event="order_completed")

    results = await asyncio.gather(*(worker_accrue() for _ in range(5)), return_exceptions=True)

    # Check outcomes
    statuses = [r["status"] for r in results if isinstance(r, dict)]
    assert len(statuses) == 5
    assert "accrued" in statuses
    # The others must be 'already_accrued'
    assert statuses.count("accrued") >= 1
    for st in statuses:
        assert st in ("accrued", "already_accrued")

    # The most critical invariant: exactly 1 obligation exists in database!
    obligations = await db.wage_obligations.find({"order_id": order_id}).to_list(10)
    assert len(obligations) == 1
    assert obligations[0]["accrual_event_key"] == f"admin_wage:{order_id}"


@pytest.mark.anyio
async def test_22_audit_log_write_failure_simulation_preserves_consistency(staging_db):
    """Scenario 22: Simulated failure on audit log insert aborts whole transaction."""
    client, db, admin = staging_db
    await set_staging_admin_wage_policy(db, enabled=True, admin_id=admin["id"], admin_name=admin["name"])
    order_id = "SYNTH-E22-022"

    order_doc = {
        "_id": order_id,
        "order_number": "ORD-E22",
        "order_status": "selesai",
        "payment_status": "lunas",
        "total_le": 900.0,
        "paid_amount_le": 900.0,
        "outstanding_amount_le": 0.0,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.orders.insert_one(order_doc)

    async def failing_audit_tx(sess):
        # Step 1: Insert obligation directly
        ob_num = await server.generate_obligation_number(session=sess)
        accrual_key = build_admin_wage_accrual_event_key(order_id)
        wob = {
            "obligation_number": ob_num,
            "accrual_event_key": accrual_key,
            "order_id": order_id,
            "total_amount_le": 50.0,
            "status": "accrued",
        }
        await db.wage_obligations.insert_one(wob, session=sess)
        # Step 2: Crash on audit log
        raise pymongo.errors.PyMongoError("Simulated disk full during audit log write")

    with pytest.raises(pymongo.errors.PyMongoError):
        async with await client.start_session() as sess:
            async with sess.start_transaction():
                await failing_audit_tx(sess)

    # Verification: neither obligation nor audit log exists!
    assert await db.wage_obligations.count_documents({"order_id": order_id}) == 0
    assert await db.audit_logs.count_documents({"entity_id": order_id}) == 0


@pytest.mark.anyio
async def test_23_retry_recovers_safely_without_duplication_or_inconsistency(staging_db):
    """Scenario 23: Retry with orphan obligation pre-committed heals order cleanly."""
    client, db, admin = staging_db
    await set_staging_admin_wage_policy(db, enabled=True, admin_id=admin["id"], admin_name=admin["name"])
    order_id = "SYNTH-E23-023"
    accrual_key = build_admin_wage_accrual_event_key(order_id)
    now_iso = datetime.now(timezone.utc).isoformat()

    # Pre-commit obligation in DB (simulating network disconnection before order was updated)
    ob_num = "WOB-20261029-9999"
    precommitted_wob = {
        "obligation_number": ob_num,
        "accrual_event_key": accrual_key,
        "task_category": "admin",
        "order_id": order_id,
        "worker_id": admin["id"],
        "worker_name": admin["name"],
        "total_amount_le": 50.0,
        "status": "accrued",
        "created_at": now_iso,
    }
    await db.wage_obligations.insert_one(precommitted_wob)

    # Order document missing obligation subdocument
    order_doc = {
        "_id": order_id,
        "order_number": "ORD-E23",
        "order_status": "selesai",
        "payment_status": "lunas",
        "total_le": 600.0,
        "paid_amount_le": 600.0,
        "outstanding_amount_le": 0.0,
        "completed_at": now_iso,
    }
    await db.orders.insert_one(order_doc)

    # Retry runs
    res = await evaluate_and_process_order_admin_wage_accrual(order_doc, admin, lifecycle_event="order_completed")
    assert res["status"] == "already_accrued"
    assert res["obligation"]["obligation_number"] == ob_num
    assert res["eligibility"]["scope_status"] == "accrued"

    # Self-healing update on order
    await db.orders.update_one(
        {"_id": order_id},
        {"$set": {
            "admin_wage_obligation": res["obligation"],
            "admin_wage_eligibility": res["eligibility"]
        }}
    )

    # Final DB assertions: exactly 1 obligation, order now healed
    assert await db.wage_obligations.count_documents({"order_id": order_id}) == 1
    healed = await db.orders.find_one({"_id": order_id})
    assert healed["admin_wage_obligation"]["obligation_number"] == ob_num
    assert healed["admin_wage_eligibility"]["scope_status"] == "accrued"
