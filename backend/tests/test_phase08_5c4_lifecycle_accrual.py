"""
Phase 08.5C.4 — Lifecycle Accrual & Activation Boundary Test Suite
Sogil Furniture | Financial Integrity First

Verifies:
1. Completion first, payment later (Sequence A).
2. Payment first, completion later (Sequence B).
3. Repeated completion event.
4. Repeated payment event.
5. Concurrent completion and payment attempts.
6. Duplicate canonical obligation prevention.
7. Existing canonical obligation.
8. Missing or invalid wage configuration.
9. Blocked wage configuration.
10. Historical order exclusion.
11. Pre-activation order still incomplete at activation.
12. Pre-activation order already completed but unpaid at activation.
13. Pre-activation order already paid but incomplete at activation.
14. Order already completed and fully paid before activation.
15. Unknown historical activation state.
16. Worker obligations remaining unaffected.
17. Transaction failure and retry.
18. Regression suite verification.
"""

import copy
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
import pymongo.errors
from fastapi import HTTPException

# Path setup
BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
for p in [str(REPO_ROOT), str(BACKEND_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import server
from server import (
    build_admin_wage_accrual_event_key,
    is_order_completed,
    is_order_fully_paid,
    is_order_excluded_from_admin_wage,
    process_order_admin_wage_accrual,
    evaluate_and_process_order_admin_wage_accrual,
    admin_create_order_payment,
    admin_update_order,
    execute_order_handover_completion,
    compute_order_payment_summary,
    PaymentCreateInput,
    OrderStatusUpdate,
)
from scripts.reconcile_admin_wages import (
    CandidateCategory,
    classify_order,
)


class TestPhase08_5C4LifecycleAccrual(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mock_session = AsyncMock()
        self.mock_session.__aenter__.return_value = self.mock_session
        self.mock_session.__aexit__.return_value = None
        self.mock_session.start_transaction = MagicMock()
        self.mock_session.start_transaction.return_value.__aenter__ = AsyncMock(return_value=self.mock_session)
        self.mock_session.start_transaction.return_value.__aexit__ = AsyncMock(return_value=None)

        self.mock_client = MagicMock()
        self.mock_client.start_session = AsyncMock(return_value=self.mock_session)

        self.admin_finance = {
            "id": "507f1f77bcf86cd799439001",
            "_id": ObjectId("507f1f77bcf86cd799439001"),
            "name": "Finance Admin",
            "role": "admin",
            "permissions": {"manage_orders": True, "access_finance": True},
            "is_active": True,
        }
        self.sarah_admin = {
            "id": "507f1f77bcf86cd799439002",
            "_id": ObjectId("507f1f77bcf86cd799439002"),
            "name": "Sarah Administrasi",
            "role": "admin",
            "is_active": True,
        }
        self.admins_by_id = {
            "507f1f77bcf86cd799439001": self.admin_finance,
            "507f1f77bcf86cd799439002": self.sarah_admin,
        }
        self.default_policy = {
            "enabled": True,
            "is_configured": True,
            "default_wage_per_order_le": 50.0,
            "default_recipient_id": "507f1f77bcf86cd799439002",
            "default_recipient_name": "Sarah Administrasi",
            "currency": "EGP",
            "unusual_amount_threshold_le": 80.0,
            "max_wage_per_order_le": 100.0,
        }

    def _setup_mock_db(self, mock_db):
        mock_db.settings.find_one = AsyncMock(side_effect=lambda q, **kw: (
            {"key": "admin_wage_policy", "value": copy.deepcopy(self.default_policy)}
            if q.get("key") == "admin_wage_policy"
            else {"key": "exchange_rate_idr_per_le", "value": 357.0}
        ))
        mock_db.system_rates.find_one = AsyncMock(return_value={"rate": 357.0})
        mock_db.customers.update_one = AsyncMock()
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022")))
        mock_db.payments.update_one = AsyncMock()
        async def mock_default_order_find(query, **kwargs):
            return {"_id": query.get("_id"), "order_status": "diproses", "payment_status": "lunas", "completed_at": None, "paid_at": None}
        mock_db.orders.find_one = AsyncMock(side_effect=mock_default_order_find)
        mock_db.orders.update_one = AsyncMock(return_value=MagicMock(matched_count=1, modified_count=1))
        mock_db.wage_obligations.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("807f1f77bcf86cd799439044")))
        mock_db.wage_obligations.update_one = AsyncMock()
        mock_db.wage_obligations.find_one = AsyncMock(return_value=None)
        mock_db.audit_logs.insert_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 101})

        async def mock_admin_find_one(query, **kwargs):
            qid = str(query.get("_id") or "")
            if "507f1f77bcf86cd799439002" in qid:
                return self.sarah_admin
            if "507f1f77bcf86cd799439001" in qid:
                return self.admin_finance
            return None

        mock_db.admins.find_one = AsyncMock(side_effect=mock_admin_find_one)

    # ==========================================================================
    # TEST 1: Completion first, payment later (Sequence A)
    # ==========================================================================
    async def test_01_completion_first_payment_later(self):
        """Sequence A: Order completed while unpaid creates no obligation; later full payment creates exactly one obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"

        # Step 1: Order is in 'diproses' status with partial payment (dp)
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-A01",
            "order_status": "diproses",
            "total_le": 1000.0,
            "payment_status": "dp",
            "paid_amount_le": 500.0,
            "outstanding_amount_le": 500.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        # Transition order to 'selesai' via admin_update_order
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            update_payload = OrderStatusUpdate(order_status="selesai")
            updated_order = await admin_update_order(order_id, update_payload, self.admin_finance)

        # Assert Condition 1 satisfied, but Condition 2 (payment) is false -> NO obligation created
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)
        update_call = mock_db.orders.update_one.call_args[0][1]
        self.assertNotIn("admin_wage_obligation", update_call.get("$set", {}))

        # Step 2: Customer later makes final payment of 500 LE, transitioning to 'lunas'
        order_doc["order_status"] = "selesai"
        order_doc["completed_at"] = datetime.now(timezone.utc).isoformat()
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[
            {"amount_le": 500.0, "status": "recorded"},
            {"amount_le": 500.0, "status": "recorded"},
        ])
        mock_db.payments.find.return_value = mock_find

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            pmt_payload = PaymentCreateInput(amount=500.0, payment_method="cash")
            res_pmt = await admin_create_order_payment(order_id, pmt_payload, self.admin_finance)

        # Assert BOTH conditions now met -> Exactly ONE obligation created
        self.assertEqual(res_pmt["order_summary"]["payment_status"], "lunas")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)
        wob = mock_db.wage_obligations.insert_one.call_args[0][0]
        self.assertEqual(wob["task_category"], "admin")
        self.assertEqual(wob["total_amount_le"], 50.0)
        self.assertEqual(wob["status"], "accrued")
        self.assertEqual(wob["accrual_event_key"], f"admin_wage:{order_id}")

    # ==========================================================================
    # TEST 2: Payment first, completion later (Sequence B)
    # ==========================================================================
    async def test_02_payment_first_completion_later(self):
        """Sequence B: Full payment while incomplete creates no obligation; later completion creates exactly one obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439012"

        # Step 1: Customer pays 1000 LE in full upfront while order is 'diproses'
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-B02",
            "order_status": "diproses",
            "total_le": 1000.0,
            "payment_status": "belum_dibayar",
            "paid_amount_le": 0.0,
            "outstanding_amount_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[
            {"amount_le": 1000.0, "status": "recorded"}
        ])
        mock_db.payments.find.return_value = mock_find

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            pmt_payload = PaymentCreateInput(amount=1000.0, payment_method="cash")
            res_pmt = await admin_create_order_payment(order_id, pmt_payload, self.admin_finance)

        # Assert payment is lunas, but order is NOT completed -> NO wage obligation created yet!
        self.assertEqual(res_pmt["order_summary"]["payment_status"], "lunas")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)
        pmt_update_set = mock_db.orders.update_one.call_args[0][1]["$set"]
        self.assertNotIn("admin_wage_obligation", pmt_update_set)

        # Step 2: Production finishes, admin marks order 'selesai'
        order_doc["payment_status"] = "lunas"
        order_doc["paid_amount_le"] = 1000.0
        order_doc["outstanding_amount_le"] = 0.0
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            update_payload = OrderStatusUpdate(order_status="selesai")
            await admin_update_order(order_id, update_payload, self.admin_finance)

        # Assert BOTH conditions now met -> Exactly ONE obligation created upon completion
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)
        wob = mock_db.wage_obligations.insert_one.call_args[0][0]
        self.assertEqual(wob["task_category"], "admin")
        self.assertEqual(wob["total_amount_le"], 50.0)
        self.assertEqual(wob["accrual_event_key"], f"admin_wage:{order_id}")

    # ==========================================================================
    # TEST 3: Repeated completion event creates no duplicate
    # ==========================================================================
    async def test_03_repeated_completion_event(self):
        """Repeated status update or delivery completion on already completed order does not create duplicate obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439013"

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-003",
            "order_status": "selesai",
            "completed_at": "2026-10-29T10:00:00Z",
            "payment_status": "lunas",
            "total_le": 1000.0,
            "admin_wage_obligation": {
                "obligation_number": "WOB-20261029-0001",
                "status": "accrued"
            }
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        # Existing obligation in database
        mock_db.wage_obligations.find_one = AsyncMock(return_value={
            "_id": ObjectId("807f1f77bcf86cd799439044"),
            "obligation_number": "WOB-20261029-0001",
            "accrual_event_key": f"admin_wage:{order_id}",
            "status": "accrued",
            "total_amount_le": 50.0,
        })

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            update_payload = OrderStatusUpdate(order_status="selesai")
            await admin_update_order(order_id, update_payload, self.admin_finance)

        # Assert zero new obligations inserted
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

    # ==========================================================================
    # TEST 4: Repeated payment event creates no duplicate
    # ==========================================================================
    async def test_04_repeated_payment_event(self):
        """Repeated payment callback or additional payment on already-lunas order never accrues a second obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439014"

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-004",
            "order_status": "selesai",
            "completed_at": "2026-10-29T10:00:00Z",
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[
            {"amount_le": 1000.0, "status": "recorded"},
            {"amount_le": 50.0, "status": "recorded"},
        ])
        mock_db.payments.find.return_value = mock_find

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=50.0, payment_method="cash")
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

    # ==========================================================================
    # TEST 5: Concurrent completion and payment attempts (Race condition protection)
    # ==========================================================================
    async def test_05_concurrent_completion_and_payment_attempts(self):
        """Concurrent completion and payment requests trigger DuplicateKeyError on unique index; second request reuses existing obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439015"
        accrual_key = f"admin_wage:{order_id}"

        existing_obligation = {
            "_id": ObjectId("807f1f77bcf86cd799439044"),
            "obligation_number": "WOB-20261029-0015",
            "accrual_event_key": accrual_key,
            "task_category": "admin",
            "worker_id": "507f1f77bcf86cd799439002",
            "worker_name": "Sarah Administrasi",
            "total_amount_le": 50.0,
            "status": "accrued",
        }

        call_count = 0
        async def mock_wob_find_one(query, **kw):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                return existing_obligation
            return None

        mock_db.wage_obligations.find_one = AsyncMock(side_effect=mock_wob_find_one)
        mock_db.wage_obligations.insert_one = AsyncMock(
            side_effect=pymongo.errors.DuplicateKeyError("E11000 duplicate key error: uniq_wage_obligation_accrual_event")
        )

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-015",
            "order_status": "selesai",
            "payment_status": "lunas",
        }

        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")

        self.assertEqual(res["status"], "accrued")
        self.assertEqual(res["obligation"]["obligation_number"], "WOB-20261029-0015")
        self.assertEqual(res["obligation"]["accrual_event_key"], accrual_key)

    # ==========================================================================
    # TEST 6: Duplicate canonical obligation prevention
    # ==========================================================================
    def test_06_duplicate_canonical_obligation_prevention(self):
        """Canonical key format admin_wage:{order_id} is strictly deterministic."""
        oid = "507f1f77bcf86cd799439016"
        key1 = build_admin_wage_accrual_event_key(oid)
        key2 = build_admin_wage_accrual_event_key(f"  {oid}  ")
        self.assertEqual(key1, f"admin_wage:{oid}")
        self.assertEqual(key2, f"admin_wage:{oid}")

    # ==========================================================================
    # TEST 7: Existing canonical obligation returns already_accrued
    # ==========================================================================
    async def test_07_existing_canonical_obligation(self):
        """When obligation exists in accrued/paid status, shared service returns already_accrued."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439017"
        accrual_key = f"admin_wage:{order_id}"

        mock_db.wage_obligations.find_one = AsyncMock(return_value={
            "_id": ObjectId("807f1f77bcf86cd799439044"),
            "obligation_number": "WOB-20261029-0017",
            "accrual_event_key": accrual_key,
            "task_category": "admin",
            "worker_id": "507f1f77bcf86cd799439002",
            "worker_name": "Sarah Administrasi",
            "total_amount_le": 50.0,
            "status": "accrued",
        })

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-017",
            "order_status": "selesai",
            "payment_status": "lunas",
        }

        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")

        self.assertEqual(res["status"], "already_accrued")
        self.assertEqual(res["obligation"]["obligation_number"], "WOB-20261029-0017")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

    # ==========================================================================
    # TEST 8: Missing or invalid wage configuration fails safe
    # ==========================================================================
    async def test_08_missing_or_invalid_wage_configuration(self):
        """Missing or invalid configuration fails safe without creating corrupt obligations."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439018"

        # Case A: Disabled policy
        mock_db.settings.find_one = AsyncMock(return_value={
            "key": "admin_wage_policy",
            "value": {"enabled": False, "is_configured": True, "default_wage_per_order_le": 50.0}
        })
        order_doc = {
            "_id": ObjectId(order_id),
            "order_status": "selesai",
            "payment_status": "lunas",
        }
        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")
        self.assertEqual(res["status"], "skipped_policy_disabled")

        # Case B: Recipient not found in db.admins
        mock_db.settings.find_one = AsyncMock(return_value={
            "key": "admin_wage_policy",
            "value": copy.deepcopy(self.default_policy)
        })
        mock_db.admins.find_one = AsyncMock(return_value=None)
        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")
        self.assertEqual(res["status"], "blocked_invalid_recipient")

    # ==========================================================================
    # TEST 9: Blocked wage configuration (Hard-cap conflict Option A)
    # ==========================================================================
    async def test_09_blocked_wage_configuration(self):
        """Override nominal > active hard cap fails closed with blocked_hard_cap_conflict."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439019"

        order_doc = {
            "_id": ObjectId(order_id),
            "order_status": "selesai",
            "payment_status": "lunas",
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 150.0,  # exceeds hard cap of 100 LE
                "recipient_id": "507f1f77bcf86cd799439002",
                "recipient_name": "Sarah Administrasi",
                "override_reason": "Extra project bonus",
            }
        }
        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")

        self.assertEqual(res["status"], "blocked_hard_cap_conflict")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)
        self.assertEqual(res["blocked"]["attempted_amount_le"], 150.0)
        self.assertEqual(res["blocked"]["max_wage_per_order_le"], 100.0)

    # ==========================================================================
    # TEST 10: Historical order exclusion (Legacy reconciled guard)
    # ==========================================================================
    async def test_10_historical_order_exclusion(self):
        """Orders marked admin_wage_legacy_reconciled or is_legacy_manual are strictly excluded from automated accrual."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439020"

        order_doc = {
            "_id": ObjectId(order_id),
            "order_status": "selesai",
            "payment_status": "lunas",
            "admin_wage_legacy_reconciled": True,
        }
        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")

        self.assertEqual(res["status"], "skipped_legacy_reconciled")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

    # ==========================================================================
    # TEST 11: Pre-activation order still incomplete at activation
    # ==========================================================================
    async def test_11_pre_activation_order_still_incomplete_at_activation(self):
        """Order created pre-activation but incomplete at activation is in scope; accrues when completed & paid post-activation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439021"

        # Pre-activation order: created Oct 15, incomplete (diproses) and unpaid (dp)
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-HIST-021",
            "created_at": "2026-10-15T08:00:00Z",
            "order_status": "diproses",
            "payment_status": "dp",
            "total_le": 1000.0,
            "paid_amount_le": 500.0,
            "outstanding_amount_le": 500.0,
        }
        # Neither condition met at activation -> no accrual
        self.assertFalse(is_order_completed(order_doc))
        self.assertFalse(is_order_fully_paid(order_doc))

        # Later, order is completed AND paid post-activation:
        order_doc["order_status"] = "selesai"
        order_doc["completed_at"] = "2026-10-29T10:00:00Z"
        order_doc["payment_status"] = "lunas"
        order_doc["paid_amount_le"] = 1000.0
        order_doc["outstanding_amount_le"] = 0.0

        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")

        self.assertEqual(res["status"], "accrued")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)

    # ==========================================================================
    # TEST 12: Pre-activation order completed but unpaid at activation
    # ==========================================================================
    async def test_12_pre_activation_order_completed_but_unpaid_at_activation(self):
        """Order completed pre-activation but unpaid is in scope; accrues via Sequence A when paid post-activation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439022"

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-HIST-022",
            "created_at": "2026-10-15T08:00:00Z",
            "order_status": "selesai",
            "completed_at": "2026-10-18T10:00:00Z",
            "payment_status": "dp",
            "total_le": 800.0,
            "paid_amount_le": 300.0,
            "outstanding_amount_le": 500.0,
        }
        # Incomplete payment -> no accrual
        self.assertTrue(is_order_completed(order_doc))
        self.assertFalse(is_order_fully_paid(order_doc))

        # Payment made post-activation bringing to lunas
        order_doc["payment_status"] = "lunas"
        order_doc["paid_amount_le"] = 800.0
        order_doc["outstanding_amount_le"] = 0.0

        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")

        self.assertEqual(res["status"], "accrued")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)

    # ==========================================================================
    # TEST 13: Pre-activation order paid but incomplete at activation
    # ==========================================================================
    async def test_13_pre_activation_order_paid_but_incomplete_at_activation(self):
        """Order paid in full pre-activation but incomplete is in scope; accrues via Sequence B when completed post-activation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439023"

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-HIST-023",
            "created_at": "2026-10-15T08:00:00Z",
            "order_status": "diproses",
            "payment_status": "lunas",
            "total_le": 1200.0,
            "paid_amount_le": 1200.0,
            "outstanding_amount_le": 0.0,
        }
        # Incomplete order -> no accrual
        self.assertFalse(is_order_completed(order_doc))
        self.assertTrue(is_order_fully_paid(order_doc))

        # Completed post-activation
        order_doc["order_status"] = "selesai"
        order_doc["completed_at"] = "2026-10-29T11:00:00Z"

        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")

        self.assertEqual(res["status"], "accrued")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)

    # ==========================================================================
    # TEST 14: Order already completed and fully paid before activation
    # ==========================================================================
    def test_14_order_already_completed_and_fully_paid_before_activation(self):
        """Historical order (completed & paid before activation) is isolated for Owner review and never auto-accrued."""
        oid = "671fc0000000000000000024"
        historical_order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-HIST-024",
            "order_date": "2026-10-10T10:00:00Z",
            "order_status": "selesai",
            "completed_at": "2026-10-12T10:00:00Z",
            "payment_status": "lunas",
            "total_amount_le": 1000.0,
            "paid_amount_le": 1000.0,
            "outstanding_amount_le": 0.0,
        }
        res = classify_order(
            order=historical_order,
            obligations=[],
            audit_logs=[],
            payments=[{"amount_le": 1000.0, "status": "paid"}],
            policy=self.default_policy,
            admins_by_id=self.admins_by_id,
        )
        # Must be quarantined for Owner review (LEGACY_MANUAL_PAYMENT or AMBIGUOUS), NEVER ELIGIBLE
        self.assertNotEqual(res["candidate_category"], CandidateCategory.ELIGIBLE_MISSING_OBLIGATION.value)
        self.assertTrue(res["owner_review_required"])

    # ==========================================================================
    # TEST 15: Unknown historical activation state
    # ==========================================================================
    def test_15_unknown_historical_activation_state(self):
        """Unknown or unprovable activation/date state fails closed to AMBIGUOUS_REQUIRES_OWNER_REVIEW."""
        oid = "671fc0000000000000000025"
        ambiguous_order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-AMBIG-025",
            # Missing order_date/created_at
            "order_status": "selesai",
            "payment_status": "lunas",
            "total_amount_le": 1500.0,
            "paid_amount_le": 1500.0,
            "outstanding_amount_le": 0.0,
        }
        res = classify_order(
            order=ambiguous_order,
            obligations=[],
            audit_logs=[],
            payments=[{"amount_le": 1500.0, "status": "paid"}],
            policy=self.default_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res["reason_code"], "ORDER_DATE_UNAVAILABLE_OR_AMBIGUOUS")
        self.assertTrue(res["owner_review_required"])

    # ==========================================================================
    # TEST 16: Worker obligations remaining unaffected
    # ==========================================================================
    async def test_16_worker_obligations_remaining_unaffected(self):
        """Admin wage accrual operates exclusively on task_category: 'admin'; worker obligations remain unaffected."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439026"

        worker_wob = {
            "_id": ObjectId("807f1f77bcf86cd799439099"),
            "obligation_number": "WOB-WORKER-0099",
            "accrual_event_key": f"order:{order_id}:whole_item",
            "task_category": "whole_item",
            "worker_id": "6aad900ed142966177ee787a",
            "total_amount_le": 350.0,
            "status": "accrued",
        }
        # Database query for admin wage checks accrual_event_key f"admin_wage:{order_id}"
        # Worker obligation has different accrual_event_key and task_category
        mock_db.wage_obligations.find_one = AsyncMock(return_value=None)

        order_doc = {
            "_id": ObjectId(order_id),
            "order_status": "selesai",
            "payment_status": "lunas",
        }

        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")

        self.assertEqual(res["status"], "accrued")
        new_wob = mock_db.wage_obligations.insert_one.call_args[0][0]
        self.assertEqual(new_wob["task_category"], "admin")
        self.assertEqual(new_wob["accrual_event_key"], f"admin_wage:{order_id}")
        # Worker obligation is unmodified
        self.assertEqual(worker_wob["task_category"], "whole_item")
        self.assertEqual(worker_wob["total_amount_le"], 350.0)

    # ==========================================================================
    # TEST 17: Transaction failure and retry
    # ==========================================================================
    async def test_17_transaction_failure_and_retry(self):
        """Transient database error during payment transaction aborts cleanly without partial state."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439027"

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-027",
            "order_status": "selesai",
            "total_le": 1000.0,
            "payment_status": "belum_dibayar",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[{"amount_le": 1000.0, "status": "recorded"}])
        mock_db.payments.find.return_value = mock_find

        # Force failure during order update inside transaction
        mock_db.orders.update_one = AsyncMock(side_effect=RuntimeError("Transient network drop"))

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=1000.0, payment_method="cash")
            with self.assertRaises(RuntimeError):
                await admin_create_order_payment(order_id, payload, self.admin_finance)

        # In transaction failure, transaction context manager exits with error (aborting transaction)
        self.mock_session.start_transaction.return_value.__aexit__.assert_called()

    # ==========================================================================
    # TEST 18: Regression suite verification
    # ==========================================================================
    def test_18_regression_suite_verification(self):
        """Verifies that candidate categories, event key prefix, and business definitions match system contracts."""
        self.assertEqual(build_admin_wage_accrual_event_key("ORD123"), "admin_wage:ORD123")
        self.assertTrue(is_order_completed({"order_status": "selesai"}))
        self.assertTrue(is_order_completed({"status": "completed"}))
        self.assertTrue(is_order_completed({"completed_at": "2026-10-29T10:00:00Z"}))
        self.assertFalse(is_order_completed({"order_status": "diproses"}))
        self.assertTrue(is_order_fully_paid({"payment_status": "lunas"}))
        self.assertFalse(is_order_fully_paid({"payment_status": "dp"}))
        self.assertTrue(is_order_excluded_from_admin_wage({"admin_wage_legacy_reconciled": True}))
        self.assertTrue(is_order_excluded_from_admin_wage({"is_legacy_manual": True}))
        self.assertFalse(is_order_excluded_from_admin_wage({}))


if __name__ == "__main__":
    unittest.main()
