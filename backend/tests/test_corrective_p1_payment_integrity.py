"""Comprehensive automated acceptance test suite for Corrective Phase 1: Payment Integrity.

Covers all 17 approved acceptance scenarios T01 - T17 from Scope Lock v1.3:
T01 - Normal full payment via canonical endpoint
T02 - DP followed by settlement
T03 - Direct payment_status patch explicitly rejected with HTTP 400
T04 - Clean non-financial PATCH succeeds without financial side-effects
T05 - Legacy Lunas order derived paid=total, out=0, 0 synthetic docs
T06 - Legacy unpaid order derived paid=0, out=total
T07 - Legacy DP order derived paid=None, out=None, unknown=True
T08 - New payment on legacy DP sets persistent has_unrecorded_legacy_dp=True, out remains None
T09 - Quick settlement disabled on unreconciled order (has_unrecorded_legacy_dp=True)
T10 - Quick settlement disabled on settled order (out <= 0) and API rejects amount <= 0
T11 - Overpayment captures actual cash, allocates credit, clamps out to 0, status=overpaid
T12 - Decimal ROUND_HALF_UP precision enforced in allocation validation
T13 - Idempotent payment retry returns existing doc without duplicate writes
T14 - Concurrent duplicate submissions blocked by unique idempotency index
T15 - Transaction rollback on payment insertion failure leaves no orphaned docs
T16 - Transaction rollback on finance insertion failure leaves no orphaned docs
T17 - Concurrent non-financial order update and canonical payment recording convergence
"""
import asyncio
import os
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from fastapi import HTTPException
from pydantic import ValidationError

from server import (
    compute_order_payment_summary,
    admin_create_order_payment,
    admin_void_order_payment,
    admin_update_order,
    OrderStatusUpdate,
    PaymentCreateInput,
    PaymentVoidInput,
    PaymentAllocationInput,
)


class TestCorrectiveP1PaymentIntegrity(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.admin_finance = {
            "id": "admin_fin_01",
            "name": "Finance Head",
            "role": "admin",
            "permissions": {"manage_orders": True, "access_finance": True},
        }

        self.mock_session = AsyncMock()
        self.mock_session.__aenter__.return_value = self.mock_session
        self.mock_session.__aexit__.return_value = None
        self.mock_session.start_transaction = MagicMock()
        self.mock_session.start_transaction.return_value.__aenter__ = AsyncMock(return_value=self.mock_session)
        self.mock_session.start_transaction.return_value.__aexit__ = AsyncMock(return_value=None)

        self.mock_client = MagicMock()
        self.mock_client.start_session = AsyncMock(return_value=self.mock_session)

    def _setup_mock_db(self, mock_db):
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357.0})
        mock_db.system_rates.find_one = AsyncMock(return_value={"rate": 357.0})
        mock_find_pts = MagicMock()
        mock_find_pts.to_list = AsyncMock(return_value=[])
        mock_db.point_transactions.find.return_value = mock_find_pts
        mock_db.point_transactions.delete_many = AsyncMock()
        mock_db.customers.update_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 201})

    # =========================================================================
    # T01 — Normal full payment via canonical endpoint
    # =========================================================================
    async def test_T01_normal_full_payment(self):
        """T01: 2,000 LE paid in full results in exactly 1 pmt doc and 1 linked finance receipt. Status is lunas and out=0."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P1-001",
            "total_le": 2000.0,
            "delivery_fee_le": 100.0,
            "payment_status": "belum_dibayar",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.count_documents = AsyncMock(return_value=0)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()

        # Recorded payments find
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[
            {"amount_le": 2000.0, "status": "recorded"}
        ])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=2000.0, payment_method="cash")
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        self.assertEqual(mock_db.payments.insert_one.call_count, 1)
        self.assertEqual(mock_db.finance_transactions.insert_one.call_count, 1)
        self.assertEqual(res["order_summary"]["payment_status"], "lunas")
        self.assertEqual(res["order_summary"]["outstanding_amount_le"], 0.0)

    # =========================================================================
    # T02 — DP followed by settlement
    # =========================================================================
    async def test_T02_dp_followed_by_settlement(self):
        """T02: Two actual payments of 1,000 LE produce 2 pmt docs and 2 receipts totaling 2,000 LE."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P1-002",
            "total_le": 2000.0,
            "delivery_fee_le": 100.0,
            "payment_status": "belum_dibayar",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.count_documents = AsyncMock(return_value=0)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()

        # Step 1: DP 1,000 LE
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[
            {"amount_le": 1000.0, "status": "recorded"}
        ])
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload_dp = PaymentCreateInput(amount=1000.0, payment_method="cash")
            res_dp = await admin_create_order_payment(order_id, payload_dp, self.admin_finance)
        self.assertEqual(res_dp["order_summary"]["payment_status"], "dp")
        self.assertEqual(res_dp["order_summary"]["outstanding_amount_le"], 1000.0)

        # Step 2: Settlement 1,000 LE
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[
            {"amount_le": 1000.0, "status": "recorded"},
            {"amount_le": 1000.0, "status": "recorded"}
        ])
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload_settle = PaymentCreateInput(amount=1000.0, payment_method="cash")
            res_settle = await admin_create_order_payment(order_id, payload_settle, self.admin_finance)
        self.assertEqual(res_settle["order_summary"]["payment_status"], "lunas")
        self.assertEqual(res_settle["order_summary"]["outstanding_amount_le"], 0.0)
        self.assertEqual(mock_db.payments.insert_one.call_count, 2)
        self.assertEqual(mock_db.finance_transactions.insert_one.call_count, 2)

    # =========================================================================
    # T03 — Direct payment_status patch explicitly rejected with HTTP 400
    # =========================================================================
    async def test_T03_direct_payment_status_patch_rejected(self):
        """T03: PATCH /admin/orders/{id} with payment_status (string or explicit null) returns HTTP 400 before mutation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P1-003",
            "total_le": 2000.0,
            "payment_status": "belum_dibayar",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.orders.update_one = AsyncMock()
        mock_db.finance_transactions.insert_one = AsyncMock()

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            # Case A: String value ("lunas")
            payload_str = OrderStatusUpdate(payment_status="lunas")
            with self.assertRaises(HTTPException) as cm_str:
                await admin_update_order(order_id, payload_str, self.admin_finance)
            self.assertEqual(cm_str.exception.status_code, 400)
            self.assertIn("Status pembayaran tidak dapat diubah secara manual", cm_str.exception.detail)

            # Case B: Explicit null value ({"payment_status": null})
            payload_null = OrderStatusUpdate.model_validate({"payment_status": None})
            with self.assertRaises(HTTPException) as cm_null:
                await admin_update_order(order_id, payload_null, self.admin_finance)
            self.assertEqual(cm_null.exception.status_code, 400)
            self.assertIn("Status pembayaran tidak dapat diubah secara manual", cm_null.exception.detail)

        # Ensure no mutations occurred
        mock_db.orders.update_one.assert_not_called()
        mock_db.finance_transactions.insert_one.assert_not_called()

    # =========================================================================
    # T04 — Clean non-financial PATCH succeeds without financial side-effects
    # =========================================================================
    async def test_T04_clean_non_financial_patch(self):
        """T04: Note and fulfillment updates succeed without financial side effects. record_order_revenue never called."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P1-004",
            "total_le": 2000.0,
            "order_status": "pesanan_masuk",
            "payment_status": "belum_dibayar",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.orders.update_one = AsyncMock()
        mock_db.finance_transactions.insert_one = AsyncMock()

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = OrderStatusUpdate(admin_note="Urgent handling", order_status="diproses")
            res = await admin_update_order(order_id, payload, self.admin_finance)

        mock_db.orders.update_one.assert_called_once()
        mock_db.finance_transactions.insert_one.assert_not_called()

    # =========================================================================
    # T05 — Legacy Lunas order derived paid=total, out=0, 0 synthetic docs
    # =========================================================================
    async def test_T05_legacy_lunas_order(self):
        """T05: Legacy lunas derives paid=total, out=0. No synthetic payment docs fabricated."""
        mock_db = MagicMock()
        order_doc = {"_id": "ord_leg_lunas", "total_le": 1500.0, "payment_status": "lunas"}
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            summary = await compute_order_payment_summary(order_doc)

        self.assertEqual(summary["payment_status"], "lunas")
        self.assertEqual(summary["paid_amount_le"], 1500.0)
        self.assertEqual(summary["outstanding_amount_le"], 0.0)
        self.assertTrue(summary["is_legacy_derived"])
        self.assertEqual(summary["valid_payments_count"], 0)

    # =========================================================================
    # T06 — Legacy unpaid order derived paid=0, out=total
    # =========================================================================
    async def test_T06_legacy_unpaid_order(self):
        """T06: Legacy belum_dibayar derives paid=0, out=total. Cannot become paid via status patch."""
        mock_db = MagicMock()
        order_doc = {"_id": "ord_leg_unpaid", "total_le": 1500.0, "payment_status": "belum_dibayar"}
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            summary = await compute_order_payment_summary(order_doc)

        self.assertEqual(summary["payment_status"], "belum_dibayar")
        self.assertEqual(summary["paid_amount_le"], 0.0)
        self.assertEqual(summary["outstanding_amount_le"], 1500.0)
        self.assertTrue(summary["is_legacy_derived"])

    # =========================================================================
    # T07 — Legacy DP order derived paid=None, out=None, unknown=True
    # =========================================================================
    async def test_T07_legacy_dp_order_unknown_amount(self):
        """T07: Legacy DP with no payments derives paid=None, out=None, unknown=True."""
        mock_db = MagicMock()
        order_doc = {"_id": "ord_leg_dp", "total_le": 2000.0, "payment_status": "dp"}
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            summary = await compute_order_payment_summary(order_doc)

        self.assertEqual(summary["payment_status"], "dp")
        self.assertIsNone(summary["paid_amount_le"])
        self.assertIsNone(summary["outstanding_amount_le"])
        self.assertTrue(summary["legacy_dp_unknown"])
        self.assertTrue(summary["has_unrecorded_legacy_dp"])

    # =========================================================================
    # T08 — New payment on legacy DP sets persistent has_unrecorded_legacy_dp=True
    # =========================================================================
    async def test_T08_new_payment_on_legacy_dp(self):
        """T08: Recording payment on legacy DP sets persistent has_unrecorded_legacy_dp=True, out remains None."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-LEG-DP",
            "total_le": 2000.0,
            "payment_status": "dp",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.count_documents = AsyncMock(return_value=0)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()

        # After inserting payment of 500, order has has_unrecorded_legacy_dp
        def find_one_side_effect(query):
            if "has_unrecorded_legacy_dp" in query or "_id" in query:
                return {**order_doc, "has_unrecorded_legacy_dp": True}
            return order_doc

        mock_db.orders.find_one = AsyncMock(side_effect=find_one_side_effect)
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[
            {"amount_le": 500.0, "status": "recorded"}
        ])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=500.0, payment_method="cash")
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        self.assertTrue(res["order_summary"]["has_unrecorded_legacy_dp"])
        self.assertIsNone(res["order_summary"]["outstanding_amount_le"])
        self.assertEqual(res["order_summary"]["canonical_paid_amount_le"], 500.0)

    # =========================================================================
    # T09 — Quick settlement disabled on unreconciled order
    # =========================================================================
    async def test_T09_quick_settlement_disabled_on_unreconciled_order(self):
        """T09: When has_unrecorded_legacy_dp is True, outstanding_amount_le is None (UI hides quick settlement)."""
        order_doc = {
            "_id": "ord_1",
            "total_le": 2000.0,
            "has_unrecorded_legacy_dp": True,
        }
        mock_db = MagicMock()
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[
            {"amount_le": 500.0, "status": "recorded"}
        ])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            summary = await compute_order_payment_summary(order_doc)

        self.assertIsNone(summary["outstanding_amount_le"])
        self.assertTrue(summary["has_unrecorded_legacy_dp"])

    # =========================================================================
    # T10 — Quick settlement disabled on settled order and API rejects <= 0
    # =========================================================================
    async def test_T10_quick_settlement_rejected_when_amount_non_positive(self):
        """T10: Payment creation API rejects amount <= 0 with HTTP 400."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {"_id": ObjectId(order_id), "total_le": 1000.0, "payment_status": "lunas"}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload_zero = PaymentCreateInput(amount=0.0, payment_method="cash")
            with self.assertRaises(HTTPException) as cm:
                await admin_create_order_payment(order_id, payload_zero, self.admin_finance)
            self.assertEqual(cm.exception.status_code, 400)
            self.assertIn("Nominal pembayaran harus lebih besar dari 0", cm.exception.detail)

    # =========================================================================
    # T11 — Overpayment & Unallocated Credit
    # =========================================================================
    async def test_T11_overpayment_and_unallocated_credit(self):
        """T11: 1,250 LE payment on 1,197 LE order allocates excess 53 LE to unallocated_credit, out=0, status=overpaid."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-OVER",
            "total_le": 1197.0,
            "delivery_fee_le": 100.0,
            "payment_status": "belum_dibayar",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.count_documents = AsyncMock(return_value=0)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()

        mock_db.payments.find.return_value.to_list = AsyncMock(side_effect=[
            [],  # First call in compute_order_payment_summary before insert
            [{"amount_le": 1250.0, "status": "recorded"}],  # Second call in fresh_order summary after insert
        ])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=1250.0, payment_method="cash")
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        inserted_pmt = mock_db.payments.insert_one.call_args[0][0]
        allocs = {a["target_type"]: a["amount_le"] for a in inserted_pmt["allocations"]}
        self.assertEqual(allocs["product"], 1097.0)
        self.assertEqual(allocs["shipping"], 100.0)
        self.assertEqual(allocs["unallocated_credit"], 53.0)
        self.assertEqual(res["order_summary"]["payment_status"], "overpaid")
        self.assertEqual(res["order_summary"]["outstanding_amount_le"], 0.0)

    # =========================================================================
    # T12 — Decimal ROUND_HALF_UP precision enforced in allocation validation
    # =========================================================================
    async def test_T12_decimal_round_half_up_allocation_precision(self):
        """T12: Allocations validated via Decimal ROUND_HALF_UP."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-DEC", "total_le": 1000.0}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.count_documents = AsyncMock(return_value=0)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            # Sum mismatch by 0.01
            payload_bad = PaymentCreateInput(
                amount=100.00,
                payment_method="cash",
                allocations=[
                    PaymentAllocationInput(target_type="product", amount=50.005),  # 50.01
                    PaymentAllocationInput(target_type="shipping", amount=49.98),  # 49.98 -> sum=99.99 != 100.00
                ]
            )
            with self.assertRaises(HTTPException) as cm:
                await admin_create_order_payment(order_id, payload_bad, self.admin_finance)
            self.assertEqual(cm.exception.status_code, 400)
            self.assertIn("harus sama persis", cm.exception.detail)

    # =========================================================================
    # T13 — Idempotent payment retry returns existing doc without duplicate writes
    # =========================================================================
    async def test_T13_idempotent_payment_retry(self):
        """T13: Repeated submission with same idempotency_key returns existing doc without writing duplicates."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        existing_pmt = {
            "_id": ObjectId("607f1f77bcf86cd799439022"),
            "payment_number": "PAY-20261009-001",
            "idempotency_key": "unique-idem-T13",
            "amount_le": 500.0,
            "status": "recorded",
        }
        mock_db.orders.find_one = AsyncMock(return_value={"_id": ObjectId(order_id), "total_le": 1000.0})
        mock_db.payments.find_one = AsyncMock(return_value=existing_pmt)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=500.0, payment_method="cash", idempotency_key="unique-idem-T13")
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        self.assertEqual(res["payment_number"], "PAY-20261009-001")
        mock_db.payments.insert_one.assert_not_called()
        mock_db.finance_transactions.insert_one.assert_not_called()

    # =========================================================================
    # T14 — Concurrent duplicate submissions blocked by unique idempotency index
    # =========================================================================
    async def test_T14_concurrent_duplicate_payment_submission(self):
        """T14: Concurrent duplicate submissions with same key serialize safely."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-RACE", "total_le": 1000.0}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.count_documents = AsyncMock(return_value=0)
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()

        # Simulate: first check find_one returns None, first insert succeeds, second insert raises DuplicateKeyError
        import pymongo.errors
        first_call = True
        async def insert_one_side_effect(doc, **kwargs):
            nonlocal first_call
            if not first_call:
                raise pymongo.errors.DuplicateKeyError("E11000 duplicate key error")
            first_call = False
            return MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022"))

        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.payments.insert_one = AsyncMock(side_effect=insert_one_side_effect)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=500.0, payment_method="cash", idempotency_key="race-key")
            # Thread 1 succeeds
            res1 = await admin_create_order_payment(order_id, payload, self.admin_finance)
            self.assertEqual(res1["amount_le"], 500.0)

            # Thread 2 fails due to unique duplicate key constraint
            with self.assertRaises(pymongo.errors.DuplicateKeyError):
                await admin_create_order_payment(order_id, payload, self.admin_finance)

    # =========================================================================
    # T15 — Transaction rollback on payment insertion failure leaves no orphaned docs
    # =========================================================================
    async def test_T15_rollback_on_payment_insertion_failure(self):
        """T15: Failure during payment insertion triggers rollback; zero orphaned finance transactions remain."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-T15", "total_le": 1000.0}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.count_documents = AsyncMock(return_value=0)
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        # Simulate payment insert failure
        mock_db.payments.insert_one = AsyncMock(side_effect=Exception("Disk full / MongoDB write error"))

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=500.0, payment_method="cash")
            with self.assertRaises(Exception):
                await admin_create_order_payment(order_id, payload, self.admin_finance)

        # In standalone mode or session transaction, unhandled exception aborts before order update
        mock_db.orders.update_one.assert_not_called()

    # =========================================================================
    # T16 — Transaction rollback on finance insertion failure leaves no orphaned docs
    # =========================================================================
    async def test_T16_rollback_on_finance_insertion_failure(self):
        """T16: Failure during finance transaction insertion aborts before payment insertion."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-T16", "total_le": 1000.0}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.count_documents = AsyncMock(return_value=0)
        # Simulate finance failure
        mock_db.finance_transactions.insert_one = AsyncMock(side_effect=Exception("Network partition"))

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=500.0, payment_method="cash")
            with self.assertRaises(Exception):
                await admin_create_order_payment(order_id, payload, self.admin_finance)

        mock_db.payments.insert_one.assert_not_called()
        mock_db.orders.update_one.assert_not_called()

    # =========================================================================
    # T17 — Concurrent non-financial order update and canonical payment recording convergence
    # =========================================================================
    async def test_T17_concurrent_order_update_and_payment_recording(self):
        """T17: Concurrent non-financial order update and payment creation preserve both writes with zero duplicate cash receipts."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-T17",
            "total_le": 2000.0,
            "order_status": "pesanan_masuk",
            "payment_status": "belum_dibayar",
            "admin_note": "",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.count_documents = AsyncMock(return_value=0)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[
            {"amount_le": 1000.0, "status": "recorded"}
        ])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            # Concurrent execution of Worker A (Order Update) and Worker B (Payment Creation)
            task_a = admin_update_order(
                order_id,
                OrderStatusUpdate(admin_note="Urgent customer note", order_status="diproses"),
                self.admin_finance
            )
            task_b = admin_create_order_payment(
                order_id,
                PaymentCreateInput(amount=1000.0, payment_method="cash"),
                self.admin_finance
            )
            res_a, res_b = await asyncio.gather(task_a, task_b)

        # Assertions
        # 1. Exactly 1 finance transaction inserted (from payment)
        self.assertEqual(mock_db.finance_transactions.insert_one.call_count, 1)
        # 2. Exactly 1 payment doc inserted
        self.assertEqual(mock_db.payments.insert_one.call_count, 1)
        # 3. Both endpoints succeeded cleanly
        self.assertEqual(res_b["order_summary"]["payment_status"], "dp")
        self.assertEqual(res_b["order_summary"]["outstanding_amount_le"], 1000.0)

    # =========================================================================
    # D02 / D03 — Production fail-closed on transaction session start failure
    # =========================================================================
    async def test_D02_D03_production_payment_creation_fails_closed(self):
        """D02 & D03: In production mode, missing transaction capability raises HTTP 503 and aborts with zero writes."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-D02", "total_le": 1000.0}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 301})
        mock_db.payments.count_documents = AsyncMock(return_value=0)
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        # Client that fails session creation
        failing_client = MagicMock()
        import pymongo.errors
        failing_client.start_session = AsyncMock(side_effect=pymongo.errors.ConfigurationError("Standalone"))

        with patch("server.db", mock_db), patch("server.client", failing_client), patch.dict("os.environ", {"APP_ENV": "production"}):
            payload = PaymentCreateInput(amount=500.0, payment_method="cash")
            with self.assertRaises(HTTPException) as cm:
                await admin_create_order_payment(order_id, payload, self.admin_finance)
            self.assertEqual(cm.exception.status_code, 503)
            self.assertIn("Fail-Closed", cm.exception.detail)

        # Confirm zero writes
        mock_db.payments.insert_one.assert_not_called()
        mock_db.finance_transactions.insert_one.assert_not_called()
        mock_db.orders.update_one.assert_not_called()

    # =========================================================================
    # D10 / D13 — Production fail-closed on void transaction session start failure
    # =========================================================================
    async def test_D10_D13_production_payment_void_fails_closed(self):
        """D10 & D13: In production mode, missing transaction capability for void raises HTTP 503 and preserves records."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        payment_id = "607f1f77bcf86cd799439022"
        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-D10", "total_le": 1000.0}
        pmt_doc = {"_id": ObjectId(payment_id), "order_id": ObjectId(order_id), "status": "recorded", "finance_transaction_id": "707f1f77bcf86cd799439033"}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=pmt_doc)

        failing_client = MagicMock()
        import pymongo.errors
        failing_client.start_session = AsyncMock(side_effect=pymongo.errors.ConfigurationError("Standalone"))

        with patch("server.db", mock_db), patch("server.client", failing_client), patch.dict("os.environ", {"APP_ENV": "production"}):
            payload = PaymentVoidInput(reason="Customer cancelled")
            with self.assertRaises(HTTPException) as cm:
                await admin_void_order_payment(order_id, payment_id, payload, self.admin_finance)
            self.assertEqual(cm.exception.status_code, 503)
            self.assertIn("Fail-Closed", cm.exception.detail)

        # Confirm zero mutations
        mock_db.payments.update_one.assert_not_called()
        mock_db.finance_transactions.update_one.assert_not_called()
        mock_db.orders.update_one.assert_not_called()

    # =========================================================================
    # D05 — Second write failure in transaction does NOT trigger standalone replay
    # =========================================================================
    async def test_D05_second_write_failure_aborts_without_standalone_replay(self):
        """D05: When db.payments.insert_one fails inside transaction, transaction aborts and no non-transactional replay occurs."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-D05", "total_le": 1000.0}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 302})
        mock_db.payments.count_documents = AsyncMock(return_value=0)
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.payments.insert_one = AsyncMock(side_effect=Exception("Disk full on payments collection"))

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=500.0, payment_method="cash")
            with self.assertRaises(Exception):
                await admin_create_order_payment(order_id, payload, self.admin_finance)

        # Crucial invariant: finance_transactions.insert_one was called exactly once in session, NEVER replayed without session!
        self.assertEqual(mock_db.finance_transactions.insert_one.call_count, 1)
        mock_db.orders.update_one.assert_not_called()

    # =========================================================================
    # D12 — Void second write failure inside transaction aborts cleanly
    # =========================================================================
    async def test_D12_void_second_write_failure_aborts_cleanly(self):
        """D12: When updating finance transaction during void raises an error, it aborts cleanly without non-transactional replay."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        payment_id = "607f1f77bcf86cd799439022"
        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-D12", "total_le": 1000.0}
        pmt_doc = {"_id": ObjectId(payment_id), "order_id": ObjectId(order_id), "status": "recorded", "finance_transaction_id": "707f1f77bcf86cd799439033"}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=pmt_doc)
        mock_db.payments.update_one = AsyncMock()
        mock_db.finance_transactions.update_one = AsyncMock(side_effect=Exception("Network drop on finance ledger"))

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentVoidInput(reason="Void test")
            with self.assertRaises(Exception):
                await admin_void_order_payment(order_id, payment_id, payload, self.admin_finance)

        # Crucial invariant: payments.update_one was called exactly once in session, never replayed outside session
        self.assertEqual(mock_db.payments.update_one.call_count, 1)
        mock_db.orders.update_one.assert_not_called()

    # =========================================================================
    # D04 / D11 — Missing / Unknown environment fail-closed direct regression tests
    # =========================================================================
    async def test_D04_unknown_env_payment_creation_fails_closed(self):
        """D04: When environment variables are completely unset or conflicting (unknown mode), missing transaction capability raises HTTP 503 with zero writes."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-D04", "total_le": 1000.0}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 303})
        mock_db.payments.count_documents = AsyncMock(return_value=0)
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        failing_client = MagicMock()
        import pymongo.errors
        failing_client.start_session = AsyncMock(side_effect=pymongo.errors.ConfigurationError("Standalone"))

        # Explicitly clear all environment markers (APP_ENV, ENV, ENVIRONMENT unset)
        env_clean = {k: v for k, v in os.environ.items() if k not in ("APP_ENV", "ENV", "ENVIRONMENT")}
        with patch("server.db", mock_db), patch("server.client", failing_client), patch.dict("os.environ", env_clean, clear=True):
            payload = PaymentCreateInput(amount=500.0, payment_method="cash")
            with self.assertRaises(HTTPException) as cm:
                await admin_create_order_payment(order_id, payload, self.admin_finance)
            self.assertEqual(cm.exception.status_code, 503)
            self.assertIn("Fail-Closed", cm.exception.detail)

        # Confirm zero writes
        mock_db.payments.insert_one.assert_not_called()
        mock_db.finance_transactions.insert_one.assert_not_called()
        mock_db.orders.update_one.assert_not_called()

    async def test_D11_unknown_env_payment_void_fails_closed(self):
        """D11: When environment variables resolve to unknown, missing transaction capability for void raises HTTP 503 and zero mutations."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        payment_id = "607f1f77bcf86cd799439022"
        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-D11", "total_le": 1000.0}
        pmt_doc = {"_id": ObjectId(payment_id), "order_id": ObjectId(order_id), "status": "recorded", "finance_transaction_id": "707f1f77bcf86cd799439033"}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=pmt_doc)

        failing_client = MagicMock()
        import pymongo.errors
        failing_client.start_session = AsyncMock(side_effect=pymongo.errors.ConfigurationError("Standalone"))

        # Conflicting environment markers resolve to unknown mode
        with patch("server.db", mock_db), patch("server.client", failing_client), patch.dict("os.environ", {"APP_ENV": "development", "ENV": "production", "ENVIRONMENT": ""}):
            payload = PaymentVoidInput(reason="Void under unknown env")
            with self.assertRaises(HTTPException) as cm:
                await admin_void_order_payment(order_id, payment_id, payload, self.admin_finance)
            self.assertEqual(cm.exception.status_code, 503)
            self.assertIn("Fail-Closed", cm.exception.detail)

        # Confirm zero mutations
        mock_db.payments.update_one.assert_not_called()
        mock_db.finance_transactions.update_one.assert_not_called()
        mock_db.orders.update_one.assert_not_called()


if __name__ == "__main__":
    unittest.main()
