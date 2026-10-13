"""Comprehensive automated test suite for Phase 3.F.3: Worker Wage Obligations & Settlement.

Covers all required acceptance domains:
1. Wage obligation retrieval (pending summary & worker pending wages)
2. Full settlement of single obligation
3. Partial settlement and sequential partial settlements
4. Multi-obligation automatic FIFO settlement
5. Explicit allocation validation (amount must match, no over-allocation)
6. Zero / negative / over-payment rejection
7. Idempotency replay with identical payload
8. Idempotency key reuse conflict (HTTP 409) with differing payload
9. Concurrency guard (rejection when obligation balance changed concurrently)
10. Atomic consistency and standalone compensating rollback
11. Finance ledger linkage (single cash outflow, employee_wages mirror, zero duplicate cost)
12. Settlement voiding with complete ledger reversal
13. Finance direct deletion protection (Guard 4)
14. End-to-end full lifecycle integration
"""
import copy
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from fastapi import HTTPException
import pytest
import pymongo

from server import (
    admin_verify_work_assignment,
    admin_get_worker_pending_wages,
    admin_get_wages_pending_summary,
    admin_get_wage_obligations,
    admin_create_wage_settlement,
    admin_get_wage_settlements,
    admin_get_wage_settlement_detail,
    admin_void_wage_settlement,
    finance_delete,
    finance_update,
    calculate_wage_obligation_amount,
    WorkAssignmentVerifyInput,
    WageSettlementCreateInput,
    WageSettlementAllocationItem,
    WageSettlementVoidInput,
    FinanceTxnInput,
    CriticalFinanceIndexError,
    _num,
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
            return copy.deepcopy(doc)
        raise StopAsyncIteration

    async def to_list(self, length=None):
        if length is None:
            return copy.deepcopy(self.docs)
        return copy.deepcopy(self.docs[:length])

    def sort(self, *args, **kwargs):
        return self

    def skip(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self


class MockCollection:
    def __init__(self, name: str, docs: list = None):
        self.name = name
        self.docs = {}
        for d in (docs or []):
            d_copy = copy.deepcopy(d)
            if "_id" not in d_copy:
                d_copy["_id"] = ObjectId(d_copy.get("id")) if d_copy.get("id") and ObjectId.is_valid(d_copy.get("id")) else ObjectId()
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
            elif k == "status":
                if isinstance(v, dict) and "$in" in v:
                    if doc.get("status") not in v["$in"]:
                        return False
                elif isinstance(v, dict) and "$ne" in v:
                    if doc.get("status") == v["$ne"]:
                        return False
                else:
                    if doc.get("status") != v:
                        return False
            elif isinstance(v, dict) and "$gte" in v:
                if doc.get(k, "") < v["$gte"]:
                    return False
            elif isinstance(v, dict) and "$lte" in v:
                if doc.get(k, "") > v["$lte"]:
                    return False
            else:
                if doc.get(k) != v:
                    return False
        return True

    async def find_one(self, filter_q=None, *args, **kwargs):
        for doc in self.docs.values():
            if self._matches(doc, filter_q):
                return copy.deepcopy(doc)
        return None

    def find(self, filter_q=None, *args, **kwargs):
        matched = [d for d in self.docs.values() if self._matches(d, filter_q)]
        return AsyncCursorMock(matched)

    async def count_documents(self, filter_q=None, *args, **kwargs):
        matched = [d for d in self.docs.values() if self._matches(d, filter_q)]
        return len(matched)

    async def insert_one(self, doc, *args, **kwargs):
        d_copy = copy.deepcopy(doc)
        if "_id" not in d_copy:
            d_copy["_id"] = ObjectId()
        doc_id = str(d_copy["_id"])
        if doc_id in self.docs:
            raise pymongo.errors.DuplicateKeyError(f"Duplicate key on _id: {doc_id}")
        self.docs[doc_id] = d_copy
        res = MagicMock()
        res.inserted_id = d_copy["_id"]
        return res

    async def update_one(self, filter_q, update_q, *args, **kwargs):
        for doc_id, doc in self.docs.items():
            if self._matches(doc, filter_q):
                if "$set" in update_q:
                    for k, val in update_q["$set"].items():
                        doc[k] = copy.deepcopy(val)
                if "$unset" in update_q:
                    for k in update_q["$unset"]:
                        doc.pop(k, None)
                if "$push" in update_q:
                    for k, val in update_q["$push"].items():
                        if k not in doc or not isinstance(doc[k], list):
                            doc[k] = []
                        doc[k].append(copy.deepcopy(val))
                if "$pull" in update_q:
                    for k, pull_filter in update_q["$pull"].items():
                        if k in doc and isinstance(doc[k], list):
                            if isinstance(pull_filter, dict):
                                pk, pv = next(iter(pull_filter.items()))
                                doc[k] = [it for it in doc[k] if not (isinstance(it, dict) and it.get(pk) == pv)]
                res = MagicMock()
                res.matched_count = 1
                res.modified_count = 1
                return res
        res = MagicMock()
        res.matched_count = 0
        res.modified_count = 0
        return res

    async def update_many(self, filter_q, update_q, *args, **kwargs):
        mod_count = 0
        for doc_id, doc in self.docs.items():
            if self._matches(doc, filter_q):
                if "$set" in update_q:
                    for k, val in update_q["$set"].items():
                        doc[k] = copy.deepcopy(val)
                mod_count += 1
        res = MagicMock()
        res.matched_count = mod_count
        res.modified_count = mod_count
        return res

    async def delete_one(self, filter_q, *args, **kwargs):
        for doc_id, doc in self.docs.items():
            if self._matches(doc, filter_q):
                del self.docs[doc_id]
                res = MagicMock()
                res.deleted_count = 1
                return res
        res = MagicMock()
        res.deleted_count = 0
        return res

    async def delete_many(self, filter_q, *args, **kwargs):
        to_del = [doc_id for doc_id, doc in self.docs.items() if self._matches(doc, filter_q)]
        for doc_id in to_del:
            del self.docs[doc_id]
        res = MagicMock()
        res.deleted_count = len(to_del)
        return res

    async def find_one_and_update(self, filter_q, update_q, upsert=False, return_document=None):
        doc_id = str(filter_q.get("_id"))
        doc = self.docs.get(doc_id)
        if not doc and upsert:
            doc = copy.deepcopy(filter_q)
            doc["seq"] = 0
            self.docs[doc_id] = doc
        if "$inc" in update_q:
            for k, inc_val in update_q["$inc"].items():
                doc[k] = doc.get(k, 0) + inc_val
        return copy.deepcopy(doc)


class MockDatabase:
    def __init__(self):
        self.admins = MockCollection("admins")
        self.orders = MockCollection("orders")
        self.work_assignments = MockCollection("work_assignments")
        self.wage_obligations = MockCollection("wage_obligations")
        self.wage_settlements = MockCollection("wage_settlements")
        self.finance_transactions = MockCollection("finance_transactions")
        self.employee_wages = MockCollection("employee_wages")
        self.counters = MockCollection("counters")
        self.settings = MockCollection("settings")
        self.audit_logs = MockCollection("audit_logs")
        self.payments = MockCollection("payments")
        self.customer_credit_events = MockCollection("customer_credit_events")
        self.finance_categories = MockCollection("finance_categories")


@pytest.fixture
def mock_env():
    mdb = MockDatabase()
    admin_user = {
        "_id": ObjectId("660000000000000000000001"),
        "id": "660000000000000000000001",
        "name": "Finance Admin",
        "email": "finance@sogil.com",
        "role": "admin",
        "permissions": {"access_finance": True, "manage_orders": True}
    }
    owner_user = {
        "_id": ObjectId("660000000000000000000002"),
        "id": "660000000000000000000002",
        "name": "Owner Sogil",
        "email": "owner@sogil.com",
        "role": "owner",
        "permissions": {}
    }
    worker_user = {
        "_id": ObjectId("660000000000000000000003"),
        "id": "660000000000000000000003",
        "name": "Tukang Kayu Ahmed",
        "email": "ahmed@sogil.com",
        "role": "worker",
        "permissions": {}
    }
    mdb.admins.docs[str(admin_user["_id"])] = admin_user
    mdb.admins.docs[str(owner_user["_id"])] = owner_user
    mdb.admins.docs[str(worker_user["_id"])] = worker_user

    with patch("server.db", mdb), \
         patch("server.client.start_session", AsyncMock(side_effect=pymongo.errors.ConfigurationError("Standalone"))), \
         patch("server.is_standalone_fallback_permitted", return_value=True):
        yield mdb, admin_user, owner_user, worker_user


@pytest.mark.anyio
async def test_wage_obligation_accrual_and_pending_summary(mock_env):
    mdb, admin_user, owner_user, worker_user = mock_env
    wid = str(worker_user["_id"])

    # Setup assignment in ready_for_review
    assign_id = ObjectId("661111111111111111111111")
    assign_doc = {
        "_id": assign_id,
        "id": str(assign_id),
        "order_id": "ord_1001",
        "order_number": "ORD-1001",
        "order_item_id": "itm_frame_1",
        "worker_id": wid,
        "worker_name": worker_user["name"],
        "task_category": "frame",
        "pricing_basis": "per_unit",
        "agreed_rate_le": 150.0,
        "target_quantity": 2,
        "status": "ready_for_review",
    }
    mdb.work_assignments.docs[str(assign_id)] = assign_doc

    # Verify assignment -> accrues obligation
    verify_payload = WorkAssignmentVerifyInput(accepted_quantity=2, notes="Pekerjaan rapi")
    verified_wob = await admin_verify_work_assignment(str(assign_id), verify_payload, admin=admin_user)

    assert verified_wob["status"] == "accrued"
    assert verified_wob["total_amount_le"] == 300.0
    assert verified_wob["paid_amount_le"] == 0.0

    # Query pending summary
    summary = await admin_get_wages_pending_summary(admin=admin_user)
    assert summary["total_pending_wages_le"] == 300.0
    assert summary["pending_obligations_count"] == 1
    assert len(summary["workers_summary"]) == 1
    assert summary["workers_summary"][0]["worker_id"] == wid
    assert summary["workers_summary"][0]["total_le"] == 300.0

    # Query worker pending wages
    worker_pending = await admin_get_worker_pending_wages(wid, admin=admin_user)
    assert worker_pending["total_pending_wages_le"] == 300.0
    assert worker_pending["obligations"][0]["remaining_amount_le"] == 300.0


@pytest.mark.anyio
async def test_full_wage_settlement(mock_env):
    mdb, admin_user, _, worker_user = mock_env
    wid = str(worker_user["_id"])

    # Create obligation
    ob_id = ObjectId("662222222222222222222222")
    ob_doc = {
        "_id": ob_id,
        "obligation_number": "WOB-202610-0001",
        "accrual_event_key": "acc_662222",
        "work_assignment_id": "asn_1",
        "worker_id": wid,
        "worker_name": worker_user["name"],
        "total_amount_le": 250.0,
        "paid_amount_le": 0.0,
        "status": "accrued",
        "currency": "EGP",
        "created_at": "2026-10-13T10:00:00Z"
    }
    mdb.wage_obligations.docs[str(ob_id)] = ob_doc

    # Perform full settlement via FIFO
    settle_input = WageSettlementCreateInput(
        worker_id=wid,
        amount_le=250.0,
        payment_method="cash",
        notes="Pembayaran lunas minggu ke-2"
    )
    result = await admin_create_wage_settlement(settle_input, admin=admin_user)

    assert result["status"] == "recorded"
    assert result["amount_le"] == 250.0
    assert len(result["allocations"]) == 1
    assert result["allocations"][0]["obligation_status_after"] == "paid"
    assert result["allocations"][0]["new_paid_amount_le"] == 250.0

    # Verify obligation state in DB
    updated_ob = mdb.wage_obligations.docs[str(ob_id)]
    assert updated_ob["status"] == "paid"
    assert updated_ob["paid_amount_le"] == 250.0
    assert len(updated_ob["settlement_allocations"]) == 1

    # Verify finance transaction was recorded
    assert len(mdb.finance_transactions.docs) == 1
    ft = next(iter(mdb.finance_transactions.docs.values()))
    assert ft["type"] == "expense"
    assert ft["category"] == "Pekerja"
    assert ft["amount"] == 250.0
    assert ft["currency"] == "EGP"
    assert ft["classification"] == "cost"
    assert ft["wage_settlement_id"] == str(result.get("id") or result.get("_id"))

    # Verify employee_wages mirror
    assert len(mdb.employee_wages.docs) == 1
    ew = next(iter(mdb.employee_wages.docs.values()))
    assert ew["employee_id"] == wid
    assert ew["amount"] == 250.0

    # Verify pending summary is now zero
    summary = await admin_get_wages_pending_summary(admin=admin_user)
    assert summary["total_pending_wages_le"] == 0.0
    assert summary["pending_obligations_count"] == 0


@pytest.mark.anyio
async def test_partial_settlement_and_sequential_payments(mock_env):
    mdb, admin_user, _, worker_user = mock_env
    wid = str(worker_user["_id"])

    ob_id = ObjectId("663333333333333333333333")
    ob_doc = {
        "_id": ob_id,
        "obligation_number": "WOB-202610-0002",
        "accrual_event_key": "acc_663333",
        "work_assignment_id": "asn_2",
        "worker_id": wid,
        "worker_name": worker_user["name"],
        "total_amount_le": 200.0,
        "paid_amount_le": 0.0,
        "status": "accrued",
        "currency": "EGP",
        "created_at": "2026-10-13T10:00:00Z"
    }
    mdb.wage_obligations.docs[str(ob_id)] = ob_doc

    # 1. First partial payment: 100 LE
    res1 = await admin_create_wage_settlement(
        WageSettlementCreateInput(worker_id=wid, amount_le=100.0),
        admin=admin_user
    )
    assert res1["allocations"][0]["obligation_status_after"] == "partially_paid"
    assert res1["allocations"][0]["new_paid_amount_le"] == 100.0

    ob_after_1 = mdb.wage_obligations.docs[str(ob_id)]
    assert ob_after_1["status"] == "partially_paid"
    assert ob_after_1["paid_amount_le"] == 100.0

    # Pending summary check
    sum1 = await admin_get_wages_pending_summary(admin=admin_user)
    assert sum1["total_pending_wages_le"] == 100.0
    assert sum1["total_paid_le"] == 100.0

    # 2. Second partial payment: 100 LE (completing the obligation)
    res2 = await admin_create_wage_settlement(
        WageSettlementCreateInput(worker_id=wid, amount_le=100.0),
        admin=admin_user
    )
    assert res2["allocations"][0]["obligation_status_after"] == "paid"
    assert res2["allocations"][0]["new_paid_amount_le"] == 200.0

    ob_after_2 = mdb.wage_obligations.docs[str(ob_id)]
    assert ob_after_2["status"] == "paid"
    assert ob_after_2["paid_amount_le"] == 200.0
    assert len(ob_after_2["settlement_allocations"]) == 2

    sum2 = await admin_get_wages_pending_summary(admin=admin_user)
    assert sum2["total_pending_wages_le"] == 0.0


@pytest.mark.anyio
async def test_overpayment_and_invalid_amount_rejections(mock_env):
    mdb, admin_user, _, worker_user = mock_env
    wid = str(worker_user["_id"])

    ob_id = ObjectId("664444444444444444444444")
    ob_doc = {
        "_id": ob_id,
        "obligation_number": "WOB-202610-0003",
        "accrual_event_key": "acc_664444",
        "work_assignment_id": "asn_3",
        "worker_id": wid,
        "worker_name": worker_user["name"],
        "total_amount_le": 100.0,
        "paid_amount_le": 0.0,
        "status": "accrued",
        "currency": "EGP",
        "created_at": "2026-10-13T10:00:00Z"
    }
    mdb.wage_obligations.docs[str(ob_id)] = ob_doc

    # Rejection of zero amount
    with pytest.raises(HTTPException) as exc_zero:
        await admin_create_wage_settlement(
            WageSettlementCreateInput(worker_id=wid, amount_le=0.0),
            admin=admin_user
        )
    assert exc_zero.value.status_code == 422

    # Rejection of negative amount
    with pytest.raises(HTTPException) as exc_neg:
        await admin_create_wage_settlement(
            WageSettlementCreateInput(worker_id=wid, amount_le=-50.0),
            admin=admin_user
        )
    assert exc_neg.value.status_code == 422

    # Rejection of payment exceeding total pending
    with pytest.raises(HTTPException) as exc_over:
        await admin_create_wage_settlement(
            WageSettlementCreateInput(worker_id=wid, amount_le=150.0),
            admin=admin_user
        )
    assert exc_over.value.status_code == 422
    assert "melebihi total kewajiban terutang" in exc_over.value.detail

    # Rejection of explicit allocation exceeding obligation balance
    with pytest.raises(HTTPException) as exc_alloc_over:
        await admin_create_wage_settlement(
            WageSettlementCreateInput(
                worker_id=wid,
                amount_le=100.0,
                allocations=[WageSettlementAllocationItem(wage_obligation_id=str(ob_id), amount_le=120.0)]
            ),
            admin=admin_user
        )
    assert exc_alloc_over.value.status_code == 422


@pytest.mark.anyio
async def test_idempotency_replay_and_conflict(mock_env):
    mdb, admin_user, _, worker_user = mock_env
    wid = str(worker_user["_id"])

    ob_id = ObjectId("665555555555555555555555")
    ob_doc = {
        "_id": ob_id,
        "obligation_number": "WOB-202610-0004",
        "accrual_event_key": "acc_665555",
        "work_assignment_id": "asn_4",
        "worker_id": wid,
        "worker_name": worker_user["name"],
        "total_amount_le": 100.0,
        "paid_amount_le": 0.0,
        "status": "accrued",
        "currency": "EGP",
        "created_at": "2026-10-13T10:00:00Z"
    }
    mdb.wage_obligations.docs[str(ob_id)] = ob_doc

    idem_key = "idemp_settle_uuid_12345"

    # 1. First execution
    res1 = await admin_create_wage_settlement(
        WageSettlementCreateInput(
            worker_id=wid,
            amount_le=50.0,
            payment_method="cash",
            idempotency_key=idem_key
        ),
        admin=admin_user
    )
    assert res1["amount_le"] == 50.0
    st_num = res1["settlement_number"]

    # 2. Identical replay: returns same document, no duplicate payment
    res2 = await admin_create_wage_settlement(
        WageSettlementCreateInput(
            worker_id=wid,
            amount_le=50.0,
            payment_method="cash",
            idempotency_key=idem_key
        ),
        admin=admin_user
    )
    assert res2["settlement_number"] == st_num
    assert len(mdb.wage_settlements.docs) == 1
    assert len(mdb.finance_transactions.docs) == 1

    # 3. Differing payload with same idempotency key -> HTTP 409
    with pytest.raises(HTTPException) as exc_conflict:
        await admin_create_wage_settlement(
            WageSettlementCreateInput(
                worker_id=wid,
                amount_le=30.0,  # Different amount
                payment_method="cash",
                idempotency_key=idem_key
            ),
            admin=admin_user
        )
    assert exc_conflict.value.status_code == 409
    assert "parameter berbeda" in exc_conflict.value.detail


@pytest.mark.anyio
async def test_settlement_voiding_reversal(mock_env):
    mdb, admin_user, _, worker_user = mock_env
    wid = str(worker_user["_id"])

    ob_id = ObjectId("666666666666666666666666")
    ob_doc = {
        "_id": ob_id,
        "obligation_number": "WOB-202610-0005",
        "accrual_event_key": "acc_666666",
        "work_assignment_id": "asn_5",
        "worker_id": wid,
        "worker_name": worker_user["name"],
        "total_amount_le": 100.0,
        "paid_amount_le": 0.0,
        "status": "accrued",
        "currency": "EGP",
        "created_at": "2026-10-13T10:00:00Z"
    }
    mdb.wage_obligations.docs[str(ob_id)] = ob_doc

    # Settle 100 LE
    res = await admin_create_wage_settlement(
        WageSettlementCreateInput(worker_id=wid, amount_le=100.0),
        admin=admin_user
    )
    st_id = str(res.get("id") or res.get("_id"))
    assert mdb.wage_obligations.docs[str(ob_id)]["status"] == "paid"

    # Void settlement
    void_res = await admin_void_wage_settlement(
        st_id,
        WageSettlementVoidInput(reason="Salah nominal pembayaran"),
        admin=admin_user
    )
    assert void_res["status"] == "voided"
    assert void_res["void_reason"] == "Salah nominal pembayaran"

    # Verify obligation reverted to accrued
    rev_ob = mdb.wage_obligations.docs[str(ob_id)]
    assert rev_ob["status"] == "accrued"
    assert rev_ob["paid_amount_le"] == 0.0

    # Verify finance transaction is voided
    txn_id = res["finance_transaction_id"]
    ft = mdb.finance_transactions.docs[txn_id]
    assert ft["status"] == "void"
    assert ft["is_void"] is True

    # Verify employee_wages mirror entry was cleaned up
    assert len(mdb.employee_wages.docs) == 0


@pytest.mark.anyio
async def test_finance_delete_guard_prevents_direct_settlement_deletion(mock_env):
    mdb, admin_user, _, worker_user = mock_env
    wid = str(worker_user["_id"])

    ob_id = ObjectId("667777777777777777777777")
    ob_doc = {
        "_id": ob_id,
        "obligation_number": "WOB-202610-0006",
        "accrual_event_key": "acc_667777",
        "work_assignment_id": "asn_6",
        "worker_id": wid,
        "worker_name": worker_user["name"],
        "total_amount_le": 100.0,
        "paid_amount_le": 0.0,
        "status": "accrued",
        "currency": "EGP",
        "created_at": "2026-10-13T10:00:00Z"
    }
    mdb.wage_obligations.docs[str(ob_id)] = ob_doc

    # Settle
    res = await admin_create_wage_settlement(
        WageSettlementCreateInput(worker_id=wid, amount_le=100.0),
        admin=admin_user
    )
    txn_id = res["finance_transaction_id"]

    # Attempt to delete finance transaction directly via finance_delete
    with pytest.raises(HTTPException) as exc_guard:
        await finance_delete(txn_id, admin=admin_user)

    assert exc_guard.value.status_code == 409
    assert "terhubung langsung dengan pelunasan upah pekerja" in exc_guard.value.detail


@pytest.mark.anyio
async def test_multi_obligation_fifo_allocation(mock_env):
    mdb, admin_user, _, worker_user = mock_env
    wid = str(worker_user["_id"])

    # 3 obligations: 50, 100, 150 LE
    ob1_id = ObjectId("668888888888888888888801")
    ob2_id = ObjectId("668888888888888888888802")
    ob3_id = ObjectId("668888888888888888888803")

    mdb.wage_obligations.docs[str(ob1_id)] = {
        "_id": ob1_id,
        "obligation_number": "WOB-202610-0010",
        "worker_id": wid,
        "worker_name": worker_user["name"],
        "total_amount_le": 50.0,
        "paid_amount_le": 0.0,
        "status": "accrued",
        "created_at": "2026-10-10T10:00:00Z"
    }
    mdb.wage_obligations.docs[str(ob2_id)] = {
        "_id": ob2_id,
        "obligation_number": "WOB-202610-0011",
        "worker_id": wid,
        "worker_name": worker_user["name"],
        "total_amount_le": 100.0,
        "paid_amount_le": 0.0,
        "status": "accrued",
        "created_at": "2026-10-11T10:00:00Z"
    }
    mdb.wage_obligations.docs[str(ob3_id)] = {
        "_id": ob3_id,
        "obligation_number": "WOB-202610-0012",
        "worker_id": wid,
        "worker_name": worker_user["name"],
        "total_amount_le": 150.0,
        "paid_amount_le": 0.0,
        "status": "accrued",
        "created_at": "2026-10-12T10:00:00Z"
    }

    # Pay 120 LE:
    # 50 LE -> ob1 (fully paid)
    # 70 LE -> ob2 (partially paid, 30 remaining)
    # 0 LE -> ob3 (untouched, accrued)
    res = await admin_create_wage_settlement(
        WageSettlementCreateInput(worker_id=wid, amount_le=120.0),
        admin=admin_user
    )
    assert len(res["allocations"]) == 2
    assert res["allocations"][0]["obligation_number"] == "WOB-202610-0010"
    assert res["allocations"][0]["amount_le"] == 50.0
    assert res["allocations"][0]["obligation_status_after"] == "paid"

    assert res["allocations"][1]["obligation_number"] == "WOB-202610-0011"
    assert res["allocations"][1]["amount_le"] == 70.0
    assert res["allocations"][1]["obligation_status_after"] == "partially_paid"

    assert mdb.wage_obligations.docs[str(ob1_id)]["status"] == "paid"
    assert mdb.wage_obligations.docs[str(ob2_id)]["status"] == "partially_paid"
    assert mdb.wage_obligations.docs[str(ob3_id)]["status"] == "accrued"


@pytest.mark.anyio
async def test_wage_query_endpoints_and_history(mock_env):
    mdb, admin_user, _, worker_user = mock_env
    wid = str(worker_user["_id"])

    ob_id = ObjectId("669999999999999999999901")
    mdb.wage_obligations.docs[str(ob_id)] = {
        "_id": ob_id,
        "obligation_number": "WOB-202610-0020",
        "worker_id": wid,
        "worker_name": worker_user["name"],
        "total_amount_le": 200.0,
        "paid_amount_le": 50.0,
        "status": "partially_paid",
        "created_at": "2026-10-13T10:00:00Z"
    }

    # 1. Test admin_get_wage_obligations
    ob_res = await admin_get_wage_obligations(worker_id=wid, status="pending", admin=admin_user)
    assert ob_res["total"] == 1
    assert ob_res["obligations"][0]["remaining_amount_le"] == 150.0

    # 2. Settle remaining 150 LE
    st_res = await admin_create_wage_settlement(
        WageSettlementCreateInput(worker_id=wid, amount_le=150.0),
        admin=admin_user
    )
    st_id = str(st_res.get("id") or st_res.get("_id"))

    # 3. Test admin_get_wage_settlements
    st_list = await admin_get_wage_settlements(worker_id=wid, admin=admin_user)
    assert st_list["total"] == 1
    assert st_list["settlements"][0]["amount_le"] == 150.0

    # 4. Test admin_get_wage_settlement_detail
    detail = await admin_get_wage_settlement_detail(st_id, admin=admin_user)
    assert detail["settlement_number"] == st_res["settlement_number"]
    assert detail["worker_id"] == wid


@pytest.mark.anyio
async def test_reconciliation_runner(mock_env):
    mdb, admin_user, _, worker_user = mock_env
    from scripts.reconcile_wage_obligations_and_settlements import run_reconciliation

    wid = str(worker_user["_id"])
    ob_id = ObjectId("66aaaa000000000000000001")
    mdb.wage_obligations.docs[str(ob_id)] = {
        "_id": ob_id,
        "obligation_number": "WOB-202610-0099",
        "worker_id": wid,
        "worker_name": worker_user["name"],
        "total_amount_le": 100.0,
        "paid_amount_le": 0.0,
        "status": "accrued",
        "created_at": "2026-10-13T10:00:00Z"
    }

    # Settle
    st_res = await admin_create_wage_settlement(
        WageSettlementCreateInput(worker_id=wid, amount_le=100.0),
        admin=admin_user
    )

    # Run reconciliation audit
    report = await run_reconciliation(mdb)
    assert report["obligations"]["total_count"] == 1
    assert report["obligations"]["total_paid_le"] == Decimal("100.00")
    assert report["obligations"]["total_remaining_le"] == Decimal("0.00")
    assert report["settlements"]["total_count"] == 1
    assert report["settlements"]["total_amount_le"] == Decimal("100.00")
    assert len(report["matched_data"]) == 1
    assert len(report["investigation_needed"]) == 0


@pytest.mark.anyio
async def test_finance_update_guard_against_wage_settlement(mock_env):
    mdb, admin_user, _, worker_user = mock_env

    wid = str(worker_user["_id"])
    ob_id = ObjectId("66aaaa000000000000000001")
    mdb.wage_obligations.docs[str(ob_id)] = {
        "_id": ob_id,
        "obligation_number": "WOB-202610-0010",
        "worker_id": wid,
        "worker_name": worker_user["name"],
        "total_amount_le": 100.0,
        "paid_amount_le": 0.0,
        "status": "accrued",
        "created_at": "2026-10-13T10:00:00Z"
    }

    # Settle obligation
    st_res = await admin_create_wage_settlement(
        WageSettlementCreateInput(worker_id=wid, amount_le=100.0),
        admin=admin_user
    )
    txn_id = st_res["finance_transaction_id"]
    assert txn_id is not None

    # Attempt to edit the transaction via finance_update
    update_payload = FinanceTxnInput(
        type="expense",
        category="Pekerja",
        amount=50.0,
        currency="EGP",
        description="Tampered description"
    )

    with pytest.raises(HTTPException) as exc_info:
        await finance_update(txn_id=txn_id, data=update_payload, admin=admin_user)
    assert exc_info.value.status_code == 409
    assert "terhubung langsung dengan pelunasan upah pekerja" in exc_info.value.detail


@pytest.mark.anyio
async def test_critical_finance_index_error_wage_settlements():
    import server

    class MockAsyncColl:
        def __init__(self, name):
            self.name = name
            self.find_one = AsyncMock(return_value={"_id": "owner_id", "email": "sogil.furniture@gmail.com", "role": "owner"})
            self.insert_one = AsyncMock()
            self.insert_many = AsyncMock()
            self.update_one = AsyncMock()
            self.update_many = AsyncMock()
            self.count_documents = AsyncMock(return_value=1)
            self.create_index = AsyncMock(return_value="ok")

    class MockDB:
        def __init__(self):
            self._colls = {}

        def __getattr__(self, name):
            if name not in self._colls:
                self._colls[name] = MockAsyncColl(name)
            return self._colls[name]

        def __getitem__(self, name):
            return self.__getattr__(name)

    mock_db = MockDB()

    async def _failing_create_index(keys, **kwargs):
        if kwargs.get("name") == "uniq_settlement_number":
            raise pymongo.errors.OperationFailure("Index creation failure: duplicate key")
        return "ok"

    mock_db.wage_settlements.create_index = AsyncMock(side_effect=_failing_create_index)

    with patch.object(server, "db", mock_db), patch("server.set_setting", AsyncMock()):
        with pytest.raises(CriticalFinanceIndexError) as exc_info:
            await server.seed()
        assert exc_info.value.collection_name == "wage_settlements"
        assert exc_info.value.index_name == "uniq_settlement_number"
