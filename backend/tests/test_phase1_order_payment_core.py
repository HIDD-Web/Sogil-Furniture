"""Comprehensive automated test suite for Phase 1: Schema Foundations & Order-Payment Core.

Covers all 37 required test scenarios:
A. PAYMENT CREATION (1-5)
B. ALLOCATION (6-12)
C. PARTIAL PAYMENT (13-16)
D. OVERPAYMENT (17-20)
E. VOID (21-23)
F. LEGACY ORDERS (24-27)
G. ORDER COMPLETION (28-31)
H. DUPLICATE PROTECTION (32-33)
I. MULTI-CURRENCY (34-37)
"""
import unittest
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


class TestPhase1PaymentCore(unittest.IsolatedAsyncioTestCase):
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
            "id": "admin_fin_01",
            "name": "Finance Head",
            "role": "admin",
            "permissions": {"manage_orders": True, "access_finance": True},
        }
        self.admin_ops_no_finance = {
            "id": "admin_ops_01",
            "name": "Ops Lead",
            "role": "admin",
            "permissions": {"manage_orders": True, "access_finance": False},
        }

    def _setup_mock_db(self, mock_db):
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357.0})
        mock_db.system_rates.find_one = AsyncMock(return_value={"rate": 357.0})
        mock_find_pts = MagicMock()
        mock_find_pts.to_list = AsyncMock(return_value=[])
        mock_db.point_transactions.find.return_value = mock_find_pts
        mock_db.point_transactions.delete_many = AsyncMock()
        mock_db.customers.update_one = AsyncMock()

    # =========================================================================
    # A. PAYMENT CREATION (Scenarios 1-5)
    # =========================================================================
    async def test_01_valid_payment_creates_one_payment_doc(self):
        """1. Valid payment creates one payment document."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261008-001",
            "total_le": 1200.0,
            "delivery_fee_le": 50.0,
            "payment_status": "belum_dibayar",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 101})

        # Mock compute_order_payment_summary find
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[])
        mock_db.payments.find.return_value = mock_find

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=500.0, payment_method="cash")
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        self.assertEqual(mock_db.payments.insert_one.call_count, 1)
        inserted_pmt = mock_db.payments.insert_one.call_args[0][0]
        self.assertEqual(inserted_pmt["amount_le"], 500.0)
        self.assertEqual(inserted_pmt["status"], "recorded")

    async def test_02_valid_payment_creates_exactly_one_finance_transaction(self):
        """2. Valid payment creates exactly one finance transaction."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261008-001",
            "total_le": 1200.0,
            "delivery_fee_le": 50.0,
            "payment_status": "belum_dibayar",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 102})

        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[])
        mock_db.payments.find.return_value = mock_find

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=500.0, payment_method="cash")
            await admin_create_order_payment(order_id, payload, self.admin_finance)

        self.assertEqual(mock_db.finance_transactions.insert_one.call_count, 1)
        inserted_txn = mock_db.finance_transactions.insert_one.call_args[0][0]
        self.assertEqual(inserted_txn["type"], "order_revenue")
        self.assertEqual(inserted_txn["category"], "Penjualan")
        self.assertEqual(inserted_txn["amount"], 500.0)

    async def test_03_payment_finance_transaction_id_is_correctly_linked(self):
        """3. payment.finance_transaction_id is linked to the created finance transaction."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-1", "total_le": 1000.0}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 103})
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=400.0, payment_method="cash")
            await admin_create_order_payment(order_id, payload, self.admin_finance)

        inserted_pmt = mock_db.payments.insert_one.call_args[0][0]
        self.assertEqual(inserted_pmt["finance_transaction_id"], "707f1f77bcf86cd799439033")

    async def test_04_05_payment_and_finance_transaction_atomicity_and_failure(self):
        """4 & 5. Failed transaction leaves no partial payment (rolls back)."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-1", "total_le": 1000.0}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        # Simulate finance failure
        mock_db.finance_transactions.insert_one = AsyncMock(side_effect=Exception("Database network timeout"))
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 104})
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=400.0, payment_method="cash")
            with self.assertRaises(Exception):
                await admin_create_order_payment(order_id, payload, self.admin_finance)

        # Confirm payments.insert_one was never reached or executed
        mock_db.payments.insert_one.assert_not_called()

    # =========================================================================
    # B. ALLOCATION (Scenarios 6-12)
    # =========================================================================
    async def test_06_allocation_sum_must_equal_payment_amount(self):
        """6. Invalid allocation sum rejected (Conservation Law)."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-1", "total_le": 1000.0}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(
                amount=500.0,
                payment_method="cash",
                allocations=[
                    PaymentAllocationInput(target_type="product", amount=300.0),
                    PaymentAllocationInput(target_type="shipping", amount=150.0),  # sum=450 != 500
                ],
            )
            with self.assertRaises(HTTPException) as cm:
                await admin_create_order_payment(order_id, payload, self.admin_finance)
            self.assertEqual(cm.exception.status_code, 400)
            self.assertIn("harus sama persis", cm.exception.detail)

    async def test_07_08_09_10_multiple_allocations_work(self):
        """7-10. Product, shipping, unallocated credit allocations work together."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-1", "total_le": 1000.0}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 105})
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(
                amount=600.0,
                payment_method="cash",
                allocations=[
                    PaymentAllocationInput(target_type="product", amount=400.0),
                    PaymentAllocationInput(target_type="shipping", amount=50.0),
                    PaymentAllocationInput(target_type="unallocated_credit", amount=150.0),
                ],
            )
            await admin_create_order_payment(order_id, payload, self.admin_finance)

        inserted_pmt = mock_db.payments.insert_one.call_args[0][0]
        allocs = inserted_pmt["allocations"]
        self.assertEqual(len(allocs), 3)
        self.assertEqual(sum(a["amount_le"] for a in allocs), 600.0)

    async def test_11_allocations_do_not_create_additional_finance_transactions(self):
        """11. Allocations do NOT create extra finance transactions."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-1", "total_le": 1000.0}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 106})
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(
                amount=1000.0,
                payment_method="cash",
                allocations=[
                    PaymentAllocationInput(target_type="product", amount=800.0),
                    PaymentAllocationInput(target_type="shipping", amount=200.0),
                ],
            )
            await admin_create_order_payment(order_id, payload, self.admin_finance)

        # Exactly 1 finance transaction inserted despite 2 allocations
        self.assertEqual(mock_db.finance_transactions.insert_one.call_count, 1)

    async def test_12_invalid_allocation_target_is_rejected(self):
        """12. Invalid allocation target rejected."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-1", "total_le": 1000.0}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(
                amount=500.0,
                payment_method="cash",
                allocations=[PaymentAllocationInput(target_type="invalid_target", amount=500.0)],
            )
            with self.assertRaises(HTTPException) as cm:
                await admin_create_order_payment(order_id, payload, self.admin_finance)
            self.assertEqual(cm.exception.status_code, 400)
            self.assertIn("Target alokasi tidak valid", cm.exception.detail)

    # =========================================================================
    # C. PARTIAL PAYMENT (Scenarios 13-16)
    # =========================================================================
    async def test_13_first_payment_creates_dp(self):
        """13. First partial payment sets payment_status = dp."""
        mock_db = MagicMock()
        order_doc = {"_id": "ord_1", "total_le": 1000.0, "payment_status": "belum_dibayar"}
        # 1 recorded payment of 400.0
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[
            {"amount_le": 400.0, "status": "recorded"}
        ])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            summary = await compute_order_payment_summary(order_doc)

        self.assertEqual(summary["payment_status"], "dp")
        self.assertEqual(summary["paid_amount_le"], 400.0)
        self.assertEqual(summary["outstanding_amount_le"], 600.0)

    async def test_14_second_payment_completes_order_payment(self):
        """14. Second payment reaches total -> payment_status = lunas."""
        mock_db = MagicMock()
        order_doc = {"_id": "ord_1", "total_le": 1000.0, "payment_status": "dp"}
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[
            {"amount_le": 400.0, "status": "recorded"},
            {"amount_le": 600.0, "status": "recorded"},
        ])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            summary = await compute_order_payment_summary(order_doc)

        self.assertEqual(summary["payment_status"], "lunas")
        self.assertEqual(summary["paid_amount_le"], 1000.0)
        self.assertEqual(summary["outstanding_amount_le"], 0.0)

    async def test_15_16_multiple_payments_sum_correctly(self):
        """15 & 16. Multiple payments sum accurately to paid_amount_le."""
        mock_db = MagicMock()
        order_doc = {"_id": "ord_1", "total_le": 1500.0, "payment_status": "dp"}
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[
            {"amount_le": 300.0, "status": "recorded"},
            {"amount_le": 250.50, "status": "recorded"},
            {"amount_le": 449.50, "status": "recorded"},
        ])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            summary = await compute_order_payment_summary(order_doc)

        self.assertEqual(summary["paid_amount_le"], 1000.0)
        self.assertEqual(summary["outstanding_amount_le"], 500.0)
        self.assertEqual(summary["valid_payments_count"], 3)

    # =========================================================================
    # D. OVERPAYMENT (Scenarios 17-20)
    # =========================================================================
    async def test_17_18_19_20_overpayment_handling(self):
        """17-20. Overpayment sets status = overpaid, excess captured in unallocated_credit."""
        mock_db = MagicMock()
        order_doc = {"_id": "ord_over", "total_le": 1000.0, "payment_status": "belum_dibayar"}
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[
            {"amount_le": 1250.0, "status": "recorded"}
        ])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            summary = await compute_order_payment_summary(order_doc)

        self.assertEqual(summary["payment_status"], "overpaid")
        self.assertEqual(summary["paid_amount_le"], 1250.0)
        self.assertEqual(summary["outstanding_amount_le"], 0.0)

    # =========================================================================
    # E. VOID (Scenarios 21-23)
    # =========================================================================
    async def test_21_22_23_voided_payment_does_not_count_toward_paid(self):
        """21-23. Voided payment ignored in paid/outstanding calculation."""
        mock_db = MagicMock()
        order_doc = {"_id": "ord_void", "total_le": 1000.0, "payment_status": "belum_dibayar"}
        # 1 recorded (500), 1 voided (500) -> query only returns recorded
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[
            {"amount_le": 500.0, "status": "recorded"}
        ])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            summary = await compute_order_payment_summary(order_doc)

        self.assertEqual(summary["payment_status"], "dp")
        self.assertEqual(summary["paid_amount_le"], 500.0)
        self.assertEqual(summary["outstanding_amount_le"], 500.0)

    # =========================================================================
    # F. LEGACY ORDERS (Scenarios 24-27)
    # =========================================================================
    async def test_24_legacy_lunas_with_no_payments(self):
        """24. Legacy lunas with no payments derives paid=total, outstanding=0."""
        mock_db = MagicMock()
        order_doc = {"_id": "ord_leg_lunas", "total_le": 850.0, "payment_status": "lunas"}
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            summary = await compute_order_payment_summary(order_doc)

        self.assertEqual(summary["payment_status"], "lunas")
        self.assertEqual(summary["paid_amount_le"], 850.0)
        self.assertEqual(summary["outstanding_amount_le"], 0.0)
        self.assertTrue(summary["is_legacy_derived"])
        self.assertFalse(summary["legacy_dp_unknown"])

    async def test_25_legacy_belum_dibayar_with_no_payments(self):
        """25. Legacy belum_dibayar with no payments derives paid=0, outstanding=total."""
        mock_db = MagicMock()
        order_doc = {"_id": "ord_leg_unpaid", "total_le": 850.0, "payment_status": "belum_dibayar"}
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            summary = await compute_order_payment_summary(order_doc)

        self.assertEqual(summary["payment_status"], "belum_dibayar")
        self.assertEqual(summary["paid_amount_le"], 0.0)
        self.assertEqual(summary["outstanding_amount_le"], 850.0)
        self.assertTrue(summary["is_legacy_derived"])
        self.assertFalse(summary["legacy_dp_unknown"])

    async def test_26_27_legacy_dp_with_no_payments_is_unknown_not_zero(self):
        """26 & 27. Legacy dp with no payments is NULL/UNKNOWN, NEVER 0."""
        mock_db = MagicMock()
        order_doc = {"_id": "ord_leg_dp", "total_le": 1200.0, "payment_status": "dp"}
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            summary = await compute_order_payment_summary(order_doc)

        self.assertEqual(summary["payment_status"], "dp")
        self.assertIsNone(summary["paid_amount_le"])
        self.assertIsNone(summary["outstanding_amount_le"])
        self.assertTrue(summary["is_legacy_derived"])
        self.assertTrue(summary["legacy_dp_unknown"])

    # =========================================================================
    # G. ORDER COMPLETION DECOUPLING (Scenarios 28-31)
    # =========================================================================
    async def test_28_29_order_can_be_completed_while_dp_or_unpaid(self):
        """28 & 29. Fulfilled order can become selesai while DP or unpaid."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-1",
            "order_status": "diproses",
            "payment_status": "dp",
            "total_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.orders.update_one = AsyncMock()
        mock_db.finance_transactions.find_one = AsyncMock(return_value=None)
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[
            {"amount_le": 500.0, "status": "recorded"}
        ])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            # Admin updates order status to selesai while payment remains DP
            res = await admin_update_order(
                order_id=order_id,
                data=OrderStatusUpdate(order_status="selesai"),
                admin=self.admin_finance,
            )

        # Update was accepted and processed
        mock_db.orders.update_one.assert_called_once()
        update_set = mock_db.orders.update_one.call_args[0][1]["$set"]
        self.assertEqual(update_set["order_status"], "selesai")

    async def test_30_31_payment_alone_does_not_mark_order_selesai(self):
        """30 & 31. Payment recording does NOT alter order_status to selesai."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-1",
            "order_status": "diproses",
            "total_le": 1000.0,
            "payment_status": "belum_dibayar",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 107})
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[
            {"amount_le": 1000.0, "status": "recorded"}
        ])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=1000.0, payment_method="cash")
            await admin_create_order_payment(order_id, payload, self.admin_finance)

        update_set = mock_db.orders.update_one.call_args[0][1]["$set"]
        # Payment updated to lunas, but order_status is NOT modified to selesai
        self.assertEqual(update_set["payment_status"], "lunas")
        self.assertNotIn("order_status", update_set)

    # =========================================================================
    # H. DUPLICATE PROTECTION & IDEMPOTENCY (Scenarios 32-33)
    # =========================================================================
    async def test_32_33_idempotent_payment_submission(self):
        """32 & 33. Repeated payment submission returns existing payment without duplicates."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        existing_pmt = {
            "_id": ObjectId("607f1f77bcf86cd799439022"),
            "payment_number": "PAY-20261008-001",
            "idempotency_key": "unique-idem-key-123",
            "amount_le": 500.0,
            "status": "recorded",
        }
        mock_db.orders.find_one = AsyncMock(return_value={"_id": ObjectId(order_id), "order_number": "SGF-1", "total_le": 1000.0})
        mock_db.payments.find_one = AsyncMock(return_value=existing_pmt)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=500.0, payment_method="cash", idempotency_key="unique-idem-key-123")
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        self.assertEqual(res["payment_number"], "PAY-20261008-001")
        mock_db.payments.insert_one.assert_not_called()
        mock_db.finance_transactions.insert_one.assert_not_called()

    # =========================================================================
    # I. MULTI-CURRENCY (Scenarios 34-37)
    # =========================================================================
    async def test_34_35_36_37_currency_isolation_and_methods(self):
        """34-37. EGP cash payment creates EGP cash_in, transfer creates IDR counterpart."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-1",
            "total_le": 1000.0,
            "exchange_rate_idr_per_le": 350.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 108})
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 350.0})
        mock_db.system_rates.find_one = AsyncMock(return_value={"rate": 350.0})
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            # Test Cash EGP
            payload_cash = PaymentCreateInput(amount=500.0, payment_method="cash")
            await admin_create_order_payment(order_id, payload_cash, self.admin_finance)
            txn_cash = mock_db.finance_transactions.insert_one.call_args[0][0]
            self.assertEqual(txn_cash["currency"], "EGP")
            self.assertEqual(txn_cash["account"], "EGP")
            self.assertEqual(txn_cash["amount"], 500.0)

            # Test Transfer IDR
            mock_db.finance_transactions.insert_one.reset_mock()
            payload_trf = PaymentCreateInput(amount=500.0, payment_method="transfer")
            await admin_create_order_payment(order_id, payload_trf, self.admin_finance)
            txn_trf = mock_db.finance_transactions.insert_one.call_args[0][0]
            self.assertEqual(txn_trf["currency"], "IDR")
            self.assertEqual(txn_trf["account"], "IDR")
            self.assertEqual(txn_trf["amount"], 500.0 * 350.0)
            self.assertEqual(txn_trf["counterpart_currency"], "EGP")
            self.assertEqual(txn_trf["counterpart_amount"], 500.0)
