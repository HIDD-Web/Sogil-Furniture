"""
Phase 08.2 — Multi-Worker Production Wage Flow Test Suite.

Rigorously verifies:
1. Multi-worker assignment (1 to 5 workers, rejection of 6 workers, duplicate worker rejection, invalid worker ID rejection).
2. Wage calculation & shared integer piastre allocation (exact math, zero money drift).
3. Unit allocation & capacity tracking (ordered vs assigned vs remaining, invariant enforcement).
4. Multiple workflow patterns:
   - Pattern 1: One worker, two units.
   - Pattern 2: Two workers, different units (separate assignments).
   - Pattern 3: Two workers working together on two units (shared assignment).
5. Assignment cancellation & capacity release (status marked cancelled, capacity freed, financial history safe).
6. Production completion & wage accrual (idempotent, no duplicates, snapshot integrity, dual-custody).
7. Manual wage override, reason validation, Owner-only permissions, threshold and hard cap.
8. Unconfigured production policy fail-closed handling.
9. Immutability of historical wage obligations upon policy updates.
10. Wage settlement consistency (settlement, partial settlement, voiding without duplicate obligations).
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
    admin_update_assignment_progress,
    admin_verify_work_assignment,
    admin_cancel_work_assignment,
    admin_get_order_assignments,
    admin_create_wage_settlement,
    admin_void_wage_settlement,
    admin_get_wages_pending_summary,
    admin_get_wage_obligations,
    get_active_production_wage_policy,
    distribute_wage_piastres,
    calculate_wage_obligation_amount,
    id_query,
    WorkAssignmentCreateInput,
    WorkAssignmentProgressInput,
    WorkAssignmentVerifyInput,
    WorkAssignmentCancelInput,
    WageSettlementCreateInput,
    WageSettlementAllocationItem,
    WageSettlementVoidInput,
)


class AsyncCursorMock:
    def __init__(self, docs):
        self.docs = copy.deepcopy(docs)
        self.idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.idx < len(self.docs):
            doc = self.docs[self.idx]
            self.idx += 1
            return doc
        raise StopAsyncIteration

    def sort(self, *args, **kwargs):
        return self

    def skip(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    async def to_list(self, length=None):
        if length is not None:
            return copy.deepcopy(self.docs[:length])
        return copy.deepcopy(self.docs)


class MockCollection:
    def __init__(self, name: str, docs: list = None):
        self.name = name
        self.docs = {}
        for d in (docs or []):
            d_copy = copy.deepcopy(d)
            if "_id" not in d_copy:
                d_copy["_id"] = ObjectId()
            self.docs[str(d_copy["_id"])] = d_copy

    def _matches(self, doc, filter_q):
        if not filter_q:
            return True
        for k, v in filter_q.items():
            if k == "_id":
                if isinstance(v, dict) and "$in" in v:
                    vals = [str(x) for x in v["$in"]]
                    if str(doc.get("_id")) not in vals:
                        return False
                else:
                    if str(doc.get("_id")) != str(v):
                        return False
            elif k == "work_assignment_id":
                if str(doc.get("work_assignment_id")) != str(v):
                    return False
            elif k == "order_id":
                if str(doc.get("order_id")) != str(v):
                    return False
            elif k == "order_item_id":
                if str(doc.get("order_item_id")) != str(v):
                    return False
            elif k == "task_category":
                if isinstance(v, dict) and "$in" in v:
                    if doc.get("task_category") not in v["$in"]:
                        return False
                elif doc.get("task_category") != v:
                    return False
            elif k == "status":
                if isinstance(v, dict) and "$in" in v:
                    if doc.get("status") not in v["$in"]:
                        return False
                elif doc.get("status") != v:
                    return False
            elif k == "key":
                if doc.get("key") != v:
                    return False
            elif k == "worker_id":
                if str(doc.get("worker_id")) != str(v):
                    return False
            elif k == "accrual_event_key":
                if doc.get("accrual_event_key") != v:
                    return False
            elif k == "idempotency_key":
                if doc.get("idempotency_key") != v:
                    return False
            else:
                if doc.get(k) != v:
                    return False
        return True

    async def find_one(self, filter_q, *args, **kwargs):
        for doc in self.docs.values():
            if self._matches(doc, filter_q):
                return copy.deepcopy(doc)
        return None

    def find(self, filter_q=None, *args, **kwargs):
        matched = [copy.deepcopy(doc) for doc in self.docs.values() if self._matches(doc, filter_q)]
        return AsyncCursorMock(matched)

    async def insert_one(self, doc, *args, **kwargs):
        d_copy = copy.deepcopy(doc)
        if "_id" not in d_copy:
            d_copy["_id"] = ObjectId()
        self.docs[str(d_copy["_id"])] = d_copy
        res = MagicMock()
        res.inserted_id = d_copy["_id"]
        return res

    async def update_one(self, filter_q, update_q, upsert=False, *args, **kwargs):
        for doc in self.docs.values():
            if self._matches(doc, filter_q):
                if "$set" in update_q:
                    doc.update(copy.deepcopy(update_q["$set"]))
                if "$unset" in update_q:
                    for uk in update_q["$unset"]:
                        doc.pop(uk, None)
                res = MagicMock()
                res.matched_count = 1
                res.modified_count = 1
                return res
        if upsert:
            new_doc = copy.deepcopy(filter_q)
            if "$set" in update_q:
                new_doc.update(copy.deepcopy(update_q["$set"]))
            if "_id" not in new_doc:
                new_doc["_id"] = ObjectId()
            self.docs[str(new_doc["_id"])] = new_doc
            res = MagicMock()
            res.matched_count = 0
            res.modified_count = 1
            res.upserted_id = new_doc["_id"]
            return res
        res = MagicMock()
        res.matched_count = 0
        res.modified_count = 0
        return res

    async def update_many(self, filter_q, update_q, *args, **kwargs):
        count = 0
        for doc in self.docs.values():
            if self._matches(doc, filter_q):
                if "$set" in update_q:
                    doc.update(copy.deepcopy(update_q["$set"]))
                count += 1
        res = MagicMock()
        res.matched_count = count
        res.modified_count = count
        return res

    async def delete_one(self, filter_q, *args, **kwargs):
        for k, doc in list(self.docs.items()):
            if self._matches(doc, filter_q):
                del self.docs[k]
                res = MagicMock()
                res.deleted_count = 1
                return res
        res = MagicMock()
        res.deleted_count = 0
        return res

    async def delete_many(self, filter_q, *args, **kwargs):
        count = 0
        for k, doc in list(self.docs.items()):
            if self._matches(doc, filter_q):
                del self.docs[k]
                count += 1
        res = MagicMock()
        res.deleted_count = count
        return res

    async def find_one_and_update(self, filter_q, update_spec, upsert=False, return_document=None, **kwargs):
        for doc in self.docs.values():
            if self._matches(doc, filter_q):
                if "$inc" in update_spec:
                    for k, inc_val in update_spec["$inc"].items():
                        doc[k] = doc.get(k, 0) + inc_val
                if "$set" in update_spec:
                    doc.update(copy.deepcopy(update_spec["$set"]))
                return copy.deepcopy(doc)
        if upsert:
            new_doc = copy.deepcopy(filter_q)
            if "_id" not in new_doc:
                new_doc["_id"] = ObjectId()
            if "$inc" in update_spec:
                for k, inc_val in update_spec["$inc"].items():
                    new_doc[k] = inc_val
            if "$set" in update_spec:
                new_doc.update(copy.deepcopy(update_spec["$set"]))
            self.docs[str(new_doc["_id"])] = new_doc
            return copy.deepcopy(new_doc)
        return None

    async def count_documents(self, filter_q=None, *args, **kwargs):
        matched = [doc for doc in self.docs.values() if self._matches(doc, filter_q)]
        return len(matched)


class MockDB:
    def __init__(self):
        self.admins = MockCollection("admins")
        self.orders = MockCollection("orders")
        self.work_assignments = MockCollection("work_assignments")
        self.wage_obligations = MockCollection("wage_obligations")
        self.wage_settlements = MockCollection("wage_settlements")
        self.finance_transactions = MockCollection("finance_transactions")
        self.settings = MockCollection("settings")
        self.counters = MockCollection("counters")
        self.audit_logs = MockCollection("audit_logs")
        self.item_instances = MockCollection("item_instances")
        self.outbox_events = MockCollection("outbox_events")
        self.employee_wages = MockCollection("employee_wages")
        self.payments = MockCollection("payments")
        self.customer_credit_events = MockCollection("customer_credit_events")
        self.finance_categories = MockCollection("finance_categories")


def setup_standard_fixture():
    mdb = MockDB()

    # Users
    owner = {"_id": ObjectId("607f1f77bcf86cd799439099"), "id": "607f1f77bcf86cd799439099", "name": "Pak Owner", "role": "owner"}
    manager = {"_id": ObjectId("607f1f77bcf86cd799439098"), "id": "607f1f77bcf86cd799439098", "name": "Bu Manager", "role": "manager", "permissions": {"manage_orders": True, "access_finance": True}}

    workers = [
        {"_id": ObjectId("607f1f77bcf86cd799439001"), "id": "607f1f77bcf86cd799439001", "name": "Ahmad", "role": "employee", "status": "active"},
        {"_id": ObjectId("607f1f77bcf86cd799439002"), "id": "607f1f77bcf86cd799439002", "name": "Budi", "role": "employee", "status": "active"},
        {"_id": ObjectId("607f1f77bcf86cd799439003"), "id": "607f1f77bcf86cd799439003", "name": "Citra", "role": "employee", "status": "active"},
        {"_id": ObjectId("607f1f77bcf86cd799439004"), "id": "607f1f77bcf86cd799439004", "name": "Dedi", "role": "employee", "status": "active"},
        {"_id": ObjectId("607f1f77bcf86cd799439005"), "id": "607f1f77bcf86cd799439005", "name": "Eko", "role": "employee", "status": "active"},
        {"_id": ObjectId("607f1f77bcf86cd799439006"), "id": "607f1f77bcf86cd799439006", "name": "Fajar", "role": "employee", "status": "active"},
        {"_id": ObjectId("607f1f77bcf86cd799439090"), "id": "607f1f77bcf86cd799439090", "name": "Nonaktif", "role": "employee", "status": "inactive"},
    ]
    for w in [owner, manager] + workers:
        mdb.admins.docs[str(w["_id"])] = copy.deepcopy(w)

    # Standard Order with 2 line items:
    # Item 1: Meja Makan (quantity = 2)
    # Item 2: Kursi Makan (quantity = 4)
    order_id = ObjectId("507f1f77bcf86cd799439011")
    order = {
        "_id": order_id,
        "order_number": "SGF-ORD-082",
        "order_status": "diproses",
        "payment_status": "dp",
        "items": [
            {
                "item_id": "itm_table_01",
                "product_name_snapshot": "Meja Makan Jati 6 Kursi",
                "quantity": 2,
                "unit_price_le": 1200.0,
                "subtotal_le": 2400.0,
            },
            {
                "item_id": "itm_chair_01",
                "product_name_snapshot": "Kursi Makan Kayu Jati",
                "quantity": 4,
                "unit_price_le": 250.0,
                "subtotal_le": 1000.0,
            }
        ]
    }
    mdb.orders.docs[str(order_id)] = copy.deepcopy(order)

    # Configured Production Wage Policy
    mdb.settings.docs["production_wage_policy"] = {
        "key": "production_wage_policy",
        "value": {
            "default_wage_per_unit_le": 100.0,
            "unusual_amount_threshold_le": 200.0,
            "max_wage_per_unit_le": 500.0,
            "enabled": True,
            "currency": "EGP",
            "rounding_policy": "piastre_round_half_up",
        }
    }

    return mdb, owner, manager, workers, str(order_id)


# =============================================================================
# TESTS: PHASE 08.2 REQUIREMENTS F.1 - F.25
# =============================================================================

@pytest.mark.anyio
async def test_01_assignment_with_one_worker():
    """F.1: Assignment with exactly one worker."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    w1_id = workers[0]["id"]

    with patch("server.db", mdb):
        payload = WorkAssignmentCreateInput(
            worker_ids=[w1_id],
            order_item_id="itm_table_01",
            task_category="whole_item",
            target_quantity=1
        )
        asn = await admin_create_work_assignment(ord_id, payload, manager)
        assert asn["worker_id"] == w1_id
        assert asn["worker_ids"] == [w1_id]
        assert len(asn["workers"]) == 1
        assert asn["workers"][0]["worker_name"] == "Ahmad"
        assert asn["agreed_rate_le"] == 100.0  # From policy default


@pytest.mark.anyio
async def test_02_assignment_with_two_workers():
    """F.2: Assignment with two workers."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    wids = [workers[0]["id"], workers[1]["id"]]

    with patch("server.db", mdb):
        payload = WorkAssignmentCreateInput(
            worker_ids=wids,
            order_item_id="itm_table_01",
            task_category="whole_item",
            target_quantity=2
        )
        asn = await admin_create_work_assignment(ord_id, payload, manager)
        assert asn["worker_ids"] == wids
        assert len(asn["workers"]) == 2
        assert {w["worker_name"] for w in asn["workers"]} == {"Ahmad", "Budi"}


@pytest.mark.anyio
async def test_03_assignment_with_five_workers():
    """F.3: Assignment with maximum permitted 5 workers."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    wids = [workers[i]["id"] for i in range(5)]

    with patch("server.db", mdb):
        payload = WorkAssignmentCreateInput(
            worker_ids=wids,
            order_item_id="itm_chair_01",
            task_category="assembly",
            target_quantity=4
        )
        asn = await admin_create_work_assignment(ord_id, payload, manager)
        assert len(asn["worker_ids"]) == 5
        assert len(asn["workers"]) == 5


@pytest.mark.anyio
async def test_04_rejection_of_six_workers():
    """F.4: Rejection of assignment with 6 workers (hard limit max 5)."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    wids = [workers[i]["id"] for i in range(6)]

    with patch("server.db", mdb):
        payload = WorkAssignmentCreateInput(
            worker_ids=wids,
            order_item_id="itm_chair_01",
            task_category="assembly",
            target_quantity=4
        )
        with pytest.raises(HTTPException) as exc:
            await admin_create_work_assignment(ord_id, payload, manager)
        assert exc.value.status_code == 422
        assert "tidak boleh melebihi 5 orang" in str(exc.value.detail)


@pytest.mark.anyio
async def test_05_rejection_of_duplicate_workers():
    """F.5: Rejection of assignment containing duplicate worker IDs."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    w1_id = workers[0]["id"]

    with patch("server.db", mdb):
        payload = WorkAssignmentCreateInput(
            worker_ids=[w1_id, w1_id],
            order_item_id="itm_table_01",
            task_category="whole_item",
            target_quantity=1
        )
        with pytest.raises(HTTPException) as exc:
            await admin_create_work_assignment(ord_id, payload, manager)
        assert exc.value.status_code == 422
        assert "memuat ID duplikat" in str(exc.value.detail)


@pytest.mark.anyio
async def test_06_rejection_of_invalid_or_inactive_worker_id():
    """F.6: Rejection of nonexistent or inactive worker accounts."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    nonexistent_id = str(ObjectId())
    inactive_id = "607f1f77bcf86cd799439090"

    with patch("server.db", mdb):
        # Nonexistent worker
        payload_nonexistent = WorkAssignmentCreateInput(
            worker_ids=[nonexistent_id],
            order_item_id="itm_table_01",
            task_category="whole_item",
            target_quantity=1
        )
        with pytest.raises(HTTPException) as exc1:
            await admin_create_work_assignment(ord_id, payload_nonexistent, manager)
        assert exc1.value.status_code == 404

        # Inactive worker
        payload_inactive = WorkAssignmentCreateInput(
            worker_ids=[inactive_id],
            order_item_id="itm_table_01",
            task_category="whole_item",
            target_quantity=1
        )
        with pytest.raises(HTTPException) as exc2:
            await admin_create_work_assignment(ord_id, payload_inactive, manager)
        assert exc2.value.status_code == 422
        assert "berstatus tidak aktif" in str(exc2.value.detail)


@pytest.mark.anyio
async def test_07_total_wage_calculation_from_rate_and_quantity():
    """F.7: Total wage = configured_rate_per_unit * assigned_quantity."""
    rate = 100.0
    qty = 2
    total = calculate_wage_obligation_amount(rate, qty, "per_unit")
    assert total == 200.0


@pytest.mark.anyio
async def test_08_exact_piastre_split_without_drift():
    """F.8: Exact piastre split for 200 LE among 3 workers: 66.67, 66.67, 66.66 LE."""
    recipients = [{"worker_id": "w1"}, {"worker_id": "w2"}, {"worker_id": "w3"}]
    allocs = distribute_wage_piastres(200.0, recipients)
    assert len(allocs) == 3
    assert allocs[0]["amount_le"] == 66.67
    assert allocs[0]["amount_piastres"] == 6667
    assert allocs[1]["amount_le"] == 66.67
    assert allocs[1]["amount_piastres"] == 6667
    assert allocs[2]["amount_le"] == 66.66
    assert allocs[2]["amount_piastres"] == 6666
    assert sum(a["amount_piastres"] for a in allocs) == 20000
    assert sum(a["amount_le"] for a in allocs) == 200.0


@pytest.mark.anyio
async def test_09_one_order_line_two_units_two_assignments_one_unit_each():
    """F.9: Pola 2 — Order quantity 2, two separate assignments of 1 unit each."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    w1_id = workers[0]["id"]
    w2_id = workers[1]["id"]

    with patch("server.db", mdb):
        # Assignment A: 1 unit, worker A
        asn_a = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(
                worker_ids=[w1_id],
                order_item_id="itm_table_01",
                task_category="whole_item",
                target_quantity=1
            ),
            manager
        )
        assert asn_a["target_quantity"] == 1

        # Assignment B: 1 unit, worker B
        asn_b = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(
                worker_ids=[w2_id],
                order_item_id="itm_table_01",
                task_category="whole_item",
                target_quantity=1
            ),
            manager
        )
        assert asn_b["target_quantity"] == 1


@pytest.mark.anyio
async def test_10_rejection_of_assignment_exceeding_ordered_quantity():
    """F.10: Rejection of assignment that would exceed ordered quantity (Invariant C3)."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    w1_id = workers[0]["id"]
    w2_id = workers[1]["id"]
    w3_id = workers[2]["id"]

    with patch("server.db", mdb):
        # Assignment 1: 1 unit of table (ordered: 2)
        await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=1),
            manager
        )

        # Assignment 2: 1 unit of table (remaining: 1)
        await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w2_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=1),
            manager
        )

        # Assignment 3: 1 unit of table (remaining: 0 -> REJECTED!)
        with pytest.raises(HTTPException) as exc:
            await admin_create_work_assignment(
                ord_id,
                WorkAssignmentCreateInput(worker_ids=[w3_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=1),
                manager
            )
        assert exc.value.status_code == 422
        assert "melebihi sisa kapasitas unit yang tersedia" in str(exc.value.detail)


@pytest.mark.anyio
async def test_11_two_workers_together_on_two_units():
    """F.11: Pola 3 — Single assignment of 2 units shared between worker A and worker B."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    wids = [workers[0]["id"], workers[1]["id"]]

    with patch("server.db", mdb):
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(
                worker_ids=wids,
                order_item_id="itm_table_01",
                task_category="whole_item",
                target_quantity=2
            ),
            manager
        )
        assert asn["target_quantity"] == 2
        assert asn["worker_ids"] == wids


@pytest.mark.anyio
async def test_12_assignment_cancellation_releases_capacity():
    """F.12: Cancelling an assignment releases its allocated unit capacity."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    w1_id = workers[0]["id"]
    w2_id = workers[1]["id"]

    with patch("server.db", mdb):
        # Assign 2 units (full capacity of itm_table_01)
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=2),
            manager
        )
        asn_id = asn["id"]

        # Attempting 1 more unit is rejected
        with pytest.raises(HTTPException):
            await admin_create_work_assignment(
                ord_id,
                WorkAssignmentCreateInput(worker_ids=[w2_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=1),
                manager
            )

        # Cancel assignment
        await admin_cancel_work_assignment(asn_id, WorkAssignmentCancelInput(reason="Perubahan alokasi tim"), manager)

        # Capacity released: New assignment of 2 units now succeeds!
        new_asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w2_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=2),
            manager
        )
        assert new_asn["target_quantity"] == 2


@pytest.mark.anyio
async def test_13_cancellation_does_not_destroy_or_duplicate_wage_history():
    """F.13: Cancelling voids accrued obligations cleanly without deleting or duplicating history."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    wids = [workers[0]["id"], workers[1]["id"]]

    with patch("server.db", mdb):
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=wids, order_item_id="itm_table_01", task_category="whole_item", target_quantity=2),
            manager
        )
        asn_id = asn["id"]

        # Progress to ready_for_review and verify
        await admin_update_assignment_progress(asn_id, WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=2), manager)
        res = await admin_verify_work_assignment(asn_id, WorkAssignmentVerifyInput(accepted_quantity=2), manager)
        assert len(res["wage_obligations"]) == 2

        # Cancel verified assignment (Owner permission)
        await admin_cancel_work_assignment(asn_id, WorkAssignmentCancelInput(reason="Pembatalan produksi oleh owner"), owner)

        # Assert obligations are voided (not deleted)
        wobs = await mdb.wage_obligations.find({"work_assignment_id": asn_id}).to_list(10)
        assert len(wobs) == 2
        for w in wobs:
            assert w["status"] == "voided"
            assert w["void_reason"] == "Pembatalan produksi oleh owner"


@pytest.mark.anyio
async def test_14_production_completion_creates_exact_wage_obligations():
    """F.14: Completing multi-worker production creates exactly 1 wage obligation per assigned worker."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    wids = [workers[0]["id"], workers[1]["id"], workers[2]["id"]]

    with patch("server.db", mdb):
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=wids, order_item_id="itm_table_01", task_category="whole_item", target_quantity=2),
            manager
        )
        asn_id = asn["id"]

        await admin_update_assignment_progress(asn_id, WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=2), manager)
        verify_res = await admin_verify_work_assignment(asn_id, WorkAssignmentVerifyInput(accepted_quantity=2), manager)

        assert verify_res["total_amount_le"] == 200.0  # 100 LE * 2 units
        assert len(verify_res["wage_obligations"]) == 3
        assert verify_res["wage_obligations"][0]["total_amount_le"] == 66.67
        assert verify_res["wage_obligations"][1]["total_amount_le"] == 66.67
        assert verify_res["wage_obligations"][2]["total_amount_le"] == 66.66


@pytest.mark.anyio
async def test_15_idempotent_retry_does_not_create_duplicate_obligations():
    """F.15: Retrying verify request returns identical obligations without duplicating."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    wids = [workers[0]["id"], workers[1]["id"]]

    with patch("server.db", mdb):
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=wids, order_item_id="itm_table_01", task_category="whole_item", target_quantity=2),
            manager
        )
        asn_id = asn["id"]

        await admin_update_assignment_progress(asn_id, WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=2), manager)
        res1 = await admin_verify_work_assignment(asn_id, WorkAssignmentVerifyInput(accepted_quantity=2), manager)

        # Retry verify with identical input
        res2 = await admin_verify_work_assignment(asn_id, WorkAssignmentVerifyInput(accepted_quantity=2), manager)

        assert res1["total_amount_le"] == res2["total_amount_le"]
        all_wobs = await mdb.wage_obligations.find({"work_assignment_id": asn_id}).to_list(10)
        assert len(all_wobs) == 2  # Exactly 2, not 4!


@pytest.mark.anyio
async def test_16_non_owner_self_approval_rejected():
    """F.16: Dual-custody: Worker involved in assignment cannot approve their own assignment unless Owner."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    w1 = workers[0]
    w1_id = w1["id"]

    with patch("server.db", mdb):
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=1),
            manager
        )
        asn_id = asn["id"]

        await admin_update_assignment_progress(asn_id, WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=1), manager)

        # Worker attempts self-approval
        with pytest.raises(HTTPException) as exc:
            await admin_verify_work_assignment(asn_id, WorkAssignmentVerifyInput(accepted_quantity=1), w1)
        assert exc.value.status_code == 403
        assert "Dual-Custody" in str(exc.value.detail)


@pytest.mark.anyio
async def test_17_unconfigured_production_policy_fails_closed():
    """F.17: When production policy is unconfigured, assignment creation fails closed."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    # Delete policy
    del mdb.settings.docs["production_wage_policy"]
    w1_id = workers[0]["id"]

    with patch("server.db", mdb):
        payload = WorkAssignmentCreateInput(
            worker_ids=[w1_id],
            order_item_id="itm_table_01",
            task_category="whole_item",
            target_quantity=1
        )
        with pytest.raises(HTTPException) as exc:
            await admin_create_work_assignment(ord_id, payload, manager)
        assert exc.value.status_code == 422
        assert "Kebijakan upah produksi belum dikonfigurasi" in str(exc.value.detail)


@pytest.mark.anyio
async def test_18_policy_mutation_does_not_alter_historical_obligations():
    """F.18: Mutating production policy settings does NOT recalculate or mutate historical obligations."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    w1_id = workers[0]["id"]

    with patch("server.db", mdb):
        # Create & verify at rate 100 LE
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=1),
            manager
        )
        await admin_update_assignment_progress(asn["id"], WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=1), manager)
        await admin_verify_work_assignment(asn["id"], WorkAssignmentVerifyInput(accepted_quantity=1), manager)

        # Mutate policy to 150 LE
        mdb.settings.docs["production_wage_policy"]["value"]["default_wage_per_unit_le"] = 150.0

        # Assert historical obligation is still 100 LE
        hist = await mdb.wage_obligations.find_one({"work_assignment_id": asn["id"]})
        assert hist["total_amount_le"] == 100.0


@pytest.mark.anyio
async def test_19_manual_override_requires_reason_and_owner():
    """F.19: Manual rate override requires Owner role and reason (min 3 chars)."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    w1_id = workers[0]["id"]

    with patch("server.db", mdb):
        # Manager attempts override without Owner role
        payload_mgr = WorkAssignmentCreateInput(
            worker_ids=[w1_id],
            order_item_id="itm_table_01",
            task_category="whole_item",
            agreed_rate_le=120.0,
            rate_override_reason="Model rumit",
            target_quantity=1
        )
        with pytest.raises(HTTPException) as exc1:
            await admin_create_work_assignment(ord_id, payload_mgr, manager)
        assert exc1.value.status_code == 403

        # Owner attempts override without reason
        payload_no_reason = WorkAssignmentCreateInput(
            worker_ids=[w1_id],
            order_item_id="itm_table_01",
            task_category="whole_item",
            agreed_rate_le=120.0,
            rate_override_reason="",
            target_quantity=1
        )
        with pytest.raises(HTTPException) as exc2:
            await admin_create_work_assignment(ord_id, payload_no_reason, owner)
        assert exc2.value.status_code == 422
        assert "Alasan penyesuaian tarif manual wajib diisi" in str(exc2.value.detail)

        # Owner attempts override with valid reason
        payload_valid = WorkAssignmentCreateInput(
            worker_ids=[w1_id],
            order_item_id="itm_table_01",
            task_category="whole_item",
            agreed_rate_le=120.0,
            rate_override_reason="Model ukiran rumit",
            target_quantity=1
        )
        asn_ok = await admin_create_work_assignment(ord_id, payload_valid, owner)
        assert asn_ok["agreed_rate_le"] == 120.0
        assert asn_ok["is_override"] is True


@pytest.mark.anyio
async def test_20_hard_cap_enforcement():
    """F.20: Exceeding production policy hard cap (500 LE) is strictly rejected."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    w1_id = workers[0]["id"]

    with patch("server.db", mdb):
        payload_cap = WorkAssignmentCreateInput(
            worker_ids=[w1_id],
            order_item_id="itm_table_01",
            task_category="whole_item",
            agreed_rate_le=550.0,  # Exceeds max 500 LE
            rate_override_reason="Bahan sangat mahal",
            target_quantity=1
        )
        with pytest.raises(HTTPException) as exc:
            await admin_create_work_assignment(ord_id, payload_cap, owner)
        assert exc.value.status_code == 422
        assert "melebihi batas maksimum keras" in str(exc.value.detail)


@pytest.mark.anyio
async def test_21_wage_settlement_and_partial_settlement_consistency():
    """F.21: Production wage obligations appear in pending summary and can be settled cleanly."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    wids = [workers[0]["id"], workers[1]["id"]]
    w1_id = workers[0]["id"]

    with patch("server.db", mdb):
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=wids, order_item_id="itm_table_01", task_category="whole_item", target_quantity=2),
            manager
        )
        await admin_update_assignment_progress(asn["id"], WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=2), manager)
        verify_res = await admin_verify_work_assignment(asn["id"], WorkAssignmentVerifyInput(accepted_quantity=2), manager)

        w1_wob = next(w for w in verify_res["wage_obligations"] if w["worker_id"] == w1_id)
        assert w1_wob["total_amount_le"] == 100.0

        # Check pending payments summary
        summary = await admin_get_wages_pending_summary(manager)
        assert summary["total_pending_wages_le"] >= 200.0

        # Partial settlement of 40 LE for Worker 1
        w1_wob_id = w1_wob.get("id") or w1_wob.get("_id")
        settle_payload = WageSettlementCreateInput(
            worker_id=w1_id,
            amount_le=40.0,
            allocations=[WageSettlementAllocationItem(wage_obligation_id=str(w1_wob_id), amount_le=40.0)]
        )
        settle_res = await admin_create_wage_settlement(settle_payload, manager)
        assert settle_res["amount_le"] == 40.0
        assert settle_res["status"] == "recorded"

        # Assert obligation is partially_paid
        w1_after = await mdb.wage_obligations.find_one({"_id": id_query(w1_wob_id)})
        assert w1_after["status"] == "partially_paid"
        assert w1_after["paid_amount_le"] == 40.0


@pytest.mark.anyio
async def test_22_void_wage_settlement_restores_pending_obligation():
    """F.22: Voiding wage settlement restores obligation to accrued without duplicating."""
    mdb, owner, manager, workers, ord_id = setup_standard_fixture()
    w1_id = workers[0]["id"]

    with patch("server.db", mdb):
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=1),
            manager
        )
        await admin_update_assignment_progress(asn["id"], WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=1), manager)
        verify_res = await admin_verify_work_assignment(asn["id"], WorkAssignmentVerifyInput(accepted_quantity=1), manager)
        wob_id = verify_res["wage_obligations"][0].get("id") or verify_res["wage_obligations"][0].get("_id")

        # Full settlement 100 LE
        settle_payload = WageSettlementCreateInput(
            worker_id=w1_id,
            amount_le=100.0,
            allocations=[WageSettlementAllocationItem(wage_obligation_id=str(wob_id), amount_le=100.0)]
        )
        settle = await admin_create_wage_settlement(settle_payload, manager)
        assert settle["status"] == "recorded"

        # Void settlement
        void_res = await admin_void_wage_settlement(settle["id"], WageSettlementVoidInput(reason="Koreksi kas bon"), manager)
        assert void_res["status"] == "voided"

        # Obligation reverted to accrued with 0 paid
        wob_restored = await mdb.wage_obligations.find_one({"_id": id_query(wob_id)})
        assert wob_restored["status"] == "accrued"
        assert wob_restored["paid_amount_le"] == 0.0
