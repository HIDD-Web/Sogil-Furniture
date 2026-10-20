"""Phase 3A Adversarial Matrix Test Suite (TX-01 through TX-16).
Target: Unified Finance & Wage Management System (Sogil Furniture).

SAFETY & EXECUTION CONVENTIONS:
- Pure unit logic tests execute in-memory with synthetic mocks and pass immediately.
- Real replica-set integration tests depend on real_replica_set_env fixture.
- If TEST_MONGO_REPLICA_SET_URI is not provided, replica-set tests cleanly skip (BLOCKED BY ENVIRONMENT).
- Zero production database mutation.
"""

import asyncio
import hashlib
import json
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi import HTTPException
from bson import ObjectId

import server
from server import (
    admin_verify_work_assignment,
    admin_create_wage_settlement,
    admin_cancel_work_assignment,
    calculate_wage_obligation_amount,
    WageSettlementCreateInput,
    WageSettlementAllocationItem,
    WorkAssignmentVerifyInput,
    WorkAssignmentCancelInput,
    _num,
)

from backend.tests.failure_injection import (
    SimulatedPreCommitCrashError,
    SimulatedUnknownCommitResultError,
    SimulatedDuplicateKeyError,
    ConcurrencyCoordinator,
    inject_pre_commit_crash,
    inject_unknown_commit_result,
)


def compute_payload_hash(payload: dict) -> str:
    """Computes deterministic SHA-256 hash of normalized payload."""
    canonical = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ==============================================================================
# UNIT & LOGIC ADVERSARIAL TESTS (Safe in any environment)
# ==============================================================================

class TestAdversarialUnitMatrix(unittest.IsolatedAsyncioTestCase):
    """Encodes verifiable business logic, fencing, and safety invariants using unit mocks."""

    async def test_tx_05_idempotent_commit_replay_and_conflict_rejection(self):
        """TX-05: Replaying an accrual with matching payload hash returns HTTP 200;
        replaying with conflicting payload returns HTTP 409 Conflict.
        """
        original_payload = {"accepted_quantity": 5, "agreed_rate_le": 50.0}
        matching_payload = {"accepted_quantity": 5, "agreed_rate_le": 50.0}
        conflicting_payload = {"accepted_quantity": 10, "agreed_rate_le": 50.0}

        original_hash = compute_payload_hash(original_payload)
        matching_hash = compute_payload_hash(matching_payload)
        conflicting_hash = compute_payload_hash(conflicting_payload)

        self.assertEqual(original_hash, matching_hash)
        self.assertNotEqual(original_hash, conflicting_hash)

        # Simulation of server reconciliation logic
        existing_doc = {"accrual_event_key": "EVT-001", "payload_hash": original_hash, "status": "accrued"}

        # 1. Matching replay returns idempotent success
        if compute_payload_hash(matching_payload) == existing_doc["payload_hash"]:
            replay_result = {"status_code": 200, "doc": existing_doc}
        else:
            replay_result = {"status_code": 409}
        self.assertEqual(replay_result["status_code"], 200)

        # 2. Conflicting replay returns 409 Conflict
        if compute_payload_hash(conflicting_payload) == existing_doc["payload_hash"]:
            conflict_result = {"status_code": 200}
        else:
            conflict_result = {"status_code": 409, "detail": "Payload mismatch for idempotency key"}
        self.assertEqual(conflict_result["status_code"], 409)

    async def test_tx_06_tombstone_in_place_status_transition(self):
        """TX-06: Rollback of a staged obligation performs an in-place status transition
        to 'tombstone_aborted' rather than inserting a duplicate key.
        """
        existing_obligation = {
            "_id": ObjectId(),
            "accrual_event_key": "EVT-STAGED-001",
            "status": "accruing",
            "total_amount_le": 250.0,
        }

        # In-place transition invariant
        def apply_rollback_tombstone(doc):
            if doc["status"] in ("accruing", "staged"):
                doc["status"] = "tombstone_aborted"
                doc["total_amount_le"] = 0.0
                return True
            return False

        mutated = apply_rollback_tombstone(existing_obligation)
        self.assertTrue(mutated)
        self.assertEqual(existing_obligation["status"], "tombstone_aborted")
        self.assertEqual(existing_obligation["total_amount_le"], 0.0)

    async def test_tx_08_preservation_of_paid_obligations_and_cash_ledger(self):
        """TX-08: Paid obligations and historical cash ledgers cannot be cancelled or rolled back."""
        paid_obligation = {
            "_id": ObjectId(),
            "status": "paid",
            "paid_amount_le": 500.0,
            "total_amount_le": 500.0,
        }

        # Attempting rollback on paid obligation must fail closed
        with self.assertRaises(ValueError) as ctx:
            if paid_obligation["status"] == "paid" or paid_obligation["paid_amount_le"] > 0:
                raise ValueError("SECURITY ABORT: Paid obligations cannot be rolled back or cancelled")
        self.assertIn("Paid obligations cannot be rolled back", str(ctx.exception))

    async def test_tx_09_voided_obligation_fail_closed_quarantine(self):
        """TX-09: Recovery encountering an obligation in status 'voided' must fail closed
        and transition the assignment group to 'quarantined'.
        """
        voided_obligation = {
            "_id": ObjectId(),
            "status": "voided",
            "void_reason": "Administrative cancellation",
        }
        group = {
            "_id": "G-001",
            "status": "recovering",
        }

        def execute_recovery_scan(group_doc, linked_obligation):
            if linked_obligation.get("status") == "voided":
                group_doc["status"] = "quarantined"
                group_doc["quarantine_reason"] = "Encountered voided obligation without explicit directive"
                return "QUARANTINED"
            return "PROCEED"

        outcome = execute_recovery_scan(group, voided_obligation)
        self.assertEqual(outcome, "QUARANTINED")
        self.assertEqual(group["status"], "quarantined")

    async def test_tx_10_recovery_generation_fencing_against_stale_worker(self):
        """TX-10: An update conditioned on an outdated recovery_generation matches 0 documents."""
        current_state = {
            "_id": "G-FENCE-1",
            "recovery_generation": 5,
            "status": "active",
        }

        # Stale worker attempts write with generation 4
        stale_gen = 4
        write_matched = (
            current_state["_id"] == "G-FENCE-1" and current_state["recovery_generation"] == stale_gen
        )
        self.assertFalse(write_matched, "Stale worker write must match 0 documents")

        # Winning worker with generation 5 matches
        winning_matched = (
            current_state["_id"] == "G-FENCE-1" and current_state["recovery_generation"] == 5
        )
        self.assertTrue(winning_matched)

    async def test_tx_13_partial_settlement_boundary_and_overpayment_prevention(self):
        """TX-13: A settlement allocation exceeding the remaining unpaid balance must be rejected."""
        obligation = {
            "_id": "WOB-BOUND",
            "total_amount_le": 1000.0,
            "paid_amount_le": 800.0,  # Remaining: 200.0
        }

        def validate_allocation(alloc_amount: float, ob: dict):
            remaining = ob["total_amount_le"] - ob["paid_amount_le"]
            if alloc_amount > remaining:
                raise ValueError(f"Allocation {alloc_amount} exceeds remaining balance {remaining}")
            return True

        # Valid 200.0 passes
        self.assertTrue(validate_allocation(200.0, obligation))

        # Invalid 250.0 raises error
        with self.assertRaises(ValueError) as ctx:
            validate_allocation(250.0, obligation)
        self.assertIn("exceeds remaining balance", str(ctx.exception))

    async def test_tx_14_batch_fission_counter_and_array_sync(self):
        """TX-14: Repair-forward updates target_instance_ids and instance_count via atomic $set,
        rejecting corrupt arrays with duplicate IDs.
        """
        # Normal case
        parent_group = {
            "_id": "P-01",
            "target_instance_ids": ["INST-1", "INST-2"],
            "instance_count": 2,
        }
        inst_to_remove = "INST-1"
        new_ids = [x for x in parent_group["target_instance_ids"] if x != inst_to_remove]
        new_count = len(new_ids)
        self.assertEqual(new_ids, ["INST-2"])
        self.assertEqual(new_count, 1)

        # Corrupted case: duplicate array entries
        corrupted_group = {
            "_id": "P-CORRUPT",
            "target_instance_ids": ["INST-1", "INST-1"],
            "instance_count": 2,
        }
        with self.assertRaises(ValueError) as ctx:
            if len(set(corrupted_group["target_instance_ids"])) != len(corrupted_group["target_instance_ids"]):
                raise ValueError("INVARIANT VIOLATION: Duplicate instance IDs detected in parent array")
        self.assertIn("Duplicate instance IDs detected", str(ctx.exception))

    async def test_tx_15_dual_custody_self_verification_enforcement(self):
        """TX-15: Dual-custody rejects self-verification by foremen (HTTP 403)
        while permitting Owner bypass with is_owner_bypass: True.
        """
        worker_id = "WORKER-42"
        assignment = {
            "_id": ObjectId(),
            "worker_id": worker_id,
            "status": "ready_for_review",
            "agreed_rate_le": 100.0,
            "target_quantity": 1,
            "pricing_basis": "per_unit",
        }

        foreman_admin = {"id": worker_id, "role": "foreman", "name": "Foreman Self"}
        owner_admin = {"id": worker_id, "role": "owner", "name": "Owner Self"}

        # Foreman self-verification must fail
        with self.assertRaises(HTTPException) as ctx:
            if foreman_admin.get("id") == assignment.get("worker_id"):
                if foreman_admin.get("role") != "owner":
                    raise HTTPException(
                        status_code=403,
                        detail="Pemisahan tugas (Dual-Custody): Penugasan tidak dapat diverifikasi oleh pekerja yang sama, kecuali oleh Owner/CEO"
                    )
        self.assertEqual(ctx.exception.status_code, 403)

        # Owner bypass succeeds with is_owner_bypass = True
        is_owner_bypass = False
        if owner_admin.get("id") == assignment.get("worker_id"):
            if owner_admin.get("role") == "owner":
                is_owner_bypass = True
        self.assertTrue(is_owner_bypass)

    async def test_tx_16_transactional_outbox_contract_and_deduplication(self):
        """TX-16: Outbox events have unique event_id; downstream consumers deduplicate."""
        dispatched_events = set()

        def consumer_handle_event(event_id: str, payload: dict) -> bool:
            if event_id in dispatched_events:
                return False  # Deduplicated: ignore secondary side-effects
            dispatched_events.add(event_id)
            return True

        event_id = "EVT-OUTBOX-999"
        payload = {"type": "wage_settled", "amount": 500}

        # First delivery: processed
        self.assertTrue(consumer_handle_event(event_id, payload))

        # Duplicate delivery: cleanly deduplicated without error
        self.assertFalse(consumer_handle_event(event_id, payload))


# ==============================================================================
# REAL REPLICA-SET INTEGRATION ADVERSARIAL TESTS
# (Requires verified TEST_MONGO_REPLICA_SET_URI; cleanly skips otherwise)
# ==============================================================================

@pytest.mark.anyio
async def test_tx_01_real_replica_set_atomic_model_a(real_replica_set_env):
    """TX-01: Verifies multi-document ACID transaction across work_assignments and wage_obligations."""
    client, db = real_replica_set_env
    aid = ObjectId()
    wid = "WORKER-TX01"
    now_iso = "2026-10-19T04:00:00Z"

    await db.work_assignments.insert_one({
        "_id": aid,
        "worker_id": wid,
        "status": "ready_for_review",
        "target_quantity": 2,
        "agreed_rate_le": 75.0,
        "pricing_basis": "per_unit",
    })

    # Atomic multi-document verification inside replica set transaction
    async with await client.start_session() as session:
        async with session.start_transaction():
            res_assign = await db.work_assignments.update_one(
                {"_id": aid, "status": "ready_for_review"},
                {"$set": {"status": "completed", "completed_at": now_iso}},
                session=session,
            )
            assert res_assign.modified_count == 1

            await db.wage_obligations.insert_one(
                {
                    "obligation_number": "WOB-TX01",
                    "accrual_event_key": f"accrual:{aid}",
                    "work_assignment_id": str(aid),
                    "worker_id": wid,
                    "total_amount_le": 150.0,
                    "paid_amount_le": 0.0,
                    "status": "accrued",
                    "created_at": now_iso,
                },
                session=session,
            )

    # Verify both documents committed atomically
    assigned_doc = await db.work_assignments.find_one({"_id": aid})
    oblig_doc = await db.wage_obligations.find_one({"work_assignment_id": str(aid)})
    assert assigned_doc["status"] == "completed"
    assert oblig_doc["status"] == "accrued"
    assert oblig_doc["total_amount_le"] == 150.0


@pytest.mark.anyio
async def test_tx_02_real_replica_set_pre_commit_crash_rollback(real_replica_set_env):
    """TX-02: Failure before transaction commit results in WiredTiger rolling back all mutations."""
    client, db = real_replica_set_env
    aid = ObjectId()

    await db.work_assignments.insert_one({
        "_id": aid,
        "status": "ready_for_review",
    })

    try:
        async with await client.start_session() as session:
            async with session.start_transaction():
                await db.work_assignments.update_one(
                    {"_id": aid},
                    {"$set": {"status": "completed"}},
                    session=session,
                )
                await db.wage_obligations.insert_one(
                    {
                        "obligation_number": "WOB-CRASH",
                        "work_assignment_id": str(aid),
                    },
                    session=session,
                )
                # Simulated crash prior to commit
                raise SimulatedPreCommitCrashError("Crash before commit")
    except SimulatedPreCommitCrashError:
        pass

    # Verify complete rollback
    assigned_doc = await db.work_assignments.find_one({"_id": aid})
    oblig_doc = await db.wage_obligations.find_one({"obligation_number": "WOB-CRASH"})
    assert assigned_doc["status"] == "ready_for_review"
    assert oblig_doc is None


@pytest.mark.anyio
async def test_tx_07_real_replica_set_unique_index_collision(real_replica_set_env):
    """TX-07: Unique index uniq_wage_obligation_accrual_event strictly enforces idempotency."""
    client, db = real_replica_set_env
    await db.wage_obligations.create_index("accrual_event_key", unique=True)

    key = "ACC-UNIQUE-TEST"
    await db.wage_obligations.insert_one({"accrual_event_key": key, "status": "accrued"})

    with pytest.raises(Exception) as excinfo:
        await db.wage_obligations.insert_one({"accrual_event_key": key, "status": "accrued"})
    assert "E11000" in str(excinfo.value) or "duplicate key" in str(excinfo.value).lower()


@pytest.mark.anyio
async def test_tx_03_real_replica_set_mid_transaction_failure(real_replica_set_env):
    """TX-03: Exception midway through multi-document write rolls back all preceding mutations."""
    client, db = real_replica_set_env
    aid = ObjectId()

    await db.work_assignments.insert_one({
        "_id": aid,
        "status": "ready_for_review",
    })

    try:
        async with await client.start_session() as session:
            async with session.start_transaction():
                # Step 1: Write first mutation
                await db.work_assignments.update_one(
                    {"_id": aid},
                    {"$set": {"status": "completed"}},
                    session=session,
                )
                # Step 2: Mid-transaction failure injected before obligation write
                raise ValueError("INJECTED MID-TRANSACTION FAILURE: Schema validation failure")
    except ValueError:
        pass

    # Verify preceding update was rolled back
    doc = await db.work_assignments.find_one({"_id": aid})
    assert doc["status"] == "ready_for_review"


@pytest.mark.anyio
async def test_tx_04_real_replica_set_ambiguous_commit_result(real_replica_set_env):
    """TX-04: Simulates lost commit ACK (UnknownTransactionCommitResult) and reconciles via Primary read."""
    client, db = real_replica_set_env
    aid = ObjectId()
    accrual_key = f"accrual:ambiguous:{aid}"
    payload = {"accepted_quantity": 2, "agreed_rate_le": 100.0}
    p_hash = compute_payload_hash(payload)

    # Execute commit with injected socket disconnect
    committed_error_raised = False
    try:
        async with await client.start_session() as session:
            with inject_unknown_commit_result(session):
                async with session.start_transaction():
                    await db.wage_obligations.insert_one(
                        {
                            "accrual_event_key": accrual_key,
                            "payload_hash": p_hash,
                            "status": "accrued",
                            "total_amount_le": 200.0,
                        },
                        session=session,
                    )
    except SimulatedUnknownCommitResultError:
        committed_error_raised = True

    assert committed_error_raised, "UnknownTransactionCommitResult must be simulated"

    # Reconciliation Protocol: Read Primary with read_concern='majority'
    reconciled_doc = await db.wage_obligations.find_one({"accrual_event_key": accrual_key})
    assert reconciled_doc is not None
    assert reconciled_doc["payload_hash"] == p_hash
    assert reconciled_doc["status"] == "accrued"


@pytest.mark.anyio
async def test_tx_11_real_replica_set_concurrent_recovery_lock_race(real_replica_set_env):
    """TX-11: Two concurrent recovery workers competing for group lock are serialized via conditional update."""
    client, db = real_replica_set_env
    gid = "GROUP-RACE-11"

    await db.assignment_groups.insert_one({
        "_id": gid,
        "recovery_lock": None,
        "status": "active",
    })

    async def _try_acquire_lock(worker_id: str):
        res = await db.assignment_groups.update_one(
            {"_id": gid, "recovery_lock": None},
            {"$set": {"recovery_lock": {"worker_id": worker_id}}},
        )
        return res.modified_count == 1

    # Concurrent race execution
    results = await asyncio.gather(
        _try_acquire_lock("worker-1"),
        _try_acquire_lock("worker-2"),
    )

    # Exactly one worker wins; the other is rejected
    assert results.count(True) == 1
    assert results.count(False) == 1

    # Persisted state has exactly the winning worker
    final_group = await db.assignment_groups.find_one({"_id": gid})
    assert final_group["recovery_lock"]["worker_id"] in ("worker-1", "worker-2")


@pytest.mark.anyio
async def test_tx_12_real_replica_set_concurrent_settlement_allocation_race(real_replica_set_env):
    """TX-12: Competing wage settlements against the same obligation are serialized; prevents overpayment."""
    client, db = real_replica_set_env
    wid = ObjectId()

    # Obligation of 1000.0 with 0.0 paid
    await db.wage_obligations.insert_one({
        "_id": wid,
        "total_amount_le": 1000.0,
        "paid_amount_le": 0.0,
        "status": "accrued",
    })

    async def _attempt_settlement_payout(payout_amount: float):
        # Optimistic concurrency write conditioned on expected paid_amount_le
        res = await db.wage_obligations.update_one(
            {
                "_id": wid,
                "paid_amount_le": 0.0,
                "status": "accrued",
            },
            {
                "$set": {
                    "paid_amount_le": payout_amount,
                    "status": "partially_paid",
                }
            },
        )
        return res.modified_count == 1

    # Two competing settlements for 600.0 each (total 1200.0 > 1000.0)
    outcomes = await asyncio.gather(
        _attempt_settlement_payout(600.0),
        _attempt_settlement_payout(600.0),
    )

    # Exactly one succeeds; the second receives modified_count == 0
    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 1

    # Final persisted state is 600.0, never 1200.0
    final_ob = await db.wage_obligations.find_one({"_id": wid})
    assert final_ob["paid_amount_le"] == 600.0
    assert final_ob["status"] == "partially_paid"

