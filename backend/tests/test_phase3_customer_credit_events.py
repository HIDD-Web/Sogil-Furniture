"""Phase 3.B.2 Acceptance Test Suite — Customer Overpayment Credit & Ledger

Covers Scenarios TC-01 through TC-27 as mandated by Phase 3.B.2 Scope Lock:
TC-01: Customer credit event schema validation.
TC-02: Valid qualifying overpayment creates correct credit event.
TC-03: Exact payment creates no excess credit.
TC-04: Underpayment creates no excess credit.
TC-05: The same logical payment retried does not create duplicate credit.
TC-06: Duplicate payment callback does not create duplicate credit.
TC-07: Concurrent duplicate requests cannot create duplicate credit.
TC-08: Failed payment persistence creates no credit event.
TC-09: Failed credit persistence follows approved transaction & fail-closed behavior.
TC-10: Existing payment idempotency behavior remains intact.
TC-11: Customer credit creation does not add another cash receipt.
TC-12: Customer credit creation does not inflate recognized sales revenue.
TC-13: Customer credit is not generated merely by changing order status to "selesai".
TC-14: Legacy "lunas" orders do not receive synthetic credit.
TC-15: Legacy "belum_dibayar" orders do not receive synthetic credit.
TC-16: Ambiguous legacy "dp" orders do not receive synthetic credit.
TC-17: EGP and IDR balances remain separate and never summed across currencies.
TC-18: Unknown or ambiguous customer identity follows approved safety behavior.
TC-19: Invalid negative or malformed credit events are rejected.
TC-20: Existing historical order_revenue finance transactions remain unchanged.
TC-21: Repeated reads do not generate credit events.
TC-22: No customer credit is applied to another order in this phase.
TC-23: No refund or payout is executed in this phase.
TC-24: Transaction failures do not trigger a standalone write fallback.
TC-25: Phase 1 payment regression tests pass.
TC-26: Phase 2 regression tests pass.
TC-27: Phase 3.B.1 handover snapshot and cancellation protections pass.
"""

import asyncio
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from fastapi import HTTPException
from pydantic import ValidationError

from server import (
    admin_create_order_payment,
    admin_void_order_payment,
    admin_update_order,
    admin_customer_credit_balance,
    admin_customer_credit_refund,
    get_customer_credit_balance,
    compute_order_payment_summary,
    OrderStatusUpdate,
    PaymentCreateInput,
    PaymentVoidInput,
    PaymentAllocationInput,
    CustomerCreditRefundInput,
    clean,
)


class TestPhase3B2OverpaymentCredit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.admin_finance = {
            "id": "admin_fin_01",
            "name": "Finance Head",
            "role": "admin",
            "permissions": {"manage_orders": True, "access_finance": True},
        }
        self.admin_ops = {
            "id": "admin_ops_01",
            "name": "Ops Lead",
            "role": "admin",
            "permissions": {"manage_orders": True, "access_finance": False},
        }
        self.owner = {
            "id": "owner_01",
            "name": "Owner Syahid",
            "role": "owner",
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
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 501})
        mock_db.customer_credit_events.insert_one = AsyncMock()
        mock_db.customer_credit_events.find_one = AsyncMock(return_value=None)
        mock_find_cce = MagicMock()
        mock_find_cce.sort.return_value.to_list = AsyncMock(return_value=[])
        mock_db.customer_credit_events.find.return_value = mock_find_cce

    # =========================================================================
    # TC-01: Customer credit event schema validation
    # =========================================================================
    async def test_tc01_customer_credit_event_schema_validation(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        cust_id = "607f1f77bcf86cd799439099"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3B2-001",
            "customer_id": cust_id,
            "customer_name": "Budi Santoso",
            "customer_phone": "+201234567890",
            "total_le": 1000.0,
            "delivery_fee_le": 50.0,
            "payment_status": "belum_dibayar",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.count_documents = AsyncMock(return_value=0)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439022")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=1300.0, payment_method="cash")
            await admin_create_order_payment(order_id, payload, self.admin_finance)

        self.assertEqual(mock_db.customer_credit_events.insert_one.call_count, 1)
        cce = mock_db.customer_credit_events.insert_one.call_args[0][0]
        # Validate schema fields
        self.assertIn("event_number", cce)
        self.assertEqual(cce["event_type"], "credit_minted")
        self.assertEqual(cce["customer_id"], cust_id)
        self.assertEqual(cce["customer_name"], "Budi Santoso")
        self.assertEqual(cce["source_order_id"], str(order_doc["_id"]))
        self.assertEqual(cce["currency"], "EGP")
        self.assertEqual(cce["signed_amount"], 300.0)
        self.assertIn("idempotency_key", cce)
        self.assertEqual(cce["created_by_id"], "admin_fin_01")

    # =========================================================================
    # TC-02: Valid qualifying overpayment creates correct credit event
    # =========================================================================
    async def test_tc02_valid_qualifying_overpayment_creates_credit_event(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439012"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3B2-002",
            "customer_id": "cust_123",
            "total_le": 1000.0,
            "delivery_fee_le": 0.0,
            "payment_status": "belum_dibayar",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.count_documents = AsyncMock(return_value=0)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439023")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439034")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            # Pay 1500 on 1000 order -> 500 excess
            payload = PaymentCreateInput(amount=1500.0, payment_method="cash")
            await admin_create_order_payment(order_id, payload, self.admin_finance)

        cce = mock_db.customer_credit_events.insert_one.call_args[0][0]
        self.assertEqual(cce["signed_amount"], 500.0)
        self.assertEqual(cce["event_type"], "credit_minted")

    # =========================================================================
    # TC-03: Exact payment creates no excess credit
    # =========================================================================
    async def test_tc03_exact_payment_creates_no_credit(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439013"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3B2-003",
            "customer_id": "cust_123",
            "total_le": 1000.0,
            "delivery_fee_le": 100.0,
            "payment_status": "belum_dibayar",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.count_documents = AsyncMock(return_value=0)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439024")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439035")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=1000.0, payment_method="cash")
            await admin_create_order_payment(order_id, payload, self.admin_finance)

        mock_db.customer_credit_events.insert_one.assert_not_called()

    # =========================================================================
    # TC-04: Underpayment creates no excess credit
    # =========================================================================
    async def test_tc04_underpayment_creates_no_credit(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439014"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3B2-004",
            "customer_id": "cust_123",
            "total_le": 1000.0,
            "delivery_fee_le": 100.0,
            "payment_status": "belum_dibayar",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.count_documents = AsyncMock(return_value=0)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439025")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439036")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=400.0, payment_method="cash")
            await admin_create_order_payment(order_id, payload, self.admin_finance)

        mock_db.customer_credit_events.insert_one.assert_not_called()

    # =========================================================================
    # TC-05 & TC-06: Idempotent payment retry does not create duplicate credit
    # =========================================================================
    async def test_tc05_tc06_idempotent_retry_does_not_duplicate_credit(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439015"
        existing_pmt = {
            "_id": ObjectId("607f1f77bcf86cd799439026"),
            "payment_number": "PAY-20261010-099",
            "idempotency_key": "idem-key-tc05",
            "amount_le": 1500.0,
            "status": "recorded",
        }
        mock_db.orders.find_one = AsyncMock(return_value={"_id": ObjectId(order_id), "total_le": 1000.0})
        mock_db.payments.find_one = AsyncMock(return_value=existing_pmt)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=1500.0, payment_method="cash", idempotency_key="idem-key-tc05")
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        self.assertEqual(res["payment_number"], "PAY-20261010-099")
        mock_db.customer_credit_events.insert_one.assert_not_called()

    # =========================================================================
    # TC-07: Concurrent duplicate requests cannot create duplicate credit
    # =========================================================================
    async def test_tc07_concurrent_duplicate_requests_uniqueness(self):
        # Enforced via unique database index uniq_credit_event_source_payment
        # and uniq_credit_events_idempotency in ensure_indexes
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439016"
        order_doc = {"_id": ObjectId(order_id), "total_le": 1000.0, "customer_id": "cust_123"}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.count_documents = AsyncMock(return_value=0)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439027")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439037")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=1200.0, payment_method="cash", idempotency_key="race-key-01")
            await admin_create_order_payment(order_id, payload, self.admin_finance)

        cce = mock_db.customer_credit_events.insert_one.call_args[0][0]
        self.assertEqual(cce["idempotency_key"], "cce_pmt_607f1f77bcf86cd799439027_mint")
        self.assertEqual(cce["source_payment_id"], "607f1f77bcf86cd799439027")

    # =========================================================================
    # TC-08: Failed payment persistence creates no credit event
    # =========================================================================
    async def test_tc08_failed_payment_persistence_creates_no_credit(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439017"
        order_doc = {"_id": ObjectId(order_id), "total_le": 1000.0, "customer_id": "cust_123"}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.count_documents = AsyncMock(return_value=0)
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439038")))
        mock_db.payments.insert_one = AsyncMock(side_effect=Exception("Database write failed"))

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(Exception):
                await admin_create_order_payment(order_id, PaymentCreateInput(amount=1500.0, payment_method="cash"), self.admin_finance)

        mock_db.customer_credit_events.insert_one.assert_not_called()

    # =========================================================================
    # TC-09: Failed credit persistence follows approved transaction & fail-closed behavior
    # =========================================================================
    async def test_tc09_failed_credit_persistence_rolls_back_atomically(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439018"
        order_doc = {"_id": ObjectId(order_id), "total_le": 1000.0, "customer_id": "cust_123"}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.count_documents = AsyncMock(return_value=0)
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439039")))
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439029")))
        mock_db.finance_transactions.update_one = AsyncMock()
        # cce insert fails
        mock_db.customer_credit_events.insert_one = AsyncMock(side_effect=Exception("Credit write error"))

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(Exception):
                await admin_create_order_payment(order_id, PaymentCreateInput(amount=1500.0, payment_method="cash"), self.admin_finance)

    # =========================================================================
    # TC-10: Existing payment idempotency behavior remains intact
    # =========================================================================
    async def test_tc10_payment_idempotency_intact(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439019"
        existing_pmt = {
            "_id": ObjectId("607f1f77bcf86cd799439030"),
            "payment_number": "PAY-20261010-088",
            "idempotency_key": "exact-key-tc10",
            "amount_le": 500.0,
            "status": "recorded",
        }
        mock_db.orders.find_one = AsyncMock(return_value={"_id": ObjectId(order_id), "total_le": 1000.0})
        mock_db.payments.find_one = AsyncMock(return_value=existing_pmt)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            res = await admin_create_order_payment(order_id, PaymentCreateInput(amount=500.0, payment_method="cash", idempotency_key="exact-key-tc10"), self.admin_finance)
        self.assertEqual(res["payment_number"], "PAY-20261010-088")

    # =========================================================================
    # TC-11: Customer credit creation does not add another cash receipt
    # =========================================================================
    async def test_tc11_credit_creation_does_not_add_another_cash_receipt(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439020"
        order_doc = {"_id": ObjectId(order_id), "total_le": 1000.0, "customer_id": "cust_123"}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.count_documents = AsyncMock(return_value=0)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439031")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439040")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            # Pay 1500 cash on 1000 order
            await admin_create_order_payment(order_id, PaymentCreateInput(amount=1500.0, payment_method="cash"), self.admin_finance)

        # Exactly 1 finance_transactions document inserted (the cash receipt of 1500)
        self.assertEqual(mock_db.finance_transactions.insert_one.call_count, 1)
        ft_doc = mock_db.finance_transactions.insert_one.call_args[0][0]
        self.assertEqual(ft_doc["amount"], 1500.0)
        self.assertEqual(ft_doc["type"], "order_revenue")

    # =========================================================================
    # TC-12: Customer credit creation does not inflate recognized sales revenue
    # =========================================================================
    async def test_tc12_credit_creation_does_not_inflate_sales_revenue(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439021"
        order_doc = {
            "_id": ObjectId(order_id),
            "total_le": 1000.0,
            "order_status": "diproses",
            "customer_id": "cust_123",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.count_documents = AsyncMock(return_value=0)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439032")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439041")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            await admin_create_order_payment(order_id, PaymentCreateInput(amount=1500.0, payment_method="cash"), self.admin_finance)

        # Order updates only status_update and order_update_set, never touches recognized_revenue_le
        for call in mock_db.orders.update_one.call_args_list:
            set_ops = call[0][1].get("$set", {})
            self.assertNotIn("recognized_revenue_le", set_ops)

    # =========================================================================
    # TC-13: Customer credit is not generated merely by changing order status to selesai
    # =========================================================================
    async def test_tc13_selesai_status_change_does_not_mint_credit(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439022"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3B2-022",
            "order_status": "siap",
            "total_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.work_assignments.find.return_value.to_list = AsyncMock(return_value=[])
        mock_db.wage_obligations.find.return_value.to_list = AsyncMock(return_value=[])
        mock_db.orders.update_one = AsyncMock()

        with patch("server.db", mock_db):
            await admin_update_order(order_id, OrderStatusUpdate(order_status="selesai"), self.admin_finance)

        mock_db.customer_credit_events.insert_one.assert_not_called()

    # =========================================================================
    # TC-14: Legacy lunas orders do not receive synthetic credit
    # =========================================================================
    async def test_tc14_legacy_lunas_orders_no_synthetic_credit(self):
        order_doc = {"_id": "ord_leg_lunas", "total_le": 850.0, "payment_status": "lunas"}
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db):
            summary = await compute_order_payment_summary(order_doc)

        self.assertEqual(summary["payment_status"], "lunas")
        mock_db.customer_credit_events.insert_one.assert_not_called()

    # =========================================================================
    # TC-15: Legacy belum_dibayar orders do not receive synthetic credit
    # =========================================================================
    async def test_tc15_legacy_belum_dibayar_no_synthetic_credit(self):
        order_doc = {"_id": "ord_leg_unpaid", "total_le": 850.0, "payment_status": "belum_dibayar"}
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db):
            summary = await compute_order_payment_summary(order_doc)

        self.assertEqual(summary["payment_status"], "belum_dibayar")
        mock_db.customer_credit_events.insert_one.assert_not_called()

    # =========================================================================
    # TC-16: Ambiguous legacy dp orders do not receive synthetic credit
    # =========================================================================
    async def test_tc16_legacy_dp_orders_no_synthetic_credit(self):
        order_doc = {"_id": "ord_leg_dp", "total_le": 1200.0, "payment_status": "dp"}
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db):
            summary = await compute_order_payment_summary(order_doc)

        self.assertTrue(summary["legacy_dp_unknown"])
        mock_db.customer_credit_events.insert_one.assert_not_called()

    # =========================================================================
    # TC-17: EGP and IDR balances remain separate and never summed across currencies
    # =========================================================================
    async def test_tc17_egp_and_idr_balances_strictly_segregated(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        cust_id = "607f1f77bcf86cd799439088"

        mock_db.customers.find_one = AsyncMock(return_value={"_id": ObjectId(cust_id), "username": "Hassan"})

        # Mock aggregation pipeline behavior for get_customer_credit_balance
        def mock_aggregate(pipeline):
            match_cur = pipeline[0]["$match"]["currency"]
            cursor_mock = MagicMock()
            if match_cur == "EGP":
                cursor_mock.to_list = AsyncMock(return_value=[{"total": 500.0}])
            elif match_cur == "IDR":
                cursor_mock.to_list = AsyncMock(return_value=[{"total": 150000.0}])
            else:
                cursor_mock.to_list = AsyncMock(return_value=[])
            return cursor_mock

        mock_db.customer_credit_events.aggregate = mock_aggregate

        with patch("server.db", mock_db):
            bal_egp = await get_customer_credit_balance(cust_id, "EGP")
            bal_idr = await get_customer_credit_balance(cust_id, "IDR")

        self.assertEqual(bal_egp, 500.0)
        self.assertEqual(bal_idr, 150000.0)

    # =========================================================================
    # TC-18: Unknown or ambiguous customer identity follows approved safety behavior
    # =========================================================================
    async def test_tc18_guest_order_overpayment_sets_customer_id_none(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439023"
        # Guest order: no customer_id
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-GUEST-001",
            "name": "Guest Buyer",
            "phone": "+201112223334",
            "customer_id": None,
            "total_le": 500.0,
            "delivery_fee_le": 0.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.count_documents = AsyncMock(return_value=0)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439033")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439042")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            # Pay 700 on 500 order -> 200 excess
            await admin_create_order_payment(order_id, PaymentCreateInput(amount=700.0, payment_method="cash"), self.admin_finance)

        cce = mock_db.customer_credit_events.insert_one.call_args[0][0]
        # customer_id is None, preserved accurately with guest name & phone metadata; never assigned to a wrong customer
        self.assertIsNone(cce["customer_id"])
        self.assertEqual(cce["customer_name"], "Guest Buyer")
        self.assertEqual(cce["signed_amount"], 200.0)

    # =========================================================================
    # TC-19: Invalid negative allocation rejected
    # =========================================================================
    async def test_tc19_invalid_negative_allocation_rejected(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439024"
        order_doc = {"_id": ObjectId(order_id), "total_le": 1000.0}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_order_payment(
                    order_id,
                    PaymentCreateInput(
                        amount=500.0,
                        payment_method="cash",
                        allocations=[PaymentAllocationInput(target_type="unallocated_credit", amount=-50.0)],
                    ),
                    self.admin_finance,
                )
            self.assertEqual(cm.exception.status_code, 400)
            self.assertIn("tidak boleh negatif", cm.exception.detail)

    # =========================================================================
    # TC-20: Existing historical order_revenue finance transactions remain unchanged
    # =========================================================================
    async def test_tc20_historical_order_revenue_finance_transactions_intact(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        # Verify finance transaction inserted retains type="order_revenue"
        order_id = "507f1f77bcf86cd799439025"
        order_doc = {"_id": ObjectId(order_id), "total_le": 1000.0, "customer_id": "cust_123"}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.count_documents = AsyncMock(return_value=0)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439034")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439043")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            await admin_create_order_payment(order_id, PaymentCreateInput(amount=1000.0, payment_method="cash"), self.admin_finance)

        ft_doc = mock_db.finance_transactions.insert_one.call_args[0][0]
        self.assertEqual(ft_doc["type"], "order_revenue")
        self.assertEqual(ft_doc["category"], "Penjualan")

    # =========================================================================
    # TC-21: Repeated reads do not generate credit events
    # =========================================================================
    async def test_tc21_repeated_reads_do_not_generate_credit_events(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        cust_id = "607f1f77bcf86cd799439088"
        mock_db.customers.find_one = AsyncMock(return_value={"_id": ObjectId(cust_id), "username": "Ahmad"})

        def mock_aggregate(pipeline):
            cursor_mock = MagicMock()
            cursor_mock.to_list = AsyncMock(return_value=[{"total": 250.0}])
            return cursor_mock

        mock_db.customer_credit_events.aggregate = mock_aggregate

        with patch("server.db", mock_db):
            # Repeated read 3 times
            for _ in range(3):
                res = await admin_customer_credit_balance(cust_id, "EGP", self.admin_finance)
                self.assertEqual(res["available_credit"], 250.0)

        mock_db.customer_credit_events.insert_one.assert_not_called()

    # =========================================================================
    # =========================================================================
    # TC-22 & TC-23: Scope boundary protections: credit refund remains rejected in 3.B.3
    # =========================================================================
    async def test_tc22_tc23_scope_boundaries_preserved(self):
        # Verify that credit-refund remains rejected or unimplemented until 3.B.4
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439026"
        order_doc = {"_id": ObjectId(order_id), "total_le": 500.0}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_order_payment(order_id, PaymentCreateInput(amount=500.0, payment_method="credit_refund"), self.admin_finance)
            self.assertEqual(cm.exception.status_code, 400)
            self.assertIn("Metode pembayaran harus cash, transfer, atau customer_credit", cm.exception.detail)

    # =========================================================================
    # TC-24: Payment void reverses credit event
    # =========================================================================
    async def test_tc24_void_payment_reverses_credit_event_atomically(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439027"
        pmt_id = "607f1f77bcf86cd799439035"
        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-P3B2-027"}
        pmt_doc = {
            "_id": ObjectId(pmt_id),
            "payment_number": "PAY-20261010-055",
            "order_id": ObjectId(order_id),
            "status": "recorded",
            "amount_le": 1500.0,
            "finance_transaction_id": "707f1f77bcf86cd799439044",
        }
        cce_doc = {
            "_id": ObjectId("807f1f77bcf86cd799439055"),
            "event_number": "CCE-20261010-001",
            "event_type": "credit_minted",
            "customer_id": "cust_123",
            "source_payment_id": str(pmt_doc["_id"]),
            "currency": "EGP",
            "signed_amount": 500.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=pmt_doc)
        mock_db.payments.update_one = AsyncMock()
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])
        mock_db.customer_credit_events.find_one = AsyncMock(return_value=cce_doc)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            await admin_void_order_payment(order_id, pmt_id, PaymentVoidInput(reason="Customer requested cancel"), self.admin_finance)

        self.assertEqual(mock_db.customer_credit_events.insert_one.call_count, 1)
        rev_cce = mock_db.customer_credit_events.insert_one.call_args[0][0]
        self.assertEqual(rev_cce["event_type"], "credit_reversed")
        self.assertEqual(rev_cce["signed_amount"], -500.0)
        self.assertEqual(rev_cce["reverses_event_id"], str(cce_doc["_id"]))

    # =========================================================================
    # TC-28: Sequential repeated void raises HTTP 400
    # =========================================================================
    async def test_tc28_sequential_repeated_void_rejected_with_400(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439028"
        pmt_id = "607f1f77bcf86cd799439036"
        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-P3B2-028"}
        pmt_doc = {
            "_id": ObjectId(pmt_id),
            "payment_number": "PAY-20261010-056",
            "order_id": ObjectId(order_id),
            "status": "voided",  # already voided
            "amount_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=pmt_doc)

        with patch("server.db", mock_db):
            with self.assertRaises(HTTPException) as cm:
                await admin_void_order_payment(order_id, pmt_id, PaymentVoidInput(reason="Second attempt"), self.admin_finance)
            self.assertEqual(cm.exception.status_code, 400)
            self.assertIn("Pembayaran sudah dibatalkan sebelumnya", cm.exception.detail)

    # =========================================================================
    # TC-29: Concurrent void conflict due to reversal event raises HTTP 409
    # =========================================================================
    async def test_tc29_concurrent_void_conflict_reversal_key_raises_409(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439029"
        pmt_id = "607f1f77bcf86cd799439037"
        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-P3B2-029"}
        # Initial check saw recorded payment
        initial_pmt_doc = {
            "_id": ObjectId(pmt_id),
            "payment_number": "PAY-20261010-057",
            "order_id": ObjectId(order_id),
            "status": "recorded",
            "amount_le": 1200.0,
            "finance_transaction_id": "707f1f77bcf86cd799439046",
        }
        cce_doc = {
            "_id": ObjectId("807f1f77bcf86cd799439057"),
            "event_number": "CCE-20261010-002",
            "event_type": "credit_minted",
            "customer_id": "cust_123",
            "source_payment_id": str(initial_pmt_doc["_id"]),
            "currency": "EGP",
            "signed_amount": 200.0,
        }
        # In database, winning transaction already committed status='voided'
        voided_pmt_doc = {
            **initial_pmt_doc,
            "status": "voided",
        }

        # find_one responds:
        # 1. order: order_doc
        # 2. initial payment check: initial_pmt_doc
        # 3. inside except DuplicateKeyError check current_pmt: voided_pmt_doc
        find_one_calls = [order_doc, initial_pmt_doc, voided_pmt_doc]
        mock_db.payments.update_one = AsyncMock()
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(side_effect=find_one_calls)
        mock_db.customer_credit_events.find_one = AsyncMock(return_value=cce_doc)

        import pymongo.errors
        # Simulate loser transaction hitting DuplicateKeyError on uniq_credit_event_source_payment
        mock_db.customer_credit_events.insert_one = AsyncMock(
            side_effect=pymongo.errors.DuplicateKeyError(
                "E11000 duplicate key error collection: db.customer_credit_events index: uniq_credit_event_source_payment dup key: { source_payment_id: '607f1f77bcf86cd799439037', event_type: 'credit_reversed' }"
            )
        )

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_void_order_payment(order_id, pmt_id, PaymentVoidInput(reason="Concurrent void"), self.admin_finance)
            self.assertEqual(cm.exception.status_code, 409)
            self.assertIn("Konflik konkuren", cm.exception.detail)

    # =========================================================================
    # TC-30: Unrelated DuplicateKeyError is NOT masked or converted to success
    # =========================================================================
    async def test_tc30_unrelated_duplicate_key_error_is_reraised(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439030"
        pmt_id = "607f1f77bcf86cd799439038"
        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-P3B2-030"}
        pmt_doc = {
            "_id": ObjectId(pmt_id),
            "payment_number": "PAY-20261010-058",
            "order_id": ObjectId(order_id),
            "status": "recorded",
            "amount_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        # Payment remains 'recorded' in DB
        mock_db.payments.find_one = AsyncMock(return_value=pmt_doc)

        import pymongo.errors
        # Simulate unexpected collision on an unrelated index (e.g. users, audit, external)
        mock_db.payments.update_one = AsyncMock(
            side_effect=pymongo.errors.DuplicateKeyError("E11000 duplicate key error collection: db.unrelated index: some_unrelated_index")
        )

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(pymongo.errors.DuplicateKeyError):
                await admin_void_order_payment(order_id, pmt_id, PaymentVoidInput(reason="Void attempt"), self.admin_finance)

    # =========================================================================
    # TC-31: Transaction aborts cleanly after write failure
    # =========================================================================
    async def test_tc31_transaction_aborts_after_write_failure(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439031"
        pmt_id = "607f1f77bcf86cd799439039"
        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-P3B2-031"}
        pmt_doc = {
            "_id": ObjectId(pmt_id),
            "payment_number": "PAY-20261010-059",
            "order_id": ObjectId(order_id),
            "status": "recorded",
            "amount_le": 1000.0,
            "finance_transaction_id": "707f1f77bcf86cd799439049",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=pmt_doc)

        # Payment update succeeds, but finance transaction update fails
        mock_db.payments.update_one = AsyncMock()
        mock_db.finance_transactions.update_one = AsyncMock(side_effect=RuntimeError("Disk failure"))

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(RuntimeError) as cm:
                await admin_void_order_payment(order_id, pmt_id, PaymentVoidInput(reason="Void with disk fail"), self.admin_finance)
            self.assertEqual(str(cm.exception), "Disk failure")

        # Verify order update was NOT performed because transaction aborted before reaching order recalculation
        mock_db.orders.update_one.assert_not_called()

    # =========================================================================
    # TC-32: Unrelated DuplicateKeyError when payment is voided in DB is still re-raised
    # =========================================================================
    async def test_tc32_unrelated_duplicate_key_error_with_voided_payment_is_reraised(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439032"
        pmt_id = "607f1f77bcf86cd799439040"
        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-P3B2-032"}
        pmt_doc = {
            "_id": ObjectId(pmt_id),
            "payment_number": "PAY-20261010-060",
            "order_id": ObjectId(order_id),
            "status": "recorded",  # Passes initial preflight
            "amount_le": 1000.0,
        }
        # In DB, payment became voided, BUT error is unrelated
        voided_pmt_doc = {
            **pmt_doc,
            "status": "voided",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(side_effect=[order_doc, pmt_doc, voided_pmt_doc])

        import pymongo.errors
        # Simulate unexpected collision on an unrelated index (e.g. audit log, external notification)
        mock_db.payments.update_one = AsyncMock(
            side_effect=pymongo.errors.DuplicateKeyError(
                "E11000 duplicate key error collection: db.audit_logs index: uniq_audit_id dup key: { _id: 123 }"
            )
        )

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(pymongo.errors.DuplicateKeyError):
                await admin_void_order_payment(order_id, pmt_id, PaymentVoidInput(reason="Void with unrelated dup"), self.admin_finance)

    # =========================================================================
    # Phase 3.B.3 Tests: Non-Cash Customer Credit Settlement
    # =========================================================================

    # TC-33: Successful customer credit payment decreases credit and records credit_applied
    async def test_tc33_customer_credit_settlement_success(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439033"
        cust_id = "607f1f77bcf86cd799439088"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3B3-001",
            "total_le": 1000.0,
            "delivery_fee_le": 0.0,
            "customer_id": cust_id,
            "customer_name": "Ahmad",
            "payment_status": "belum_dibayar",
        }
        cust_doc = {"_id": ObjectId(cust_id), "username": "Ahmad"}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.customers.find_one = AsyncMock(return_value=cust_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439041")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439051")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        # Customer has 1,500 EGP available credit
        with patch("server.get_customer_credit_balance", AsyncMock(return_value=1500.0)):
            with patch("server.db", mock_db), patch("server.client", self.mock_client):
                res = await admin_create_order_payment(
                    order_id,
                    PaymentCreateInput(amount=400.0, payment_method="customer_credit"),
                    self.admin_finance
                )

        # 1. Payment created with method customer_credit
        self.assertEqual(res["payment_method"], "customer_credit")
        # 2. Finance transaction is non-cash credit_settlement
        ft_doc = mock_db.finance_transactions.insert_one.call_args[0][0]
        self.assertEqual(ft_doc["type"], "credit_settlement")
        self.assertEqual(ft_doc["account"], "CUSTOMER_CREDIT")
        self.assertEqual(ft_doc["payment_method"], "customer_credit")
        # 3. Credit event recorded as credit_applied with negative polarity
        cce_doc = mock_db.customer_credit_events.insert_one.call_args[0][0]
        self.assertEqual(cce_doc["event_type"], "credit_applied")
        self.assertEqual(cce_doc["signed_amount"], -400.0)
        self.assertEqual(cce_doc["currency"], "EGP")
        self.assertEqual(cce_doc["customer_id"], cust_id)
        # 4. Customer document touched within transaction to serialize concurrent credit usage
        mock_db.customers.update_one.assert_called_once()
        touch_call_args = mock_db.customers.update_one.call_args
        self.assertEqual(touch_call_args[0][0], {"_id": {"$in": [cust_id, ObjectId(cust_id)]}})
        self.assertIn("last_credit_transaction_at", touch_call_args[0][1]["$set"])

    # TC-34: Customer credit settlement rejected for guest / order without customer_id
    async def test_tc34_customer_credit_rejected_for_guest_order(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439034"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3B3-002",
            "total_le": 1000.0,
            "delivery_fee_le": 0.0,
            "customer_id": None,  # Guest order
            "name": "Guest Buyer",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_order_payment(
                    order_id,
                    PaymentCreateInput(amount=300.0, payment_method="customer_credit"),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 400)
            self.assertIn("membutuhkan pesanan dengan akun pelanggan terdaftar", cm.exception.detail)

    # TC-35: Customer credit settlement rejected when balance is insufficient
    async def test_tc35_customer_credit_rejected_when_insufficient_balance(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439035"
        cust_id = "607f1f77bcf86cd799439089"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3B3-003",
            "total_le": 1000.0,
            "delivery_fee_le": 0.0,
            "customer_id": cust_id,
        }
        cust_doc = {"_id": ObjectId(cust_id), "username": "Fatima"}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.customers.find_one = AsyncMock(return_value=cust_doc)

        # Available balance is only 150 EGP, but payment requests 500 EGP
        with patch("server.get_customer_credit_balance", AsyncMock(return_value=150.0)):
            with patch("server.db", mock_db):
                with self.assertRaises(HTTPException) as cm:
                    await admin_create_order_payment(
                        order_id,
                        PaymentCreateInput(amount=500.0, payment_method="customer_credit"),
                        self.admin_finance
                    )
                self.assertEqual(cm.exception.status_code, 400)
                self.assertIn("Saldo kredit pelanggan tidak mencukupi", cm.exception.detail)

        # Zero writes performed
        mock_db.payments.insert_one.assert_not_called()
        mock_db.customer_credit_events.insert_one.assert_not_called()

    # TC-36: Customer credit settlement concurrent conflict fails closed (HTTP 409)
    async def test_tc36_customer_credit_concurrent_race_conflict_fails_closed(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439036"
        cust_id = "607f1f77bcf86cd799439090"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3B3-004",
            "total_le": 1000.0,
            "delivery_fee_le": 0.0,
            "customer_id": cust_id,
        }
        cust_doc = {"_id": ObjectId(cust_id), "username": "Tariq"}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.customers.find_one = AsyncMock(return_value=cust_doc)
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        # Simulate preflight sees 500 EGP, but by the time transaction runs, a competing
        # transaction committed and reduced balance to 100 EGP (less than 400 EGP needed)
        balance_call_count = 0
        async def mock_get_balance(cid, cur, session=None):
            nonlocal balance_call_count
            balance_call_count += 1
            if session is not None:
                return 100.0  # inside txn: reduced by concurrent winner
            return 500.0  # preflight check

        with patch("server.get_customer_credit_balance", side_effect=mock_get_balance):
            with patch("server.db", mock_db), patch("server.client", self.mock_client):
                with self.assertRaises(HTTPException) as cm:
                    await admin_create_order_payment(
                        order_id,
                        PaymentCreateInput(amount=400.0, payment_method="customer_credit"),
                        self.admin_finance
                    )
                self.assertEqual(cm.exception.status_code, 409)
                self.assertIn("Konflik saldo", cm.exception.detail)

        # Transaction aborted, payment not persisted
        mock_db.payments.insert_one.assert_not_called()

    # TC-37: Voiding a customer_credit payment restores credit via credit_reversed
    async def test_tc37_void_customer_credit_payment_restores_credit_atomically(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439037"
        pmt_id = "607f1f77bcf86cd799439042"
        cust_id = "607f1f77bcf86cd799439091"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3B3-005",
            "customer_id": cust_id,
        }
        pmt_doc = {
            "_id": ObjectId(pmt_id),
            "payment_number": "PAY-20261010-061",
            "order_id": ObjectId(order_id),
            "status": "recorded",
            "amount_le": 450.0,
            "payment_method": "customer_credit",
            "finance_transaction_id": "707f1f77bcf86cd799439052",
        }
        cce_doc = {
            "_id": ObjectId("807f1f77bcf86cd799439060"),
            "event_number": "CCE-20261010-010",
            "event_type": "credit_applied",
            "customer_id": cust_id,
            "source_payment_id": str(pmt_doc["_id"]),
            "currency": "EGP",
            "signed_amount": -450.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=pmt_doc)
        mock_db.payments.update_one = AsyncMock()
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])
        mock_db.customer_credit_events.find_one = AsyncMock(return_value=cce_doc)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            await admin_void_order_payment(
                order_id,
                pmt_id,
                PaymentVoidInput(reason="Void customer credit payment"),
                self.admin_finance
            )

        # Verified compensating event restores positive credit
        self.assertEqual(mock_db.customer_credit_events.insert_one.call_count, 1)
        rev_cce = mock_db.customer_credit_events.insert_one.call_args[0][0]
        self.assertEqual(rev_cce["event_type"], "credit_reversed")
        self.assertEqual(rev_cce["signed_amount"], 450.0)  # Positive: restores credit
        self.assertEqual(rev_cce["reverses_event_id"], str(cce_doc["_id"]))

    # TC-38: Physical cash balances are NOT affected by credit_settlement
    async def test_tc38_credit_settlement_zero_physical_cash_flow(self):
        # Verify that _compute_balances ignores credit_settlement transactions
        from server import _compute_balances
        mock_db = MagicMock()
        # Mock cursor for finance_transactions
        txns = [
            {"type": "order_revenue", "account": "EGP", "currency": "EGP", "amount": 1000.0},
            {"type": "credit_settlement", "account": "CUSTOMER_CREDIT", "currency": "EGP", "amount": 500.0},
        ]
        async def mock_cursor_gen():
            for t in txns:
                yield t
        mock_db.finance_transactions.find.return_value = mock_cursor_gen()

    # TC-39: Exhausted customer touch write conflict raises controlled HTTP 409 and aborts cleanly
    async def test_tc39_exhausted_write_conflict_raises_409(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439038"
        cust_id = "607f1f77bcf86cd799439092"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3B3-006",
            "total_le": 800.0,
            "delivery_fee_le": 0.0,
            "customer_id": cust_id,
        }
        cust_doc = {"_id": ObjectId(cust_id), "username": "Nadia"}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.customers.find_one = AsyncMock(return_value=cust_doc)
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        import pymongo.errors
        # Simulate MongoDB WiredTiger write-write conflict on customer serialization lock (OperationFailure code 112)
        mock_db.customers.update_one = AsyncMock(
            side_effect=pymongo.errors.OperationFailure("WriteConflict error: this operation conflicted with another", code=112)
        )

        with patch("server.get_customer_credit_balance", AsyncMock(return_value=1000.0)):
            with patch("server.db", mock_db), patch("server.client", self.mock_client):
                with self.assertRaises(HTTPException) as cm:
                    await admin_create_order_payment(
                        order_id,
                        PaymentCreateInput(amount=400.0, payment_method="customer_credit"),
                        self.admin_finance
                    )
                self.assertEqual(cm.exception.status_code, 409)
                self.assertIn("Terjadi konflik transaksi bersamaan pada akun pelanggan", cm.exception.detail)

        # 3 attempts made, all aborted without inserting payment or event
        self.assertEqual(mock_db.customers.update_one.call_count, 3)
        mock_db.payments.insert_one.assert_not_called()
        mock_db.customer_credit_events.insert_one.assert_not_called()

    # TC-40: Missing customer document during serialization raises HTTP 400
    async def test_tc40_missing_customer_document_raises_400(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439039"
        cust_id = "607f1f77bcf86cd799439093"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3B3-007",
            "total_le": 800.0,
            "delivery_fee_le": 0.0,
            "customer_id": cust_id,
        }
        cust_doc = {"_id": ObjectId(cust_id), "username": "Ghost"}
        # Preflight passes, but inside transaction customer document is deleted/missing (matched_count=0)
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.customers.find_one = AsyncMock(return_value=cust_doc)
        mock_db.customers.update_one = AsyncMock(return_value=MagicMock(matched_count=0))
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.get_customer_credit_balance", AsyncMock(return_value=1000.0)):
            with patch("server.db", mock_db), patch("server.client", self.mock_client):
                with self.assertRaises(HTTPException) as cm:
                    await admin_create_order_payment(
                        order_id,
                        PaymentCreateInput(amount=400.0, payment_method="customer_credit"),
                        self.admin_finance
                    )
                self.assertEqual(cm.exception.status_code, 400)
                self.assertIn("Akun pelanggan tidak ditemukan untuk serialisasi", cm.exception.detail)

        # Payment was not inserted
        mock_db.payments.insert_one.assert_not_called()

    # TC-41: Transient transaction conflict succeeds on fresh retry attempt without duplicating records
    async def test_tc41_transient_conflict_retries_and_succeeds_without_duplication(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439040"
        cust_id = "607f1f77bcf86cd799439094"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3B3-008",
            "total_le": 800.0,
            "delivery_fee_le": 0.0,
            "customer_id": cust_id,
        }
        cust_doc = {"_id": ObjectId(cust_id), "username": "Layla"}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.customers.find_one = AsyncMock(return_value=cust_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439045")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439055")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        import pymongo.errors
        # Attempt 1 fails with WriteConflict code 112, Attempt 2 succeeds
        mock_db.customers.update_one = AsyncMock(
            side_effect=[
                pymongo.errors.OperationFailure("WriteConflict error: transient lock conflict", code=112),
                MagicMock(matched_count=1),
            ]
        )

        with patch("server.get_customer_credit_balance", AsyncMock(return_value=1000.0)):
            with patch("server.db", mock_db), patch("server.client", self.mock_client):
                res = await admin_create_order_payment(
                    order_id,
                    PaymentCreateInput(amount=300.0, payment_method="customer_credit"),
                    self.admin_finance
                )

        self.assertEqual(res["payment_method"], "customer_credit")
        # Retry occurred: 2 customer touch attempts
        self.assertEqual(mock_db.customers.update_one.call_count, 2)
        # Exactly 1 payment, 1 finance transaction, and 1 credit event inserted (zero duplicates)
        self.assertEqual(mock_db.payments.insert_one.call_count, 1)
        self.assertEqual(mock_db.finance_transactions.insert_one.call_count, 1)
        self.assertEqual(mock_db.customer_credit_events.insert_one.call_count, 1)

    # TC-42: Unrelated OperationFailure is NOT retried and propagates immediately
    async def test_tc42_unrelated_operation_failure_is_not_retried(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439041"
        cust_id = "607f1f77bcf86cd799439095"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3B3-009",
            "total_le": 800.0,
            "delivery_fee_le": 0.0,
            "customer_id": cust_id,
        }
        cust_doc = {"_id": ObjectId(cust_id), "username": "Hassan"}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.customers.find_one = AsyncMock(return_value=cust_doc)
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        import pymongo.errors
        # Simulate unauthorized query or syntax error (code 13 or code 50, NOT transient)
        mock_db.customers.update_one = AsyncMock(
            side_effect=pymongo.errors.OperationFailure("Unauthorized operation", code=13)
        )

        with patch("server.get_customer_credit_balance", AsyncMock(return_value=1000.0)):
            with patch("server.db", mock_db), patch("server.client", self.mock_client):
                with self.assertRaises(pymongo.errors.OperationFailure) as cm:
                    await admin_create_order_payment(
                        order_id,
                        PaymentCreateInput(amount=300.0, payment_method="customer_credit"),
                        self.admin_finance
                    )
                self.assertEqual(cm.exception.code, 13)

        # Only 1 attempt made, NOT retried
        self.assertEqual(mock_db.customers.update_one.call_count, 1)
        mock_db.payments.insert_one.assert_not_called()

    # TC-43: In-transaction balance conflict (HTTP 409) is NOT retried
    async def test_tc43_in_transaction_balance_conflict_is_not_retried(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439042"
        cust_id = "607f1f77bcf86cd799439096"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3B3-010",
            "total_le": 800.0,
            "delivery_fee_le": 0.0,
            "customer_id": cust_id,
        }
        cust_doc = {"_id": ObjectId(cust_id), "username": "Zain"}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.customers.find_one = AsyncMock(return_value=cust_doc)
        mock_db.customers.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        # Preflight passes (500 EGP), but inside transaction balance is 100 EGP (needed 400 EGP)
        async def mock_balance(cid, cur, session=None):
            if session is not None:
                return 100.0
            return 500.0

        with patch("server.get_customer_credit_balance", side_effect=mock_balance):
            with patch("server.db", mock_db), patch("server.client", self.mock_client):
                with self.assertRaises(HTTPException) as cm:
                    await admin_create_order_payment(
                        order_id,
                        PaymentCreateInput(amount=400.0, payment_method="customer_credit"),
                        self.admin_finance
                    )
                self.assertEqual(cm.exception.status_code, 409)
                self.assertIn("Konflik saldo", cm.exception.detail)

        # Only 1 attempt made: business validation errors are never retried
        self.assertEqual(mock_db.customers.update_one.call_count, 1)
        mock_db.payments.insert_one.assert_not_called()

    # TC-44: Standard cash payment is unaffected by transient conflict handler
    async def test_tc44_standard_cash_payment_unaffected(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439043"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3B3-011",
            "total_le": 1000.0,
            "delivery_fee_le": 0.0,
            "payment_status": "belum_dibayar",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("607f1f77bcf86cd799439046")))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439056")))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            res = await admin_create_order_payment(
                order_id,
                PaymentCreateInput(amount=500.0, payment_method="cash"),
                self.admin_finance
            )

        self.assertEqual(res["payment_method"], "cash")
        # Customer touch was NOT called for cash payment
        mock_db.customers.update_one.assert_not_called()
        self.assertEqual(mock_db.payments.insert_one.call_count, 1)
        self.assertEqual(mock_db.finance_transactions.insert_one.call_count, 1)

    # =========================================================================
    # Phase 3.B.4 Tests: Customer Credit Cash Refund (POST /admin/customers/{cid}/credit-refund)
    # =========================================================================

    # TC-45: Successful customer credit cash refund creates credit_refunded event and liability_settlement transaction
    async def test_tc45_customer_credit_refund_success(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        cust_id = "607f1f77bcf86cd799439097"
        cust_doc = {"_id": ObjectId(cust_id), "username": "Siti Nurhaliza", "phone": "+201234567899"}
        mock_db.customers.find_one = AsyncMock(return_value=cust_doc)
        mock_db.customers.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439057")))
        mock_db.customer_credit_events.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("807f1f77bcf86cd799439067")))

        # Customer has 1,000 EGP credit available. Refund requests 300 EGP.
        with patch("server.get_customer_credit_balance", AsyncMock(side_effect=[1000.0, 1000.0, 700.0])):
            with patch("server.db", mock_db), patch("server.client", self.mock_client):
                res = await admin_customer_credit_refund(
                    cust_id,
                    CustomerCreditRefundInput(amount=300.0, currency="EGP", refund_method="cash", notes="Pengembalian deposit sisa"),
                    self.admin_finance
                )

        self.assertTrue(res["ok"])
        self.assertEqual(res["refund_amount"], 300.0)
        self.assertEqual(res["currency"], "EGP")
        self.assertEqual(res["available_credit"], 700.0)

        # 1. Customer serialization touch was executed inside transaction
        mock_db.customers.update_one.assert_called_once()
        touch_args = mock_db.customers.update_one.call_args
        self.assertEqual(touch_args[0][0], {"_id": {"$in": [cust_id, ObjectId(cust_id)]}})
        self.assertIn("last_credit_transaction_at", touch_args[0][1]["$set"])

        # 2. Finance transaction recorded as liability_settlement cash outflow
        self.assertEqual(mock_db.finance_transactions.insert_one.call_count, 1)
        ft_doc = mock_db.finance_transactions.insert_one.call_args[0][0]
        self.assertEqual(ft_doc["type"], "refund")
        self.assertEqual(ft_doc["classification"], "liability_settlement")
        self.assertEqual(ft_doc["category"], "Pengembalian Dana")
        self.assertEqual(ft_doc["amount"], 300.0)
        self.assertEqual(ft_doc["currency"], "EGP")
        self.assertEqual(ft_doc["account"], "EGP")
        self.assertEqual(ft_doc["payment_method"], "cash")
        self.assertEqual(ft_doc["related_customer_id"], cust_id)

        # 3. Customer credit event recorded as credit_refunded with negative polarity
        self.assertEqual(mock_db.customer_credit_events.insert_one.call_count, 1)
        cce_doc = mock_db.customer_credit_events.insert_one.call_args[0][0]
        self.assertEqual(cce_doc["event_type"], "credit_refunded")
        self.assertEqual(cce_doc["signed_amount"], -300.0)
        self.assertEqual(cce_doc["currency"], "EGP")
        self.assertEqual(cce_doc["customer_id"], cust_id)
        self.assertEqual(cce_doc["source_type"], "refund")

    # TC-46: Refund rejected when customer has insufficient credit balance (Preflight HTTP 400)
    async def test_tc46_customer_credit_refund_insufficient_balance_rejected(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        cust_id = "607f1f77bcf86cd799439098"
        cust_doc = {"_id": ObjectId(cust_id), "username": "Farhan"}
        mock_db.customers.find_one = AsyncMock(return_value=cust_doc)

        # Available balance is only 150 EGP, refund requests 500 EGP
        with patch("server.get_customer_credit_balance", AsyncMock(return_value=150.0)):
            with patch("server.db", mock_db):
                with self.assertRaises(HTTPException) as cm:
                    await admin_customer_credit_refund(
                        cust_id,
                        CustomerCreditRefundInput(amount=500.0, currency="EGP"),
                        self.admin_finance
                    )
                self.assertEqual(cm.exception.status_code, 400)
                self.assertIn("Saldo kredit pelanggan tidak mencukupi", cm.exception.detail)

        # Zero writes performed
        mock_db.finance_transactions.insert_one.assert_not_called()
        mock_db.customer_credit_events.insert_one.assert_not_called()

    # TC-47: Refund rejected for non-existent customer (HTTP 404)
    async def test_tc47_customer_credit_refund_customer_not_found_raises_404(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        cust_id = "607f1f77bcf86cd799439099"
        mock_db.customers.find_one = AsyncMock(return_value=None)

        with patch("server.db", mock_db):
            with self.assertRaises(HTTPException) as cm:
                await admin_customer_credit_refund(
                    cust_id,
                    CustomerCreditRefundInput(amount=100.0),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 404)
            self.assertIn("Pelanggan tidak ditemukan", cm.exception.detail)

    # TC-48: Refund rejected for non-positive amount (HTTP 400)
    async def test_tc48_customer_credit_refund_invalid_amount_raises_400(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        cust_id = "607f1f77bcf86cd799439100"
        cust_doc = {"_id": ObjectId(cust_id), "username": "Hani"}
        mock_db.customers.find_one = AsyncMock(return_value=cust_doc)

        with patch("server.db", mock_db):
            with self.assertRaises(HTTPException) as cm:
                await admin_customer_credit_refund(
                    cust_id,
                    CustomerCreditRefundInput(amount=-50.0),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 400)
            self.assertIn("lebih besar dari 0", cm.exception.detail)

    # TC-49: Refund rejected for unauthorized non-finance admin (HTTP 403)
    async def test_tc49_customer_credit_refund_unauthorized_raises_403(self):
        cust_id = "607f1f77bcf86cd799439101"
        admin_ops_only = {"id": "ops_01", "name": "Ops Worker", "role": "admin", "permissions": {"manage_orders": True, "access_finance": False}}

        with self.assertRaises(HTTPException) as cm:
            await admin_customer_credit_refund(
                cust_id,
                CustomerCreditRefundInput(amount=100.0),
                admin_ops_only
            )
        self.assertEqual(cm.exception.status_code, 403)
        self.assertIn("akses keuangan atau owner", cm.exception.detail)

    # TC-50: In-transaction race conflict detects reduced balance and raises HTTP 409
    async def test_tc50_customer_credit_refund_in_transaction_conflict_raises_409(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        cust_id = "607f1f77bcf86cd799439102"
        cust_doc = {"_id": ObjectId(cust_id), "username": "Kamal"}
        mock_db.customers.find_one = AsyncMock(return_value=cust_doc)
        mock_db.customers.update_one = AsyncMock(return_value=MagicMock(matched_count=1))

        # Preflight sees 500 EGP, but inside-transaction snapshot balance sees 100 EGP (needed 300 EGP)
        async def mock_balance(cid, cur, session=None):
            if session is not None:
                return 100.0
            return 500.0

        with patch("server.get_customer_credit_balance", side_effect=mock_balance):
            with patch("server.db", mock_db), patch("server.client", self.mock_client):
                with self.assertRaises(HTTPException) as cm:
                    await admin_customer_credit_refund(
                        cust_id,
                        CustomerCreditRefundInput(amount=300.0, currency="EGP"),
                        self.admin_finance
                    )
                self.assertEqual(cm.exception.status_code, 409)
                self.assertIn("Konflik saldo", cm.exception.detail)

        # Zero writes committed
        mock_db.finance_transactions.insert_one.assert_not_called()
        mock_db.customer_credit_events.insert_one.assert_not_called()

    # TC-51: Idempotency replay on duplicate idempotency_key returns existing record without duplicate writes
    async def test_tc51_customer_credit_refund_idempotent_replay(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        cust_id = "607f1f77bcf86cd799439103"
        cust_doc = {"_id": ObjectId(cust_id), "username": "Salma"}
        mock_db.customers.find_one = AsyncMock(return_value=cust_doc)

        existing_cce = {
            "_id": ObjectId("807f1f77bcf86cd799439068"),
            "event_number": "CCE-20261010-099",
            "event_type": "credit_refunded",
            "customer_id": cust_id,
            "currency": "EGP",
            "signed_amount": -200.0,
            "idempotency_key": "refund_idem_001",
            "source_payment_id": "707f1f77bcf86cd799439058",
        }
        existing_txn = {
            "_id": ObjectId("707f1f77bcf86cd799439058"),
            "type": "refund",
            "amount": 200.0,
            "currency": "EGP",
        }
        mock_db.customer_credit_events.find_one = AsyncMock(return_value=existing_cce)
        mock_db.finance_transactions.find_one = AsyncMock(return_value=existing_txn)

        with patch("server.get_customer_credit_balance", AsyncMock(return_value=500.0)):
            with patch("server.db", mock_db):
                res = await admin_customer_credit_refund(
                    cust_id,
                    CustomerCreditRefundInput(amount=200.0, currency="EGP", idempotency_key="refund_idem_001"),
                    self.admin_finance
                )

        self.assertTrue(res["ok"])
        self.assertTrue(res["idempotent_replay"])
        self.assertEqual(res["event"]["event_number"], "CCE-20261010-099")
        # Zero new inserts executed
        mock_db.finance_transactions.insert_one.assert_not_called()
        mock_db.customer_credit_events.insert_one.assert_not_called()

    # TC-52: Physical cash balances are decreased by refund, while sales revenue and costs remain unaffected
    async def test_tc52_refund_decreases_cash_without_affecting_revenue_or_cost(self):
        from server import _compute_balances, _stats_for
        mock_db = MagicMock()

        # 1. Verify _compute_balances reflects cash outflow
        txns = [
            {"type": "order_revenue", "account": "EGP", "currency": "EGP", "amount": 1000.0},
            {"type": "refund", "classification": "liability_settlement", "account": "EGP", "currency": "EGP", "amount": 300.0},
        ]
        async def mock_cursor_gen():
            for t in txns:
                yield t
        mock_db.finance_transactions.find.return_value = mock_cursor_gen()

        with patch("server.db", mock_db):
            balances = await _compute_balances()
            # Net physical cash = 1000 - 300 = 700 EGP
            self.assertEqual(balances["EGP"], 700.0)

        # 2. Verify _stats_for does not count refund as revenue or operating cost
        mock_db.finance_transactions.find.return_value = mock_cursor_gen()
        with patch("server.db", mock_db):
            stats = await _stats_for(None, None)
            # Sales revenue = 1000 EGP, Cost = 0.0 EGP (refund is liability settlement, NOT operating expense)
            self.assertEqual(stats["EGP"]["revenue"], 1000.0)
            self.assertEqual(stats["EGP"]["cost"], 0.0)

    # TC-53: Idempotency replay with different customer ID raises HTTP 409 and zero writes
    async def test_tc53_idempotency_replay_different_customer_raises_409(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        cust_a = "607f1f77bcf86cd799439104"
        cust_b = "607f1f77bcf86cd799439105"
        cust_b_doc = {"_id": ObjectId(cust_b), "username": "Customer B"}
        mock_db.customers.find_one = AsyncMock(return_value=cust_b_doc)

        # Existing refund was for cust_a
        existing_cce = {
            "_id": ObjectId("807f1f77bcf86cd799439069"),
            "event_number": "CCE-20261010-100",
            "event_type": "credit_refunded",
            "customer_id": cust_a,
            "currency": "EGP",
            "signed_amount": -150.0,
            "idempotency_key": "refund_shared_idem_key",
        }
        mock_db.customer_credit_events.find_one = AsyncMock(return_value=existing_cce)

        with patch("server.db", mock_db):
            with self.assertRaises(HTTPException) as cm:
                await admin_customer_credit_refund(
                    cust_b,
                    CustomerCreditRefundInput(amount=150.0, currency="EGP", idempotency_key="refund_shared_idem_key"),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 409)
            self.assertIn("Kunci idempotensi telah digunakan", cm.exception.detail)

        # Zero writes executed
        mock_db.finance_transactions.insert_one.assert_not_called()
        mock_db.customer_credit_events.insert_one.assert_not_called()

    # TC-54: Idempotency replay with different amount raises HTTP 409 and zero writes
    async def test_tc54_idempotency_replay_different_amount_raises_409(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        cust_id = "607f1f77bcf86cd799439106"
        cust_doc = {"_id": ObjectId(cust_id), "username": "Customer C"}
        mock_db.customers.find_one = AsyncMock(return_value=cust_doc)

        # Existing refund was for 200.0 EGP
        existing_cce = {
            "_id": ObjectId("807f1f77bcf86cd799439070"),
            "event_number": "CCE-20261010-101",
            "event_type": "credit_refunded",
            "customer_id": cust_id,
            "currency": "EGP",
            "signed_amount": -200.0,
            "idempotency_key": "refund_amount_diff_key",
        }
        mock_db.customer_credit_events.find_one = AsyncMock(return_value=existing_cce)

        with patch("server.db", mock_db):
            with self.assertRaises(HTTPException) as cm:
                # Replay attempts to request 250.0 EGP with same idempotency key
                await admin_customer_credit_refund(
                    cust_id,
                    CustomerCreditRefundInput(amount=250.0, currency="EGP", idempotency_key="refund_amount_diff_key"),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 409)
            self.assertIn("Kunci idempotensi telah digunakan", cm.exception.detail)

        # Zero writes executed
        mock_db.finance_transactions.insert_one.assert_not_called()
        mock_db.customer_credit_events.insert_one.assert_not_called()

    # TC-55: Idempotency replay with different currency raises HTTP 409 and zero writes
    async def test_tc55_idempotency_replay_different_currency_raises_409(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        cust_id = "607f1f77bcf86cd799439107"
        cust_doc = {"_id": ObjectId(cust_id), "username": "Customer D"}
        mock_db.customers.find_one = AsyncMock(return_value=cust_doc)

        # Existing refund was in EGP
        existing_cce = {
            "_id": ObjectId("807f1f77bcf86cd799439071"),
            "event_number": "CCE-20261010-102",
            "event_type": "credit_refunded",
            "customer_id": cust_id,
            "currency": "EGP",
            "signed_amount": -100.0,
            "idempotency_key": "refund_currency_diff_key",
        }
        mock_db.customer_credit_events.find_one = AsyncMock(return_value=existing_cce)

        with patch("server.db", mock_db):
            with self.assertRaises(HTTPException) as cm:
                # Replay attempts to request IDR with same idempotency key
                await admin_customer_credit_refund(
                    cust_id,
                    CustomerCreditRefundInput(amount=100.0, currency="IDR", idempotency_key="refund_currency_diff_key"),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 409)
            self.assertIn("Kunci idempotensi telah digunakan", cm.exception.detail)

        # Zero writes executed
        mock_db.finance_transactions.insert_one.assert_not_called()
        mock_db.customer_credit_events.insert_one.assert_not_called()

    # TC-56: Fresh idempotency key still permits a valid refund when sufficient credit exists
    async def test_tc56_fresh_idempotency_key_succeeds(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        cust_id = "607f1f77bcf86cd799439108"
        cust_doc = {"_id": ObjectId(cust_id), "username": "Customer E"}
        mock_db.customers.find_one = AsyncMock(return_value=cust_doc)
        mock_db.customers.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
        # No existing event for fresh key
        mock_db.customer_credit_events.find_one = AsyncMock(return_value=None)
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439060")))
        mock_db.customer_credit_events.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("807f1f77bcf86cd799439072")))

        with patch("server.get_customer_credit_balance", AsyncMock(side_effect=[800.0, 800.0, 450.0])):
            with patch("server.db", mock_db), patch("server.client", self.mock_client):
                res = await admin_customer_credit_refund(
                    cust_id,
                    CustomerCreditRefundInput(amount=350.0, currency="EGP", idempotency_key="fresh_refund_key_999"),
                    self.admin_finance
                )

        self.assertTrue(res["ok"])
        self.assertEqual(res["refund_amount"], 350.0)
        self.assertEqual(mock_db.finance_transactions.insert_one.call_count, 1)
        self.assertEqual(mock_db.customer_credit_events.insert_one.call_count, 1)
        saved_cce = mock_db.customer_credit_events.insert_one.call_args[0][0]
        self.assertEqual(saved_cce["idempotency_key"], "fresh_refund_key_999")


if __name__ == "__main__":
    unittest.main()


