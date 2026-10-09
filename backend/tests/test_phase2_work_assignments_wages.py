"""Comprehensive automated test suite for Phase 2: Work Assignments, Production Piece-Rate & Wage Obligation Accrual.

Covers all 15 required acceptance domains from v1.2.9:
1. Money & Rate Precision (TC-MON-01, TC-MON-02)
2. Currency Allowlist Enforcement (TC-CUR-01, TC-CUR-02)
3. Lump-Sum Acceptance Contract / Decision B-1 (TC-LMP-01, TC-LMP-02)
4. Production Transaction Fail-Closed & Standalone Recovery (TC-TXN-01, TC-TXN-02)
5. Order-Item Identity Stability & Deletion Protection (TC-ITM-01, TC-ITM-02, TC-ITM-03)
6. Dual Custody & Owner Self-Approval / Decision E2 (TC-AUT-01, TC-AUT-02)
7. Concurrency & Idempotency Fencing (TC-CON-01)
8. Cancellation & Paid Obligation Protection (TC-CAN-01, TC-CAN-02)
9. Complete 3-Collection Invariant Check (TC-FIN-01) with Unbounded Snapshots
"""
import copy
import os
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from fastapi import HTTPException
from pydantic import ValidationError
import pytest
import pymongo

from server import (
    normalize_cash_balance,
    calculate_wage_obligation_amount,
    admin_get_wage_rules,
    admin_create_wage_rule,
    admin_update_wage_rule,
    admin_delete_wage_rule,
    admin_create_work_assignment,
    admin_update_assignment_progress,
    admin_reject_assignment,
    admin_verify_work_assignment,
    admin_cancel_work_assignment,
    admin_get_worker_pending_wages,
    admin_get_wages_pending_summary,
    admin_update_order,
    admin_permanent_delete_order,
    run_transaction_probe,
    OrderStatusUpdate,
    PermanentDeleteInput,
    WageRuleInput,
    WageRuleUpdate,
    WorkAssignmentCreateInput,
    WorkAssignmentProgressInput,
    WorkAssignmentVerifyInput,
    WorkAssignmentRejectInput,
    WorkAssignmentCancelInput,
    _compute_balances,
    get_environment_mode,
    is_standalone_fallback_permitted,
)


class AsyncCursorMock:
    """Async iterator helper for simulating Motor collection.find({})."""
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
                elif isinstance(v, dict) and "$ne" in v:
                    if str(doc.get("_id")) == str(v["$ne"]):
                        return False
                else:
                    if str(doc.get("_id")) != str(v):
                        return False
            elif isinstance(v, dict):
                if "$in" in v:
                    if doc.get(k) not in v["$in"]:
                        return False
                elif "$ne" in v:
                    if doc.get(k) == v["$ne"]:
                        return False
            else:
                if doc.get(k) != v:
                    return False
        return True

    async def count_documents(self, filter_q=None, **kwargs):
        return len([d for d in self.docs.values() if self._matches(d, filter_q)])

    async def find_one(self, filter_q, **kwargs):
        for d in self.docs.values():
            if self._matches(d, filter_q):
                return copy.deepcopy(d)
        return None

    def find(self, filter_q=None, **kwargs):
        res = [copy.deepcopy(d) for d in self.docs.values() if self._matches(d, filter_q)]
        return AsyncCursorMock(res)

    async def insert_one(self, doc, **kwargs):
        doc_copy = copy.deepcopy(doc)
        if "_id" not in doc_copy:
            doc_copy["_id"] = ObjectId()
        self.docs[str(doc_copy["_id"])] = doc_copy
        mock_res = MagicMock()
        mock_res.inserted_id = doc_copy["_id"]
        return mock_res

    async def update_one(self, filter_q, update_spec, **kwargs):
        mock_res = MagicMock()
        mock_res.modified_count = 0
        for doc in self.docs.values():
            if self._matches(doc, filter_q):
                if "$set" in update_spec:
                    doc.update(copy.deepcopy(update_spec["$set"]))
                if "$unset" in update_spec:
                    for k in update_spec["$unset"]:
                        doc.pop(k, None)
                mock_res.modified_count = 1
                return mock_res
        return mock_res

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

    async def update_many(self, filter_q, update_spec, **kwargs):
        mock_res = MagicMock()
        cnt = 0
        for doc in self.docs.values():
            if self._matches(doc, filter_q):
                if "$set" in update_spec:
                    doc.update(copy.deepcopy(update_spec["$set"]))
                if "$unset" in update_spec:
                    for k in update_spec["$unset"]:
                        doc.pop(k, None)
                cnt += 1
        mock_res.modified_count = cnt
        return mock_res

    async def delete_one(self, filter_q, **kwargs):
        mock_res = MagicMock()
        mock_res.deleted_count = 0
        for did, doc in list(self.docs.items()):
            if self._matches(doc, filter_q):
                del self.docs[did]
                mock_res.deleted_count = 1
                return mock_res
        return mock_res

    async def delete_many(self, filter_q, **kwargs):
        mock_res = MagicMock()
        cnt = 0
        for did, doc in list(self.docs.items()):
            if self._matches(doc, filter_q):
                del self.docs[did]
                cnt += 1
        mock_res.deleted_count = cnt
        return mock_res

    async def create_index(self, *args, **kwargs):
        pass


class MockDatabase:
    def __init__(self, initial_data: dict = None):
        data = initial_data or {}
        self._collections = {
            "admins": MockCollection("admins", data.get("admins", [])),
            "orders": MockCollection("orders", data.get("orders", [])),
            "wage_rules": MockCollection("wage_rules", data.get("wage_rules", [])),
            "work_assignments": MockCollection("work_assignments", data.get("work_assignments", [])),
            "wage_obligations": MockCollection("wage_obligations", data.get("wage_obligations", [])),
            "finance_transactions": MockCollection("finance_transactions", data.get("finance_transactions", [])),
            "employee_wages": MockCollection("employee_wages", data.get("employee_wages", [])),
            "payments": MockCollection("payments", data.get("payments", [])),
            "audit_logs": MockCollection("audit_logs", data.get("audit_logs", [])),
            "counters": MockCollection("counters", data.get("counters", [])),
            "settings": MockCollection("settings", data.get("settings", [])),
        }

    def __getattr__(self, name: str):
        if name in self._collections:
            return self._collections[name]
        col = MockCollection(name, [])
        self._collections[name] = col
        return col

    def __getitem__(self, name: str):
        return self.__getattr__(name)


class MockSession:
    def __init__(self, client):
        self.client = client
        self.in_transaction = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.in_transaction = False
            self.client.restore_backup()

    def start_transaction(self):
        self.in_transaction = True
        return self


class MockClient:
    def __init__(self, db: MockDatabase):
        self.db = db
        self._backup = None
        self.fail_session = False

    async def start_session(self):
        if self.fail_session:
            raise pymongo.errors.ConfigurationError("Transaction not supported on standalone")
        self._backup = {
            cname: copy.deepcopy(col.docs) for cname, col in self.db._collections.items()
        }
        return MockSession(self)

    def restore_backup(self):
        if self._backup:
            for cname, docs in self._backup.items():
                self.db._collections[cname].docs = copy.deepcopy(docs)

    def __getitem__(self, name: str):
        return self.db


async def snapshot_entity_map(collection) -> dict:
    """
    Unbounded asynchronous iteration snapshot protocol (v1.2.9 Section 5).
    Guarantees zero truncation regardless of collection size.
    """
    snapshot = {}
    async for doc in collection.find({}):
        snapshot[str(doc["_id"])] = copy.deepcopy(doc)
    return snapshot


async def verify_finance_invariants(
    mock_db: MockDatabase,
    pre_snap_txns: dict,
    pre_snap_wages: dict,
    pre_snap_payments: dict,
    pre_egp_balance,
    pre_idr_balance
):
    """
    Rigorously verifies zero writes across finance_transactions, employee_wages, payments,
    and zero cash balance movements within epsilon.
    """
    post_snap_txns = await snapshot_entity_map(mock_db.finance_transactions)
    post_snap_wages = await snapshot_entity_map(mock_db.employee_wages)
    post_snap_payments = await snapshot_entity_map(mock_db.payments)

    assert set(post_snap_txns.keys()) == set(pre_snap_txns.keys()), (
        f"Finance transaction IDs mismatch! "
        f"New: {set(post_snap_txns.keys()) - set(pre_snap_txns.keys())}, "
        f"Deleted: {set(pre_snap_txns.keys()) - set(post_snap_txns.keys())}"
    )
    for tid, orig_doc in pre_snap_txns.items():
        assert post_snap_txns[tid] == orig_doc, f"Finance transaction {tid} was mutated!"

    assert set(post_snap_wages.keys()) == set(pre_snap_wages.keys()), (
        f"Employee wage IDs mismatch! "
        f"New: {set(post_snap_wages.keys()) - set(pre_snap_wages.keys())}, "
        f"Deleted: {set(pre_snap_wages.keys()) - set(post_snap_wages.keys())}"
    )
    for wid, orig_doc in pre_snap_wages.items():
        assert post_snap_wages[wid] == orig_doc, f"Employee wage {wid} was mutated!"

    assert set(post_snap_payments.keys()) == set(pre_snap_payments.keys()), (
        f"Payment IDs mismatch! "
        f"New: {set(post_snap_payments.keys()) - set(pre_snap_payments.keys())}, "
        f"Deleted: {set(pre_snap_payments.keys()) - set(post_snap_payments.keys())}"
    )
    for pid, orig_doc in pre_snap_payments.items():
        assert post_snap_payments[pid] == orig_doc, f"Payment document {pid} was mutated!"

    with patch("server.db", mock_db):
        balances = await _compute_balances()
    post_egp_norm = normalize_cash_balance(balances.get("EGP", 0.0), "EGP")
    pre_egp_norm = normalize_cash_balance(pre_egp_balance, "EGP")
    delta_egp = abs(post_egp_norm - pre_egp_norm)

    post_idr_norm = normalize_cash_balance(balances.get("IDR", 0.0), "IDR")
    pre_idr_norm = normalize_cash_balance(pre_idr_balance, "IDR")
    delta_idr = abs(post_idr_norm - pre_idr_norm)

    assert delta_egp < Decimal("0.0001"), f"Cash balance in EGP moved! Delta: {delta_egp}"
    assert delta_idr < Decimal("0.0001"), f"Cash balance in IDR moved! Delta: {delta_idr}"


class TestPhase2WorkAssignmentsWages(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.owner = {
            "_id": ObjectId("607f1f77bcf86cd799439099"),
            "id": "607f1f77bcf86cd799439099",
            "name": "Owner Sogil",
            "role": "owner",
            "permissions": {"manage_orders": True, "access_finance": True, "manage_settings": True},
        }
        self.admin_manager = {
            "_id": ObjectId("607f1f77bcf86cd799439098"),
            "id": "607f1f77bcf86cd799439098",
            "name": "Manager Ops",
            "role": "manager",
            "permissions": {"manage_orders": True, "access_finance": False, "manage_settings": True},
        }
        self.worker_user = {
            "_id": ObjectId("607f1f77bcf86cd799439001"),
            "id": "607f1f77bcf86cd799439001",
            "name": "Tukang Kayu Ahmad",
            "role": "employee",
            "status": "active",
        }
        self.worker_admin = {
            "_id": ObjectId("607f1f77bcf86cd799439002"),
            "id": "607f1f77bcf86cd799439002",
            "name": "Admin Supervisor Budi",
            "role": "admin",
            "status": "active",
        }

        self.initial_order = {
            "_id": ObjectId("507f1f77bcf86cd799439011"),
            "order_number": "SGF-P2-001",
            "order_status": "diproses",
            "payment_status": "dp",
            "total_le": 1500.0,
            "items": [
                {
                    "item_id": "itm_rak_kayu_01",
                    "product_name_snapshot": "Rak Kayu 3 Tingkat",
                    "quantity": 3,
                    "unit_price_le": 500.0,
                    "subtotal_le": 1500.0,
                }
            ],
            "item": {
                "item_id": "itm_rak_kayu_01",
                "product_name_snapshot": "Rak Kayu 3 Tingkat",
                "quantity": 3,
                "unit_price_le": 500.0,
                "subtotal_le": 1500.0,
            }
        }

        # Seed pre-existing financial records across all 3 protected collections
        self.fixture_txns = [
            {"_id": ObjectId("707f1f77bcf86cd799439001"), "date": "2026-10-01", "type": "income", "amount": 2000.0, "currency": "EGP", "account": "EGP", "status": "recorded"},
            {"_id": ObjectId("707f1f77bcf86cd799439002"), "date": "2026-10-02", "type": "expense", "amount": 500.0, "currency": "EGP", "account": "EGP", "status": "recorded"},
        ]
        self.fixture_wages = [
            {"_id": ObjectId("807f1f77bcf86cd799439001"), "employee_id": "emp_old", "amount": 1000.0, "status": "legacy"},
        ]
        self.fixture_payments = [
            {"_id": ObjectId("907f1f77bcf86cd799439001"), "payment_number": "PAY-20261001-001", "amount_le": 500.0, "status": "recorded"},
        ]

        self.mock_db = MockDatabase({
            "admins": [self.worker_user, self.worker_admin, self.owner, self.admin_manager],
            "orders": [self.initial_order],
            "finance_transactions": self.fixture_txns,
            "employee_wages": self.fixture_wages,
            "payments": self.fixture_payments,
            "counters": [{"_id": "wob_20261009", "seq": 10}],
            "settings": [{"key": "exchange_rate_idr_per_le", "value": 357.0}],
        })
        self.mock_client = MockClient(self.mock_db)

    async def _capture_pre_state(self):
        pre_txns = await snapshot_entity_map(self.mock_db.finance_transactions)
        pre_wages = await snapshot_entity_map(self.mock_db.employee_wages)
        pre_payments = await snapshot_entity_map(self.mock_db.payments)
        with patch("server.db", self.mock_db):
            balances = await _compute_balances()
        return pre_txns, pre_wages, pre_payments, balances.get("EGP", 0.0), balances.get("IDR", 0.0)

    # =========================================================================
    # 1. Money & Rate Precision (TC-MON-01, TC-MON-02)
    # =========================================================================
    async def test_TC_MON_01_monetary_exact_calculation(self):
        """TC-MON-01: Agreed rate 33.33 LE, accepted qty 3 -> Obligation accrued 99.99 LE."""
        pre_txns, pre_wages, pre_payments, pre_egp, pre_idr = await self._capture_pre_state()

        amt = calculate_wage_obligation_amount(33.33, 3, "per_unit")
        self.assertEqual(amt, 99.99)

        # Verification through full pipeline
        with patch("server.db", self.mock_db), patch("server.client", self.mock_client):
            asn_doc = await admin_create_work_assignment(
                "507f1f77bcf86cd799439011",
                WorkAssignmentCreateInput(
                    worker_id=str(self.worker_user["id"]),
                    order_item_id="itm_rak_kayu_01",
                    task_category="assembly",
                    pricing_basis="per_unit",
                    agreed_rate_le=33.33,
                    target_quantity=3,
                ),
                self.admin_manager
            )
            asn_id = asn_doc["id"]
            # Mark ready for review
            await admin_update_assignment_progress(
                asn_id,
                WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=3),
                self.admin_manager
            )
            # Verify
            wob = await admin_verify_work_assignment(
                asn_id,
                WorkAssignmentVerifyInput(accepted_quantity=3),
                self.admin_manager
            )

        self.assertEqual(wob["total_amount_le"], 99.99)
        self.assertEqual(wob["currency"], "EGP")
        self.assertEqual(wob["status"], "accrued")

        # Invariant check
        with patch("server.db", self.mock_db):
            await verify_finance_invariants(self.mock_db, pre_txns, pre_wages, pre_payments, pre_egp, pre_idr)

    async def test_TC_MON_02_rate_over_precision_rejected(self):
        """TC-MON-02: Rate with > 2 decimal places (e.g. 45.125 LE) rejected with HTTP 422."""
        with patch("server.db", self.mock_db):
            with self.assertRaises(HTTPException) as ctx:
                await admin_create_wage_rule(
                    WageRuleInput(
                        task_category="assembly",
                        pricing_basis="per_unit",
                        standard_rate_le=45.125,
                    ),
                    self.admin_manager
                )
            self.assertEqual(ctx.exception.status_code, 422)

    # =========================================================================
    # 2. Currency Allowlist Enforcement (TC-CUR-01, TC-CUR-02)
    # =========================================================================
    def test_TC_CUR_01_currency_allowlist_valid(self):
        """TC-CUR-01: 'EGP' and 'IDR' select precise minor and whole unit precisions."""
        self.assertEqual(normalize_cash_balance(140.55, "EGP"), Decimal("140.55"))
        self.assertEqual(normalize_cash_balance("140.55", "egp"), Decimal("140.55"))
        self.assertEqual(normalize_cash_balance(2500000.4, "IDR"), Decimal("2500000"))
        self.assertEqual(normalize_cash_balance(2500000.6, "idr"), Decimal("2500001"))

    def test_TC_CUR_02_currency_allowlist_rejections(self):
        """TC-CUR-02: 'EUR', 'USD', 'EGG', '' rejected with ValueError (fail-closed)."""
        for invalid in ["EUR", "USD", "EGG", "IDRR", "", None]:
            with self.assertRaises(ValueError):
                normalize_cash_balance(100.0, invalid)

    # =========================================================================
    # 3. Lump-Sum Acceptance Contract / Decision B-1 (TC-LMP-01, TC-LMP-02)
    # =========================================================================
    async def test_TC_LMP_01_lump_sum_full_acceptance(self):
        """TC-LMP-01: Target 3 units lump-sum at 500 LE; accepts 3 -> Completed & accrued 500.00 LE."""
        pre_txns, pre_wages, pre_payments, pre_egp, pre_idr = await self._capture_pre_state()

        with patch("server.db", self.mock_db), patch("server.client", self.mock_client):
            asn = await admin_create_work_assignment(
                "507f1f77bcf86cd799439011",
                WorkAssignmentCreateInput(
                    worker_id=str(self.worker_user["id"]),
                    order_item_id="itm_rak_kayu_01",
                    task_category="whole_item",
                    pricing_basis="lump_sum",
                    agreed_rate_le=500.0,
                    target_quantity=3,
                ),
                self.admin_manager
            )
            await admin_update_assignment_progress(
                asn["id"],
                WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=3),
                self.admin_manager
            )
            wob = await admin_verify_work_assignment(
                asn["id"],
                WorkAssignmentVerifyInput(accepted_quantity=3),
                self.admin_manager
            )

        self.assertEqual(wob["total_amount_le"], 500.0)
        self.assertEqual(wob["pricing_basis"], "lump_sum")
        self.assertEqual(wob["accepted_quantity"], 3)

        with patch("server.db", self.mock_db):
            await verify_finance_invariants(self.mock_db, pre_txns, pre_wages, pre_payments, pre_egp, pre_idr)

    async def test_TC_LMP_02_lump_sum_partial_acceptance_rejected(self):
        """TC-LMP-02: Target 3 units lump-sum at 500 LE; accepts 2 -> Rejected HTTP 422, zero mutations."""
        pre_txns, pre_wages, pre_payments, pre_egp, pre_idr = await self._capture_pre_state()

        with patch("server.db", self.mock_db), patch("server.client", self.mock_client):
            asn = await admin_create_work_assignment(
                "507f1f77bcf86cd799439011",
                WorkAssignmentCreateInput(
                    worker_id=str(self.worker_user["id"]),
                    order_item_id="itm_rak_kayu_01",
                    task_category="whole_item",
                    pricing_basis="lump_sum",
                    agreed_rate_le=500.0,
                    target_quantity=3,
                ),
                self.admin_manager
            )
            await admin_update_assignment_progress(
                asn["id"],
                WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=2),
                self.admin_manager
            )

            with self.assertRaises(HTTPException) as ctx:
                await admin_verify_work_assignment(
                    asn["id"],
                    WorkAssignmentVerifyInput(accepted_quantity=2),
                    self.admin_manager
                )
            self.assertEqual(ctx.exception.status_code, 422)

            # Confirm assignment remains in ready_for_review and zero obligations created
            stored_asn = await self.mock_db.work_assignments.find_one({"_id": ObjectId(asn["id"])})
            self.assertEqual(stored_asn["status"], "ready_for_review")
            wob = await self.mock_db.wage_obligations.find_one({"work_assignment_id": asn["id"]})
            self.assertIsNone(wob)

        with patch("server.db", self.mock_db):
            await verify_finance_invariants(self.mock_db, pre_txns, pre_wages, pre_payments, pre_egp, pre_idr)

    # =========================================================================
    # 4. Production Transaction Fail-Closed & Standalone Recovery (TC-TXN-01, TC-TXN-02)
    # =========================================================================
    async def test_TC_TXN_01_transaction_probe(self):
        """TC-TXN-01: Verifies multi-document transaction probe execution and fail-closed handling."""
        mock_mongo_client = MagicMock()
        mock_session = AsyncMock()
        mock_mongo_client.start_session = AsyncMock(return_value=mock_session)
        mock_session.__aenter__.return_value = mock_session
        mock_session.start_transaction = MagicMock(return_value=mock_session)

        mock_db = MagicMock()
        mock_mongo_client.__getitem__.return_value = mock_db
        mock_col = AsyncMock()
        mock_db.__getitem__.return_value = mock_col
        mock_col.find_one = AsyncMock(return_value={"_id": "doc"})

        # Successful probe
        result = await run_transaction_probe(mock_mongo_client, "sogil")
        self.assertTrue(result)

        # Standalone topology failure returns False
        mock_mongo_client.start_session = AsyncMock(side_effect=pymongo.errors.ConfigurationError("Standalone"))
        result_standalone = await run_transaction_probe(mock_mongo_client, "sogil")
        self.assertFalse(result_standalone)

    async def test_TC_TXN_02_standalone_recovery_and_rollback(self):
        """TC-TXN-02: Standalone mode fallback rolls back properly on insert failure."""
        pre_txns, pre_wages, pre_payments, pre_egp, pre_idr = await self._capture_pre_state()

        self.mock_client.fail_session = True  # Triggers standalone branch

        with patch("server.db", self.mock_db), patch("server.client", self.mock_client), patch.dict("os.environ", {"APP_ENV": "test"}):
            asn = await admin_create_work_assignment(
                "507f1f77bcf86cd799439011",
                WorkAssignmentCreateInput(
                    worker_id=str(self.worker_user["id"]),
                    order_item_id="itm_rak_kayu_01",
                    task_category="assembly",
                    pricing_basis="per_unit",
                    agreed_rate_le=100.0,
                    target_quantity=1,
                ),
                self.admin_manager
            )
            await admin_update_assignment_progress(
                asn["id"],
                WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=1),
                self.admin_manager
            )

            # Mock insert failure to trigger compensating rollback
            with patch.object(self.mock_db.wage_obligations, "insert_one", AsyncMock(side_effect=Exception("Disk full"))):
                with self.assertRaises(HTTPException) as ctx:
                    await admin_verify_work_assignment(
                        asn["id"],
                        WorkAssignmentVerifyInput(accepted_quantity=1),
                        self.admin_manager
                    )
                self.assertEqual(ctx.exception.status_code, 500)

            # Verify compensating rollback restored ready_for_review
            stored_asn = await self.mock_db.work_assignments.find_one({"_id": ObjectId(asn["id"])})
            self.assertEqual(stored_asn["status"], "ready_for_review")

        with patch("server.db", self.mock_db):
            await verify_finance_invariants(self.mock_db, pre_txns, pre_wages, pre_payments, pre_egp, pre_idr)

    async def test_TC_TXN_03_production_verification_fails_closed(self):
        """Test C1 & AC-01: In production mode, missing transaction capability returns HTTP 503 and zero writes."""
        pre_txns, pre_wages, pre_payments, pre_egp, pre_idr = await self._capture_pre_state()
        self.mock_client.fail_session = True

        with patch("server.db", self.mock_db), patch("server.client", self.mock_client), patch.dict("os.environ", {"APP_ENV": "production"}):
            asn = await admin_create_work_assignment(
                "507f1f77bcf86cd799439011",
                WorkAssignmentCreateInput(
                    worker_id=str(self.worker_user["id"]),
                    order_item_id="itm_rak_kayu_01",
                    task_category="assembly",
                    pricing_basis="per_unit",
                    agreed_rate_le=100.0,
                    target_quantity=1,
                ),
                self.admin_manager
            )
            await admin_update_assignment_progress(
                asn["id"],
                WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=1),
                self.admin_manager
            )

            with self.assertRaises(HTTPException) as ctx:
                await admin_verify_work_assignment(
                    asn["id"],
                    WorkAssignmentVerifyInput(accepted_quantity=1),
                    self.admin_manager
                )
            self.assertEqual(ctx.exception.status_code, 503)
            self.assertIn("Fail-Closed", ctx.exception.detail)

            # State remains strictly unchanged: ready_for_review, zero obligations created
            stored_asn = await self.mock_db.work_assignments.find_one({"_id": ObjectId(asn["id"])})
            self.assertEqual(stored_asn["status"], "ready_for_review")
            wob = await self.mock_db.wage_obligations.find_one({"work_assignment_id": asn["id"]})
            self.assertIsNone(wob)

        with patch("server.db", self.mock_db):
            await verify_finance_invariants(self.mock_db, pre_txns, pre_wages, pre_payments, pre_egp, pre_idr)

    async def test_TC_TXN_04_production_cancellation_fails_closed(self):
        """Test C2 & AC-02: In production mode, missing transaction capability for cancel returns HTTP 503 and zero writes."""
        pre_txns, pre_wages, pre_payments, pre_egp, pre_idr = await self._capture_pre_state()

        # Create and complete an assignment in normal transaction-capable mode
        with patch("server.db", self.mock_db), patch("server.client", self.mock_client):
            asn = await admin_create_work_assignment(
                "507f1f77bcf86cd799439011",
                WorkAssignmentCreateInput(
                    worker_id=str(self.worker_user["id"]),
                    order_item_id="itm_rak_kayu_01",
                    task_category="assembly",
                    pricing_basis="per_unit",
                    agreed_rate_le=100.0,
                    target_quantity=1,
                ),
                self.admin_manager
            )
            await admin_update_assignment_progress(
                asn["id"],
                WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=1),
                self.admin_manager
            )
            wob = await admin_verify_work_assignment(
                asn["id"],
                WorkAssignmentVerifyInput(accepted_quantity=1),
                self.admin_manager
            )

        # Now simulate production transaction failure during cancellation
        self.mock_client.fail_session = True
        with patch("server.db", self.mock_db), patch("server.client", self.mock_client), patch.dict("os.environ", {"APP_ENV": "production"}):
            with self.assertRaises(HTTPException) as ctx:
                await admin_cancel_work_assignment(
                    asn["id"],
                    WorkAssignmentCancelInput(reason="Defects found"),
                    self.owner
                )
            self.assertEqual(ctx.exception.status_code, 503)
            self.assertIn("Fail-Closed", ctx.exception.detail)

            # Assignment remains completed and obligation remains accrued
            stored_asn = await self.mock_db.work_assignments.find_one({"_id": ObjectId(asn["id"])})
            self.assertEqual(stored_asn["status"], "completed")
            stored_wob = await self.mock_db.wage_obligations.find_one({"_id": ObjectId(wob["id"])})
            self.assertEqual(stored_wob["status"], "accrued")

        self.mock_client.fail_session = False
        with patch("server.db", self.mock_db):
            await verify_finance_invariants(self.mock_db, pre_txns, pre_wages, pre_payments, pre_egp, pre_idr)

    async def test_TC_TXN_05_production_transaction_failure_does_not_fall_back(self):
        """Test C3 & AC-03: When transaction starts but write fails in production, aborts cleanly without fallback."""
        pre_txns, pre_wages, pre_payments, pre_egp, pre_idr = await self._capture_pre_state()

        with patch("server.db", self.mock_db), patch("server.client", self.mock_client), patch.dict("os.environ", {"APP_ENV": "production"}):
            asn = await admin_create_work_assignment(
                "507f1f77bcf86cd799439011",
                WorkAssignmentCreateInput(
                    worker_id=str(self.worker_user["id"]),
                    order_item_id="itm_rak_kayu_01",
                    task_category="assembly",
                    pricing_basis="per_unit",
                    agreed_rate_le=100.0,
                    target_quantity=1,
                ),
                self.admin_manager
            )
            await admin_update_assignment_progress(
                asn["id"],
                WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=1),
                self.admin_manager
            )

            # Simulate failure during transactional insert_one
            with patch.object(self.mock_db.wage_obligations, "insert_one", AsyncMock(side_effect=Exception("Transaction abort test"))):
                with self.assertRaises(HTTPException) as ctx:
                    await admin_verify_work_assignment(
                        asn["id"],
                        WorkAssignmentVerifyInput(accepted_quantity=1),
                        self.admin_manager
                    )
                self.assertEqual(ctx.exception.status_code, 500)

            # State rolled back by MockSession __aexit__ / client.restore_backup
            stored_asn = await self.mock_db.work_assignments.find_one({"_id": ObjectId(asn["id"])})
            self.assertEqual(stored_asn["status"], "ready_for_review")
            wob = await self.mock_db.wage_obligations.find_one({"work_assignment_id": asn["id"]})
            self.assertIsNone(wob)

        with patch("server.db", self.mock_db):
            await verify_finance_invariants(self.mock_db, pre_txns, pre_wages, pre_payments, pre_egp, pre_idr)

    async def test_TC_TXN_06_unknown_environment_fails_closed(self):
        """Test C5 & AC-05: Missing, unknown, or invalid environment configuration strictly fails closed."""
        self.mock_client.fail_session = True
        with patch("server.db", self.mock_db), patch("server.client", self.mock_client), patch.dict("os.environ", {"APP_ENV": "staging_unknown", "ENV": "", "ENVIRONMENT": ""}):
            asn = await admin_create_work_assignment(
                "507f1f77bcf86cd799439011",
                WorkAssignmentCreateInput(
                    worker_id=str(self.worker_user["id"]),
                    order_item_id="itm_rak_kayu_01",
                    task_category="assembly",
                    pricing_basis="per_unit",
                    agreed_rate_le=100.0,
                    target_quantity=1,
                ),
                self.admin_manager
            )
            await admin_update_assignment_progress(
                asn["id"],
                WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=1),
                self.admin_manager
            )

            with self.assertRaises(HTTPException) as ctx:
                await admin_verify_work_assignment(
                    asn["id"],
                    WorkAssignmentVerifyInput(accepted_quantity=1),
                    self.admin_manager
                )
            self.assertEqual(ctx.exception.status_code, 503)
            self.assertIn("Fail-Closed", ctx.exception.detail)
        self.mock_client.fail_session = False

    # =========================================================================
    # 5. Order-Item Identity Stability & Deletion Protection (TC-ITM-01, TC-ITM-02, TC-ITM-03)
    # =========================================================================
    async def test_TC_ITM_01_item_identity_and_reorder_stability(self):
        """TC-ITM-01: Updating items preserves existing item_ids and assigns new ones cleanly."""
        pre_txns, pre_wages, pre_payments, pre_egp, pre_idr = await self._capture_pre_state()

        with patch("server.db", self.mock_db):
            # Update order items: Keep itm_rak_kayu_01 and add a new item without item_id
            payload = OrderStatusUpdate(
                items=[
                    {
                        "item_id": "itm_rak_kayu_01",
                        "product_name_snapshot": "Rak Kayu 3 Tingkat (Edited)",
                        "quantity": 3,
                        "unit_price_le": 500.0,
                        "subtotal_le": 1500.0,
                    },
                    {
                        "product_name_snapshot": "Kursi Tambahan",
                        "quantity": 1,
                        "unit_price_le": 200.0,
                        "subtotal_le": 200.0,
                    }
                ]
            )
            updated_order = await admin_update_order(
                "507f1f77bcf86cd799439011",
                payload,
                self.owner
            )

        items = updated_order["items"]
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["item_id"], "itm_rak_kayu_01")
        self.assertTrue(items[1]["item_id"].startswith("itm_"))

        with patch("server.db", self.mock_db):
            await verify_finance_invariants(self.mock_db, pre_txns, pre_wages, pre_payments, pre_egp, pre_idr)

    async def test_TC_ITM_02_active_item_delete_blocked(self):
        """TC-ITM-02: Deleting an order item with active work assignments raises HTTP 409 Conflict."""
        with patch("server.db", self.mock_db):
            # Create active assignment on itm_rak_kayu_01
            await admin_create_work_assignment(
                "507f1f77bcf86cd799439011",
                WorkAssignmentCreateInput(
                    worker_id=str(self.worker_user["id"]),
                    order_item_id="itm_rak_kayu_01",
                    task_category="assembly",
                    pricing_basis="per_unit",
                    agreed_rate_le=100.0,
                    target_quantity=1,
                ),
                self.admin_manager
            )

            # Try to update order with empty items array (omitting itm_rak_kayu_01)
            payload = OrderStatusUpdate(items=[])
            with self.assertRaises(HTTPException) as ctx:
                await admin_update_order("507f1f77bcf86cd799439011", payload, self.owner)
            self.assertEqual(ctx.exception.status_code, 409)

    async def test_TC_ITM_03_cancelled_item_delete_blocked(self):
        """TC-ITM-03: Deleting an order item with cancelled assignment raises HTTP 409 Conflict for audit integrity."""
        with patch("server.db", self.mock_db):
            asn = await admin_create_work_assignment(
                "507f1f77bcf86cd799439011",
                WorkAssignmentCreateInput(
                    worker_id=str(self.worker_user["id"]),
                    order_item_id="itm_rak_kayu_01",
                    task_category="finishing",
                    pricing_basis="per_unit",
                    agreed_rate_le=50.0,
                    target_quantity=1,
                ),
                self.admin_manager
            )
            await admin_cancel_work_assignment(asn["id"], WorkAssignmentCancelInput(reason="Client changed color"), self.admin_manager)

            # Attempt to delete the item
            payload = OrderStatusUpdate(items=[])
            with self.assertRaises(HTTPException) as ctx:
                await admin_update_order("507f1f77bcf86cd799439011", payload, self.owner)
            self.assertEqual(ctx.exception.status_code, 409)

    # =========================================================================
    # 6. Dual Custody & Owner Self-Approval / Decision E2 (TC-AUT-01, TC-AUT-02)
    # =========================================================================
    async def test_TC_AUT_01_non_owner_self_approval_rejected(self):
        """TC-AUT-01: Admin/manager verifying their own work assignment is rejected with HTTP 403."""
        with patch("server.db", self.mock_db), patch("server.client", self.mock_client):
            asn = await admin_create_work_assignment(
                "507f1f77bcf86cd799439011",
                WorkAssignmentCreateInput(
                    worker_id=str(self.worker_admin["id"]),
                    order_item_id="itm_rak_kayu_01",
                    task_category="cutting",
                    pricing_basis="per_unit",
                    agreed_rate_le=40.0,
                    target_quantity=1,
                ),
                self.owner
            )
            await admin_update_assignment_progress(
                asn["id"],
                WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=1),
                self.worker_admin
            )

            # worker_admin attempts to verify their own work
            with self.assertRaises(HTTPException) as ctx:
                await admin_verify_work_assignment(
                    asn["id"],
                    WorkAssignmentVerifyInput(accepted_quantity=1),
                    self.worker_admin
                )
            self.assertEqual(ctx.exception.status_code, 403)

    async def test_TC_AUT_02_owner_self_approval_allowed_with_audit_trail(self):
        """TC-AUT-02: Server-verified owner may self-approve work assignment with is_owner_bypass: True."""
        pre_txns, pre_wages, pre_payments, pre_egp, pre_idr = await self._capture_pre_state()

        with patch("server.db", self.mock_db), patch("server.client", self.mock_client):
            asn = await admin_create_work_assignment(
                "507f1f77bcf86cd799439011",
                WorkAssignmentCreateInput(
                    worker_id=str(self.owner["id"]),
                    order_item_id="itm_rak_kayu_01",
                    task_category="custom",
                    pricing_basis="per_unit",
                    agreed_rate_le=150.0,
                    target_quantity=1,
                ),
                self.owner
            )
            await admin_update_assignment_progress(
                asn["id"],
                WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=1),
                self.owner
            )

            # Owner self-approves
            wob = await admin_verify_work_assignment(
                asn["id"],
                WorkAssignmentVerifyInput(accepted_quantity=1),
                self.owner
            )

        self.assertTrue(wob["is_owner_bypass"])
        self.assertEqual(wob["status"], "accrued")
        self.assertEqual(wob["total_amount_le"], 150.0)

        # Check audit log recorded
        audit = await self.mock_db.audit_logs.find_one({"action": "WORK_ASSIGNMENT_VERIFIED", "entity_id": asn["id"]})
        self.assertIsNotNone(audit)
        self.assertTrue(audit["metadata"]["is_owner_bypass"])

        with patch("server.db", self.mock_db):
            await verify_finance_invariants(self.mock_db, pre_txns, pre_wages, pre_payments, pre_egp, pre_idr)

    # =========================================================================
    # 7. Concurrency & Idempotency Fencing (TC-CON-01)
    # =========================================================================
    async def test_TC_CON_01_idempotent_replay_and_duplicate_safety(self):
        """TC-CON-01: Replaying verify returns canonical obligation with exactly 1 record created."""
        with patch("server.db", self.mock_db), patch("server.client", self.mock_client):
            asn = await admin_create_work_assignment(
                "507f1f77bcf86cd799439011",
                WorkAssignmentCreateInput(
                    worker_id=str(self.worker_user["id"]),
                    order_item_id="itm_rak_kayu_01",
                    task_category="assembly",
                    pricing_basis="per_unit",
                    agreed_rate_le=75.0,
                    target_quantity=1,
                ),
                self.admin_manager
            )
            await admin_update_assignment_progress(
                asn["id"],
                WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=1),
                self.admin_manager
            )

            # First verify
            wob1 = await admin_verify_work_assignment(
                asn["id"],
                WorkAssignmentVerifyInput(accepted_quantity=1),
                self.admin_manager
            )

            # Second verify (replay)
            wob2 = await admin_verify_work_assignment(
                asn["id"],
                WorkAssignmentVerifyInput(accepted_quantity=1),
                self.admin_manager
            )

        self.assertEqual(wob1["obligation_number"], wob2["obligation_number"])
        self.assertEqual(wob1["total_amount_le"], wob2["total_amount_le"])

        # Confirm exactly 1 obligation exists in database
        obligations = await self.mock_db.wage_obligations.find({"work_assignment_id": asn["id"]}).to_list(10)
        self.assertEqual(len(obligations), 1)

    # =========================================================================
    # 8. Cancellation & Paid Obligation Protection (TC-CAN-01, TC-CAN-02)
    # =========================================================================
    async def test_TC_CAN_01_cancel_completed_unpaid_assignment_voids_obligation(self):
        """TC-CAN-01: Cancelling completed unpaid assignment marks assignment cancelled and obligation voided."""
        pre_txns, pre_wages, pre_payments, pre_egp, pre_idr = await self._capture_pre_state()

        with patch("server.db", self.mock_db), patch("server.client", self.mock_client):
            asn = await admin_create_work_assignment(
                "507f1f77bcf86cd799439011",
                WorkAssignmentCreateInput(
                    worker_id=str(self.worker_user["id"]),
                    order_item_id="itm_rak_kayu_01",
                    task_category="assembly",
                    pricing_basis="per_unit",
                    agreed_rate_le=120.0,
                    target_quantity=1,
                ),
                self.admin_manager
            )
            await admin_update_assignment_progress(
                asn["id"],
                WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=1),
                self.admin_manager
            )
            wob = await admin_verify_work_assignment(
                asn["id"],
                WorkAssignmentVerifyInput(accepted_quantity=1),
                self.admin_manager
            )

            # Cancel completed assignment by owner
            cancelled_asn = await admin_cancel_work_assignment(
                asn["id"],
                WorkAssignmentCancelInput(reason="Quality defects detected post-review"),
                self.owner
            )

        self.assertEqual(cancelled_asn["status"], "cancelled")
        stored_wob = await self.mock_db.wage_obligations.find_one({"_id": ObjectId(wob["id"])})
        self.assertEqual(stored_wob["status"], "voided")
        self.assertEqual(stored_wob["void_reason"], "Quality defects detected post-review")

        with patch("server.db", self.mock_db):
            await verify_finance_invariants(self.mock_db, pre_txns, pre_wages, pre_payments, pre_egp, pre_idr)

    async def test_TC_CAN_02_block_cancel_paid_obligation(self):
        """TC-CAN-02: Cancelling an assignment with paid obligation (paid_amount > 0) rejected with HTTP 400."""
        with patch("server.db", self.mock_db), patch("server.client", self.mock_client):
            asn = await admin_create_work_assignment(
                "507f1f77bcf86cd799439011",
                WorkAssignmentCreateInput(
                    worker_id=str(self.worker_user["id"]),
                    order_item_id="itm_rak_kayu_01",
                    task_category="assembly",
                    pricing_basis="per_unit",
                    agreed_rate_le=120.0,
                    target_quantity=1,
                ),
                self.admin_manager
            )
            await admin_update_assignment_progress(
                asn["id"],
                WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=1),
                self.admin_manager
            )
            wob = await admin_verify_work_assignment(
                asn["id"],
                WorkAssignmentVerifyInput(accepted_quantity=1),
                self.admin_manager
            )

            # Simulate partial payment in Phase 3
            await self.mock_db.wage_obligations.update_one(
                {"_id": ObjectId(wob["id"])},
                {"$set": {"paid_amount_le": 60.0}}
            )

            with self.assertRaises(HTTPException) as ctx:
                await admin_cancel_work_assignment(
                    asn["id"],
                    WorkAssignmentCancelInput(reason="Try cancel paid job"),
                    self.owner
                )
            self.assertEqual(ctx.exception.status_code, 400)

    # =========================================================================
    # 9. Permanent Order Delete Guard
    # =========================================================================
    async def test_permanent_delete_order_blocked_by_active_assignments(self):
        """Permanent order delete is blocked with HTTP 409 if active assignments exist."""
        with patch("server.db", self.mock_db):
            await admin_create_work_assignment(
                "507f1f77bcf86cd799439011",
                WorkAssignmentCreateInput(
                    worker_id=str(self.worker_user["id"]),
                    order_item_id="itm_rak_kayu_01",
                    task_category="assembly",
                    pricing_basis="per_unit",
                    agreed_rate_le=100.0,
                    target_quantity=1,
                ),
                self.admin_manager
            )

            payload = PermanentDeleteInput(confirmation_phrase="HAPUS PERMANEN")
            with self.assertRaises(HTTPException) as ctx:
                await admin_permanent_delete_order("507f1f77bcf86cd799439011", payload, self.owner)
            self.assertEqual(ctx.exception.status_code, 409)

    # =========================================================================
    # 10. Summary Endpoints
    # =========================================================================
    async def test_summary_endpoints(self):
        """Read-only worker pending wages and overall wages pending summary."""
        with patch("server.db", self.mock_db), patch("server.client", self.mock_client):
            asn = await admin_create_work_assignment(
                "507f1f77bcf86cd799439011",
                WorkAssignmentCreateInput(
                    worker_id=str(self.worker_user["id"]),
                    order_item_id="itm_rak_kayu_01",
                    task_category="assembly",
                    pricing_basis="per_unit",
                    agreed_rate_le=80.0,
                    target_quantity=1,
                ),
                self.admin_manager
            )
            await admin_update_assignment_progress(
                asn["id"],
                WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=1),
                self.admin_manager
            )
            await admin_verify_work_assignment(
                asn["id"],
                WorkAssignmentVerifyInput(accepted_quantity=1),
                self.admin_manager
            )

            worker_summary = await admin_get_worker_pending_wages(str(self.worker_user["id"]), self.owner)
            self.assertEqual(worker_summary["total_pending_wages_le"], 80.0)
            self.assertEqual(worker_summary["pending_obligations_count"], 1)

            overall_summary = await admin_get_wages_pending_summary(self.owner)
            self.assertGreaterEqual(overall_summary["total_pending_wages_le"], 80.0)

    # =========================================================================
    # 11. Additional Corrective Regression Tests (C6, C7, C8)
    # =========================================================================
    async def test_TC_WAG_01_wage_rule_update_does_not_mutate_existing_assignment(self):
        """Test C6 & AC-06: Existing assignment rates remain locked after wage-rule changes."""
        pre_txns, pre_wages, pre_payments, pre_egp, pre_idr = await self._capture_pre_state()

        with patch("server.db", self.mock_db), patch("server.client", self.mock_client):
            # 1. Create a wage rule
            rule_doc = await admin_create_wage_rule(
                WageRuleInput(
                    task_category="finishing",
                    pricing_basis="per_unit",
                    standard_rate_le=65.0,
                    description="Standard finishing"
                ),
                self.owner
            )
            rule_id = rule_doc["id"]

            # 2. Create an assignment using that rule rate
            asn = await admin_create_work_assignment(
                "507f1f77bcf86cd799439011",
                WorkAssignmentCreateInput(
                    worker_id=str(self.worker_user["id"]),
                    order_item_id="itm_rak_kayu_01",
                    task_category="finishing",
                    pricing_basis="per_unit",
                    agreed_rate_le=65.0,
                    target_quantity=2,
                    wage_rule_id=rule_id,
                ),
                self.admin_manager
            )
            asn_id = asn["id"]

            # 3. Update the wage rule to a higher rate
            updated_rule = await admin_update_wage_rule(
                rule_id,
                WageRuleUpdate(standard_rate_le=90.0, description="Increased finishing rate"),
                self.owner
            )
            self.assertEqual(updated_rule["standard_rate_le"], 90.0)

            # 4. Verify existing assignment rate remains strictly locked at 65.0
            stored_asn = await self.mock_db.work_assignments.find_one({"_id": ObjectId(asn_id)})
            self.assertEqual(stored_asn["agreed_rate_le"], 65.0)

            # 5. Complete assignment and verify obligation accrues at locked 65.0 rate (65 * 2 = 130)
            await admin_update_assignment_progress(
                asn_id,
                WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=2),
                self.admin_manager
            )
            wob = await admin_verify_work_assignment(
                asn_id,
                WorkAssignmentVerifyInput(accepted_quantity=2),
                self.admin_manager
            )
            self.assertEqual(wob["rate_le"], 65.0)
            self.assertEqual(wob["total_amount_le"], 130.0)

        with patch("server.db", self.mock_db):
            await verify_finance_invariants(self.mock_db, pre_txns, pre_wages, pre_payments, pre_egp, pre_idr)

    async def test_TC_ASN_01_duplicate_active_assignment_rejected(self):
        """Test C7 & AC-07: Duplicate active assignment on same item, worker, and category is rejected with HTTP 409."""
        with patch("server.db", self.mock_db), patch("server.client", self.mock_client):
            # Create first active assignment
            await admin_create_work_assignment(
                "507f1f77bcf86cd799439011",
                WorkAssignmentCreateInput(
                    worker_id=str(self.worker_user["id"]),
                    order_item_id="itm_rak_kayu_01",
                    task_category="assembly",
                    pricing_basis="per_unit",
                    agreed_rate_le=50.0,
                    target_quantity=1,
                ),
                self.admin_manager
            )

            # Attempt to create duplicate active assignment
            with self.assertRaises(HTTPException) as ctx:
                await admin_create_work_assignment(
                    "507f1f77bcf86cd799439011",
                    WorkAssignmentCreateInput(
                        worker_id=str(self.worker_user["id"]),
                        order_item_id="itm_rak_kayu_01",
                        task_category="assembly",
                        pricing_basis="per_unit",
                        agreed_rate_le=50.0,
                        target_quantity=1,
                    ),
                    self.admin_manager
                )
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertIn("sudah memiliki penugasan aktif", ctx.exception.detail)

            # Verify exactly 1 assignment exists
            assignments = await self.mock_db.work_assignments.find({
                "order_item_id": "itm_rak_kayu_01",
                "worker_id": str(self.worker_user["id"]),
                "task_category": "assembly"
            }).to_list(10)
            self.assertEqual(len(assignments), 1)

    async def test_TC_ASN_02_multiple_workers_on_same_item(self):
        """Test C8 & AC-08: Multiple workers can receive independent assignments on the same order item."""
        pre_txns, pre_wages, pre_payments, pre_egp, pre_idr = await self._capture_pre_state()

        with patch("server.db", self.mock_db), patch("server.client", self.mock_client):
            # Worker 1 assigned to cutting
            asn1 = await admin_create_work_assignment(
                "507f1f77bcf86cd799439011",
                WorkAssignmentCreateInput(
                    worker_id=str(self.worker_user["id"]),
                    order_item_id="itm_rak_kayu_01",
                    task_category="cutting",
                    pricing_basis="per_unit",
                    agreed_rate_le=30.0,
                    target_quantity=2,
                ),
                self.admin_manager
            )

            # Worker 2 assigned to assembly on the exact same item
            asn2 = await admin_create_work_assignment(
                "507f1f77bcf86cd799439011",
                WorkAssignmentCreateInput(
                    worker_id=str(self.worker_admin["id"]),
                    order_item_id="itm_rak_kayu_01",
                    task_category="assembly",
                    pricing_basis="per_unit",
                    agreed_rate_le=45.0,
                    target_quantity=2,
                ),
                self.admin_manager
            )

        self.assertNotEqual(asn1["id"], asn2["id"])
        self.assertEqual(asn1["worker_id"], str(self.worker_user["id"]))
        self.assertEqual(asn2["worker_id"], str(self.worker_admin["id"]))
        self.assertEqual(asn1["agreed_rate_le"], 30.0)
        self.assertEqual(asn2["agreed_rate_le"], 45.0)

        with patch("server.db", self.mock_db):
            await verify_finance_invariants(self.mock_db, pre_txns, pre_wages, pre_payments, pre_egp, pre_idr)

    # =========================================================================
    # 12. Environment Policy Conflict & Resolution Tests (ENV-01 to ENV-15)
    # =========================================================================
    def test_ENV_01_production_and_development_conflict(self):
        """ENV-01: APP_ENV=development and ENV=production conflicts -> mode unknown, fallback False."""
        with patch.dict("os.environ", {"APP_ENV": "development", "ENV": "production", "ENVIRONMENT": ""}):
            self.assertEqual(get_environment_mode(), "unknown")
            self.assertFalse(is_standalone_fallback_permitted())

    def test_ENV_02_test_and_production_conflict(self):
        """ENV-02: APP_ENV=test and ENV=production conflicts -> mode unknown, fallback False."""
        with patch.dict("os.environ", {"APP_ENV": "test", "ENV": "production", "ENVIRONMENT": ""}):
            self.assertEqual(get_environment_mode(), "unknown")
            self.assertFalse(is_standalone_fallback_permitted())

    def test_ENV_03_production_and_development_conflict_reverse_order(self):
        """ENV-03: APP_ENV=production and ENV=development conflicts -> mode unknown, fallback False."""
        with patch.dict("os.environ", {"APP_ENV": "production", "ENV": "development", "ENVIRONMENT": ""}):
            self.assertEqual(get_environment_mode(), "unknown")
            self.assertFalse(is_standalone_fallback_permitted())

    def test_ENV_04_alias_normalization(self):
        """ENV-04: prod & production agree on production; dev & local agree on development."""
        with patch.dict("os.environ", {"APP_ENV": "prod", "ENV": "production", "ENVIRONMENT": ""}):
            self.assertEqual(get_environment_mode(), "production")
            self.assertFalse(is_standalone_fallback_permitted())

        with patch.dict("os.environ", {"APP_ENV": "dev", "ENV": "local", "ENVIRONMENT": "development"}):
            self.assertEqual(get_environment_mode(), "development")
            self.assertTrue(is_standalone_fallback_permitted())

    def test_ENV_05_unknown_value_conflicts_with_development(self):
        """ENV-05: APP_ENV=development and ENV=staging (unknown) -> mode unknown, fallback False."""
        with patch.dict("os.environ", {"APP_ENV": "development", "ENV": "staging", "ENVIRONMENT": ""}):
            self.assertEqual(get_environment_mode(), "unknown")
            self.assertFalse(is_standalone_fallback_permitted())

    def test_ENV_06_unknown_value_conflicts_with_test(self):
        """ENV-06: APP_ENV=test and ENV=unexpected-value -> mode unknown, fallback False."""
        with patch.dict("os.environ", {"APP_ENV": "test", "ENV": "unexpected-value", "ENVIRONMENT": ""}):
            self.assertEqual(get_environment_mode(), "unknown")
            self.assertFalse(is_standalone_fallback_permitted())

    def test_ENV_07_all_variables_missing(self):
        """ENV-07: All variables unset -> mode unknown, fallback False."""
        env_clean = {k: v for k, v in os.environ.items() if k not in ("APP_ENV", "ENV", "ENVIRONMENT")}
        with patch.dict("os.environ", env_clean, clear=True):
            self.assertEqual(get_environment_mode(), "unknown")
            self.assertFalse(is_standalone_fallback_permitted())

    def test_ENV_08_all_variables_empty(self):
        """ENV-08: All variables set to empty strings -> mode unknown, fallback False."""
        with patch.dict("os.environ", {"APP_ENV": "", "ENV": "", "ENVIRONMENT": ""}):
            self.assertEqual(get_environment_mode(), "unknown")
            self.assertFalse(is_standalone_fallback_permitted())

    def test_ENV_09_whitespace_only_values(self):
        """ENV-09: Whitespace-only values -> mode unknown, fallback False."""
        with patch.dict("os.environ", {"APP_ENV": "   ", "ENV": "\t", "ENVIRONMENT": "  "}):
            self.assertEqual(get_environment_mode(), "unknown")
            self.assertFalse(is_standalone_fallback_permitted())

    def test_ENV_10_case_and_whitespace_normalization(self):
        """ENV-10: Padded uppercase ' PRODUCTION ' resolves to production."""
        with patch.dict("os.environ", {"APP_ENV": " PRODUCTION ", "ENV": "", "ENVIRONMENT": ""}):
            self.assertEqual(get_environment_mode(), "production")
            self.assertFalse(is_standalone_fallback_permitted())

    def test_ENV_11_all_variables_agree_on_production(self):
        """ENV-11: All variables agree on production -> mode production, fallback False."""
        with patch.dict("os.environ", {"APP_ENV": "production", "ENV": "prod", "ENVIRONMENT": "PRODUCTION"}):
            self.assertEqual(get_environment_mode(), "production")
            self.assertFalse(is_standalone_fallback_permitted())

    def test_ENV_12_all_variables_agree_on_development(self):
        """ENV-12: All variables agree on development -> mode development, fallback True."""
        with patch.dict("os.environ", {"APP_ENV": "development", "ENV": "dev", "ENVIRONMENT": "local"}):
            self.assertEqual(get_environment_mode(), "development")
            self.assertTrue(is_standalone_fallback_permitted())

    def test_ENV_13_all_variables_agree_on_test(self):
        """ENV-13: All variables agree on test -> mode test, fallback True."""
        with patch.dict("os.environ", {"APP_ENV": "test", "ENV": "testing", "ENVIRONMENT": "test"}):
            self.assertEqual(get_environment_mode(), "test")
            self.assertTrue(is_standalone_fallback_permitted())

    async def test_ENV_14_end_to_end_fail_closed_verification_on_conflict(self):
        """ENV-14 & AC-09: Verification endpoint fails closed (HTTP 503) under conflicting environment variables."""
        pre_txns, pre_wages, pre_payments, pre_egp, pre_idr = await self._capture_pre_state()
        self.mock_client.fail_session = True

        with patch("server.db", self.mock_db), patch("server.client", self.mock_client), patch.dict("os.environ", {"APP_ENV": "development", "ENV": "production", "ENVIRONMENT": ""}):
            asn = await admin_create_work_assignment(
                "507f1f77bcf86cd799439011",
                WorkAssignmentCreateInput(
                    worker_id=str(self.worker_user["id"]),
                    order_item_id="itm_rak_kayu_01",
                    task_category="assembly",
                    pricing_basis="per_unit",
                    agreed_rate_le=100.0,
                    target_quantity=1,
                ),
                self.admin_manager
            )
            await admin_update_assignment_progress(
                asn["id"],
                WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=1),
                self.admin_manager
            )

            with self.assertRaises(HTTPException) as ctx:
                await admin_verify_work_assignment(
                    asn["id"],
                    WorkAssignmentVerifyInput(accepted_quantity=1),
                    self.admin_manager
                )
            self.assertEqual(ctx.exception.status_code, 503)
            self.assertIn("Fail-Closed", ctx.exception.detail)

            # Assert zero mutations occurred
            stored_asn = await self.mock_db.work_assignments.find_one({"_id": ObjectId(asn["id"])})
            self.assertEqual(stored_asn["status"], "ready_for_review")
            wob = await self.mock_db.wage_obligations.find_one({"work_assignment_id": asn["id"]})
            self.assertIsNone(wob)

        self.mock_client.fail_session = False
        with patch("server.db", self.mock_db):
            await verify_finance_invariants(self.mock_db, pre_txns, pre_wages, pre_payments, pre_egp, pre_idr)

    async def test_ENV_15_end_to_end_fail_closed_cancellation_on_conflict(self):
        """ENV-15 & AC-10: Cancellation endpoint fails closed (HTTP 503) under conflicting environment variables."""
        pre_txns, pre_wages, pre_payments, pre_egp, pre_idr = await self._capture_pre_state()

        # Complete assignment in normal transaction-capable mode
        with patch("server.db", self.mock_db), patch("server.client", self.mock_client):
            asn = await admin_create_work_assignment(
                "507f1f77bcf86cd799439011",
                WorkAssignmentCreateInput(
                    worker_id=str(self.worker_user["id"]),
                    order_item_id="itm_rak_kayu_01",
                    task_category="assembly",
                    pricing_basis="per_unit",
                    agreed_rate_le=100.0,
                    target_quantity=1,
                ),
                self.admin_manager
            )
            await admin_update_assignment_progress(
                asn["id"],
                WorkAssignmentProgressInput(status="ready_for_review", reported_quantity=1),
                self.admin_manager
            )
            wob = await admin_verify_work_assignment(
                asn["id"],
                WorkAssignmentVerifyInput(accepted_quantity=1),
                self.admin_manager
            )

        # Trigger cancellation with conflicting environment values and failed session
        self.mock_client.fail_session = True
        with patch("server.db", self.mock_db), patch("server.client", self.mock_client), patch.dict("os.environ", {"APP_ENV": "development", "ENV": "production", "ENVIRONMENT": ""}):
            with self.assertRaises(HTTPException) as ctx:
                await admin_cancel_work_assignment(
                    asn["id"],
                    WorkAssignmentCancelInput(reason="Defects found"),
                    self.owner
                )
            self.assertEqual(ctx.exception.status_code, 503)
            self.assertIn("Fail-Closed", ctx.exception.detail)

            # Assignment remains completed and obligation remains accrued (zero mutations)
            stored_asn = await self.mock_db.work_assignments.find_one({"_id": ObjectId(asn["id"])})
            self.assertEqual(stored_asn["status"], "completed")
            stored_wob = await self.mock_db.wage_obligations.find_one({"_id": ObjectId(wob["id"])})
            self.assertEqual(stored_wob["status"], "accrued")

        self.mock_client.fail_session = False
        with patch("server.db", self.mock_db):
            await verify_finance_invariants(self.mock_db, pre_txns, pre_wages, pre_payments, pre_egp, pre_idr)
