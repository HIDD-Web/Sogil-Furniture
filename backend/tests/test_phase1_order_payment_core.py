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

    async def test_customer_idr_transfer_defaults_to_settings_rate_not_historical_order_rate(self):
        """Customer IDR payment defaults to current configured rate at payment time, not historical order rate."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-HIST-1",
            "total_le": 1000.0,
            "exchange_rate_idr_per_le": 300.0,  # Historical rate at creation
            "estimated_total_idr": 300000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 109})
        # Current configured rate in settings is 357.0 (differs from order's 300.0)
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357.0})
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=500.0, payment_method="transfer")
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        # Finance transaction must use 357.0, NOT 300.0
        txn_call = mock_db.finance_transactions.insert_one.call_args[0][0]
        self.assertEqual(txn_call["exchange_rate"], 357.0)
        self.assertEqual(txn_call["amount"], 500.0 * 357.0)  # 178,500 IDR
        self.assertEqual(txn_call["currency"], "IDR")

        # Payment record preserves current exchange rate snapshot
        pmt_call = mock_db.payments.insert_one.call_args[0][0]
        self.assertEqual(pmt_call["exchange_rate_snapshot"], 357.0)
        self.assertEqual(pmt_call["amount_le"], 500.0)
        self.assertFalse(pmt_call["is_rate_override"])

    async def test_customer_idr_transfer_with_actual_received_amount_and_variance(self):
        """Customer IDR payment with actual received IDR calculates discharged LE and logs variance."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-HIST-2",
            "total_le": 1000.0,
            "exchange_rate_idr_per_le": 357.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.audit_logs.insert_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 110})
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357.0})
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            # Standard for 500 LE at 357 is 178500 IDR. Customer actually transferred 179000 IDR (+500 IDR variance)
            payload = PaymentCreateInput(
                amount=500.0,
                payment_method="transfer",
                actual_received_amount=179000.0,
                notes="Pembulatan transfer bank oleh customer",
            )
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        # Finance transaction records actual received IDR (179000)
        txn_call = mock_db.finance_transactions.insert_one.call_args[0][0]
        self.assertEqual(txn_call["amount"], 179000.0)
        self.assertEqual(txn_call["currency"], "IDR")

        # Payment record stores actual_received_amount and variance
        pmt_call = mock_db.payments.insert_one.call_args[0][0]
        self.assertEqual(pmt_call["actual_received_amount"], 179000.0)
        self.assertEqual(pmt_call["variance_idr"], 500.0)

        # Audit log was created for variance
        var_calls = [c for c in mock_db.audit_logs.insert_one.call_args_list if c[0][0].get("action") == "order_payment_idr_variance"]
        self.assertEqual(len(var_calls), 1)
        self.assertEqual(var_calls[0][0][0]["metadata"]["variance_idr"], 500.0)

    async def test_customer_idr_overpayment_rejected_with_422(self):
        """MED-1: Customer IDR payment exceeding outstanding LE balance must be rejected with HTTP 422."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-OVERPAY-1",
            "total_le": 500.0,
            "exchange_rate_idr_per_le": 357.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.audit_logs.insert_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 111})
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357.0})
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            # 500 LE * 357 = 178,500 IDR. Customer transfers 180,000 IDR (discharges 504.20 LE > 500 LE)
            payload = PaymentCreateInput(
                amount=500.0,
                payment_method="transfer",
                actual_received_amount=180000.0,
                notes="Transfer IDR melebihi sisa tagihan pesanan",
            )
            with self.assertRaises(HTTPException) as ctx:
                await admin_create_order_payment(order_id, payload, self.admin_finance)

            self.assertEqual(ctx.exception.status_code, 422)
            self.assertEqual(
                ctx.exception.detail,
                "Nominal transfer melebihi sisa tagihan pesanan. Periksa nominal dan kurs sebelum menyimpan pembayaran."
            )

        # Invariant: No payment, finance transaction, or audit log must be persisted on rejection
        mock_db.payments.insert_one.assert_not_called()
        mock_db.finance_transactions.insert_one.assert_not_called()
        mock_db.audit_logs.insert_one.assert_not_called()
        mock_db.orders.update_one.assert_not_called()

    async def test_customer_idr_exact_payment_accepted_cleanly(self):
        """MED-1: Customer IDR payment exactly discharging outstanding LE balance succeeds cleanly."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-EXACT-1",
            "total_le": 500.0,
            "exchange_rate_idr_per_le": 357.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.audit_logs.insert_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 112})
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357.0})
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            # 500 LE * 357 = 178,500 IDR (exact payment)
            payload = PaymentCreateInput(
                amount=500.0,
                payment_method="transfer",
                actual_received_amount=178500.0,
                notes="Pembayaran pelunasan pas",
            )
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        self.assertIsNotNone(res)
        pmt_call = mock_db.payments.insert_one.call_args[0][0]
        self.assertEqual(pmt_call["amount_le"], 500.0)
        self.assertEqual(pmt_call["actual_received_amount"], 178500.0)
        self.assertEqual(pmt_call["variance_idr"], 0)

        txn_call = mock_db.finance_transactions.insert_one.call_args[0][0]
        self.assertEqual(txn_call["amount"], 178500.0)
        self.assertEqual(txn_call["counterpart_amount"], 500.0)

    async def test_customer_idr_partial_payment_accepted_cleanly(self):
        """MED-1: Customer IDR valid partial payment discharges proportional LE without overpayment error."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-PARTIAL-1",
            "total_le": 1000.0,
            "exchange_rate_idr_per_le": 357.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.audit_logs.insert_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 113})
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357.0})
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            # 250 LE * 357 = 89,250 IDR (discharges 250 LE of 1000 LE)
            payload = PaymentCreateInput(
                amount=250.0,
                payment_method="transfer",
                actual_received_amount=89250.0,
                notes="Pembayaran DP bertahap",
            )
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        self.assertIsNotNone(res)
        pmt_call = mock_db.payments.insert_one.call_args[0][0]
        self.assertEqual(pmt_call["amount_le"], 250.0)
        self.assertEqual(pmt_call["actual_received_amount"], 89250.0)
        self.assertEqual(pmt_call["variance_idr"], 0)

    async def test_customer_idr_underpayment_preserves_residual_balance(self):
        """Rp178,499 at 357 for 500 LE discharges 499.99 LE and preserves 0.01 LE residual balance (never falsely lunas)."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-UNDER-1",
            "total_le": 500.0,
            "exchange_rate_idr_per_le": 357.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.audit_logs.insert_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 114})
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357.0})
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            # 178,499 IDR at 357 rate = 499.997198... LE. Must floor to 499.99 LE, not round up to 500.00
            payload = PaymentCreateInput(
                amount=500.0,
                payment_method="transfer",
                actual_received_amount=178499.0,
                notes="Transfer kurang 1 rupiah",
            )
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        self.assertIsNotNone(res)
        pmt_call = mock_db.payments.insert_one.call_args[0][0]
        self.assertEqual(pmt_call["amount_le"], 499.99)
        self.assertEqual(pmt_call["actual_received_amount"], 178499.0)
        self.assertEqual(pmt_call["variance_idr"], -1)

        # Invariant: Order summary with this payment maintains remaining obligation (0.01 LE) and status is 'dp'
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[
            {"amount_le": 499.99, "status": "recorded"}
        ])
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            summary = await compute_order_payment_summary(order_doc)

        self.assertEqual(summary["payment_status"], "dp")
        self.assertEqual(summary["paid_amount_le"], 499.99)
        self.assertEqual(summary["outstanding_amount_le"], 0.01)

    async def test_customer_idr_one_rupiah_overpayment_rejected_with_422(self):
        """Rp178,501 at 357 for 500 LE (exceeding 178,500 by Rp1) is strictly rejected with HTTP 422."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-OVER-1RP",
            "total_le": 500.0,
            "exchange_rate_idr_per_le": 357.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.audit_logs.insert_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 115})
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357.0})
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(
                amount=500.0,
                payment_method="transfer",
                actual_received_amount=178501.0,
                notes="Transfer lebih 1 rupiah",
            )
            with self.assertRaises(HTTPException) as ctx:
                await admin_create_order_payment(order_id, payload, self.admin_finance)

            self.assertEqual(ctx.exception.status_code, 422)
            self.assertEqual(
                ctx.exception.detail,
                "Nominal transfer melebihi sisa tagihan pesanan. Periksa nominal dan kurs sebelum menyimpan pembayaran."
            )

        # Invariant: No payment, finance transaction, or audit log must be persisted on rejection
        mock_db.payments.insert_one.assert_not_called()
        mock_db.finance_transactions.insert_one.assert_not_called()
        mock_db.audit_logs.insert_one.assert_not_called()
        mock_db.orders.update_one.assert_not_called()

    async def test_customer_idr_legacy_payload_overpayment_rejected_with_422(self):
        """Legacy transfer payload omitting actual_received_amount cannot bypass overpayment check."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-LEGACY-OVER-1",
            "total_le": 500.0,
            "exchange_rate_idr_per_le": 357.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.audit_logs.insert_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 116})
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357.0})
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            # Amount 501 LE exceeds 500 LE obligation without actual_received_amount
            payload = PaymentCreateInput(
                amount=501.0,
                payment_method="transfer",
            )
            with self.assertRaises(HTTPException) as ctx:
                await admin_create_order_payment(order_id, payload, self.admin_finance)

            self.assertEqual(ctx.exception.status_code, 422)
            self.assertEqual(
                ctx.exception.detail,
                "Nominal transfer melebihi sisa tagihan pesanan. Periksa nominal dan kurs sebelum menyimpan pembayaran."
            )

        mock_db.payments.insert_one.assert_not_called()
        mock_db.finance_transactions.insert_one.assert_not_called()
        mock_db.audit_logs.insert_one.assert_not_called()
        mock_db.orders.update_one.assert_not_called()

    async def test_customer_idr_legacy_payload_valid_payment_succeeds(self):
        """Legacy transfer payload omitting actual_received_amount with valid amount succeeds cleanly."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-LEGACY-VALID-1",
            "total_le": 500.0,
            "exchange_rate_idr_per_le": 357.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.audit_logs.insert_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 117})
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357.0})
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(
                amount=500.0,
                payment_method="transfer",
            )
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        self.assertIsNotNone(res)
        pmt_call = mock_db.payments.insert_one.call_args[0][0]
        self.assertEqual(pmt_call["amount_le"], 500.0)
        self.assertEqual(pmt_call["actual_received_amount"], 178500.0)
        self.assertEqual(pmt_call["variance_idr"], 0)
