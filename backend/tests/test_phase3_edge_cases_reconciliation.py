"""Phase 3.C Acceptance & Regression Test Suite — Edge Cases & Reconciliation

Tests findings C-01 and C-02 according to SOGIL_PHASE_3C1_EDGE_CASE_CORRECTION_SPECIFICATION.md:
C1-TC-01: Void overpayment when customer still holds full credit balance (200 OK).
C1-TC-02: Void overpayment when customer partially spent minted credit (409 Conflict).
C1-TC-03: Void overpayment when customer spent all minted credit on Order 2 (409 Conflict).
C1-TC-04: Void overpayment when customer withdrew minted credit via cash refund (409 Conflict).
C1-TC-05: Void overpayment with external credit top-up maintaining sufficient fungible balance (200 OK).
C1-TC-06: Void payment made via customer_credit restores balance (+X) without requiring credit balance check.
C1-TC-07: IDR overpayment derives currency from source event and isolates IDR balance.
C1-TC-08: Concurrency serialization lock prevents race past balance gate.
C1-TC-09: Transaction session aborts atomically when 409 Conflict is raised; zero writes committed.
C2-TC-10: finance_delete blocked on direct payment_id (409 Conflict with descriptive guidance).
C2-TC-11: finance_delete blocked on reverse payment lookup in db.payments (409 Conflict).
C2-TC-12: finance_delete blocked on credit settlement / credit refund transaction (409 Conflict).
C2-TC-13: finance_delete permitted for standalone operational expense (200 OK).
C2-TC-14: finance_delete permitted for legacy unlinked order_revenue (200 OK).
C2-TC-15: finance_delete on already-voided transaction returns 400 Bad Request.
C-ALL-16: Suite invariants and baseline stability verification.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from fastapi import HTTPException

from server import (
    admin_void_order_payment,
    finance_delete,
    PaymentVoidInput,
)


class TestPhase3CEdgeCasesReconciliation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.admin_finance = {
            "id": "admin_fin_01",
            "name": "Finance Admin",
            "role": "admin",
            "permissions": {"manage_orders": True, "access_finance": True},
        }

        self.mock_session = AsyncMock()
        self.mock_session.__aenter__.return_value = self.mock_session
        self.mock_session.__aexit__.return_value = None
        self.mock_session.start_transaction = MagicMock()
        self.mock_session.start_transaction.return_value.__aenter__ = AsyncMock(return_value=self.mock_session)
        self.mock_session.start_transaction.return_value.__aexit__ = AsyncMock(return_value=None)
        self.mock_session.abort_transaction = AsyncMock()
        self.mock_session.commit_transaction = AsyncMock()

        self.mock_client = MagicMock()
        self.mock_client.start_session = AsyncMock(return_value=self.mock_session)

    def _setup_mock_db(self, mock_db):
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357.0})
        mock_db.system_rates.find_one = AsyncMock(return_value={"rate": 357.0})
        mock_find_pts = MagicMock()
        mock_find_pts.to_list = AsyncMock(return_value=[])
        mock_db.point_transactions.find.return_value = mock_find_pts
        mock_db.point_transactions.delete_many = AsyncMock()
        mock_db.customers.find_one = AsyncMock(return_value={"_id": ObjectId("607f1f77bcf86cd799439001"), "name": "Customer Test"})
        mock_touch_res = MagicMock()
        mock_touch_res.matched_count = 1
        mock_db.customers.update_one = AsyncMock(return_value=mock_touch_res)
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 701})
        mock_db.customer_credit_events.insert_one = AsyncMock()
        mock_db.customer_credit_events.find_one = AsyncMock(return_value=None)
        mock_db.employee_wages.delete_many = AsyncMock()
        mock_find_cce = MagicMock()
        mock_find_cce.sort.return_value.to_list = AsyncMock(return_value=[])
        mock_db.customer_credit_events.find.return_value = mock_find_cce

    # =========================================================================
    # C1-TC-01: Void overpayment when customer still holds full credit balance
    # =========================================================================
    async def test_c1_tc01_void_overpayment_full_credit_balance(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439101"
        pmt_id = "607f1f77bcf86cd799439201"
        cust_id = "607f1f77bcf86cd799439001"

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3C-001",
            "customer_id": cust_id,
            "currency": "EGP",
            "total_le": 1000.0,
        }
        pmt_doc = {
            "_id": ObjectId(pmt_id),
            "payment_number": "PAY-20261012-001",
            "order_id": ObjectId(order_id),
            "status": "recorded",
            "amount_le": 1500.0,
            "currency": "EGP",
            "finance_transaction_id": "707f1f77bcf86cd799439301",
        }
        cce_doc = {
            "_id": ObjectId("807f1f77bcf86cd799439401"),
            "event_number": "CCE-20261012-001",
            "event_type": "credit_minted",
            "customer_id": cust_id,
            "source_payment_id": str(pmt_doc["_id"]),
            "currency": "EGP",
            "signed_amount": 500.0,
        }

        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        voided_pmt_doc = {**pmt_doc, "status": "voided"}
        mock_db.payments.find_one = AsyncMock(side_effect=[pmt_doc, voided_pmt_doc])
        mock_db.payments.update_one = AsyncMock()
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])
        mock_db.customer_credit_events.find_one = AsyncMock(return_value=cce_doc)

        # Full balance 500.0 available
        mock_agg = MagicMock()
        mock_agg.to_list = AsyncMock(return_value=[{"total": 500.0}])
        mock_db.customer_credit_events.aggregate = MagicMock(return_value=mock_agg)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            res = await admin_void_order_payment(order_id, pmt_id, PaymentVoidInput(reason="Void order"), self.admin_finance)
            self.assertEqual(res["status"], "voided")

        # Payment status set to voided
        mock_db.payments.update_one.assert_called()
        # Credit reversed event inserted with signed_amount -500.0
        mock_db.customer_credit_events.insert_one.assert_called_once()
        inserted_rev = mock_db.customer_credit_events.insert_one.call_args[0][0]
        self.assertEqual(inserted_rev["event_type"], "credit_reversed")
        self.assertEqual(inserted_rev["signed_amount"], -500.0)

    # =========================================================================
    # C1-TC-02: Void overpayment when customer partially spent minted credit (409)
    # =========================================================================
    async def test_c1_tc02_void_overpayment_spent_partial_credit(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439102"
        pmt_id = "607f1f77bcf86cd799439202"
        cust_id = "607f1f77bcf86cd799439001"

        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-P3C-002", "customer_id": cust_id, "currency": "EGP"}
        pmt_doc = {
            "_id": ObjectId(pmt_id),
            "payment_number": "PAY-20261012-002",
            "order_id": ObjectId(order_id),
            "status": "recorded",
            "amount_le": 2000.0,
            "currency": "EGP",
            "finance_transaction_id": "707f1f77bcf86cd799439302",
        }
        cce_doc = {
            "_id": ObjectId("807f1f77bcf86cd799439402"),
            "event_number": "CCE-20261012-002",
            "event_type": "credit_minted",
            "customer_id": cust_id,
            "source_payment_id": str(pmt_doc["_id"]),
            "currency": "EGP",
            "signed_amount": 1000.0,
        }

        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=pmt_doc)
        mock_db.customer_credit_events.find_one = AsyncMock(return_value=cce_doc)

        # Minted 1000.0, but only 600.0 left (400.0 was spent)
        mock_agg = MagicMock()
        mock_agg.to_list = AsyncMock(return_value=[{"total": 600.0}])
        mock_db.customer_credit_events.aggregate = MagicMock(return_value=mock_agg)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_void_order_payment(order_id, pmt_id, PaymentVoidInput(reason="Void"), self.admin_finance)
            self.assertEqual(cm.exception.status_code, 409)
            self.assertIn("Konflik saldo", cm.exception.detail)
            self.assertIn("1000.00 EGP", cm.exception.detail)
            self.assertIn("600.00 EGP", cm.exception.detail)

        # No writes committed
        mock_db.payments.update_one.assert_not_called()
        mock_db.customer_credit_events.insert_one.assert_not_called()

    # =========================================================================
    # C1-TC-03: Void overpayment when customer spent all minted credit on Order 2
    # =========================================================================
    async def test_c1_tc03_void_overpayment_spent_all_credit_order2(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439103"
        pmt_id = "607f1f77bcf86cd799439203"
        cust_id = "607f1f77bcf86cd799439001"

        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-P3C-003", "customer_id": cust_id, "currency": "EGP"}
        pmt_doc = {
            "_id": ObjectId(pmt_id),
            "payment_number": "PAY-20261012-003",
            "order_id": ObjectId(order_id),
            "status": "recorded",
            "amount_le": 1500.0,
            "currency": "EGP",
        }
        cce_doc = {
            "_id": ObjectId("807f1f77bcf86cd799439403"),
            "event_number": "CCE-20261012-003",
            "event_type": "credit_minted",
            "customer_id": cust_id,
            "source_payment_id": str(pmt_doc["_id"]),
            "currency": "EGP",
            "signed_amount": 500.0,
        }

        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=pmt_doc)
        mock_db.customer_credit_events.find_one = AsyncMock(return_value=cce_doc)

        # All credit spent on Order 2 -> balance is 0.0
        mock_agg = MagicMock()
        mock_agg.to_list = AsyncMock(return_value=[{"total": 0.0}])
        mock_db.customer_credit_events.aggregate = MagicMock(return_value=mock_agg)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_void_order_payment(order_id, pmt_id, PaymentVoidInput(reason="Void"), self.admin_finance)
            self.assertEqual(cm.exception.status_code, 409)
            self.assertIn("Konflik saldo", cm.exception.detail)
            self.assertIn("500.00 EGP", cm.exception.detail)
            self.assertIn("0.00 EGP", cm.exception.detail)

        mock_db.payments.update_one.assert_not_called()
        mock_db.customer_credit_events.insert_one.assert_not_called()

    # =========================================================================
    # C1-TC-04: Void overpayment when customer withdrew credit via cash refund
    # =========================================================================
    async def test_c1_tc04_void_overpayment_withdrawn_via_cash_refund(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439104"
        pmt_id = "607f1f77bcf86cd799439204"
        cust_id = "607f1f77bcf86cd799439001"

        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-P3C-004", "customer_id": cust_id, "currency": "EGP"}
        pmt_doc = {
            "_id": ObjectId(pmt_id),
            "payment_number": "PAY-20261012-004",
            "order_id": ObjectId(order_id),
            "status": "recorded",
            "amount_le": 1800.0,
            "currency": "EGP",
        }
        cce_doc = {
            "_id": ObjectId("807f1f77bcf86cd799439404"),
            "event_number": "CCE-20261012-004",
            "event_type": "credit_minted",
            "customer_id": cust_id,
            "source_payment_id": str(pmt_doc["_id"]),
            "currency": "EGP",
            "signed_amount": 800.0,
        }

        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=pmt_doc)
        mock_db.customer_credit_events.find_one = AsyncMock(return_value=cce_doc)

        # Entire 800 LE was refunded via cash -> balance 0.0
        mock_agg = MagicMock()
        mock_agg.to_list = AsyncMock(return_value=[{"total": 0.0}])
        mock_db.customer_credit_events.aggregate = MagicMock(return_value=mock_agg)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_void_order_payment(order_id, pmt_id, PaymentVoidInput(reason="Void"), self.admin_finance)
            self.assertEqual(cm.exception.status_code, 409)
            self.assertIn("Konflik saldo", cm.exception.detail)
            self.assertIn("800.00 EGP", cm.exception.detail)

        mock_db.payments.update_one.assert_not_called()

    # =========================================================================
    # C1-TC-05: Void overpayment with external credit top-up fungible balance
    # =========================================================================
    async def test_c1_tc05_void_overpayment_with_external_credit_topup(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439105"
        pmt_id = "607f1f77bcf86cd799439205"
        cust_id = "607f1f77bcf86cd799439001"

        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-P3C-005", "customer_id": cust_id, "currency": "EGP", "total_le": 1000.0}
        pmt_doc = {
            "_id": ObjectId(pmt_id),
            "payment_number": "PAY-20261012-005",
            "order_id": ObjectId(order_id),
            "status": "recorded",
            "amount_le": 1500.0,
            "currency": "EGP",
        }
        cce_doc = {
            "_id": ObjectId("807f1f77bcf86cd799439405"),
            "event_number": "CCE-20261012-005",
            "event_type": "credit_minted",
            "customer_id": cust_id,
            "source_payment_id": str(pmt_doc["_id"]),
            "currency": "EGP",
            "signed_amount": 500.0,
        }

        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        voided_pmt_doc = {**pmt_doc, "status": "voided"}
        mock_db.payments.find_one = AsyncMock(side_effect=[pmt_doc, voided_pmt_doc])
        mock_db.payments.update_one = AsyncMock()
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])
        mock_db.customer_credit_events.find_one = AsyncMock(return_value=cce_doc)

        # Customer spent 300 LE of the original, but gained 400 LE from another order -> total 600 LE >= 500 LE
        mock_agg = MagicMock()
        mock_agg.to_list = AsyncMock(return_value=[{"total": 600.0}])
        mock_db.customer_credit_events.aggregate = MagicMock(return_value=mock_agg)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            res = await admin_void_order_payment(order_id, pmt_id, PaymentVoidInput(reason="Void"), self.admin_finance)
            self.assertEqual(res["status"], "voided")

        mock_db.customer_credit_events.insert_one.assert_called_once()
        rev_doc = mock_db.customer_credit_events.insert_one.call_args[0][0]
        self.assertEqual(rev_doc["event_type"], "credit_reversed")
        self.assertEqual(rev_doc["signed_amount"], -500.0)

    # =========================================================================
    # C1-TC-06: Void payment made via customer_credit restores balance (+X)
    # =========================================================================
    async def test_c1_tc06_void_credit_applied_restores_balance(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439106"
        pmt_id = "607f1f77bcf86cd799439206"
        cust_id = "607f1f77bcf86cd799439001"

        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-P3C-006", "customer_id": cust_id, "currency": "EGP", "total_le": 500.0}
        pmt_doc = {
            "_id": ObjectId(pmt_id),
            "payment_number": "PAY-20261012-006",
            "order_id": ObjectId(order_id),
            "status": "recorded",
            "amount_le": 300.0,
            "currency": "EGP",
            "payment_method": "customer_credit",
        }
        cce_doc = {
            "_id": ObjectId("807f1f77bcf86cd799439406"),
            "event_number": "CCE-20261012-006",
            "event_type": "credit_applied",
            "customer_id": cust_id,
            "source_payment_id": str(pmt_doc["_id"]),
            "currency": "EGP",
            "signed_amount": -300.0,
        }

        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        voided_pmt_doc6 = {**pmt_doc, "status": "voided"}
        mock_db.payments.find_one = AsyncMock(side_effect=[pmt_doc, voided_pmt_doc6])
        mock_db.payments.update_one = AsyncMock()
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.orders.update_one = AsyncMock()
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=[])
        mock_db.customer_credit_events.find_one = AsyncMock(return_value=cce_doc)

        # Available balance does not need to be positive to restore credit
        mock_agg = MagicMock()
        mock_agg.to_list = AsyncMock(return_value=[{"total": 0.0}])
        mock_db.customer_credit_events.aggregate = MagicMock(return_value=mock_agg)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            res = await admin_void_order_payment(order_id, pmt_id, PaymentVoidInput(reason="Void"), self.admin_finance)
            self.assertEqual(res["status"], "voided")

        # Restoring credit inserts a credit_reversed with POSITIVE signed_amount (+300.0)
        mock_db.customer_credit_events.insert_one.assert_called_once()
        rev_doc = mock_db.customer_credit_events.insert_one.call_args[0][0]
        self.assertEqual(rev_doc["event_type"], "credit_reversed")
        self.assertEqual(rev_doc["signed_amount"], 300.0)

    # =========================================================================
    # C1-TC-07: Currency propagation: IDR overpayment isolates IDR balance
    # =========================================================================
    async def test_c1_tc07_currency_propagation_idr_overpayment(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439107"
        pmt_id = "607f1f77bcf86cd799439207"
        cust_id = "607f1f77bcf86cd799439001"

        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-P3C-007", "customer_id": cust_id, "currency": "IDR", "total_le": 100000.0}
        pmt_doc = {
            "_id": ObjectId(pmt_id),
            "payment_number": "PAY-20261012-007",
            "order_id": ObjectId(order_id),
            "status": "recorded",
            "amount_le": 150000.0,
            "currency": "IDR",
        }
        cce_doc = {
            "_id": ObjectId("807f1f77bcf86cd799439407"),
            "event_number": "CCE-20261012-007",
            "event_type": "credit_minted",
            "customer_id": cust_id,
            "source_payment_id": str(pmt_doc["_id"]),
            "currency": "IDR",
            "signed_amount": 50000.0,
        }

        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=pmt_doc)
        mock_db.customer_credit_events.find_one = AsyncMock(return_value=cce_doc)

        # IDR balance has only 10,000 IDR (insufficient for 50,000 IDR reversal)
        mock_agg = MagicMock()
        mock_agg.to_list = AsyncMock(return_value=[{"total": 10000.0}])
        mock_db.customer_credit_events.aggregate = MagicMock(return_value=mock_agg)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_void_order_payment(order_id, pmt_id, PaymentVoidInput(reason="Void"), self.admin_finance)
            self.assertEqual(cm.exception.status_code, 409)
            self.assertIn("50000.00 IDR", cm.exception.detail)
            self.assertIn("10000.00 IDR", cm.exception.detail)

    # =========================================================================
    # C1-TC-08: Concurrency serialization lock prevents race past balance gate
    # =========================================================================
    async def test_c1_tc08_concurrency_race_credit_spend_vs_void(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439108"
        pmt_id = "607f1f77bcf86cd799439208"
        cust_id = "607f1f77bcf86cd799439001"

        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-P3C-008", "customer_id": cust_id, "currency": "EGP"}
        pmt_doc = {
            "_id": ObjectId(pmt_id),
            "payment_number": "PAY-20261012-008",
            "order_id": ObjectId(order_id),
            "status": "recorded",
            "amount_le": 1200.0,
            "currency": "EGP",
        }
        cce_doc = {
            "_id": ObjectId("807f1f77bcf86cd799439408"),
            "event_number": "CCE-20261012-008",
            "event_type": "credit_minted",
            "customer_id": cust_id,
            "source_payment_id": str(pmt_doc["_id"]),
            "currency": "EGP",
            "signed_amount": 200.0,
        }

        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=pmt_doc)
        mock_db.customer_credit_events.find_one = AsyncMock(return_value=cce_doc)

        # Customer update_one (lock) fails with matched_count == 0 (simulating customer missing or lock contention failure)
        mock_touch_fail = MagicMock()
        mock_touch_fail.matched_count = 0
        mock_db.customers.update_one = AsyncMock(return_value=mock_touch_fail)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_void_order_payment(order_id, pmt_id, PaymentVoidInput(reason="Void"), self.admin_finance)
            self.assertEqual(cm.exception.status_code, 400)
            self.assertIn("serialisasi transaksi kredit", cm.exception.detail)

    # =========================================================================
    # C1-TC-09: Replica set transaction aborts on exception (zero writes)
    # =========================================================================
    async def test_c1_tc09_replica_set_abort_on_exception(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439109"
        pmt_id = "607f1f77bcf86cd799439209"
        cust_id = "607f1f77bcf86cd799439001"

        order_doc = {"_id": ObjectId(order_id), "order_number": "SGF-P3C-009", "customer_id": cust_id, "currency": "EGP"}
        pmt_doc = {
            "_id": ObjectId(pmt_id),
            "payment_number": "PAY-20261012-009",
            "order_id": ObjectId(order_id),
            "status": "recorded",
            "amount_le": 1500.0,
            "currency": "EGP",
        }
        cce_doc = {
            "_id": ObjectId("807f1f77bcf86cd799439409"),
            "event_number": "CCE-20261012-009",
            "event_type": "credit_minted",
            "customer_id": cust_id,
            "source_payment_id": str(pmt_doc["_id"]),
            "currency": "EGP",
            "signed_amount": 500.0,
        }

        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=pmt_doc)
        mock_db.customer_credit_events.find_one = AsyncMock(return_value=cce_doc)

        # Insufficient credit -> raises 409
        mock_agg = MagicMock()
        mock_agg.to_list = AsyncMock(return_value=[{"total": 100.0}])
        mock_db.customer_credit_events.aggregate = MagicMock(return_value=mock_agg)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_void_order_payment(order_id, pmt_id, PaymentVoidInput(reason="Void"), self.admin_finance)
            self.assertEqual(cm.exception.status_code, 409)

        # Verify no commit was made
        self.mock_session.commit_transaction.assert_not_called()

    # =========================================================================
    # C2-TC-10: finance_delete blocked on direct payment_id (409 Conflict)
    # =========================================================================
    async def test_c2_tc10_finance_delete_blocked_on_direct_payment_id(self):
        mock_db = MagicMock()
        txn_id = "707f1f77bcf86cd799439310"
        pmt_id = "607f1f77bcf86cd799439210"
        order_id = "507f1f77bcf86cd799439110"

        txn_doc = {
            "_id": ObjectId(txn_id),
            "type": "order_revenue",
            "payment_id": pmt_id,
            "related_order_id": order_id,
            "amount": 1000.0,
            "currency": "EGP",
        }
        mock_db.finance_transactions.find_one = AsyncMock(return_value=txn_doc)
        mock_db.payments.find_one = AsyncMock(return_value={"_id": ObjectId(pmt_id), "status": "recorded", "order_id": order_id})

        with patch("server.db", mock_db):
            with self.assertRaises(HTTPException) as cm:
                await finance_delete(txn_id, self.admin_finance)
            self.assertEqual(cm.exception.status_code, 409)
            self.assertIn("terhubung langsung dengan pembayaran pesanan resmi", cm.exception.detail)
            self.assertIn(f"Order ID: {order_id}", cm.exception.detail)

    # =========================================================================
    # C2-TC-11: finance_delete blocked on reverse payment lookup in db.payments
    # =========================================================================
    async def test_c2_tc11_finance_delete_blocked_on_reverse_payment_lookup(self):
        mock_db = MagicMock()
        txn_id = "707f1f77bcf86cd799439311"
        order_id = "507f1f77bcf86cd799439111"

        # Transaction document has no explicit payment_id field
        txn_doc = {
            "_id": ObjectId(txn_id),
            "type": "order_revenue",
            "amount": 750.0,
            "currency": "EGP",
        }
        # But db.payments has an active recorded payment pointing to this transaction
        matching_pmt = {
            "_id": ObjectId("607f1f77bcf86cd799439211"),
            "finance_transaction_id": txn_id,
            "order_id": order_id,
            "status": "recorded",
        }
        mock_db.finance_transactions.find_one = AsyncMock(return_value=txn_doc)
        mock_db.payments.find_one = AsyncMock(return_value=matching_pmt)

        with patch("server.db", mock_db):
            with self.assertRaises(HTTPException) as cm:
                await finance_delete(txn_id, self.admin_finance)
            self.assertEqual(cm.exception.status_code, 409)
            self.assertIn("terhubung langsung dengan pembayaran pesanan resmi", cm.exception.detail)

    # =========================================================================
    # C2-TC-12: finance_delete blocked on credit settlement / credit refund
    # =========================================================================
    async def test_c2_tc12_finance_delete_blocked_on_credit_refund(self):
        mock_db = MagicMock()
        txn_id = "707f1f77bcf86cd799439312"

        txn_doc = {
            "_id": ObjectId(txn_id),
            "type": "credit_refund",
            "classification": "liability_settlement",
            "amount": 500.0,
            "currency": "EGP",
            "related_credit_event_number": "CCE-20261011-001",
        }
        mock_db.finance_transactions.find_one = AsyncMock(return_value=txn_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)

        with patch("server.db", mock_db):
            with self.assertRaises(HTTPException) as cm:
                await finance_delete(txn_id, self.admin_finance)
            self.assertEqual(cm.exception.status_code, 409)
            self.assertIn("terhubung dengan transaksi kredit atau pengembalian saldo kredit", cm.exception.detail)

    # =========================================================================
    # C2-TC-13: finance_delete permitted for standalone operational expense
    # =========================================================================
    async def test_c2_tc13_finance_delete_permitted_standalone_expense(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        txn_id = "707f1f77bcf86cd799439313"

        txn_doc = {
            "_id": ObjectId(txn_id),
            "type": "expense",
            "category": "Operasional Toko",
            "amount": 250.0,
            "currency": "EGP",
            "is_void": False,
        }
        mock_db.finance_transactions.find_one = AsyncMock(return_value=txn_doc)
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.payments.find_one = AsyncMock(return_value=None)

        with patch("server.db", mock_db):
            res = await finance_delete(txn_id, self.admin_finance)
            self.assertTrue(res.get("ok"))
            self.assertTrue(res.get("voided"))

        mock_db.finance_transactions.update_one.assert_called_once()
        update_call = mock_db.finance_transactions.update_one.call_args[0][1]
        self.assertTrue(update_call["$set"]["is_void"])
        self.assertEqual(update_call["$set"]["status"], "void")

    # =========================================================================
    # C2-TC-14: finance_delete permitted for legacy unlinked order_revenue
    # =========================================================================
    async def test_c2_tc14_finance_delete_permitted_legacy_order_revenue(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        txn_id = "707f1f77bcf86cd799439314"

        # Pre-Phase 1 legacy record without payment_id and not referenced by db.payments
        txn_doc = {
            "_id": ObjectId(txn_id),
            "type": "order_revenue",
            "amount": 400.0,
            "currency": "EGP",
            "is_void": False,
        }
        mock_db.finance_transactions.find_one = AsyncMock(return_value=txn_doc)
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.payments.find_one = AsyncMock(return_value=None)

        with patch("server.db", mock_db):
            res = await finance_delete(txn_id, self.admin_finance)
            self.assertTrue(res.get("ok"))
            self.assertTrue(res.get("voided"))

        mock_db.finance_transactions.update_one.assert_called_once()
        update_call = mock_db.finance_transactions.update_one.call_args[0][1]
        self.assertTrue(update_call["$set"]["is_void"])

    # =========================================================================
    # C2-TC-15: finance_delete on already-voided transaction returns 400
    # =========================================================================
    async def test_c2_tc15_finance_delete_already_voided_returns_400(self):
        mock_db = MagicMock()
        txn_id = "707f1f77bcf86cd799439315"

        txn_doc = {
            "_id": ObjectId(txn_id),
            "type": "expense",
            "amount": 100.0,
            "currency": "EGP",
            "is_void": True,
            "status": "void",
        }
        mock_db.finance_transactions.find_one = AsyncMock(return_value=txn_doc)

        with patch("server.db", mock_db):
            with self.assertRaises(HTTPException) as cm:
                await finance_delete(txn_id, self.admin_finance)
            self.assertEqual(cm.exception.status_code, 400)
            self.assertIn("Transaksi yang telah dibatalkan tidak dapat dibatalkan kembali", cm.exception.detail)

    # =========================================================================
    # C-ALL-16: Suite invariants and baseline stability verification
    # =========================================================================
    async def test_c_all16_full_suite_regression_invariants(self):
        # Verifies that both guards preserve basic non-existent record 404 behavior
        mock_db = MagicMock()
        mock_db.finance_transactions.find_one = AsyncMock(return_value=None)
        mock_db.orders.find_one = AsyncMock(return_value=None)

        with patch("server.db", mock_db):
            with self.assertRaises(HTTPException) as cm_fin:
                await finance_delete("707f1f77bcf86cd799439999", self.admin_finance)
            self.assertEqual(cm_fin.exception.status_code, 404)

            with self.assertRaises(HTTPException) as cm_pmt:
                await admin_void_order_payment(
                    "507f1f77bcf86cd799439999",
                    "607f1f77bcf86cd799439999",
                    PaymentVoidInput(reason="test"),
                    self.admin_finance,
                )
            self.assertEqual(cm_pmt.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
