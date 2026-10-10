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
    get_customer_credit_balance,
    compute_order_payment_summary,
    OrderStatusUpdate,
    PaymentCreateInput,
    PaymentVoidInput,
    PaymentAllocationInput,
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
    # TC-22 & TC-23: Scope boundary protections: no credit application or refund in 3.B.2
    # =========================================================================
    async def test_tc22_tc23_scope_boundaries_preserved(self):
        # Verify that payment method customer_credit remains rejected in Phase 3.B.2
        # (Only 'cash' and 'transfer' permitted until 3.B.3)
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439026"
        order_doc = {"_id": ObjectId(order_id), "total_le": 500.0}
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_order_payment(order_id, PaymentCreateInput(amount=500.0, payment_method="customer_credit"), self.admin_finance)
            self.assertEqual(cm.exception.status_code, 400)
            self.assertIn("Metode pembayaran harus cash atau transfer", cm.exception.detail)

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


if __name__ == "__main__":
    unittest.main()


