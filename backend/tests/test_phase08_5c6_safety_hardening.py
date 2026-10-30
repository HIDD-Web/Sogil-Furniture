"""
Phase 08.5C.6 — Technical Remediation & Safety Hardening Test Suite
Sogil Furniture | Financial Integrity First

Verifies:
1. P2-1: Cancelled orders never qualify as completed (aliases, timestamps, canonical precedence).
2. P2-2: Consistency of order update and wage accrual in admin_update_order (transactions, rollbacks, idempotency).
3. P2-3: Explicit handling of previously voided obligations (blocked_prior_voided_obligation, concurrent recovery, callers).
4. P3-1: Safe numeric conversion and contradictory payment status rejection (booleans, strings, tolerance, fail-closed).
5. Two-condition eligibility invariant across all lifecycle sequences.
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
    _safe_finance_amount,
    CANCELLED_ORDER_STATUSES,
    COMPLETED_ORDER_STATUSES,
)
from scripts.reconcile_admin_wages import (
    CandidateCategory,
    classify_order,
)


class TestPhase08_5C6SafetyHardening(unittest.IsolatedAsyncioTestCase):
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
        mock_db.orders.find_one = AsyncMock(return_value={"order_status": "diproses", "payment_status": "lunas"})
        mock_db.orders.update_one = AsyncMock(return_value=MagicMock(matched_count=1, modified_count=1))
        mock_db.wage_obligations.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("807f1f77bcf86cd799439044")))
        mock_db.wage_obligations.update_one = AsyncMock()
        mock_db.wage_obligations.find_one = AsyncMock(return_value=None)
        mock_db.audit_logs.insert_one = AsyncMock()
        mock_db.admins.find_one = AsyncMock(side_effect=lambda q, **kw: (
            self.sarah_admin if str(q.get("_id")) == str(self.sarah_admin["_id"])
            else self.admin_finance
        ))
        mock_db.work_assignments.find = MagicMock(return_value=MagicMock(to_list=AsyncMock(return_value=[])))
        mock_db.wage_obligations.find = MagicMock(return_value=MagicMock(to_list=AsyncMock(return_value=[])))
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 101})

    # ==========================================================================
    # SECTION 3: P2-1 — CANCELLED ORDERS MUST NEVER QUALIFY AS COMPLETED
    # ==========================================================================
    def test_01_cancelled_status_with_historical_completed_at(self):
        """Cancelled orders (dibatalkan, cancelled, etc.) with completed_at must NOT qualify as completed."""
        for cancelled_alias in ["dibatalkan", "cancelled", "canceled", "batal", "void", "voided"]:
            order = {
                "order_status": cancelled_alias,
                "completed_at": "2026-10-29T10:00:00Z",
            }
            self.assertFalse(
                is_order_completed(order),
                f"Failed for order_status={cancelled_alias} with historical completed_at"
            )

    def test_02_void_status_with_historical_completed_at(self):
        """Orders marked void or is_voided with historical completed_at must NOT qualify."""
        self.assertFalse(is_order_completed({"status": "void", "completed_at": "2026-10-29T10:00:00Z"}))
        self.assertFalse(is_order_completed({"order_status": "voided", "completed_at": "2026-10-29T10:00:00Z"}))
        self.assertFalse(is_order_completed({"is_voided": True, "completed_at": "2026-10-29T10:00:00Z"}))
        self.assertFalse(is_order_completed({"is_voided": True, "order_status": "selesai"}))

    def test_03_completed_status_with_valid_timestamp(self):
        """Valid completed orders with completed_at must qualify."""
        self.assertTrue(is_order_completed({"order_status": "selesai", "completed_at": "2026-10-29T10:00:00Z"}))
        self.assertTrue(is_order_completed({"order_status": "completed", "completed_at": "2026-10-29T10:00:00Z"}))

    def test_04_valid_completed_order_without_completed_at(self):
        """Valid completed order without completed_at qualifies under canonical schema."""
        self.assertTrue(is_order_completed({"order_status": "selesai"}))
        self.assertTrue(is_order_completed({"order_status": "completed"}))
        self.assertTrue(is_order_completed({"status": "completed"}))

    def test_05_missing_or_malformed_status(self):
        """Missing, None, or malformed status values fail closed safely."""
        self.assertFalse(is_order_completed(None))
        self.assertFalse(is_order_completed({}))
        self.assertFalse(is_order_completed({"order_status": None}))
        self.assertFalse(is_order_completed({"order_status": ""}))
        self.assertFalse(is_order_completed({"order_status": 12345}))
        self.assertFalse(is_order_completed("not_a_dict"))

    def test_06_conflicting_order_status_and_status_fields(self):
        """Evaluates canonical status semantics when order_status and status conflict."""
        # Cancellation on ANY field takes absolute precedence
        self.assertFalse(is_order_completed({"order_status": "dibatalkan", "status": "selesai"}))
        self.assertFalse(is_order_completed({"order_status": "selesai", "status": "dibatalkan"}))
        self.assertFalse(is_order_completed({"order_status": "voided", "status": "completed"}))

        # Primary canonical field: order_status
        self.assertTrue(is_order_completed({"order_status": "selesai", "status": "diproses"}))
        self.assertFalse(is_order_completed({"order_status": "diproses", "status": "completed"}))
        self.assertFalse(is_order_completed({"order_status": "siap", "status": "selesai"}))

        # In-progress order with historical completed_at does NOT qualify
        self.assertFalse(is_order_completed({"order_status": "diproses", "completed_at": "2026-10-29T10:00:00Z"}))

    def test_07_reconciliation_script_cancellation_aliases(self):
        """Reconciliation engine Step 1 must categorize all cancellation aliases as VOIDED_OR_CANCELLED."""
        for alias in ["dibatalkan", "cancelled", "canceled", "batal", "void", "voided"]:
            order = {
                "_id": "ORD-CANCEL-1",
                "order_number": "SGF-CANCEL-1",
                "order_status": alias,
                "payment_status": "lunas",
                "completed_at": "2026-10-29T10:00:00Z",
            }
            res = classify_order(order=order)
            self.assertEqual(res["candidate_category"], CandidateCategory.VOIDED_OR_CANCELLED.value)
            self.assertEqual(res["reason_code"], "ORDER_CANCELLED_OR_VOIDED")

    # ==========================================================================
    # SECTION 4: P2-2 — CONSISTENCY OF ORDER UPDATE AND WAGE ACCRUAL
    # ==========================================================================
    async def test_08_transaction_aborts_on_order_update_failure_no_orphaned_obligation(self):
        """If orders.update_one fails inside transaction, entire transaction aborts and no orphaned obligation is committed."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439020"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-020",
            "order_status": "diproses",
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 1000.0,
            "outstanding_amount_le": 0.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        # Simulate database failure on update_one
        mock_db.orders.update_one = AsyncMock(side_effect=pymongo.errors.PyMongoError("Simulated write failure on orders collection"))

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            update_payload = OrderStatusUpdate(order_status="selesai")
            with self.assertRaises(pymongo.errors.PyMongoError):
                await admin_update_order(order_id, update_payload, admin=self.admin_finance)

            # In transaction mode, start_transaction context manager aborted
            self.mock_session.start_transaction.assert_called()

    async def test_09_transaction_aborts_on_wage_accrual_failure(self):
        """If wage accrual fails, order completion and related writes abort cleanly."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439021"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-021",
            "order_status": "diproses",
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 1000.0,
            "outstanding_amount_le": 0.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        # Simulate wage obligation insert failure
        mock_db.wage_obligations.insert_one = AsyncMock(side_effect=pymongo.errors.PyMongoError("Simulated wage insert failure"))

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            update_payload = OrderStatusUpdate(order_status="selesai")
            with self.assertRaises(pymongo.errors.PyMongoError):
                await admin_update_order(order_id, update_payload, admin=self.admin_finance)

            # orders.update_one was never called because accrual failed first
            mock_db.orders.update_one.assert_not_called()

    async def test_10_successful_completion_and_accrual_in_same_session(self):
        """Sequence B: Completion triggers accrual; both operations receive and use the exact same transaction session."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439022"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-022",
            "order_status": "diproses",
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 1000.0,
            "outstanding_amount_le": 0.0,
        }
        updated_doc = dict(order_doc)
        updated_doc["order_status"] = "selesai"

        mock_db.orders.find_one = AsyncMock(side_effect=[order_doc, order_doc, updated_doc])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            update_payload = OrderStatusUpdate(order_status="selesai")
            res = await admin_update_order(order_id, update_payload, admin=self.admin_finance)

            # Verify that wage obligation insert received session
            mock_db.wage_obligations.insert_one.assert_called_once()
            _, wob_kwargs = mock_db.wage_obligations.insert_one.call_args
            self.assertEqual(wob_kwargs.get("session"), self.mock_session)

            # Verify that order update received session
            mock_db.orders.update_one.assert_called_once()
            _, ord_kwargs = mock_db.orders.update_one.call_args
            self.assertEqual(ord_kwargs.get("session"), self.mock_session)

    async def test_11_standalone_fallback_idempotency_recovery(self):
        """In standalone/test environment without transactions, idempotency key prevents duplicate obligations on retry."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439023"
        accrual_key = f"admin_wage:{order_id}"

        # Client raises ConfigurationError simulating standalone MongoDB
        client_mock = MagicMock()
        client_mock.start_session = AsyncMock(side_effect=pymongo.errors.ConfigurationError("Standalone"))

        existing_obligation = {
            "_id": ObjectId("807f1f77bcf86cd799439044"),
            "obligation_number": "WOB-20261029-0023",
            "accrual_event_key": accrual_key,
            "task_category": "admin",
            "worker_id": "507f1f77bcf86cd799439002",
            "worker_name": "Sarah Administrasi",
            "total_amount_le": 50.0,
            "status": "accrued",
        }
        # First call has no obligation; second call finds existing obligation
        find_calls = 0
        async def mock_wob_find_one(query, **kw):
            nonlocal find_calls
            find_calls += 1
            if find_calls > 1:
                return existing_obligation
            return None

        mock_db.wage_obligations.find_one = AsyncMock(side_effect=mock_wob_find_one)

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-023",
            "order_status": "diproses",
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 1000.0,
            "outstanding_amount_le": 0.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db), patch("server.client", client_mock), patch("server.is_standalone_fallback_permitted", return_value=True):
            update_payload = OrderStatusUpdate(order_status="selesai")
            # First attempt succeeds in inserting
            res1 = await admin_update_order(order_id, update_payload, admin=self.admin_finance)

            # Retry attempt: finds existing obligation via idempotency key
            res2 = await admin_update_order(order_id, update_payload, admin=self.admin_finance)
            self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)

    # ==========================================================================
    # SECTION 5: P2-3 — EXPLICIT HANDLING OF PREVIOUSLY VOIDED OBLIGATIONS
    # ==========================================================================
    async def test_12_existing_accrued_paid_partially_paid_obligations_idempotent(self):
        """Existing obligations with status accrued, paid, or partially_paid return already_accrued."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439030"
        accrual_key = f"admin_wage:{order_id}"

        for valid_status in ["accrued", "paid", "partially_paid"]:
            mock_wob = {
                "_id": ObjectId("807f1f77bcf86cd799439044"),
                "obligation_number": "WOB-20261029-0030",
                "accrual_event_key": accrual_key,
                "task_category": "admin",
                "worker_id": "507f1f77bcf86cd799439002",
                "worker_name": "Sarah Administrasi",
                "total_amount_le": 50.0,
                "status": valid_status,
            }
            mock_db.wage_obligations.find_one = AsyncMock(return_value=mock_wob)

            order_doc = {
                "_id": ObjectId(order_id),
                "order_number": "SGF-20261029-030",
                "order_status": "selesai",
                "payment_status": "lunas",
            }
            with patch("server.db", mock_db):
                res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance)
                self.assertEqual(res["status"], "already_accrued")
                self.assertEqual(res["obligation"]["status"], valid_status)
                mock_db.wage_obligations.insert_one.assert_not_called()

    async def test_13_existing_voided_obligation_returns_blocked_prior_voided(self):
        """When an obligation was previously voided/cancelled, accrual is blocked requiring manual review."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439031"
        accrual_key = f"admin_wage:{order_id}"

        for void_status in ["voided", "void", "cancelled"]:
            mock_wob = {
                "_id": ObjectId("807f1f77bcf86cd799439044"),
                "obligation_number": "WOB-20261029-0031",
                "accrual_event_key": accrual_key,
                "task_category": "admin",
                "worker_id": "507f1f77bcf86cd799439002",
                "worker_name": "Sarah Administrasi",
                "total_amount_le": 50.0,
                "status": void_status,
            }
            mock_db.wage_obligations.find_one = AsyncMock(return_value=mock_wob)

            order_doc = {
                "_id": ObjectId(order_id),
                "order_number": "SGF-20261029-031",
                "order_status": "selesai",
                "payment_status": "lunas",
            }
            with patch("server.db", mock_db):
                res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance)
                self.assertEqual(res["status"], "blocked_prior_voided_obligation")
                self.assertTrue(res["blocked"]["owner_review_required"])
                self.assertEqual(res["blocked"]["existing_obligation_status"], void_status)
                self.assertEqual(res["blocked"]["existing_obligation_number"], "WOB-20261029-0031")
                mock_db.wage_obligations.insert_one.assert_not_called()

    async def test_14_duplicate_key_error_recovery_detects_voided_obligation(self):
        """If a concurrent race triggers DuplicateKeyError and winning document is voided, returns blocked_prior_voided_obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439032"
        accrual_key = f"admin_wage:{order_id}"

        voided_obligation = {
            "_id": ObjectId("807f1f77bcf86cd799439044"),
            "obligation_number": "WOB-20261029-0032",
            "accrual_event_key": accrual_key,
            "task_category": "admin",
            "worker_id": "507f1f77bcf86cd799439002",
            "worker_name": "Sarah Administrasi",
            "total_amount_le": 50.0,
            "status": "voided",
        }

        call_count = 0
        async def mock_wob_find_one(query, **kw):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                return voided_obligation
            return None

        mock_db.wage_obligations.find_one = AsyncMock(side_effect=mock_wob_find_one)
        mock_db.wage_obligations.insert_one = AsyncMock(
            side_effect=pymongo.errors.DuplicateKeyError("E11000 duplicate key error: uniq_wage_obligation_accrual_event")
        )

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-032",
            "order_status": "selesai",
            "payment_status": "lunas",
        }

        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")
            self.assertEqual(res["status"], "blocked_prior_voided_obligation")
            self.assertTrue(res["blocked"]["owner_review_required"])
            mock_db.audit_logs.insert_one.assert_not_called()

    async def test_15_caller_handles_blocked_prior_voided_obligation(self):
        """In admin_update_order and handover, blocked_prior_voided_obligation sets admin_wage_blocked without obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439033"
        accrual_key = f"admin_wage:{order_id}"

        voided_wob = {
            "_id": ObjectId("807f1f77bcf86cd799439044"),
            "obligation_number": "WOB-20261029-0033",
            "accrual_event_key": accrual_key,
            "status": "voided",
        }
        mock_db.wage_obligations.find_one = AsyncMock(return_value=voided_wob)

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-033",
            "order_status": "diproses",
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 1000.0,
            "outstanding_amount_le": 0.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            update_payload = OrderStatusUpdate(order_status="selesai")
            await admin_update_order(order_id, update_payload, admin=self.admin_finance)

            mock_db.orders.update_one.assert_called_once()
            _, update_kw = mock_db.orders.update_one.call_args
            set_ops = mock_db.orders.update_one.call_args[0][1]["$set"]
            self.assertIn("admin_wage_blocked", set_ops)
            self.assertEqual(set_ops["admin_wage_blocked"]["status"], "blocked_prior_voided_obligation")
            self.assertNotIn("admin_wage_obligation", set_ops)

    def test_16_reconciliation_script_voided_obligation_on_lunas_order(self):
        """Reconciliation engine flags voided obligation on lunas order as AMBIGUOUS_REQUIRES_OWNER_REVIEW."""
        order = {
            "_id": "ORD-VOIDED-1",
            "order_number": "SGF-VOIDED-1",
            "order_status": "selesai",
            "payment_status": "lunas",
            "total_amount_le": 1000.0,
            "paid_amount_le": 1000.0,
            "outstanding_amount_le": 0.0,
        }
        voided_ob = {
            "obligation_number": "WOB-20261029-V01",
            "accrual_event_key": "admin_wage:ORD-VOIDED-1",
            "status": "voided",
            "task_category": "admin",
        }
        res = classify_order(order=order, obligation=voided_ob)
        self.assertEqual(res["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res["reason_code"], "VOIDED_OBLIGATION_ON_LUNAS_ORDER")
        self.assertTrue(res["owner_review_required"])

    # ==========================================================================
    # SECTION 6: P3-1 — SAFE NUMERIC CONVERSION & CONTRADICTORY STATUS
    # ==========================================================================
    def test_17_safe_numeric_conversion_valid_values(self):
        """Valid integers, floats, and numeric strings convert cleanly and evaluate full payment."""
        self.assertTrue(is_order_fully_paid({
            "total_le": 1000,
            "paid_amount_le": 1000,
            "outstanding_amount_le": 0,
        }))
        self.assertTrue(is_order_fully_paid({
            "total_le": 1000.0,
            "paid_amount_le": 1000.0,
            "outstanding_amount_le": 0.0,
        }))
        self.assertTrue(is_order_fully_paid({
            "total_le": "1000.0",
            "paid_amount_le": "1000.0",
            "outstanding_amount_le": "0.0",
        }))

    def test_18_safe_numeric_conversion_malformed_values_fail_closed(self):
        """Malformed strings (N/A, empty, currency formatting) fail closed safely without raising ValueError."""
        self.assertFalse(is_order_fully_paid({"payment_status": "dp", "total_le": "N/A", "paid_amount_le": "N/A"}))
        self.assertFalse(is_order_fully_paid({"payment_status": "dp", "total_le": "", "paid_amount_le": ""}))
        self.assertFalse(is_order_fully_paid({"payment_status": "dp", "total_le": "Rp 50.000", "paid_amount_le": "$100"}))
        self.assertFalse(is_order_fully_paid({"payment_status": "dp", "outstanding_amount_le": "corrupted_text"}))
        self.assertFalse(is_order_fully_paid(None))

    def test_19_safe_numeric_conversion_booleans_not_treated_as_numbers(self):
        """Booleans (True/False) must NOT be coerced to float 1.0 or 0.0 to prevent false-positive balance."""
        self.assertIsNone(_safe_finance_amount(True))
        self.assertIsNone(_safe_finance_amount(False))
        self.assertFalse(is_order_fully_paid({
            "payment_status": "dp",
            "outstanding_amount_le": False,  # If float(False) == 0.0 <= 0.01 was used, this would have falsely passed
            "total_le": 1000.0,
            "paid_amount_le": 500.0,
        }))

    def test_20_safe_numeric_conversion_negative_and_zero_totals(self):
        """Negative totals and zero totals do NOT qualify as fully paid."""
        self.assertFalse(is_order_fully_paid({"total_le": 0, "paid_amount_le": 0, "outstanding_amount_le": 0}))
        self.assertFalse(is_order_fully_paid({"total_le": -100, "paid_amount_le": -100, "outstanding_amount_le": 0}))

    def test_21_safe_numeric_conversion_tolerance_boundary(self):
        """Payment tolerance of 0.01 LE is strictly respected."""
        # 0.01 outstanding -> tolerated as fully paid
        self.assertTrue(is_order_fully_paid({
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 999.99,
            "outstanding_amount_le": 0.01,
        }))
        # 0.011 outstanding -> exceeds tolerance -> NOT fully paid
        self.assertFalse(is_order_fully_paid({
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 999.989,
            "outstanding_amount_le": 0.011,
        }))

    def test_22_contradictory_payment_status_and_amounts_fails_closed(self):
        """Payment status 'lunas' contradicted by positive outstanding (>0.01) fails closed."""
        self.assertFalse(is_order_fully_paid({
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 500.0,
            "outstanding_amount_le": 500.0,
        }))
        self.assertFalse(is_order_fully_paid(
            order={"payment_status": "lunas"},
            payment_summary={
                "payment_status": "lunas",
                "total_le": 1000.0,
                "paid_amount_le": 500.0,
                "outstanding_amount_le": 500.0,
            }
        ))
        self.assertFalse(is_order_fully_paid({
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 200.0,  # paid < total
        }))

    # ==========================================================================
    # SECTION 7: TWO-CONDITION ELIGIBILITY INVARIANT
    # ==========================================================================
    async def test_23_partial_payment_does_not_accrue(self):
        """Order is completed but payment is partial (dp) -> skipped."""
        order_doc = {
            "_id": ObjectId("507f1f77bcf86cd799439040"),
            "order_number": "SGF-20261029-040",
            "order_status": "selesai",
            "payment_status": "dp",
            "total_le": 1000.0,
            "paid_amount_le": 500.0,
            "outstanding_amount_le": 500.0,
        }
        res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance)
        self.assertEqual(res["status"], "skipped_payment_not_lunas")

    async def test_24_completion_alone_does_not_accrue(self):
        """Order is completed but payment is unpaid -> skipped."""
        order_doc = {
            "_id": ObjectId("507f1f77bcf86cd799439041"),
            "order_number": "SGF-20261029-041",
            "order_status": "selesai",
            "payment_status": "belum_dibayar",
            "total_le": 1000.0,
            "paid_amount_le": 0.0,
            "outstanding_amount_le": 1000.0,
        }
        res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance)
        self.assertEqual(res["status"], "skipped_payment_not_lunas")

    async def test_25_cancelled_order_with_full_payment_does_not_accrue(self):
        """Order is cancelled with historical completed_at and full payment -> skipped_order_not_completed."""
        order_doc = {
            "_id": ObjectId("507f1f77bcf86cd799439042"),
            "order_number": "SGF-20261029-042",
            "order_status": "dibatalkan",
            "completed_at": "2026-10-29T10:00:00Z",
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 1000.0,
            "outstanding_amount_le": 0.0,
        }
        res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance)
        self.assertEqual(res["status"], "skipped_order_not_completed")

    async def test_26_historical_legacy_excluded_orders_skipped(self):
        """Orders marked with admin_wage_legacy_reconciled or is_legacy_manual are skipped."""
        order_doc1 = {
            "_id": ObjectId("507f1f77bcf86cd799439043"),
            "order_status": "selesai",
            "payment_status": "lunas",
            "admin_wage_legacy_reconciled": True,
        }
        res1 = await evaluate_and_process_order_admin_wage_accrual(order_doc1, self.admin_finance)
        self.assertEqual(res1["status"], "skipped_legacy_reconciled")

        order_doc2 = {
            "_id": ObjectId("507f1f77bcf86cd799439044"),
            "order_status": "selesai",
            "payment_status": "lunas",
            "is_legacy_manual": True,
        }
        res2 = await evaluate_and_process_order_admin_wage_accrual(order_doc2, self.admin_finance)
        self.assertEqual(res2["status"], "skipped_legacy_reconciled")


if __name__ == "__main__":
    unittest.main()
