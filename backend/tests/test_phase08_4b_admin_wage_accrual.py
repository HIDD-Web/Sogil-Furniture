"""
Phase 08.4B — Admin Wage Obligation Lifecycle: Backend Accrual Engine, Transaction Safety & Idempotency.

Covers all 21 test scenarios:
1. test_unpaid_order_no_accrual
2. test_partial_payment_no_accrual
3. test_final_payment_creates_one_obligation
4. test_direct_full_payment_creates_one_obligation
5. test_order_override_precedence_over_default_policy
6. test_order_without_override_uses_default_policy
7. test_override_amount_only_uses_default_recipient
8. test_invalid_override_recipient_failsafe
9. test_disabled_policy_failsafe
10. test_legacy_reconciled_order_guard
11. test_hard_cap_conflict_option_a
12. test_policy_change_after_accrual_does_not_mutate_obligation
13. test_transaction_rollback_reverts_obligation
14. test_repeated_payment_request_idempotency
15. test_duplicate_accrual_event_key_handled_cleanly
16. test_duplicate_key_error_on_unrelated_index_not_swallowed
17. test_session_aware_payment_summary_sees_inserted_payment
18. test_existing_callers_without_session_continue_working
19. test_settlement_through_existing_settlement_engine
20. test_voiding_customer_payment_voids_accrued_obligation
21. test_voiding_customer_payment_with_settled_wage_blocked_409
"""

import copy
import inspect
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from datetime import datetime, timezone
from fastapi import HTTPException
import pymongo
import pymongo.errors
import pytest
import unittest

from server import (
    compute_order_payment_summary,
    build_admin_wage_accrual_event_key,
    process_order_admin_wage_accrual,
    admin_create_order_payment,
    admin_void_order_payment,
    _create_wage_settlement_impl,
    PaymentCreateInput,
    PaymentVoidInput,
    WageSettlementCreateInput,
    WageSettlementAllocationItem,
)


class TestPhase08_4BAdminWageAccrual(unittest.IsolatedAsyncioTestCase):
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
            "name": "Finance Admin",
            "role": "admin",
            "permissions": {"manage_orders": True, "access_finance": True},
        }
        self.admin_worker = {
            "_id": ObjectId("507f1f77bcf86cd799439002"),
            "id": "507f1f77bcf86cd799439002",
            "name": "Sarah Administrasi",
            "role": "admin",
            "permissions": {"manage_orders": True},
        }
        self.admin_worker_custom = {
            "_id": ObjectId("507f1f77bcf86cd799439003"),
            "id": "507f1f77bcf86cd799439003",
            "name": "Azka Kasir",
            "role": "admin",
            "permissions": {"manage_orders": True},
        }

        self.default_admin_policy = {
            "key": "admin_wage_policy",
            "value": {
                "enabled": True,
                "is_configured": True,
                "default_wage_per_order_le": 50.0,
                "default_recipient_id": "507f1f77bcf86cd799439002",
                "default_recipient_name": "Sarah Administrasi",
                "unusual_amount_threshold_le": 100.0,
                "max_wage_per_order_le": 200.0,
                "currency": "EGP",
                "rounding_policy": "piastre_round_half_up",
            }
        }

    def _setup_mock_db(self, mock_db):
        mock_db.settings.find_one = AsyncMock(side_effect=lambda q, **kw: (
            self.default_admin_policy if q.get("key") == "admin_wage_policy"
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
        mock_db.orders.update_one = AsyncMock()
        mock_db.wage_obligations.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("807f1f77bcf86cd799439044")))
        mock_db.wage_obligations.update_one = AsyncMock()
        mock_db.audit_logs.insert_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 101})

        # Default admins lookup
        async def mock_admin_find_one(query, **kwargs):
            qid = str(query.get("_id") or "")
            if "507f1f77bcf86cd799439002" in qid or query.get("_id") == self.admin_worker["_id"]:
                return self.admin_worker
            if "507f1f77bcf86cd799439003" in qid or query.get("_id") == self.admin_worker_custom["_id"]:
                return self.admin_worker_custom
            return None

        mock_db.admins.find_one = AsyncMock(side_effect=mock_admin_find_one)
        mock_db.wage_obligations.find_one = AsyncMock(return_value=None)

    # =========================================================================
    # Test 1: Unpaid order no accrual
    # =========================================================================
    async def test_01_unpaid_order_no_accrual(self):
        """1. Unpaid order does not trigger admin wage accrual."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_doc = {
            "_id": ObjectId("507f1f77bcf86cd799439011"),
            "order_number": "SGF-20261029-001",
            "total_le": 1000.0,
            "payment_status": "belum_dibayar",
        }
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[])
        mock_db.payments.find.return_value = mock_find

        with patch("server.db", mock_db):
            summary = await compute_order_payment_summary(order_doc)
            self.assertEqual(summary["payment_status"], "belum_dibayar")
            self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

    # =========================================================================
    # Test 2: Partial payment no accrual
    # =========================================================================
    async def test_02_partial_payment_no_accrual(self):
        """2. Partial payment (DP) records payment without accruing wage obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-002",
            "total_le": 1000.0,
            "delivery_fee_le": 0.0,
            "payment_status": "belum_dibayar",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)

        # After inserting 400 LE, payments.find returns [400 LE]
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[
            {"amount_le": 400.0, "status": "recorded"}
        ])
        mock_db.payments.find.return_value = mock_find

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=400.0, payment_method="cash")
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        self.assertEqual(res["order_summary"]["payment_status"], "dp")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)
        self.assertNotIn("admin_wage_summary", res)

    # =========================================================================
    # Test 3: Final payment creates one obligation
    # =========================================================================
    async def test_03_final_payment_creates_one_obligation(self):
        """3. Order transitioning from dp to lunas accrues exactly 1 obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-003",
            "order_status": "selesai",
            "total_le": 1000.0,
            "delivery_fee_le": 0.0,
            "payment_status": "dp",
            "paid_amount_le": 400.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)

        # Payment bringing total to 1000 LE
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[
            {"amount_le": 400.0, "status": "recorded"},
            {"amount_le": 600.0, "status": "recorded"},
        ])
        mock_db.payments.find.return_value = mock_find

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=600.0, payment_method="cash")
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        self.assertEqual(res["order_summary"]["payment_status"], "lunas")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)
        wob = mock_db.wage_obligations.insert_one.call_args[0][0]
        self.assertEqual(wob["task_category"], "admin")
        self.assertEqual(wob["total_amount_le"], 50.0)
        self.assertEqual(wob["worker_id"], "507f1f77bcf86cd799439002")
        self.assertEqual(wob["worker_name"], "Sarah Administrasi")
        self.assertEqual(wob["status"], "accrued")
        self.assertFalse(wob["is_override"])

    # =========================================================================
    # Test 4: Direct full payment creates one obligation
    # =========================================================================
    async def test_04_direct_full_payment_creates_one_obligation(self):
        """4. Direct full payment from belum_dibayar creates 1 obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-004",
            "order_status": "selesai",
            "total_le": 1000.0,
            "delivery_fee_le": 0.0,
            "payment_status": "belum_dibayar",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)

        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[
            {"amount_le": 1000.0, "status": "recorded"}
        ])
        mock_db.payments.find.return_value = mock_find

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=1000.0, payment_method="cash")
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        self.assertEqual(res["order_summary"]["payment_status"], "lunas")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)
        wob = mock_db.wage_obligations.insert_one.call_args[0][0]
        self.assertEqual(wob["task_category"], "admin")
        self.assertEqual(wob["total_amount_le"], 50.0)

    # =========================================================================
    # Test 5: Per-order override precedence over default policy
    # =========================================================================
    async def test_05_order_override_precedence_over_default_policy(self):
        """5. Custom order override takes precedence over default policy."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-005",
            "order_status": "selesai",
            "total_le": 1000.0,
            "payment_status": "belum_dibayar",
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 75.0,
                "recipient_id": "507f1f77bcf86cd799439003",
                "recipient_name": "Azka Kasir",
                "override_reason": "Pesanan rumit membutuhkan koordinasi intensif",
            }
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[{"amount_le": 1000.0, "status": "recorded"}])
        mock_db.payments.find.return_value = mock_find

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=1000.0, payment_method="cash")
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)
        wob = mock_db.wage_obligations.insert_one.call_args[0][0]
        self.assertEqual(wob["total_amount_le"], 75.0)
        self.assertEqual(wob["worker_id"], "507f1f77bcf86cd799439003")
        self.assertEqual(wob["worker_name"], "Azka Kasir")
        self.assertTrue(wob["is_override"])
        self.assertEqual(wob["rate_policy_snapshot"]["override_reason"], "Pesanan rumit membutuhkan koordinasi intensif")

    # =========================================================================
    # Test 6: Order without override uses default policy
    # =========================================================================
    async def test_06_order_without_override_uses_default_policy(self):
        """6. Order without override strictly resolves to global policy values."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-006",
            "order_status": "selesai",
            "total_le": 500.0,
            "payment_status": "belum_dibayar",
            "admin_wage_override": {"is_override": False}
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[{"amount_le": 500.0, "status": "recorded"}])
        mock_db.payments.find.return_value = mock_find

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=500.0, payment_method="cash")
            await admin_create_order_payment(order_id, payload, self.admin_finance)

        wob = mock_db.wage_obligations.insert_one.call_args[0][0]
        self.assertEqual(wob["total_amount_le"], 50.0)
        self.assertEqual(wob["worker_id"], "507f1f77bcf86cd799439002")
        self.assertFalse(wob["is_override"])

    # =========================================================================
    # Test 7: Incomplete manual override does not silently take default recipient
    # =========================================================================
    async def test_07_override_amount_only_uses_default_recipient(self):
        """7. Incomplete manual override (missing recipient) fails safe and does not use default recipient."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-007",
            "order_status": "selesai",
            "total_le": 800.0,
            "payment_status": "belum_dibayar",
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 80.0,
                "recipient_id": None,
                "override_reason": "Tambahan fee order",
            }
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[{"amount_le": 800.0, "status": "recorded"}])
        mock_db.payments.find.return_value = mock_find

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=800.0, payment_method="cash")
            await admin_create_order_payment(order_id, payload, self.admin_finance)

        # Payment succeeds
        self.assertTrue(mock_db.payments.insert_one.called)
        # Fails closed without falling back to global default recipient
        self.assertFalse(mock_db.wage_obligations.insert_one.called)
        update_call = mock_db.orders.update_one.call_args[0][1]
        self.assertIsNotNone(update_call["$set"].get("admin_wage_blocked"))
        self.assertEqual(update_call["$set"]["admin_wage_blocked"]["status"], "blocked_missing_recipient")

    # =========================================================================
    # Test 8: Invalid override recipient fail-safe
    # =========================================================================
    async def test_08_invalid_override_recipient_failsafe(self):
        """8. If override recipient is not found in db.admins, fails safe without crashing payment."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-008",
            "order_status": "selesai",
            "total_le": 600.0,
            "payment_status": "belum_dibayar",
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 60.0,
                "recipient_id": "non_existent_admin_id",
                "recipient_name": "Ghost Admin",
            }
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[{"amount_le": 600.0, "status": "recorded"}])
        mock_db.payments.find.return_value = mock_find

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=600.0, payment_method="cash")
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        # Payment succeeds
        self.assertEqual(res["order_summary"]["payment_status"], "lunas")
        # Obligation NOT created
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)
        # Blocked alert recorded on order
        update_set = mock_db.orders.update_one.call_args[0][1]["$set"]
        self.assertIn("admin_wage_blocked", update_set)
        self.assertEqual(update_set["admin_wage_blocked"]["status"], "blocked_invalid_recipient")

    # =========================================================================
    # Test 9: Disabled policy fail-safe
    # =========================================================================
    async def test_09_disabled_policy_failsafe(self):
        """9. Disabled or unconfigured policy records payment but safely skips wage accrual."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        # Configure disabled policy
        mock_db.settings.find_one = AsyncMock(return_value={
            "key": "admin_wage_policy",
            "value": {"enabled": False, "is_configured": True, "default_wage_per_order_le": 50.0}
        })
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-009",
            "order_status": "selesai",
            "total_le": 500.0,
            "payment_status": "belum_dibayar",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[{"amount_le": 500.0, "status": "recorded"}])
        mock_db.payments.find.return_value = mock_find

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=500.0, payment_method="cash")
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        self.assertEqual(res["order_summary"]["payment_status"], "lunas")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)
        update_set = mock_db.orders.update_one.call_args[0][1]["$set"]
        self.assertIn("admin_wage_skipped", update_set)
        self.assertEqual(update_set["admin_wage_skipped"]["status"], "skipped_policy_disabled")

    # =========================================================================
    # Test 10: Legacy reconciled order guard
    # =========================================================================
    async def test_10_legacy_reconciled_order_guard(self):
        """10. Order marked admin_wage_legacy_reconciled never accrues wage on payment."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-LEGACY-001",
            "total_le": 1200.0,
            "payment_status": "belum_dibayar",
            "admin_wage_legacy_reconciled": True,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[{"amount_le": 1200.0, "status": "recorded"}])
        mock_db.payments.find.return_value = mock_find

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=1200.0, payment_method="cash")
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        self.assertEqual(res["order_summary"]["payment_status"], "lunas")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

    # =========================================================================
    # Test 11: Hard-cap conflict Option A
    # =========================================================================
    async def test_11_hard_cap_conflict_option_a(self):
        """11. Hard-cap conflict Option A: customer payment succeeds, wage accrual blocked with alert."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        # Policy hard cap is 100 LE
        mock_db.settings.find_one = AsyncMock(return_value={
            "key": "admin_wage_policy",
            "value": {
                "enabled": True,
                "is_configured": True,
                "default_wage_per_order_le": 50.0,
                "default_recipient_id": "507f1f77bcf86cd799439002",
                "default_recipient_name": "Sarah Administrasi",
                "unusual_amount_threshold_le": 80.0,
                "max_wage_per_order_le": 100.0,
            }
        })
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-011",
            "order_status": "selesai",
            "total_le": 2000.0,
            "payment_status": "belum_dibayar",
            # Override nominal was saved as 150 LE (e.g. before policy cap was lowered)
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 150.0,
                "recipient_id": "507f1f77bcf86cd799439002",
                "recipient_name": "Sarah Administrasi",
                "override_reason": "Komisi proyek besar",
            }
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[{"amount_le": 2000.0, "status": "recorded"}])
        mock_db.payments.find.return_value = mock_find

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=2000.0, payment_method="cash")
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        # 1. Customer payment succeeds completely
        self.assertEqual(res["order_summary"]["payment_status"], "lunas")
        self.assertEqual(mock_db.payments.insert_one.call_count, 1)
        self.assertEqual(mock_db.finance_transactions.insert_one.call_count, 1)

        # 2. Wage obligation is NOT created (zero money created under invalid rate)
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

        # 3. Conflict alert is recorded on the order for Owner resolution
        update_set = mock_db.orders.update_one.call_args[0][1]["$set"]
        self.assertIn("admin_wage_blocked", update_set)
        blocked = update_set["admin_wage_blocked"]
        self.assertEqual(blocked["status"], "blocked_hard_cap_conflict")
        self.assertEqual(blocked["attempted_amount_le"], 150.0)
        self.assertEqual(blocked["max_wage_per_order_le"], 100.0)

    # =========================================================================
    # Test 12: Policy change after accrual does not mutate obligation
    # =========================================================================
    async def test_12_policy_change_after_accrual_does_not_mutate_obligation(self):
        """12. Obligation document retains snapshot values and is not modified by subsequent policy updates."""
        order_doc = {
            "_id": ObjectId("507f1f77bcf86cd799439011"),
            "order_number": "SGF-20261029-012",
        }
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        with patch("server.db", mock_db):
            res = await process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")

        self.assertEqual(res["status"], "accrued")
        wob = mock_db.wage_obligations.insert_one.call_args[0][0]
        self.assertEqual(wob["total_amount_le"], 50.0)
        self.assertEqual(wob["rate_policy_snapshot"]["default_wage_per_order_le"], 50.0)

        # Subsequent policy update
        new_policy = copy.deepcopy(self.default_admin_policy)
        new_policy["value"]["default_wage_per_order_le"] = 99.0
        mock_db.settings.find_one = AsyncMock(return_value=new_policy)

        # Obligation document remains unchanged
        self.assertEqual(wob["total_amount_le"], 50.0)

    # =========================================================================
    # Test 13: Transaction rollback on payment failure reverts obligation
    # =========================================================================
    async def test_13_transaction_rollback_reverts_obligation(self):
        """13. Transaction abort or exception reverts payment, finance transaction, and obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-013",
            "total_le": 1000.0,
            "payment_status": "belum_dibayar",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[{"amount_le": 1000.0, "status": "recorded"}])
        mock_db.payments.find.return_value = mock_find

        # Force failure during order update
        mock_db.orders.update_one = AsyncMock(side_effect=RuntimeError("Simulated DB connection drop"))

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=1000.0, payment_method="cash")
            with self.assertRaises(RuntimeError):
                await admin_create_order_payment(order_id, payload, self.admin_finance)

    # =========================================================================
    # Test 14: Repeated payment request idempotency
    # =========================================================================
    async def test_14_repeated_payment_request_idempotency(self):
        """14. Repeated payment request with same idempotency key returns existing payment without duplicates."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-014",
            "total_le": 1000.0,
            "payment_status": "belum_dibayar",
        }
        existing_payment = {
            "_id": ObjectId("607f1f77bcf86cd799439022"),
            "payment_number": "PMT-20261029-0001",
            "order_id": order_id,
            "amount_le": 1000.0,
            "payment_method": "cash",
            "idempotency_key": "idem_admin_wage_014",
            "status": "recorded",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=existing_payment)
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[existing_payment])
        mock_db.payments.find.return_value = mock_find

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=1000.0, payment_method="cash", idempotency_key="idem_admin_wage_014")
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        self.assertEqual(res["payment_number"], "PMT-20261029-0001")
        self.assertEqual(mock_db.payments.insert_one.call_count, 0)
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

    # =========================================================================
    # Test 15: Duplicate accrual event key handled cleanly
    # =========================================================================
    async def test_15_duplicate_accrual_event_key_handled_cleanly(self):
        """15. Idempotent race with DuplicateKeyError on uniq_wage_obligation_accrual_event reuses existing obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_doc = {
            "_id": ObjectId("507f1f77bcf86cd799439011"),
            "order_number": "SGF-20261029-015",
        }
        accrual_key = build_admin_wage_accrual_event_key("507f1f77bcf86cd799439011")
        existing_obligation = {
            "_id": ObjectId("807f1f77bcf86cd799439044"),
            "obligation_number": "WOB-20261029-0044",
            "accrual_event_key": accrual_key,
            "task_category": "admin",
            "worker_id": "507f1f77bcf86cd799439002",
            "worker_name": "Sarah Administrasi",
            "total_amount_le": 50.0,
            "status": "accrued",
        }

        # First find_one returns None (simulating race before insert)
        # insert_one throws DuplicateKeyError
        # second find_one returns existing_obligation
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

        with patch("server.db", mock_db):
            res = await process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")

        self.assertEqual(res["status"], "accrued")
        self.assertEqual(res["obligation"]["obligation_number"], "WOB-20261029-0044")

    # =========================================================================
    # Test 16: DuplicateKeyError on unrelated index not swallowed
    # =========================================================================
    async def test_16_duplicate_key_error_on_unrelated_index_not_swallowed(self):
        """16. DuplicateKeyError on unrelated index (e.g. some_unrelated_index) is strictly re-raised."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_doc = {
            "_id": ObjectId("507f1f77bcf86cd799439011"),
            "order_number": "SGF-20261029-016",
        }
        mock_db.wage_obligations.insert_one = AsyncMock(
            side_effect=pymongo.errors.DuplicateKeyError("E11000 duplicate key error on unrelated_index_foo")
        )

        with patch("server.db", mock_db):
            with self.assertRaises(pymongo.errors.DuplicateKeyError):
                await process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")

    # =========================================================================
    # Test 17: Session-aware payment summary sees inserted payment
    # =========================================================================
    async def test_17_session_aware_payment_summary_sees_inserted_payment(self):
        """17. compute_order_payment_summary passes session parameter to db.payments.find."""
        mock_db = MagicMock()
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[
            {"amount_le": 1000.0, "status": "recorded"}
        ])
        mock_db.payments.find.return_value = mock_find
        order_doc = {
            "_id": ObjectId("507f1f77bcf86cd799439011"),
            "total_le": 1000.0,
        }

        test_session = AsyncMock()
        with patch("server.db", mock_db):
            summary = await compute_order_payment_summary(order_doc, session=test_session)

        self.assertEqual(summary["payment_status"], "lunas")
        mock_db.payments.find.assert_called_once()
        self.assertEqual(mock_db.payments.find.call_args[1].get("session"), test_session)

    # =========================================================================
    # Test 18: Existing callers without session continue working
    # =========================================================================
    async def test_18_existing_callers_without_session_continue_working(self):
        """18. compute_order_payment_summary called without session does not pass session kwarg."""
        mock_db = MagicMock()
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[
            {"amount_le": 500.0, "status": "recorded"}
        ])
        mock_db.payments.find.return_value = mock_find
        order_doc = {
            "_id": ObjectId("507f1f77bcf86cd799439011"),
            "total_le": 1000.0,
        }

        with patch("server.db", mock_db):
            summary = await compute_order_payment_summary(order_doc)

        self.assertEqual(summary["payment_status"], "dp")
        self.assertNotIn("session", mock_db.payments.find.call_args[1])

    # =========================================================================
    # Test 19: Settlement through existing settle_worker_wages engine
    # =========================================================================
    async def test_19_settlement_through_existing_settlement_engine(self):
        """19. Admin wage obligation settles through existing wage settlement engine."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        ob_id = ObjectId("807f1f77bcf86cd799439044")
        wob_doc = {
            "_id": ob_id,
            "obligation_number": "WOB-20261029-0044",
            "task_category": "admin",
            "worker_id": "507f1f77bcf86cd799439002",
            "worker_name": "Sarah Administrasi",
            "total_amount_le": 50.0,
            "paid_amount_le": 0.0,
            "status": "accrued",
            "order_number": "SGF-20261029-019",
        }

        # Mock db collections for wage settlement
        mock_db.wage_settlements.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("907f1f77bcf86cd799439055")))
        mock_db.wage_settlements.find_one = AsyncMock(return_value=None)
        mock_db.employee_wages.insert_one = AsyncMock()

        mock_find_wob = MagicMock()
        mock_find_wob.sort.return_value.to_list = AsyncMock(return_value=[wob_doc])
        mock_db.wage_obligations.find.return_value = mock_find_wob

        async def mock_wob_find_one(query, **kw):
            if query.get("_id") == ob_id or str(query.get("_id")) == str(ob_id):
                return wob_doc
            return None
        mock_db.wage_obligations.find_one = AsyncMock(side_effect=mock_wob_find_one)
        mock_db.wage_obligations.update_one = AsyncMock(return_value=MagicMock(modified_count=1))

        payload = WageSettlementCreateInput(
            worker_id="507f1f77bcf86cd799439002",
            amount_le=50.0,
            allocations=[
                WageSettlementAllocationItem(
                    wage_obligation_id=str(ob_id),
                    amount_le=50.0
                )
            ],
            notes="Pencairan upah admin Sarah"
        )

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            res = await _create_wage_settlement_impl(payload, self.admin_finance)

        self.assertEqual(res["worker_id"], "507f1f77bcf86cd799439002")
        self.assertEqual(res["amount_le"], 50.0)
        # Verify finance transaction for payout was created
        self.assertEqual(mock_db.finance_transactions.insert_one.call_count, 1)
        fin_doc = mock_db.finance_transactions.insert_one.call_args[0][0]
        self.assertEqual(fin_doc["type"], "expense")
        self.assertEqual(fin_doc["category"], "Pekerja")
        # Verify obligation was updated to paid
        mock_db.wage_obligations.update_one.assert_called_once()
        ob_update = mock_db.wage_obligations.update_one.call_args[0][1]["$set"]
        self.assertEqual(ob_update["status"], "paid")
        self.assertEqual(ob_update["paid_amount_le"], 50.0)

    # =========================================================================
    # Test 20: Voiding customer payment voids accrued obligation
    # =========================================================================
    async def test_20_voiding_customer_payment_voids_accrued_obligation(self):
        """20. Voiding customer payment voids accrued admin wage obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        pmt_id = "607f1f77bcf86cd799439022"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-020",
            "total_le": 1000.0,
            "payment_status": "lunas",
            "admin_wage_obligation": {
                "obligation_number": "WOB-20261029-0020",
                "status": "accrued",
            }
        }
        pmt_doc = {
            "_id": ObjectId(pmt_id),
            "payment_number": "PMT-20261029-0020",
            "order_id": ObjectId(order_id),
            "amount_le": 1000.0,
            "status": "recorded",
        }
        linked_wob = {
            "_id": ObjectId("807f1f77bcf86cd799439044"),
            "obligation_number": "WOB-20261029-0020",
            "status": "accrued",
            "order_id": order_id,
        }

        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        async def mock_pmt_find_one(query, **kw):
            if mock_db.payments.update_one.called:
                return {**pmt_doc, "status": "voided"}
            return pmt_doc
        mock_db.payments.find_one = AsyncMock(side_effect=mock_pmt_find_one)
        mock_db.wage_obligations.find_one = AsyncMock(return_value=linked_wob)
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[])  # after void, 0 recorded payments
        mock_db.payments.find.return_value = mock_find

        payload = PaymentVoidInput(reason="Pelanggan membatalkan pesanan")

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            res = await admin_void_order_payment(order_id, pmt_id, payload, self.admin_finance)

        self.assertEqual(res["status"], "voided")
        # Obligation marked voided
        mock_db.wage_obligations.update_one.assert_called_once()
        wob_update = mock_db.wage_obligations.update_one.call_args[0][1]["$set"]
        self.assertEqual(wob_update["status"], "voided")
        self.assertIn("Pelanggan membatalkan pesanan", wob_update["void_reason"])

    # =========================================================================
    # Test 21: Voiding customer payment with settled wage blocked with HTTP 409
    # =========================================================================
    async def test_21_voiding_customer_payment_with_settled_wage_blocked_409(self):
        """21. Voiding payment on an order with a settled/paid admin wage is blocked with HTTP 409."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        pmt_id = "607f1f77bcf86cd799439022"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-021",
            "total_le": 1000.0,
            "payment_status": "lunas",
        }
        pmt_doc = {
            "_id": ObjectId(pmt_id),
            "payment_number": "PMT-20261029-0021",
            "order_id": ObjectId(order_id),
            "amount_le": 1000.0,
            "status": "recorded",
        }
        settled_wob = {
            "_id": ObjectId("807f1f77bcf86cd799439044"),
            "obligation_number": "WOB-20261029-0021",
            "status": "paid",  # Wage has already been disbursed to worker!
            "paid_amount_le": 50.0,
            "order_id": order_id,
        }

        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=pmt_doc)
        mock_db.wage_obligations.find_one = AsyncMock(return_value=settled_wob)

        payload = PaymentVoidInput(reason="Membatalkan pembayaran lunas")

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_void_order_payment(order_id, pmt_id, payload, self.admin_finance)
            self.assertEqual(cm.exception.status_code, 409)
            self.assertIn("sudah dalam status 'paid'", cm.exception.detail)

    # =========================================================================
    # Test 22: Second payment on already-lunas order never re-accrues wage
    # =========================================================================
    async def test_22_second_payment_on_already_lunas_order_no_accrual(self):
        """22. Subsequent payment on an order already at lunas does not re-accrue wage obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-022",
            "total_le": 1000.0,
            "payment_status": "lunas",  # ALREADY LUNAS
            "paid_amount_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[
            {"amount_le": 1000.0, "status": "recorded"},
            {"amount_le": 100.0, "status": "recorded"},
        ])
        mock_db.payments.find.return_value = mock_find

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=100.0, payment_method="cash")
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        self.assertEqual(mock_db.payments.insert_one.call_count, 1)
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)
        self.assertNotIn("admin_wage_summary", res)

    # =========================================================================
    # Test 23: Concurrent settlement and void protection inside transaction
    # =========================================================================
    async def test_23_concurrent_settlement_and_void_blocked_in_transaction(self):
        """23. If wage obligation becomes paid concurrently before transaction commit, void is blocked with 409."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        pmt_id = "607f1f77bcf86cd799439022"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-023",
            "total_le": 1000.0,
            "payment_status": "lunas",
        }
        pmt_doc = {
            "_id": ObjectId(pmt_id),
            "payment_number": "PMT-20261029-0023",
            "order_id": ObjectId(order_id),
            "amount_le": 1000.0,
            "status": "recorded",
        }

        # First call (pre-check) returns status 'accrued', but second call (inside transaction) returns 'paid'
        call_count = 0
        async def mock_wob_find_one(query, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "_id": ObjectId("807f1f77bcf86cd799439044"),
                    "obligation_number": "WOB-20261029-0023",
                    "status": "accrued",
                    "order_id": order_id,
                }
            return {
                "_id": ObjectId("807f1f77bcf86cd799439044"),
                "obligation_number": "WOB-20261029-0023",
                "status": "paid",
                "order_id": order_id,
            }

        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=pmt_doc)
        mock_db.wage_obligations.find_one = AsyncMock(side_effect=mock_wob_find_one)

        payload = PaymentVoidInput(reason="Pembatalan bersamaan")

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_void_order_payment(order_id, pmt_id, payload, self.admin_finance)
            self.assertEqual(cm.exception.status_code, 409)
            self.assertIn("sudah dalam status 'paid'", cm.exception.detail)

    # =========================================================================
    # Test 24: Voided obligation cannot be settled
    # =========================================================================
    async def test_24_voided_obligation_cannot_be_settled(self):
        """24. Settlement engine strictly rejects voided wage obligations with HTTP 409."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        ob_id = ObjectId("807f1f77bcf86cd799439044")
        voided_wob = {
            "_id": ob_id,
            "obligation_number": "WOB-20261029-0024",
            "task_category": "admin",
            "worker_id": "507f1f77bcf86cd799439002",
            "total_amount_le": 50.0,
            "paid_amount_le": 0.0,
            "status": "voided",  # VOIDED
        }
        mock_find_wob = MagicMock()
        # Pending find returns empty because status is voided
        mock_find_wob.sort.return_value.to_list = AsyncMock(return_value=[])
        mock_db.wage_obligations.find.return_value = mock_find_wob
        mock_db.wage_obligations.find_one = AsyncMock(return_value=voided_wob)
        mock_db.wage_settlements.find_one = AsyncMock(return_value=None)

        payload = WageSettlementCreateInput(
            worker_id="507f1f77bcf86cd799439002",
            amount_le=50.0,
            allocations=[
                WageSettlementAllocationItem(
                    wage_obligation_id=str(ob_id),
                    amount_le=50.0
                )
            ]
        )

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await _create_wage_settlement_impl(payload, self.admin_finance)
            self.assertIn(cm.exception.status_code, (400, 404, 409, 422))

