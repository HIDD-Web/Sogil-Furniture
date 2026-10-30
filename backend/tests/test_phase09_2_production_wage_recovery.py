"""
Phase 09.2 — Production Wage Assignment Recovery & Regression Hardening Test Suite.

Verifies:
1. Assignment creation persists expected fields (order_id, order_item_id, worker_ids, agreed_rate_le, status='assigned').
2. GET assignments resolves worker names for both string and ObjectId worker identifiers using multi_id_query.
3. GET assignments returns existing records after creation.
4. Backend capacity guard strictly enforces remaining capacity and rejects over-allocation.
5. Staged lifecycle: Assignment creation and progress updates do NOT create wage obligations; obligations are created ONLY upon verification.
6. Verification idempotency: Repeated verification calls do not produce duplicate wage obligations.
7. Cancellation releases reserved unit capacity and creates zero obligations.
"""

import copy
import inspect
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from fastapi import HTTPException
import pytest

from server import (
    admin_create_work_assignment,
    admin_get_order_assignments,
    admin_update_assignment_progress,
    admin_verify_work_assignment,
    admin_cancel_work_assignment,
    WorkAssignmentCreateInput,
    WorkAssignmentProgressInput,
    WorkAssignmentVerifyInput,
    WorkAssignmentCancelInput,
    multi_id_query,
)

# Re-use Mock classes from Phase 08.2 test infrastructure
from test_phase08_2_multi_worker_production_wages import (
    MockDB,
    setup_standard_fixture,
)


@pytest.mark.anyio
async def test_01_assignment_creation_persists_expected_fields():
    """Requirement C1/C5: Creating an assignment persists all expected metadata."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    w1_id = workers[0]["id"]

    with patch("server.db", mdb):
        res = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(
                worker_ids=[w1_id],
                order_item_id="itm_table_01",
                task_category="whole_item",
                pricing_basis="per_unit",
                agreed_rate_le=100.0,
                target_quantity=1,
                task_notes="Standard quality check"
            ),
            manager
        )

        assert res["order_id"] == ord_id
        assert res["order_item_id"] == "itm_table_01"
        assert res["worker_ids"] == [w1_id]
        assert res["target_quantity"] == 1
        assert res["status"] == "assigned"
        assert res["agreed_rate_le"] == 100.0

        # Verify persisted document in mock db
        saved_asn = list(mdb.work_assignments.docs.values())[0]
        assert saved_asn["order_id"] == ord_id
        assert saved_asn["status"] == "assigned"
        assert saved_asn["target_quantity"] == 1


@pytest.mark.anyio
async def test_02_get_order_assignments_resolves_worker_names_via_multi_id():
    """Requirement C1: GET /admin/orders/{id}/assignments resolves worker names for both string and ObjectId IDs."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    w1_id_str = str(workers[0]["_id"])
    w2_id_str = str(workers[1]["_id"])

    with patch("server.db", mdb):
        # Create assignment for worker 1
        await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(
                worker_ids=[w1_id_str],
                order_item_id="itm_table_01",
                task_category="whole_item",
                target_quantity=1
            ),
            manager
        )

        # Retrieve assignments
        assignments = await admin_get_order_assignments(ord_id, manager)
        assert len(assignments) == 1
        # Worker name must resolve to "Ahmad", NOT fallback "Worker"
        assert assignments[0]["worker_name"] == "Ahmad"
        assert len(assignments[0]["workers"]) == 1
        assert assignments[0]["workers"][0]["worker_name"] == "Ahmad"


@pytest.mark.anyio
async def test_03_get_assignments_resolves_multi_workers_correctly():
    """Requirement C1: Multi-worker assignments resolve all worker names in workers array and joined string."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    w1_id = workers[0]["id"]
    w2_id = workers[1]["id"]

    with patch("server.db", mdb):
        await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(
                worker_ids=[w1_id, w2_id],
                order_item_id="itm_table_01",
                task_category="whole_item",
                target_quantity=2
            ),
            manager
        )

        assignments = await admin_get_order_assignments(ord_id, manager)
        assert len(assignments) == 1
        asn = assignments[0]
        assert "Ahmad" in asn["worker_name"]
        assert "Budi" in asn["worker_name"]
        assert len(asn["workers"]) == 2
        worker_names = [w["worker_name"] for w in asn["workers"]]
        assert "Ahmad" in worker_names
        assert "Budi" in worker_names


@pytest.mark.anyio
async def test_04_backend_rejects_over_allocation_when_capacity_exhausted():
    """Requirement C3: Backend capacity invariant strictly blocks assigning beyond ordered quantity."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    w1_id = workers[0]["id"]
    w2_id = workers[1]["id"]

    with patch("server.db", mdb):
        # Assign 2 units (full capacity of itm_table_01)
        await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(
                worker_ids=[w1_id],
                order_item_id="itm_table_01",
                task_category="whole_item",
                target_quantity=2
            ),
            manager
        )

        # Retry assigning 1 more unit should be rejected with 422
        with pytest.raises(HTTPException) as exc_info:
            await admin_create_work_assignment(
                ord_id,
                WorkAssignmentCreateInput(
                    worker_ids=[w2_id],
                    order_item_id="itm_table_01",
                    task_category="whole_item",
                    target_quantity=1
                ),
                manager
            )

        assert exc_info.value.status_code == 422
        assert "melebihi sisa kapasitas" in exc_info.value.detail


@pytest.mark.anyio
async def test_05_staged_lifecycle_wage_obligation_creation():
    """Requirement C4/C5: Wage obligation is NOT created upon assignment or progress update, ONLY upon verification."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    w1_id = workers[0]["id"]

    with patch("server.db", mdb):
        # 1. Assignment creation
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(
                worker_ids=[w1_id],
                order_item_id="itm_table_01",
                task_category="whole_item",
                target_quantity=1
            ),
            manager
        )
        asn_id = asn["id"]

        # Assert 0 wage obligations exist
        assert len(mdb.wage_obligations.docs) == 0

        # 2. Progress update: assigned -> in_progress
        await admin_update_assignment_progress(
            asn_id,
            WorkAssignmentProgressInput(status="in_progress"),
            manager
        )
        assert len(mdb.wage_obligations.docs) == 0

        # 3. Progress update: in_progress -> ready_for_review
        await admin_update_assignment_progress(
            asn_id,
            WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=1),
            manager
        )
        assert len(mdb.wage_obligations.docs) == 0

        # 4. Verification: ready_for_review -> completed (with wage obligation accrual)
        verify_res = await admin_verify_work_assignment(
            asn_id,
            WorkAssignmentVerifyInput(accepted_quantity=1, notes="Verified well made"),
            owner
        )
        assert verify_res["assignment"]["status"] == "completed"
        # Now exactly 1 wage obligation exists with status "accrued"
        assert len(mdb.wage_obligations.docs) == 1
        wob = list(mdb.wage_obligations.docs.values())[0]
        assert wob["status"] == "accrued"
        assert wob["worker_id"] == w1_id
        assert wob["total_amount_le"] == 100.0
        assert wob["obligation_number"].startswith("WOB-")


@pytest.mark.anyio
async def test_06_verification_idempotency_prevents_duplicate_obligations():
    """Requirement C5: Repeated verification requests return existing obligation without creating duplicates."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    w1_id = workers[0]["id"]

    with patch("server.db", mdb):
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(
                worker_ids=[w1_id],
                order_item_id="itm_table_01",
                task_category="whole_item",
                target_quantity=1
            ),
            manager
        )
        asn_id = asn["id"]

        await admin_update_assignment_progress(asn_id, WorkAssignmentProgressInput(status="in_progress"), manager)
        await admin_update_assignment_progress(asn_id, WorkAssignmentProgressInput(status="ready_for_review"), manager)

        # Initial verification
        res1 = await admin_verify_work_assignment(
            asn_id,
            WorkAssignmentVerifyInput(accepted_quantity=1, notes="First check"),
            owner
        )
        assert len(mdb.wage_obligations.docs) == 1
        ob_num_1 = res1["obligation_number"]

        # Duplicate verification request with same payload
        res2 = await admin_verify_work_assignment(
            asn_id,
            WorkAssignmentVerifyInput(accepted_quantity=1, notes="First check"),
            owner
        )
        # Still exactly 1 obligation, same number
        assert len(mdb.wage_obligations.docs) == 1
        assert res2["obligation_number"] == ob_num_1


@pytest.mark.anyio
async def test_07_cancellation_releases_capacity_safely():
    """Requirement C3/C5: Cancelling an assignment releases capacity and creates no wage obligation."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    w1_id = workers[0]["id"]
    w2_id = workers[1]["id"]

    with patch("server.db", mdb):
        # Assign full capacity (2 units)
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(
                worker_ids=[w1_id],
                order_item_id="itm_table_01",
                task_category="whole_item",
                target_quantity=2
            ),
            manager
        )
        asn_id = asn["id"]

        # Cancel assignment
        cancel_res = await admin_cancel_work_assignment(
            asn_id,
            WorkAssignmentCancelInput(reason="Worker unavailable"),
            owner
        )
        assert cancel_res["status"] == "cancelled"
        assert len(mdb.wage_obligations.docs) == 0

        # Now capacity is freed; worker 2 can be assigned 2 units successfully
        asn2 = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(
                worker_ids=[w2_id],
                order_item_id="itm_table_01",
                task_category="whole_item",
                target_quantity=2
            ),
            manager
        )
        assert asn2["status"] == "assigned"
        assert asn2["target_quantity"] == 2


@pytest.mark.anyio
async def test_08_missing_worker_record_produces_fallback_without_crashing():
    """Requirement C1: Missing or deleted worker record falls back gracefully without crashing."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    w1_id = workers[0]["id"]

    with patch("server.db", mdb):
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(
                worker_ids=[w1_id],
                order_item_id="itm_table_01",
                task_category="whole_item",
                target_quantity=1
            ),
            manager
        )

        # Simulate worker record being removed from admins collection
        await mdb.admins.delete_one({"_id": workers[0]["_id"]})

        # Retrieve assignments should not crash and should fall back to snapshot worker_name
        assignments = await admin_get_order_assignments(ord_id, manager)
        assert len(assignments) == 1
        assert assignments[0]["worker_name"] == "Ahmad"


@pytest.mark.anyio
async def test_09_invalid_order_item_id_rejected():
    """Requirement C5/Backend 10: Non-existent order_item_id is rejected with HTTP 404."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    w1_id = workers[0]["id"]

    with patch("server.db", mdb):
        with pytest.raises(HTTPException) as exc_info:
            await admin_create_work_assignment(
                ord_id,
                WorkAssignmentCreateInput(
                    worker_ids=[w1_id],
                    order_item_id="non_existent_item_id",
                    task_category="whole_item",
                    target_quantity=1
                ),
                manager
            )
        assert exc_info.value.status_code == 404
        assert "tidak ditemukan" in exc_info.value.detail


@pytest.mark.anyio
async def test_10_duplicate_and_inactive_workers_rejected():
    """Requirement C1/Backend 10: Duplicate worker IDs and inactive workers are rejected with 422."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    w1_id = workers[0]["id"]
    inactive_w_id = workers[6]["id"]  # "Nonaktif"

    with patch("server.db", mdb):
        # 1. Duplicate worker IDs in payload
        with pytest.raises(HTTPException) as exc_info:
            await admin_create_work_assignment(
                ord_id,
                WorkAssignmentCreateInput(
                    worker_ids=[w1_id, w1_id],
                    order_item_id="itm_table_01",
                    task_category="whole_item",
                    target_quantity=1
                ),
                manager
            )
        assert exc_info.value.status_code == 422
        assert "duplikat" in exc_info.value.detail.lower()

        # 2. Inactive worker rejected
        with pytest.raises(HTTPException) as exc_info2:
            await admin_create_work_assignment(
                ord_id,
                WorkAssignmentCreateInput(
                    worker_ids=[inactive_w_id],
                    order_item_id="itm_table_01",
                    task_category="whole_item",
                    target_quantity=1
                ),
                manager
            )
        assert exc_info2.value.status_code == 422
        assert "tidak aktif" in exc_info2.value.detail.lower()
