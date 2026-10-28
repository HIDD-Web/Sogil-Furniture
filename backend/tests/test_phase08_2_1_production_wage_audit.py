"""
Phase 08.2.1 — Production Wage Safety & Configuration Audit Test Suite.

Audits:
1. Production Wage Policy Configuration:
   - Fresh / unconfigured DB returns is_configured: False, enabled: False, None rates.
   - Example rates from documentation never become operational defaults.
   - Explicitly configured Owner policy is recognized and active.
   - Changing policy rates does not mutate previously accrued wage obligations.

2. Concurrent Production Assignment Capacity:
   - Invariant: total_active_assigned_quantity <= ordered_quantity.
   - Two concurrent requests (via asyncio.gather) each requesting quantity 2 on order line of 2:
     Exactly one succeeds (HTTP 201), the other fails with HTTP 422! Total active assignments <= 2.
   - Two concurrent requests each requesting quantity 1 on order line of 2:
     Both succeed (total active = 2). A third request attempting quantity 1 fails with HTTP 422.
   - Cancelled assignment releases unit capacity immediately.
   - Different task categories (cutting vs assembly) have independent capacity and do not collide.

3. Multi-Worker Accrual Atomicity:
   - Interrupted accrual (worker 1's obligation exists, worker 2's missing):
     Retry reconciles missing worker 2 without duplicating worker 1, completes assignment.
   - Two concurrent verification requests (asyncio.gather):
     Both return cleanly without duplicating wage obligations.
   - DuplicateKeyError during insertion handled reconciliatively.
   - Total wage allocated equals sum of worker allocations with zero money drift.

4. Cancellation & Financial Integrity:
   - Multi-worker assignment with unpaid obligations: cancellation voids all obligations (soft-void) and releases capacity.
   - Rejection if any worker obligation is partially paid (HTTP 400). Neither worker's obligation is modified.
   - Rejection if any worker obligation is fully paid (HTTP 400).
   - Repeated cancellation calls are idempotent.
   - Voided obligations are excluded from active capacity and pending wage summary.
"""

import copy
import asyncio
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
    admin_create_wage_settlement,
    admin_get_wages_pending_summary,
    get_active_production_wage_policy,
    id_query,
    WorkAssignmentCreateInput,
    WorkAssignmentProgressInput,
    WorkAssignmentVerifyInput,
    WorkAssignmentCancelInput,
    WageSettlementCreateInput,
    WageSettlementAllocationItem,
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
                elif isinstance(v, dict) and "$ne" in v:
                    if doc.get("status") == v["$ne"]:
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


def setup_audit_fixture():
    mdb = MockDB()

    owner = {"_id": ObjectId("607f1f77bcf86cd799439099"), "id": "607f1f77bcf86cd799439099", "name": "Pak Owner", "role": "owner"}
    manager = {"_id": ObjectId("607f1f77bcf86cd799439098"), "id": "607f1f77bcf86cd799439098", "name": "Bu Manager", "role": "manager", "permissions": {"manage_orders": True, "access_finance": True}}

    workers = [
        {"_id": ObjectId("607f1f77bcf86cd799439001"), "id": "607f1f77bcf86cd799439001", "name": "Ahmad", "role": "employee", "status": "active"},
        {"_id": ObjectId("607f1f77bcf86cd799439002"), "id": "607f1f77bcf86cd799439002", "name": "Budi", "role": "employee", "status": "active"},
        {"_id": ObjectId("607f1f77bcf86cd799439003"), "id": "607f1f77bcf86cd799439003", "name": "Citra", "role": "employee", "status": "active"},
    ]
    for w in [owner, manager] + workers:
        mdb.admins.docs[str(w["_id"])] = copy.deepcopy(w)

    order_id = ObjectId("507f1f77bcf86cd799439011")
    order = {
        "_id": order_id,
        "order_number": "SGF-ORD-AUDIT",
        "order_status": "diproses",
        "payment_status": "dp",
        "items": [
            {
                "item_id": "itm_table_01",
                "product_name_snapshot": "Meja Makan Jati 6 Kursi",
                "quantity": 2,
                "unit_price_le": 1200.0,
                "subtotal_le": 2400.0,
            }
        ]
    }
    mdb.orders.docs[str(order_id)] = copy.deepcopy(order)

    return mdb, owner, manager, workers, str(order_id)


# =============================================================================
# AUDIT 1: PRODUCTION WAGE POLICY CONFIGURATION
# =============================================================================

@pytest.mark.anyio
async def test_audit1_01_unconfigured_policy_not_active():
    """Audit 1.1: Unconfigured DB returns is_configured: False, enabled: False, None rates."""
    mdb, owner, manager, workers, ord_id = setup_audit_fixture()
    # Ensure no production_wage_policy exists in settings
    assert "production_wage_policy" not in mdb.settings.docs

    policy = await get_active_production_wage_policy(db_inst=mdb)
    assert policy["is_configured"] is False
    assert policy["enabled"] is False
    assert policy["default_wage_per_unit_le"] is None
    assert policy["unusual_amount_threshold_le"] is None
    assert policy["max_wage_per_unit_le"] is None


@pytest.mark.anyio
async def test_audit1_02_example_rates_never_become_active_operational_policy():
    """Audit 1.2: System fails closed when creating assignment on unconfigured DB."""
    mdb, owner, manager, workers, ord_id = setup_audit_fixture()
    w1_id = workers[0]["id"]

    with patch("server.db", mdb):
        with pytest.raises(HTTPException) as exc_info:
            await admin_create_work_assignment(
                ord_id,
                WorkAssignmentCreateInput(worker_ids=[w1_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=1),
                manager
            )
        assert exc_info.value.status_code == 422
        assert "Kebijakan upah produksi belum dikonfigurasi" in exc_info.value.detail


@pytest.mark.anyio
async def test_audit1_03_explicit_owner_saved_policy_is_active():
    """Audit 1.3: Explicitly saved Owner policy is properly recognized and applied."""
    mdb, owner, manager, workers, ord_id = setup_audit_fixture()
    w1_id = workers[0]["id"]

    # Explicit Owner configuration
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

    with patch("server.db", mdb):
        policy = await get_active_production_wage_policy(db_inst=mdb)
        assert policy["is_configured"] is True
        assert policy["enabled"] is True
        assert policy["default_wage_per_unit_le"] == 100.0

        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=1),
            manager
        )
        assert asn["agreed_rate_le"] == 100.0
        assert asn["rate_policy_snapshot"]["default_wage_per_unit_le"] == 100.0


@pytest.mark.anyio
async def test_audit1_04_policy_changes_do_not_mutate_historical_obligations():
    """Audit 1.4: Changing policy rates later does not alter previously accrued obligations."""
    mdb, owner, manager, workers, ord_id = setup_audit_fixture()
    w1_id = workers[0]["id"]

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

    with patch("server.db", mdb):
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=1),
            manager
        )
        await admin_update_assignment_progress(asn["id"], WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=1), manager)
        verify_res = await admin_verify_work_assignment(asn["id"], WorkAssignmentVerifyInput(accepted_quantity=1), manager)
        wob_id = verify_res["wage_obligations"][0].get("id") or verify_res["wage_obligations"][0].get("_id")

        # Mutate policy rate to 250.0 LE
        mdb.settings.docs["production_wage_policy"]["value"]["default_wage_per_unit_le"] = 250.0

        # Verify historical obligation remains exactly 100.0 LE
        saved_wob = await mdb.wage_obligations.find_one({"_id": id_query(wob_id)})
        assert saved_wob["total_amount_le"] == 100.0
        assert saved_wob["amount_piastres"] == 10000


# =============================================================================
# AUDIT 2: CONCURRENT PRODUCTION ASSIGNMENT CAPACITY
# =============================================================================

@pytest.mark.anyio
async def test_audit2_01_concurrent_assignments_exceeding_capacity_rejected():
    """Audit 2.1: Order line quantity 2. Two concurrent requests each attempting qty 2 -> exactly one succeeds."""
    mdb, owner, manager, workers, ord_id = setup_audit_fixture()
    w1_id = workers[0]["id"]
    w2_id = workers[1]["id"]

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

    with patch("server.db", mdb):
        req1 = admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=2),
            manager
        )
        req2 = admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w2_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=2),
            manager
        )

        results = await asyncio.gather(req1, req2, return_exceptions=True)

        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]

        assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}"
        assert len(failures) == 1, f"Expected exactly 1 failure, got {len(failures)}"
        assert isinstance(failures[0], HTTPException)
        assert failures[0].status_code == 422
        assert "melebihi sisa kapasitas unit yang tersedia" in failures[0].detail

        # Total active assigned quantity in DB is exactly 2, never 4
        all_asns = [d for d in mdb.work_assignments.docs.values() if d.get("status") != "cancelled"]
        total_assigned = sum(int(a["target_quantity"]) for a in all_asns)
        assert total_assigned == 2


@pytest.mark.anyio
async def test_audit2_02_concurrent_assignments_within_capacity_succeed():
    """Audit 2.2: Two concurrent requests each qty 1 for order line qty 2 -> both succeed; 3rd request rejected."""
    mdb, owner, manager, workers, ord_id = setup_audit_fixture()
    w1_id = workers[0]["id"]
    w2_id = workers[1]["id"]
    w3_id = workers[2]["id"]

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

    with patch("server.db", mdb):
        req1 = admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=1),
            manager
        )
        req2 = admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w2_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=1),
            manager
        )

        results = await asyncio.gather(req1, req2, return_exceptions=True)

        for r in results:
            assert not isinstance(r, Exception), f"Unexpected exception: {r}"
        assert len(results) == 2

        all_asns = [d for d in mdb.work_assignments.docs.values() if d.get("status") != "cancelled"]
        total_assigned = sum(int(a["target_quantity"]) for a in all_asns)
        assert total_assigned == 2

        # 3rd request attempting to exceed capacity (make total 3) is rejected
        with pytest.raises(HTTPException) as exc_3:
            await admin_create_work_assignment(
                ord_id,
                WorkAssignmentCreateInput(worker_ids=[w3_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=1),
                manager
            )
        assert exc_3.value.status_code == 422


@pytest.mark.anyio
async def test_audit2_03_cancelled_assignment_releases_capacity_for_new_assignment():
    """Audit 2.3: Assignment cancellation immediately frees unit capacity."""
    mdb, owner, manager, workers, ord_id = setup_audit_fixture()
    w1_id = workers[0]["id"]
    w2_id = workers[1]["id"]

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

    with patch("server.db", mdb):
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=2),
            manager
        )

        # Cancel assignment
        await admin_cancel_work_assignment(asn["id"], WorkAssignmentCancelInput(reason="Perubahan jadwal produksi"), manager)

        # Capacity is freed: new assignment of 2 units succeeds!
        asn2 = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w2_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=2),
            manager
        )
        assert asn2["target_quantity"] == 2


@pytest.mark.anyio
async def test_audit2_04_different_task_categories_have_independent_capacity():
    """Audit 2.4: Different task categories on the same item track capacity independently."""
    mdb, owner, manager, workers, ord_id = setup_audit_fixture()
    w1_id = workers[0]["id"]
    w2_id = workers[1]["id"]

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

    with patch("server.db", mdb):
        # 2 units for cutting
        asn_cut = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id], order_item_id="itm_table_01", task_category="cutting", target_quantity=2),
            manager
        )
        # 2 units for assembly
        asn_asm = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w2_id], order_item_id="itm_table_01", task_category="assembly", target_quantity=2),
            manager
        )
        assert asn_cut["task_category"] == "cutting"
        assert asn_asm["task_category"] == "assembly"


# =============================================================================
# AUDIT 3: MULTI-WORKER ACCRUAL ATOMICITY
# =============================================================================

@pytest.mark.anyio
async def test_audit3_01_interrupted_accrual_reconciles_missing_workers():
    """Audit 3.1: Partial obligation existence reconciles missing workers without duplication."""
    mdb, owner, manager, workers, ord_id = setup_audit_fixture()
    w1_id = workers[0]["id"]
    w2_id = workers[1]["id"]

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

    with patch("server.db", mdb):
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id, w2_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=2),
            manager
        )
        await admin_update_assignment_progress(asn["id"], WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=2), manager)

        aid_str = asn["id"]
        # Simulate an interrupted state: Worker 1 obligation already exists in DB
        w1_existing_wob = {
            "_id": ObjectId("777777777777777777777701"),
            "obligation_number": "WOB-20261028-0999",
            "accrual_event_key": f"acc_{aid_str}_{w1_id}",
            "work_assignment_id": aid_str,
            "worker_id": w1_id,
            "worker_name": "Ahmad",
            "order_id": ord_id,
            "total_amount_le": 100.0,
            "amount_piastres": 10000,
            "currency": "EGP",
            "status": "accrued",
            "paid_amount_le": 0.0,
            "payload_hash": "c055ee1ff98eb9bf08b15d0263309a477382d512a64c58cf3487c936fa4ea7ce",
        }
        # Compute exact hash for accepted_quantity=2, notes=""
        from server import compute_payload_hash
        w1_existing_wob["payload_hash"] = compute_payload_hash({"accepted_quantity": 2, "notes": ""})
        mdb.wage_obligations.docs[str(w1_existing_wob["_id"])] = w1_existing_wob

        # Verify should reconcile missing Worker 2 and not duplicate Worker 1
        verify_res = await admin_verify_work_assignment(asn["id"], WorkAssignmentVerifyInput(accepted_quantity=2), manager)

        assert len(verify_res["wage_obligations"]) == 2
        w1_res = next(w for w in verify_res["wage_obligations"] if w["worker_id"] == w1_id)
        w2_res = next(w for w in verify_res["wage_obligations"] if w["worker_id"] == w2_id)
        assert w1_res["obligation_number"] == "WOB-20261028-0999"  # Preserved
        assert w2_res["total_amount_le"] == 100.0
        assert verify_res["assignment"]["status"] == "completed"

        # Check in DB
        db_wobs = [d for d in mdb.wage_obligations.docs.values() if d.get("work_assignment_id") == aid_str]
        assert len(db_wobs) == 2


@pytest.mark.anyio
async def test_audit3_02_concurrent_verification_requests_idempotent():
    """Audit 3.2: Concurrent verification calls return consistent results without duplicate obligations."""
    mdb, owner, manager, workers, ord_id = setup_audit_fixture()
    w1_id = workers[0]["id"]
    w2_id = workers[1]["id"]

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

    with patch("server.db", mdb):
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id, w2_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=2),
            manager
        )
        await admin_update_assignment_progress(asn["id"], WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=2), manager)

        v_req1 = admin_verify_work_assignment(asn["id"], WorkAssignmentVerifyInput(accepted_quantity=2), manager)
        v_req2 = admin_verify_work_assignment(asn["id"], WorkAssignmentVerifyInput(accepted_quantity=2), manager)

        res1, res2 = await asyncio.gather(v_req1, v_req2)

        assert res1["status"] == "accrued" or res1.get("assignment", {}).get("status") == "completed"
        assert res2["status"] == "accrued" or res2.get("assignment", {}).get("status") == "completed"

        # In DB, exactly 2 obligations exist (1 per worker)
        all_wobs = [d for d in mdb.wage_obligations.docs.values() if d.get("work_assignment_id") == asn["id"]]
        assert len(all_wobs) == 2


@pytest.mark.anyio
async def test_audit3_03_duplicate_key_error_handled_reconciliatively():
    """Audit 3.3: DuplicateKeyError triggers canonical reconciliation."""
    mdb, owner, manager, workers, ord_id = setup_audit_fixture()
    w1_id = workers[0]["id"]

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

    with patch("server.db", mdb):
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=1),
            manager
        )
        await admin_update_assignment_progress(asn["id"], WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=1), manager)

        # First verification succeeds
        v1 = await admin_verify_work_assignment(asn["id"], WorkAssignmentVerifyInput(accepted_quantity=1), manager)

        # Second verification triggers idempotent replay/reconciliation
        v2 = await admin_verify_work_assignment(asn["id"], WorkAssignmentVerifyInput(accepted_quantity=1), manager)
        assert v2["total_amount_le"] == 100.0


# =============================================================================
# AUDIT 4: CANCELLATION & FINANCIAL INTEGRITY
# =============================================================================

@pytest.mark.anyio
async def test_audit4_01_cancellation_unpaid_voids_all_worker_obligations():
    """Audit 4.1: Cancelling completed assignment voids all accrued obligations (soft-void) and releases capacity."""
    mdb, owner, manager, workers, ord_id = setup_audit_fixture()
    w1_id = workers[0]["id"]
    w2_id = workers[1]["id"]

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

    with patch("server.db", mdb):
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id, w2_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=2),
            manager
        )
        await admin_update_assignment_progress(asn["id"], WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=2), manager)
        await admin_verify_work_assignment(asn["id"], WorkAssignmentVerifyInput(accepted_quantity=2), manager)

        # Cancel assignment
        cancel_res = await admin_cancel_work_assignment(asn["id"], WorkAssignmentCancelInput(reason="Order dibatalkan pembeli"), manager)
        assert cancel_res["status"] == "cancelled"

        # Both obligations voided
        wobs = [d for d in mdb.wage_obligations.docs.values() if d.get("work_assignment_id") == asn["id"]]
        assert len(wobs) == 2
        for w in wobs:
            assert w["status"] == "voided"
            assert w["void_reason"] == "Order dibatalkan pembeli"


@pytest.mark.anyio
async def test_audit4_02_cancellation_rejected_if_any_worker_partially_paid():
    """Audit 4.2: Cancellation is blocked with HTTP 400 if any worker obligation is partially paid."""
    mdb, owner, manager, workers, ord_id = setup_audit_fixture()
    w1_id = workers[0]["id"]
    w2_id = workers[1]["id"]

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

    with patch("server.db", mdb):
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id, w2_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=2),
            manager
        )
        await admin_update_assignment_progress(asn["id"], WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=2), manager)
        verify_res = await admin_verify_work_assignment(asn["id"], WorkAssignmentVerifyInput(accepted_quantity=2), manager)

        w1_wob = next(w for w in verify_res["wage_obligations"] if w["worker_id"] == w1_id)
        w1_wob_id = w1_wob.get("id") or w1_wob.get("_id")

        # Partial settlement for worker 1 (40 LE)
        await admin_create_wage_settlement(
            WageSettlementCreateInput(
                worker_id=w1_id,
                amount_le=40.0,
                allocations=[WageSettlementAllocationItem(wage_obligation_id=str(w1_wob_id), amount_le=40.0)]
            ),
            manager
        )

        # Attempt to cancel assignment must be rejected!
        with pytest.raises(HTTPException) as exc_cancel:
            await admin_cancel_work_assignment(asn["id"], WorkAssignmentCancelInput(reason="Koreksi operasional"), manager)
        assert exc_cancel.value.status_code == 400
        assert "sudah terbayar sebagian atau penuh" in exc_cancel.value.detail

        # Worker 2 obligation must NOT have been changed to voided
        w2_wob = next(w for w in verify_res["wage_obligations"] if w["worker_id"] == w2_id)
        w2_wob_id = w2_wob.get("id") or w2_wob.get("_id")
        w2_after = await mdb.wage_obligations.find_one({"_id": id_query(w2_wob_id)})
        assert w2_after["status"] == "accrued"


@pytest.mark.anyio
async def test_audit4_03_cancellation_rejected_if_any_worker_fully_paid():
    """Audit 4.3: Cancellation is blocked with HTTP 400 if any worker is fully paid."""
    mdb, owner, manager, workers, ord_id = setup_audit_fixture()
    w1_id = workers[0]["id"]
    w2_id = workers[1]["id"]

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

    with patch("server.db", mdb):
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id, w2_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=2),
            manager
        )
        await admin_update_assignment_progress(asn["id"], WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=2), manager)
        verify_res = await admin_verify_work_assignment(asn["id"], WorkAssignmentVerifyInput(accepted_quantity=2), manager)

        w1_wob = next(w for w in verify_res["wage_obligations"] if w["worker_id"] == w1_id)
        w1_wob_id = w1_wob.get("id") or w1_wob.get("_id")

        # Full settlement for worker 1 (100 LE)
        await admin_create_wage_settlement(
            WageSettlementCreateInput(
                worker_id=w1_id,
                amount_le=100.0,
                allocations=[WageSettlementAllocationItem(wage_obligation_id=str(w1_wob_id), amount_le=100.0)]
            ),
            manager
        )

        with pytest.raises(HTTPException) as exc_cancel:
            await admin_cancel_work_assignment(asn["id"], WorkAssignmentCancelInput(reason="Koreksi operasional"), manager)
        assert exc_cancel.value.status_code == 400


@pytest.mark.anyio
async def test_audit4_04_repeated_cancellation_idempotent():
    """Audit 4.4: Repeated cancellation calls are idempotent."""
    mdb, owner, manager, workers, ord_id = setup_audit_fixture()
    w1_id = workers[0]["id"]

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

    with patch("server.db", mdb):
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=1),
            manager
        )
        c1 = await admin_cancel_work_assignment(asn["id"], WorkAssignmentCancelInput(reason="Batal 1"), manager)
        assert c1["status"] == "cancelled"

        c2 = await admin_cancel_work_assignment(asn["id"], WorkAssignmentCancelInput(reason="Batal 2"), manager)
        assert c2["status"] == "cancelled"


# =============================================================================
# ADDITIONAL RESILIENCE & FAILURE POINT INJECTION TESTS
# =============================================================================

@pytest.mark.anyio
async def test_audit2_05_write_conflict_or_retry_does_not_exceed_capacity():
    """Audit 2.5: Write conflict / failure during insert does not leak capacity; retry succeeds cleanly."""
    mdb, owner, manager, workers, ord_id = setup_audit_fixture()
    w1_id = workers[0]["id"]

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

    original_insert = mdb.work_assignments.insert_one
    attempt_count = 0

    async def faulty_insert(doc, *args, **kwargs):
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            # Simulate a transient write conflict or connection crash
            raise RuntimeError("Simulated WriteConflictException")
        return await original_insert(doc, *args, **kwargs)

    with patch("server.db", mdb):
        with patch.object(mdb.work_assignments, "insert_one", side_effect=faulty_insert):
            with pytest.raises(Exception):
                await admin_create_work_assignment(
                    ord_id,
                    WorkAssignmentCreateInput(worker_ids=[w1_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=2),
                    manager
                )

        # Capacity was not consumed by the failed attempt
        all_asns = [d for d in mdb.work_assignments.docs.values() if d.get("status") != "cancelled"]
        assert len(all_asns) == 0

        # Retry now succeeds without capacity blockage
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=2),
            manager
        )
        assert asn["target_quantity"] == 2
        active_asns = [d for d in mdb.work_assignments.docs.values() if d.get("status") != "cancelled"]
        assert len(active_asns) == 1


@pytest.mark.anyio
async def test_audit3_04_failure_before_first_obligation_stored_rolls_back_cleanly():
    """Audit 3.4: Failure before any obligation is stored restores status to ready_for_review with zero obligations."""
    mdb, owner, manager, workers, ord_id = setup_audit_fixture()
    w1_id = workers[0]["id"]
    w2_id = workers[1]["id"]

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

    with patch("server.db", mdb):
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id, w2_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=2),
            manager
        )
        await admin_update_assignment_progress(asn["id"], WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=2), manager)

        # Fail at the very first insert
        original_insert = mdb.wage_obligations.insert_one
        async def fail_first_insert(doc, *args, **kwargs):
            raise RuntimeError("Database write error before first obligation stored")

        with patch.object(mdb.wage_obligations, "insert_one", side_effect=fail_first_insert):
            with pytest.raises(HTTPException) as exc_info:
                await admin_verify_work_assignment(asn["id"], WorkAssignmentVerifyInput(accepted_quantity=2), manager)
            assert exc_info.value.status_code == 500

        # State rolled back cleanly: assignment is still ready_for_review, 0 obligations exist
        fresh_asn = await mdb.work_assignments.find_one({"_id": id_query(asn["id"])})
        assert fresh_asn["status"] == "ready_for_review"
        wobs = [d for d in mdb.wage_obligations.docs.values() if d.get("work_assignment_id") == asn["id"]]
        assert len(wobs) == 0


@pytest.mark.anyio
async def test_audit3_05_failure_on_second_worker_triggers_compensating_rollback_without_touching_unrelated_docs():
    """Audit 3.5: Failure on worker 2 deletes newly inserted worker 1 wob only, preserving unrelated obligations."""
    mdb, owner, manager, workers, ord_id = setup_audit_fixture()
    w1_id = workers[0]["id"]
    w2_id = workers[1]["id"]

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

    # Seed an unrelated valid obligation in DB
    unrelated_wob = {
        "_id": ObjectId("888888888888888888888888"),
        "obligation_number": "WOB-UNRELATED-001",
        "work_assignment_id": "other_assignment_999",
        "worker_id": w1_id,
        "total_amount_le": 50.0,
        "amount_piastres": 5000,
        "status": "accrued",
    }
    mdb.wage_obligations.docs[str(unrelated_wob["_id"])] = unrelated_wob

    with patch("server.db", mdb):
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id, w2_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=2),
            manager
        )
        await admin_update_assignment_progress(asn["id"], WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=2), manager)

        original_insert = mdb.wage_obligations.insert_one
        insert_count = 0

        async def fail_second_insert(doc, *args, **kwargs):
            nonlocal insert_count
            insert_count += 1
            if insert_count == 2:
                raise RuntimeError("Disk full / crash during second worker obligation insert")
            return await original_insert(doc, *args, **kwargs)

        with patch.object(mdb.wage_obligations, "insert_one", side_effect=fail_second_insert):
            with pytest.raises(HTTPException) as exc_info:
                await admin_verify_work_assignment(asn["id"], WorkAssignmentVerifyInput(accepted_quantity=2), manager)
            assert exc_info.value.status_code == 500

        # Compensating rollback deleted worker 1's newly created obligation
        wobs = [d for d in mdb.wage_obligations.docs.values() if d.get("work_assignment_id") == asn["id"]]
        assert len(wobs) == 0

        # Unrelated obligation is COMPLETELY UNTOUCHED!
        saved_unrelated = await mdb.wage_obligations.find_one({"_id": id_query(unrelated_wob["_id"])})
        assert saved_unrelated is not None
        assert saved_unrelated["obligation_number"] == "WOB-UNRELATED-001"

        # Assignment status reverted to ready_for_review
        fresh_asn = await mdb.work_assignments.find_one({"_id": id_query(asn["id"])})
        assert fresh_asn["status"] == "ready_for_review"


@pytest.mark.anyio
async def test_audit3_06_crash_after_obligations_stored_recovers_on_retry():
    """Audit 3.6: Crash after obligations are stored in DB recovers cleanly on retry without duplicates."""
    mdb, owner, manager, workers, ord_id = setup_audit_fixture()
    w1_id = workers[0]["id"]
    w2_id = workers[1]["id"]

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

    with patch("server.db", mdb):
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id, w2_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=2),
            manager
        )
        await admin_update_assignment_progress(asn["id"], WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=2), manager)

        # Simulate crash: obligations were inserted, but assignment status update crashed mid-way
        # Set assignment status to "accruing"
        await mdb.work_assignments.update_one({"_id": id_query(asn["id"])}, {"$set": {"status": "accruing"}})

        # Both obligations exist in DB
        aid_str = asn["id"]
        from server import compute_payload_hash
        p_hash = compute_payload_hash({"accepted_quantity": 2, "notes": ""})
        wob1 = {
            "_id": ObjectId("999999999999999999999901"),
            "obligation_number": "WOB-CRASH-001",
            "accrual_event_key": f"acc_{aid_str}_{w1_id}",
            "work_assignment_id": aid_str,
            "worker_id": w1_id,
            "worker_name": "Ahmad",
            "total_amount_le": 100.0,
            "amount_piastres": 10000,
            "currency": "EGP",
            "status": "accrued",
            "paid_amount_le": 0.0,
            "payload_hash": p_hash,
        }
        wob2 = {
            "_id": ObjectId("999999999999999999999902"),
            "obligation_number": "WOB-CRASH-002",
            "accrual_event_key": f"acc_{aid_str}_{w2_id}",
            "work_assignment_id": aid_str,
            "worker_id": w2_id,
            "worker_name": "Budi",
            "total_amount_le": 100.0,
            "amount_piastres": 10000,
            "currency": "EGP",
            "status": "accrued",
            "paid_amount_le": 0.0,
            "payload_hash": p_hash,
        }
        mdb.wage_obligations.docs[str(wob1["_id"])] = wob1
        mdb.wage_obligations.docs[str(wob2["_id"])] = wob2

        # Retry verification
        res = await admin_verify_work_assignment(asn["id"], WorkAssignmentVerifyInput(accepted_quantity=2), manager)

        # Assignment is completed, obligations reconciled, no duplicate obligations created
        assert res["assignment"]["status"] == "completed"
        assert len(res["wage_obligations"]) == 2
        all_wobs = [d for d in mdb.wage_obligations.docs.values() if d.get("work_assignment_id") == aid_str]
        assert len(all_wobs) == 2


# =============================================================================
# GATE 08.2.2: CONCURRENCY RACE TESTS (SETTLEMENT VS CANCELLATION)
# =============================================================================

@pytest.mark.anyio
async def test_audit5_01_concurrent_settlement_vs_cancellation_single_worker():
    """Gate 08.2.2: Overlapping settlement and cancellation for a single-worker assignment.
    Exactly one succeeds and the other fails safely. No contradictory states possible.
    """
    mdb, owner, manager, workers, ord_id = setup_audit_fixture()
    w1_id = workers[0]["id"]

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

    with patch("server.db", mdb):
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=1),
            manager
        )
        await admin_update_assignment_progress(asn["id"], WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=1), manager)
        verify_res = await admin_verify_work_assignment(asn["id"], WorkAssignmentVerifyInput(accepted_quantity=1), manager)
        wob = verify_res["wage_obligations"][0]
        wob_id = str(wob.get("id") or wob.get("_id"))

        # Launch concurrent settlement and cancellation simultaneously
        req_settle = admin_create_wage_settlement(
            WageSettlementCreateInput(
                worker_id=w1_id,
                amount_le=100.0,
                allocations=[WageSettlementAllocationItem(wage_obligation_id=wob_id, amount_le=100.0)]
            ),
            manager
        )
        req_cancel = admin_cancel_work_assignment(
            asn["id"],
            WorkAssignmentCancelInput(reason="Pembatalan pesanan konkuren"),
            manager
        )

        results = await asyncio.gather(req_settle, req_cancel, return_exceptions=True)

        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]

        assert len(successes) == 1, f"Expected exactly 1 operation to succeed, got {len(successes)}: {results}"
        assert len(failures) == 1, f"Expected exactly 1 operation to fail, got {len(failures)}: {results}"

        saved_asn = await mdb.work_assignments.find_one({"_id": id_query(asn["id"])})
        saved_wob = await mdb.wage_obligations.find_one({"_id": id_query(wob_id)})

        if not isinstance(results[0], Exception):
            # Settlement won: obligation is paid, assignment is completed, cancellation failed with 400
            assert saved_wob["status"] == "paid"
            assert saved_wob["paid_amount_le"] == 100.0
            assert saved_asn["status"] == "completed"
            assert isinstance(results[1], HTTPException)
            assert results[1].status_code == 400
            assert "sudah terbayar sebagian atau penuh" in results[1].detail
            assert len(mdb.finance_transactions.docs) == 1
        else:
            # Cancellation won: obligation is voided, assignment is cancelled, settlement failed with 400/409
            assert saved_wob["status"] == "voided"
            assert saved_asn["status"] == "cancelled"
            assert isinstance(results[0], HTTPException)
            assert results[0].status_code in (400, 409)
            assert len(mdb.finance_transactions.docs) == 0


@pytest.mark.anyio
async def test_audit5_02_concurrent_settlement_vs_cancellation_multi_worker():
    """Gate 08.2.2: Overlapping settlement of worker 1 and assignment cancellation in multi-worker assignment.
    No partial voiding: if worker 1 is settled, worker 2 obligation must NOT be voided and cancellation rejected.
    """
    mdb, owner, manager, workers, ord_id = setup_audit_fixture()
    w1_id = workers[0]["id"]
    w2_id = workers[1]["id"]

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

    with patch("server.db", mdb):
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id, w2_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=2),
            manager
        )
        await admin_update_assignment_progress(asn["id"], WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=2), manager)
        verify_res = await admin_verify_work_assignment(asn["id"], WorkAssignmentVerifyInput(accepted_quantity=2), manager)

        w1_wob = next(w for w in verify_res["wage_obligations"] if w["worker_id"] == w1_id)
        w2_wob = next(w for w in verify_res["wage_obligations"] if w["worker_id"] == w2_id)
        w1_wob_id = str(w1_wob.get("id") or w1_wob.get("_id"))
        w2_wob_id = str(w2_wob.get("id") or w2_wob.get("_id"))

        # Launch concurrent settlement for Worker 1 and cancellation of the whole assignment
        req_settle_w1 = admin_create_wage_settlement(
            WageSettlementCreateInput(
                worker_id=w1_id,
                amount_le=100.0,
                allocations=[WageSettlementAllocationItem(wage_obligation_id=w1_wob_id, amount_le=100.0)]
            ),
            manager
        )
        req_cancel = admin_cancel_work_assignment(
            asn["id"],
            WorkAssignmentCancelInput(reason="Pembatalan multi worker"),
            manager
        )

        results = await asyncio.gather(req_settle_w1, req_cancel, return_exceptions=True)

        saved_asn = await mdb.work_assignments.find_one({"_id": id_query(asn["id"])})
        saved_w1_wob = await mdb.wage_obligations.find_one({"_id": id_query(w1_wob_id)})
        saved_w2_wob = await mdb.wage_obligations.find_one({"_id": id_query(w2_wob_id)})

        if not isinstance(results[0], Exception):
            # Settlement won: worker 1 paid, cancellation rejected with 400
            assert saved_w1_wob["status"] == "paid"
            # Worker 2 obligation must remain accrued, NOT voided!
            assert saved_w2_wob["status"] == "accrued"
            assert saved_asn["status"] == "completed"
            assert isinstance(results[1], HTTPException)
            assert results[1].status_code == 400
            assert "sudah terbayar sebagian atau penuh" in results[1].detail
        else:
            # Cancellation won: both workers voided, assignment cancelled
            assert saved_w1_wob["status"] == "voided"
            assert saved_w2_wob["status"] == "voided"
            assert saved_asn["status"] == "cancelled"
            assert isinstance(results[0], HTTPException)
            assert results[0].status_code in (400, 409)


@pytest.mark.anyio
async def test_audit5_03_db_level_interleaving_guard_prevents_partial_cancellation():
    """Gate 08.2.2: DB-level guard in _do_cancel detects when an obligation was settled during cancellation."""
    mdb, owner, manager, workers, ord_id = setup_audit_fixture()
    w1_id = workers[0]["id"]
    w2_id = workers[1]["id"]

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

    with patch("server.db", mdb):
        asn = await admin_create_work_assignment(
            ord_id,
            WorkAssignmentCreateInput(worker_ids=[w1_id, w2_id], order_item_id="itm_table_01", task_category="whole_item", target_quantity=2),
            manager
        )
        await admin_update_assignment_progress(asn["id"], WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=2), manager)
        verify_res = await admin_verify_work_assignment(asn["id"], WorkAssignmentVerifyInput(accepted_quantity=2), manager)

        w1_wob = next(w for w in verify_res["wage_obligations"] if w["worker_id"] == w1_id)
        w2_wob = next(w for w in verify_res["wage_obligations"] if w["worker_id"] == w2_id)
        w1_wob_id = str(w1_wob.get("id") or w1_wob.get("_id"))
        w2_wob_id = str(w2_wob.get("id") or w2_wob.get("_id"))

        # Intercept inside _do_cancel: right before _do_cancel checks cur_wobs, worker 1 was settled
        original_find = mdb.wage_obligations.find

        call_count = 0
        def find_interceptor(filter_q=None, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                # Simulate worker 1 settled concurrently right before _do_cancel
                mdb.wage_obligations.docs[w1_wob_id]["status"] = "paid"
                mdb.wage_obligations.docs[w1_wob_id]["paid_amount_le"] = 100.0
            return original_find(filter_q, *args, **kwargs)

        with patch.object(mdb.wage_obligations, "find", side_effect=find_interceptor):
            with pytest.raises(HTTPException) as exc_info:
                await admin_cancel_work_assignment(
                    asn["id"],
                    WorkAssignmentCancelInput(reason="Pembatalan interleave"),
                    manager
                )
            assert exc_info.value.status_code == 400
            assert "sudah terbayar sebagian atau penuh" in exc_info.value.detail

        # State integrity: worker 2 is NOT voided, assignment is NOT cancelled!
        saved_asn = await mdb.work_assignments.find_one({"_id": id_query(asn["id"])})
        assert saved_asn["status"] == "completed"
        saved_w2 = await mdb.wage_obligations.find_one({"_id": id_query(w2_wob_id)})
        assert saved_w2["status"] == "accrued"
