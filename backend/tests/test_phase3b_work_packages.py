"""Phase 3B Verification Test Suite for Unified Finance & Wage Management System.
Validates Work Packages A, B, C, and D against real MongoDB replica set.
"""

import asyncio
import json
from decimal import Decimal
import pytest
from bson import ObjectId
from fastapi import HTTPException

import server
from server import (
    admin_create_work_assignment,
    admin_verify_work_assignment,
    admin_create_wage_settlement,
    admin_cancel_work_assignment,
    admin_fission_assignment_group,
    admin_recover_assignment_group,
    admin_quarantine_assignment_group,
    admin_get_pending_outbox_events,
    admin_dispatch_outbox_event,
    compute_payload_hash,
    WorkAssignmentCreateInput,
    WorkAssignmentVerifyInput,
    WorkAssignmentCancelInput,
    WageSettlementCreateInput,
    WageSettlementAllocationItem,
    AssignmentGroupFissionInput,
    AssignmentGroupRecoverInput,
    OutboxEventDispatchInput,
    _num,
)


@pytest.mark.anyio
async def test_wp_a_atomic_creation_with_item_instances(real_replica_set_env):
    """Work Package A: Batch assignment creation atomically binds item instances and emits outbox event."""
    client, db = real_replica_set_env
    server.client = client
    server.db = db

    admin_user = {"id": "ADM-01", "name": "Admin Test", "role": "admin", "permissions": {"manage_orders": True}}
    worker_user = {"_id": ObjectId(), "name": "Worker Wood", "role": "worker"}
    await db.admins.insert_one(worker_user)
    wid = str(worker_user["_id"])

    order_id = ObjectId()
    await db.orders.insert_one({
        "_id": order_id,
        "order_number": "SO-WPA-001",
        "items": [{"item_id": "item-wood-1", "product_name": "Meja Kayu", "quantity": 2}],
    })

    await db.item_instances.insert_many([
        {"instance_id": "INST-001", "order_id": str(order_id), "status": "unassigned", "claim_generation": 0},
        {"instance_id": "INST-002", "order_id": str(order_id), "status": "unassigned", "claim_generation": 0},
    ])

    payload = WorkAssignmentCreateInput(
        order_item_id="item-wood-1",
        worker_id=wid,
        task_category="assembly",
        pricing_basis="per_unit",
        agreed_rate_le=120.0,
        target_quantity=2,
        instance_ids=["INST-001", "INST-002"],
    )

    created = await admin_create_work_assignment(str(order_id), payload, admin_user)
    assert created["status"] == "assigned"
    assert created["instance_ids"] == ["INST-001", "INST-002"]

    # Verify item_instances updated with claim_generation increment
    inst1 = await db.item_instances.find_one({"instance_id": "INST-001"})
    inst2 = await db.item_instances.find_one({"instance_id": "INST-002"})
    assert inst1["status"] == "assigned"
    assert inst1["claim_generation"] == 1
    assert inst2["claim_generation"] == 1

    # Verify outbox event emitted
    outbox = await db.outbox_events.find_one({"aggregate_id": created["id"], "event_type": "assignment.created"})
    assert outbox is not None
    assert outbox["payload"]["worker_id"] == wid
    assert outbox["status"] == "pending"


@pytest.mark.anyio
async def test_wp_a_atomic_verification_and_outbox(real_replica_set_env):
    """Work Package A: Assignment verification updates assignment, creates obligation, and emits outbox event in same ACID transaction."""
    client, db = real_replica_set_env
    server.client = client
    server.db = db

    admin_user = {"id": "ADM-02", "name": "Manager QA", "role": "manager", "permissions": {"manage_orders": True}}
    wid = "WORKER-WPA-2"

    aid = ObjectId()
    await db.work_assignments.insert_one({
        "_id": aid,
        "worker_id": wid,
        "worker_name": "Worker Metal",
        "order_number": "SO-WPA-002",
        "task_category": "welding",
        "pricing_basis": "per_unit",
        "agreed_rate_le": 85.0,
        "target_quantity": 4,
        "status": "ready_for_review",
    })

    payload = WorkAssignmentVerifyInput(accepted_quantity=4, notes="Kualitas sempurna")
    verified = await admin_verify_work_assignment(str(aid), payload, admin_user)

    assert verified["status"] == "accrued"
    assert verified["total_amount_le"] == 340.0
    assert verified["payload_hash"] is not None

    # Check assignment status
    asn = await db.work_assignments.find_one({"_id": aid})
    assert asn["status"] == "completed"

    # Check transactional outbox event
    outbox = await db.outbox_events.find_one({"aggregate_id": str(aid), "event_type": "assignment.verified"})
    assert outbox is not None
    assert outbox["payload"]["total_amount_le"] == 340.0


@pytest.mark.anyio
async def test_wp_b_group_fission_sync_and_corruption_quarantine(real_replica_set_env):
    """Work Package B: Fission applies synchronized $set on target_instance_ids and instance_count; corruption triggers quarantine."""
    client, db = real_replica_set_env
    server.client = client
    server.db = db

    admin_user = {"id": "ADM-03", "name": "Admin Ops", "role": "admin", "permissions": {"manage_orders": True}}

    # 1. Normal fission
    gid = "GRP-NORM-01"
    await db.assignment_groups.insert_one({
        "_id": gid,
        "group_number": "GRP-NORM-01",
        "target_instance_ids": ["INST-10", "INST-20", "INST-30"],
        "instance_count": 3,
        "recovery_generation": 1,
        "status": "active",
    })
    await db.item_instances.insert_one({"instance_id": "INST-20", "assignment_group_id": gid, "claim_generation": 1})

    fission_in = AssignmentGroupFissionInput(
        target_instance_id="INST-20",
        child_worker_id="WORKER-CHILD-1",
        child_group_id="GRP-CHILD-01",
    )
    res = await admin_fission_assignment_group(gid, fission_in, admin_user)
    assert res["parent_group"]["instance_count"] == 2
    assert res["parent_group"]["target_instance_ids"] == ["INST-10", "INST-30"]
    assert res["child_group"]["instance_count"] == 1
    assert res["child_group"]["target_instance_ids"] == ["INST-20"]

    # 2. Corrupted array (duplicate IDs) fails closed to quarantined
    gid_corrupt = "GRP-CORRUPT-01"
    await db.assignment_groups.insert_one({
        "_id": gid_corrupt,
        "group_number": "GRP-CORRUPT-01",
        "target_instance_ids": ["INST-A", "INST-A"],
        "instance_count": 2,
        "status": "active",
    })
    with pytest.raises(HTTPException) as excinfo:
        await admin_fission_assignment_group(
            gid_corrupt,
            AssignmentGroupFissionInput(target_instance_id="INST-A", child_worker_id="W-X"),
            admin_user
        )
    assert excinfo.value.status_code == 422
    corrupt_doc = await db.assignment_groups.find_one({"_id": gid_corrupt})
    assert corrupt_doc["status"] == "quarantined"


@pytest.mark.anyio
async def test_wp_b_group_recovery_fencing_and_voided_quarantine(real_replica_set_env):
    """Work Package B: Recovery enforces generation fencing, fail-closed on voided obligation, and in-place tombstone on rollback."""
    client, db = real_replica_set_env
    server.client = client
    server.db = db

    owner_user = {"id": "OWNER-01", "name": "Owner Sogil", "role": "owner", "permissions": {"access_finance": True}}

    # 1. Recovery generation fencing
    gid = "GRP-REC-FENCE"
    await db.assignment_groups.insert_one({
        "_id": gid,
        "group_number": "GRP-REC-01",
        "target_instance_ids": ["INST-X", "INST-Y"],
        "instance_count": 2,
        "recovery_generation": 3,
        "status": "active",
    })

    # Stale generation 2 must raise 409
    with pytest.raises(HTTPException) as exc409:
        await admin_recover_assignment_group(
            gid,
            AssignmentGroupRecoverInput(expected_generation=2, action="repair_forward"),
            owner_user
        )
    assert exc409.value.status_code == 409

    # Valid generation 3 succeeds and increments generation to 4
    rec_res = await admin_recover_assignment_group(
        gid,
        AssignmentGroupRecoverInput(expected_generation=3, action="repair_forward"),
        owner_user
    )
    assert rec_res["recovery_generation"] == 4
    assert rec_res["status"] == "active"

    # 2. Encountering voided obligation transitions group to quarantined (fail-closed)
    gid_void = "GRP-VOID-CHECK"
    await db.assignment_groups.insert_one({
        "_id": gid_void,
        "group_number": "GRP-VOID-01",
        "target_instance_ids": ["INST-Z"],
        "instance_count": 1,
        "recovery_generation": 1,
        "status": "active",
    })
    await db.wage_obligations.insert_one({
        "obligation_number": "WOB-VOID-1",
        "assignment_group_id": gid_void,
        "status": "voided",
        "void_reason": "Cancelled upstream",
    })

    with pytest.raises(HTTPException) as exc_void:
        await admin_recover_assignment_group(
            gid_void,
            AssignmentGroupRecoverInput(expected_generation=1, action="repair_forward"),
            owner_user
        )
    assert exc_void.value.status_code == 422
    void_group = await db.assignment_groups.find_one({"_id": gid_void})
    assert void_group["status"] == "quarantined"

    # 3. Rollback on paid obligation is rejected (Immutability violation)
    gid_paid = "GRP-PAID-CHECK"
    await db.assignment_groups.insert_one({
        "_id": gid_paid,
        "group_number": "GRP-PAID-01",
        "target_instance_ids": ["INST-PAID"],
        "instance_count": 1,
        "recovery_generation": 1,
        "status": "active",
    })
    await db.wage_obligations.insert_one({
        "obligation_number": "WOB-PAID-1",
        "assignment_group_id": gid_paid,
        "status": "paid",
        "paid_amount_le": 500.0,
        "total_amount_le": 500.0,
    })

    with pytest.raises(HTTPException) as exc_paid:
        await admin_recover_assignment_group(
            gid_paid,
            AssignmentGroupRecoverInput(expected_generation=1, action="rollback"),
            owner_user
        )
    assert exc_paid.value.status_code == 400


@pytest.mark.anyio
async def test_wp_c_outbox_query_and_dispatch_deduplication(real_replica_set_env):
    """Work Package C: Pending outbox events can be queried and dispatched with idempotent deduplication."""
    client, db = real_replica_set_env
    server.client = client
    server.db = db

    owner_user = {"id": "OWNER-02", "name": "Owner Sogil", "role": "owner", "permissions": {"access_finance": True}}

    event_id = "EVT-TEST-DISPATCH-001"
    await db.outbox_events.insert_one({
        "event_id": event_id,
        "event_type": "wage.settled",
        "aggregate_type": "wage_settlement",
        "aggregate_id": "WST-123",
        "payload": {"amount_le": 200.0},
        "payload_hash": "dummyhash",
        "status": "pending",
        "retry_count": 0,
        "created_at": "2026-10-19T04:00:00Z",
    })

    # Query pending
    pending = await admin_get_pending_outbox_events(limit=10, admin=owner_user)
    assert any(e["event_id"] == event_id for e in pending)

    # Dispatch first time
    disp1 = await admin_dispatch_outbox_event(event_id, OutboxEventDispatchInput(deduplication_token="tok-1"), owner_user)
    assert disp1["status"] == "dispatched"

    # Duplicate dispatch returns clean already_dispatched deduplication without side effects
    disp2 = await admin_dispatch_outbox_event(event_id, OutboxEventDispatchInput(deduplication_token="tok-1"), owner_user)
    assert disp2["status"] == "already_dispatched"


@pytest.mark.anyio
async def test_wp_d_wage_settlement_idempotency_and_conflict_rejection(real_replica_set_env):
    """Work Package D: Wage settlement verifies payload hash on idempotency retry; matching returns HTTP 200, conflicting raises 409."""
    client, db = real_replica_set_env
    server.client = client
    server.db = db

    owner_user = {"id": "OWNER-03", "name": "Owner Sogil", "role": "owner", "permissions": {"access_finance": True}}

    wid = str(ObjectId())
    await db.admins.insert_one({"_id": ObjectId(wid), "name": "Worker Settle", "role": "worker"})

    ob_id = ObjectId()
    await db.wage_obligations.insert_one({
        "_id": ob_id,
        "obligation_number": "WOB-SETTLE-01",
        "worker_id": wid,
        "worker_name": "Worker Settle",
        "total_amount_le": 1000.0,
        "paid_amount_le": 0.0,
        "status": "accrued",
        "created_at": "2026-10-19T04:00:00Z",
    })

    idem_key = "IDEM-WST-UNIQUE-1"
    payload_original = WageSettlementCreateInput(
        worker_id=wid,
        amount_le=500.0,
        payment_currency="EGP",
        payment_method="cash",
        idempotency_key=idem_key,
        allocations=[WageSettlementAllocationItem(wage_obligation_id=str(ob_id), amount_le=500.0)],
    )

    # First settlement succeeds
    res1 = await admin_create_wage_settlement(payload_original, owner_user)
    assert res1["amount_le"] == 500.0
    assert res1["status"] == "recorded"
    assert res1["idempotency_key"] == idem_key

    # Replay with identical payload returns idempotent HTTP 200 replay
    res_replay = await admin_create_wage_settlement(payload_original, owner_user)
    assert res_replay["settlement_number"] == res1["settlement_number"]
    assert res_replay["idempotency_key"] == idem_key

    # Replay with conflicting amount using SAME idempotency key raises HTTP 409 Conflict
    payload_conflicting = WageSettlementCreateInput(
        worker_id=wid,
        amount_le=200.0,  # Changed amount!
        payment_currency="EGP",
        payment_method="cash",
        idempotency_key=idem_key,
        allocations=[WageSettlementAllocationItem(wage_obligation_id=str(ob_id), amount_le=200.0)],
    )
    with pytest.raises(HTTPException) as excinfo:
        await admin_create_wage_settlement(payload_conflicting, owner_user)
    assert excinfo.value.status_code == 409
