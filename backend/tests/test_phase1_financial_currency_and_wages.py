"""Isolated unit and regression test suite for Phase 1 — Financial Currency Correction,
Multi-Currency Wage Settlement, and Google Maps Order Validation.

Uses synthetic mocks and isolated in-memory fixtures. No external database or network calls.
"""

import asyncio
import json
import math
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from fastapi import HTTPException
import pymongo

from server import (
    _stats_for,
    admin_create_wage_settlement,
    admin_get_worker_pending_wages,
    app,
    get_current_admin,
    validate_and_normalize_maps_url,
    WageSettlementCreateInput,
)


class TestPhase1SalesRevenueReporting(unittest.IsolatedAsyncioTestCase):
    """Verifies that sales revenue from completed orders is attributed strictly to the
    currency in which payments were received (EGP vs IDR) without double counting or leakage.
    """

    async def test_egp_paid_sale_contributes_to_egp_sales_revenue(self):
        """Order completed and paid in EGP contributes to EGP sales_revenue, zero IDR sales_revenue."""
        mock_db = MagicMock()
        order_id = "670868f123456789abcdef01"

        txns = [
            {"type": "order_revenue", "account": "EGP", "currency": "EGP", "amount": 2500.0, "is_void": False, "status": "recorded", "date": "2026-10-05T10:00:00Z"}
        ]
        orders = [
            {
                "_id": ObjectId(order_id),
                "order_number": "SO-EGP-001",
                "order_status": "selesai",
                "completed_at": "2026-10-10T12:00:00Z",
                "recognized_revenue_le": 2500.0,
                "total_le": 2500.0,
                "payment_method": "cash",
            }
        ]
        pmts = [
            {
                "order_id": order_id,
                "amount_le": 2500.0,
                "primary_amount": 2500.0,
                "primary_currency": "EGP",
                "payment_method": "cash",
                "status": "recorded",
            }
        ]

        async def gen_txns(*args, **kwargs):
            for t in txns: yield t
        async def gen_orders(*args, **kwargs):
            for o in orders: yield o
        async def gen_pmts(*args, **kwargs):
            for p in pmts: yield p
        async def gen_empty(*args, **kwargs):
            if False: yield {}

        mock_db.finance_transactions.find = gen_txns
        mock_db.orders.find = gen_orders
        mock_db.payments.find = gen_pmts
        mock_db.finance_adjustments.find = gen_empty
        mock_db.customer_credit_events.find = gen_empty
        mock_db.customer_credit_events.aggregate.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db):
            stats = await _stats_for("2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z")

        # EGP has sales revenue 2500, real cash inflow 2500
        self.assertEqual(stats["EGP"]["sales_revenue"], 2500.0)
        self.assertEqual(stats["EGP"]["real_cash_inflow"], 2500.0)
        # IDR has strictly 0 sales revenue, 0 real cash inflow
        self.assertEqual(stats["IDR"]["sales_revenue"], 0.0)
        self.assertEqual(stats["IDR"]["real_cash_inflow"], 0.0)

    async def test_idr_paid_sale_contributes_to_idr_sales_revenue(self):
        """Order completed and paid in IDR bank transfer contributes to IDR sales_revenue, zero EGP sales_revenue."""
        mock_db = MagicMock()
        order_id = "670868f123456789abcdef02"

        txns = [
            {"type": "order_revenue", "account": "IDR", "currency": "IDR", "amount": 3570000.0, "is_void": False, "status": "recorded", "date": "2026-10-06T10:00:00Z"}
        ]
        orders = [
            {
                "_id": ObjectId(order_id),
                "order_number": "SO-IDR-001",
                "order_status": "selesai",
                "completed_at": "2026-10-10T12:00:00Z",
                "recognized_revenue_le": 1000.0,
                "total_le": 1000.0,
                "exchange_rate_idr_per_le": 357.0,
                "estimated_total_idr": 3570000,
                "payment_method": "transfer",
            }
        ]
        pmts = [
            {
                "order_id": order_id,
                "amount_le": 1000.0,
                "primary_amount": 3570000.0,
                "primary_currency": "IDR",
                "payment_method": "transfer",
                "exchange_rate_snapshot": 357.0,
                "status": "recorded",
            }
        ]

        async def gen_txns(*args, **kwargs):
            for t in txns: yield t
        async def gen_orders(*args, **kwargs):
            for o in orders: yield o
        async def gen_pmts(*args, **kwargs):
            for p in pmts: yield p
        async def gen_empty(*args, **kwargs):
            if False: yield {}

        mock_db.finance_transactions.find = gen_txns
        mock_db.orders.find = gen_orders
        mock_db.payments.find = gen_pmts
        mock_db.finance_adjustments.find = gen_empty
        mock_db.customer_credit_events.find = gen_empty
        mock_db.customer_credit_events.aggregate.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db):
            stats = await _stats_for("2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z")

        # IDR has sales revenue 3,570,000, real cash inflow 3,570,000
        self.assertEqual(stats["IDR"]["sales_revenue"], 3570000.0)
        self.assertEqual(stats["IDR"]["real_cash_inflow"], 3570000.0)
        # EGP has strictly 0 sales revenue, 0 real cash inflow
        self.assertEqual(stats["EGP"]["sales_revenue"], 0.0)
        self.assertEqual(stats["EGP"]["real_cash_inflow"], 0.0)

    async def test_split_currency_payments_distribute_correctly(self):
        """Order paid 50% in EGP and 50% in IDR splits sales revenue between both currencies."""
        mock_db = MagicMock()
        order_id = "670868f123456789abcdef03"

        txns = [
            {"type": "order_revenue", "account": "EGP", "currency": "EGP", "amount": 500.0, "is_void": False, "status": "recorded", "date": "2026-10-05T10:00:00Z"},
            {"type": "order_revenue", "account": "IDR", "currency": "IDR", "amount": 1785000.0, "is_void": False, "status": "recorded", "date": "2026-10-06T10:00:00Z"}
        ]
        orders = [
            {
                "_id": ObjectId(order_id),
                "order_number": "SO-SPLIT-001",
                "order_status": "selesai",
                "completed_at": "2026-10-10T12:00:00Z",
                "recognized_revenue_le": 1000.0,
                "total_le": 1000.0,
                "exchange_rate_idr_per_le": 357.0,
            }
        ]
        pmts = [
            {
                "order_id": order_id,
                "amount_le": 500.0,
                "primary_amount": 500.0,
                "primary_currency": "EGP",
                "payment_method": "cash",
                "status": "recorded",
            },
            {
                "order_id": order_id,
                "amount_le": 500.0,
                "primary_amount": 1785000.0,
                "primary_currency": "IDR",
                "payment_method": "transfer",
                "exchange_rate_snapshot": 357.0,
                "status": "recorded",
            }
        ]

        async def gen_txns(*args, **kwargs):
            for t in txns: yield t
        async def gen_orders(*args, **kwargs):
            for o in orders: yield o
        async def gen_pmts(*args, **kwargs):
            for p in pmts: yield p
        async def gen_empty(*args, **kwargs):
            if False: yield {}

        mock_db.finance_transactions.find = gen_txns
        mock_db.orders.find = gen_orders
        mock_db.payments.find = gen_pmts
        mock_db.finance_adjustments.find = gen_empty
        mock_db.customer_credit_events.find = gen_empty
        mock_db.customer_credit_events.aggregate.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db):
            stats = await _stats_for("2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z")

        self.assertEqual(stats["EGP"]["sales_revenue"], 500.0)
        self.assertEqual(stats["EGP"]["real_cash_inflow"], 500.0)
        self.assertEqual(stats["IDR"]["sales_revenue"], 1785000.0)
        self.assertEqual(stats["IDR"]["real_cash_inflow"], 1785000.0)

    async def test_no_double_counting_across_payments_and_finance_transactions(self):
        """Payments in db.payments and finance_transactions do not duplicate sales revenue."""
        mock_db = MagicMock()
        order_id = "670868f123456789abcdef04"

        # finance_transactions has 1 entry of 1000 LE
        txns = [
            {"type": "order_revenue", "account": "EGP", "currency": "EGP", "amount": 1000.0, "is_void": False, "status": "recorded", "date": "2026-10-05T10:00:00Z"}
        ]
        # order is completed with 1000 LE recognized revenue
        orders = [
            {
                "_id": ObjectId(order_id),
                "order_number": "SO-004",
                "order_status": "selesai",
                "completed_at": "2026-10-10T12:00:00Z",
                "recognized_revenue_le": 1000.0,
                "total_le": 1000.0,
            }
        ]
        # payments has 1 record of 1000 LE
        pmts = [
            {"order_id": order_id, "amount_le": 1000.0, "primary_amount": 1000.0, "primary_currency": "EGP", "status": "recorded"}
        ]

        async def gen_txns(*args, **kwargs):
            for t in txns: yield t
        async def gen_orders(*args, **kwargs):
            for o in orders: yield o
        async def gen_pmts(*args, **kwargs):
            for p in pmts: yield p
        async def gen_empty(*args, **kwargs):
            if False: yield {}

        mock_db.finance_transactions.find = gen_txns
        mock_db.orders.find = gen_orders
        mock_db.payments.find = gen_pmts
        mock_db.finance_adjustments.find = gen_empty
        mock_db.customer_credit_events.find = gen_empty
        mock_db.customer_credit_events.aggregate.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db):
            stats = await _stats_for("2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z")

        # Revenue is recognized exactly once as 1000.0
        self.assertEqual(stats["EGP"]["sales_revenue"], 1000.0)
        self.assertEqual(stats["EGP"]["total_revenue"], 1000.0)
        # Cash inflow is counted exactly once from finance_transactions
        self.assertEqual(stats["EGP"]["real_cash_inflow"], 1000.0)

    async def test_partial_idr_payment_with_outstanding_receivable(self):
        """Test A: Partial IDR payment (400 LE = 142,800 IDR) with 600 LE uncollected balance
        yields 357,000 IDR sales revenue, 142,800 IDR cash inflow, and 600 LE accounts receivable.
        """
        mock_db = MagicMock()
        order_id = "670868f123456789abcdef05"

        # finance_transactions has 1 entry for the 142,800 IDR cash inflow
        txns = [
            {
                "type": "order_payment",
                "account": "IDR",
                "currency": "IDR",
                "amount": 142800.0,
                "is_void": False,
                "status": "recorded",
                "date": "2026-10-05T10:00:00Z"
            }
        ]
        # Order is completed (handed over) with recognized revenue of 1000 LE, transfer method, rate 357
        orders = [
            {
                "_id": ObjectId(order_id),
                "order_number": "SO-005",
                "order_status": "selesai",
                "completed_at": "2026-10-10T12:00:00Z",
                "recognized_revenue_le": 1000.0,
                "payment_method": "transfer",
                "exchange_rate_idr_per_le": 357.0,
                "estimated_total_idr": 357000.0,
                "total_le": 1000.0,
            }
        ]
        # payments collection has 1 recorded payment of 400 LE = 142,800 IDR
        pmts = [
            {
                "order_id": order_id,
                "amount_le": 400.0,
                "primary_amount": 142800.0,
                "primary_currency": "IDR",
                "payment_method": "transfer",
                "exchange_rate_snapshot": 357.0,
                "status": "recorded"
            }
        ]

        async def gen_txns(*args, **kwargs):
            for t in txns: yield t
        async def gen_orders(*args, **kwargs):
            for o in orders: yield o
        async def gen_pmts(*args, **kwargs):
            for p in pmts: yield p
        async def gen_empty(*args, **kwargs):
            if False: yield {}

        mock_db.finance_transactions.find = gen_txns
        mock_db.orders.find = gen_orders
        mock_db.payments.find = gen_pmts
        mock_db.finance_adjustments.find = gen_empty
        mock_db.customer_credit_events.find = gen_empty
        mock_db.customer_credit_events.aggregate.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db):
            stats = await _stats_for("2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z")

        # 1. Recognized sales revenue is 357,000 IDR and zero EGP
        self.assertEqual(stats["IDR"]["sales_revenue"], 357000.0)
        self.assertEqual(stats["IDR"]["total_revenue"], 357000.0)
        self.assertEqual(stats["EGP"]["sales_revenue"], 0.0)
        self.assertEqual(stats["EGP"]["total_revenue"], 0.0)

        # 2. Actual cash inflow is 142,800 IDR and zero EGP
        self.assertEqual(stats["IDR"]["real_cash_inflow"], 142800.0)
        self.assertEqual(stats["EGP"]["real_cash_inflow"], 0.0)

        # 3. Accounts receivable is 600 LE (under EGP working capital ledger)
        self.assertEqual(stats["EGP"]["accounts_receivable"], 600.0)
        self.assertEqual(stats["IDR"]["accounts_receivable"], 0.0)

        # 4. Customer advances is zero (since order is completed)
        self.assertEqual(stats["EGP"]["customer_advances"], 0.0)

    async def test_handed_over_transfer_order_with_no_payments(self):
        """Test B: Handed-over transfer order with zero payments recognizes 357,000 IDR revenue,
        zero cash inflow, and 1,000 LE accounts receivable.
        """
        mock_db = MagicMock()
        order_id = "670868f123456789abcdef06"

        # finance_transactions has zero entries
        txns = []

        # Order is completed with recognized revenue of 1000 LE, transfer method, rate 357
        orders = [
            {
                "_id": ObjectId(order_id),
                "order_number": "SO-006",
                "order_status": "selesai",
                "completed_at": "2026-10-10T12:00:00Z",
                "recognized_revenue_le": 1000.0,
                "payment_method": "transfer",
                "exchange_rate_idr_per_le": 357.0,
                "estimated_total_idr": 357000.0,
                "total_le": 1000.0,
            }
        ]

        # payments has zero entries
        pmts = []

        async def gen_txns(*args, **kwargs):
            for t in txns: yield t
        async def gen_orders(*args, **kwargs):
            for o in orders: yield o
        async def gen_pmts(*args, **kwargs):
            for p in pmts: yield p
        async def gen_empty(*args, **kwargs):
            if False: yield {}

        mock_db.finance_transactions.find = gen_txns
        mock_db.orders.find = gen_orders
        mock_db.payments.find = gen_pmts
        mock_db.finance_adjustments.find = gen_empty
        mock_db.customer_credit_events.find = gen_empty
        mock_db.customer_credit_events.aggregate.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db):
            stats = await _stats_for("2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z")

        # 1. Recognized sales revenue is 357,000 IDR and zero EGP
        self.assertEqual(stats["IDR"]["sales_revenue"], 357000.0)
        self.assertEqual(stats["IDR"]["total_revenue"], 357000.0)
        self.assertEqual(stats["EGP"]["sales_revenue"], 0.0)
        self.assertEqual(stats["EGP"]["total_revenue"], 0.0)

        # 2. Actual cash inflow is zero in both currencies
        self.assertEqual(stats["IDR"]["real_cash_inflow"], 0.0)
        self.assertEqual(stats["EGP"]["real_cash_inflow"], 0.0)

        # 3. Accounts receivable is 1,000 LE
        self.assertEqual(stats["EGP"]["accounts_receivable"], 1000.0)
        self.assertEqual(stats["IDR"]["accounts_receivable"], 0.0)

        # 4. Customer advances is zero
        self.assertEqual(stats["EGP"]["customer_advances"], 0.0)


class TestPhase1MultiCurrencyWageSettlement(unittest.IsolatedAsyncioTestCase):
    """Verifies that employee wage settlements support payouts in EGP or IDR,
    reduce the correct physical cash / bank account, preserve immutable dispatch rates,
    and require an explicit reason when rate overrides occur.
    """

    def setUp(self):
        self.admin = {"id": "adm_1", "name": "Head Finance", "role": "owner", "permissions": {"access_finance": True}}
        self.worker = {"_id": ObjectId("670868f123456789abcdef10"), "id": "w_10", "name": "Budi Santoso", "role": "employee"}

    async def test_egp_settlement_reduces_egp_cash_account(self):
        """EGP wage settlement creates EGP finance expense, reduces EGP account, preserves LE liability."""
        mock_db = MagicMock()
        mock_db.admins.find_one = AsyncMock(return_value=self.worker)
        mock_db.wage_settlements.find_one = AsyncMock(return_value=None)

        ob_doc = {
            "_id": ObjectId("670868f123456789abcdef11"),
            "worker_id": "w_10",
            "obligation_number": "WOB-001",
            "total_amount_le": 200.0,
            "paid_amount_le": 0.0,
            "currency": "EGP",
            "status": "accrued",
            "locked_exchange_rate": 357.0,
        }
        find_ob_mock = MagicMock()
        find_ob_mock.sort.return_value.to_list = AsyncMock(return_value=[ob_doc])
        mock_db.wage_obligations.find.return_value = find_ob_mock

        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.employee_wages.insert_one = AsyncMock()
        mock_db.wage_settlements.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.wage_obligations.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        mock_db.audit_logs.insert_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 1})
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357})

        payload = WageSettlementCreateInput(
            worker_id="w_10",
            amount_le=200.0,
            payment_currency="EGP",
            payment_method="cash",
        )

        with patch("server.db", mock_db), \
             patch("server.client.start_session", AsyncMock(side_effect=pymongo.errors.ConfigurationError("Standalone"))), \
             patch("server.is_standalone_fallback_permitted", return_value=True):
            res = await admin_create_wage_settlement(payload, self.admin)

        self.assertIsNotNone(res)
        # Check finance transaction inserted
        txn_call = mock_db.finance_transactions.insert_one.call_args[0][0]
        self.assertEqual(txn_call["account"], "EGP")
        self.assertEqual(txn_call["currency"], "EGP")
        self.assertEqual(txn_call["amount"], 200.0)
        self.assertEqual(txn_call["category"], "Pekerja")
        self.assertEqual(txn_call["classification"], "cost")

        # Check wage settlement inserted
        st_call = mock_db.wage_settlements.insert_one.call_args[0][0]
        self.assertEqual(st_call["payout_currency"], "EGP")
        self.assertEqual(st_call["payout_amount"], 200.0)
        self.assertEqual(st_call["amount_le"], 200.0)

        # Check obligation updated in LE
        ob_call = mock_db.wage_obligations.update_one.call_args[0][1]
        self.assertEqual(ob_call["$set"]["paid_amount_le"], 200.0)
        self.assertEqual(ob_call["$set"]["status"], "paid")

    async def test_idr_settlement_using_locked_rate_by_default(self):
        """IDR wage settlement uses locked dispatch rate (357) by default, reduces IDR bank account."""
        mock_db = MagicMock()
        mock_db.admins.find_one = AsyncMock(return_value=self.worker)
        mock_db.wage_settlements.find_one = AsyncMock(return_value=None)

        ob_doc = {
            "_id": ObjectId("670868f123456789abcdef12"),
            "worker_id": "w_10",
            "obligation_number": "WOB-002",
            "total_amount_le": 100.0,
            "paid_amount_le": 0.0,
            "currency": "EGP",
            "status": "accrued",
            "locked_exchange_rate": 357.0,
        }
        find_ob_mock = MagicMock()
        find_ob_mock.sort.return_value.to_list = AsyncMock(return_value=[ob_doc])
        mock_db.wage_obligations.find.return_value = find_ob_mock

        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.employee_wages.insert_one = AsyncMock()
        mock_db.wage_settlements.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.wage_obligations.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        mock_db.audit_logs.insert_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 1})
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357})

        payload = WageSettlementCreateInput(
            worker_id="w_10",
            amount_le=100.0,
            payment_currency="IDR",
            payment_method="bank_transfer",
        )

        with patch("server.db", mock_db), \
             patch("server.client.start_session", AsyncMock(side_effect=pymongo.errors.ConfigurationError("Standalone"))), \
             patch("server.is_standalone_fallback_permitted", return_value=True):
            res = await admin_create_wage_settlement(payload, self.admin)

        self.assertIsNotNone(res)
        # Check finance transaction inserted in IDR
        txn_call = mock_db.finance_transactions.insert_one.call_args[0][0]
        self.assertEqual(txn_call["account"], "IDR")
        self.assertEqual(txn_call["currency"], "IDR")
        self.assertEqual(txn_call["amount"], 35700.0)  # 100 LE * 357 = Rp 35,700
        self.assertEqual(txn_call["counterpart_amount"], 100.0)
        self.assertEqual(txn_call["counterpart_currency"], "EGP")

        # Settlement document
        st_call = mock_db.wage_settlements.insert_one.call_args[0][0]
        self.assertEqual(st_call["payout_currency"], "IDR")
        self.assertEqual(st_call["payout_amount"], 35700.0)
        self.assertEqual(st_call["locked_exchange_rate"], 357.0)
        self.assertEqual(st_call["settlement_rate"], 357.0)
        self.assertFalse(st_call["is_rate_override"])

        # No rate override audit log triggered
        override_calls = [c for c in mock_db.audit_logs.insert_one.call_args_list if c[0][0].get("action") == "wage_settlement_rate_override"]
        self.assertEqual(len(override_calls), 0)

    async def test_idr_settlement_with_authorized_override_and_reason(self):
        """IDR wage settlement with rate override (e.g. 365) and reason records audit log and IDR amount."""
        mock_db = MagicMock()
        mock_db.admins.find_one = AsyncMock(return_value=self.worker)
        mock_db.wage_settlements.find_one = AsyncMock(return_value=None)

        ob_doc = {
            "_id": ObjectId("670868f123456789abcdef13"),
            "worker_id": "w_10",
            "obligation_number": "WOB-003",
            "total_amount_le": 100.0,
            "paid_amount_le": 0.0,
            "currency": "EGP",
            "status": "accrued",
            "locked_exchange_rate": 357.0,
        }
        find_ob_mock = MagicMock()
        find_ob_mock.sort.return_value.to_list = AsyncMock(return_value=[ob_doc])
        mock_db.wage_obligations.find.return_value = find_ob_mock

        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.employee_wages.insert_one = AsyncMock()
        mock_db.wage_settlements.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.wage_obligations.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        mock_db.audit_logs.insert_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 1})
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357})

        payload = WageSettlementCreateInput(
            worker_id="w_10",
            amount_le=100.0,
            payment_currency="IDR",
            payment_method="bank_transfer",
            settlement_rate=365.0,
            is_rate_override=True,
            override_reason="Penyesuaian kurs bank BCA riil saat transfer",
        )

        with patch("server.db", mock_db), \
             patch("server.client.start_session", AsyncMock(side_effect=pymongo.errors.ConfigurationError("Standalone"))), \
             patch("server.is_standalone_fallback_permitted", return_value=True):
            res = await admin_create_wage_settlement(payload, self.admin)

        self.assertIsNotNone(res)
        # Transaction amount is 100 * 365 = 36500 IDR
        txn_call = mock_db.finance_transactions.insert_one.call_args[0][0]
        self.assertEqual(txn_call["amount"], 36500.0)
        self.assertEqual(txn_call["currency"], "IDR")
        self.assertEqual(txn_call["exchange_rate"], 365.0)

        # Settlement preserves both locked rate and override rate
        st_call = mock_db.wage_settlements.insert_one.call_args[0][0]
        self.assertEqual(st_call["locked_exchange_rate"], 357.0)
        self.assertEqual(st_call["settlement_rate"], 365.0)
        self.assertTrue(st_call["is_rate_override"])
        self.assertEqual(st_call["override_reason"], "Penyesuaian kurs bank BCA riil saat transfer")

        # Audit log was recorded for rate override
        override_calls = [c for c in mock_db.audit_logs.insert_one.call_args_list if c[0][0].get("action") == "wage_settlement_rate_override"]
        self.assertEqual(len(override_calls), 1)
        audit_call = override_calls[0][0][0]
        self.assertEqual(audit_call["action"], "wage_settlement_rate_override")
        self.assertEqual(audit_call["metadata"]["original_locked_rate"], 357.0)
        self.assertEqual(audit_call["metadata"]["override_rate"], 365.0)
        self.assertEqual(audit_call["metadata"]["override_reason"], "Penyesuaian kurs bank BCA riil saat transfer")

    async def test_rejection_of_override_without_reason(self):
        """Rate override without reason is rejected with HTTP 422."""
        mock_db = MagicMock()
        mock_db.admins.find_one = AsyncMock(return_value=self.worker)
        mock_db.wage_settlements.find_one = AsyncMock(return_value=None)
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357})

        ob_doc = {
            "_id": ObjectId("670868f123456789abcdef14"),
            "worker_id": "w_10",
            "total_amount_le": 100.0,
            "paid_amount_le": 0.0,
            "locked_exchange_rate": 357.0,
        }
        find_ob_mock = MagicMock()
        find_ob_mock.sort.return_value.to_list = AsyncMock(return_value=[ob_doc])
        mock_db.wage_obligations.find.return_value = find_ob_mock

        payload = WageSettlementCreateInput(
            worker_id="w_10",
            amount_le=100.0,
            payment_currency="IDR",
            settlement_rate=365.0,
            is_rate_override=True,
            override_reason="",  # Missing reason
        )

        with patch("server.db", mock_db):
            with self.assertRaises(HTTPException) as ctx:
                await admin_create_wage_settlement(payload, self.admin)
            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("Alasan perubahan kurs wajib diisi", ctx.exception.detail)

    async def test_rejection_of_invalid_override_rate(self):
        """Rate override with zero or negative or non-finite rate is rejected with HTTP 422."""
        mock_db = MagicMock()
        mock_db.admins.find_one = AsyncMock(return_value=self.worker)
        mock_db.wage_settlements.find_one = AsyncMock(return_value=None)
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357})

        ob_doc = {
            "_id": ObjectId("670868f123456789abcdef15"),
            "worker_id": "w_10",
            "total_amount_le": 100.0,
            "paid_amount_le": 0.0,
            "locked_exchange_rate": 357.0,
        }
        find_ob_mock = MagicMock()
        find_ob_mock.sort.return_value.to_list = AsyncMock(return_value=[ob_doc])
        mock_db.wage_obligations.find.return_value = find_ob_mock

        payload = WageSettlementCreateInput(
            worker_id="w_10",
            amount_le=100.0,
            payment_currency="IDR",
            settlement_rate=-10.0,  # Negative rate
            is_rate_override=True,
            override_reason="Invalid rate test",
        )

        with patch("server.db", mock_db):
            with self.assertRaises(HTTPException) as ctx:
                await admin_create_wage_settlement(payload, self.admin)
            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("Kurs override harus berupa angka positif", ctx.exception.detail)

    async def test_legacy_obligation_without_locked_rate_defaults_to_settings_rate(self):
        """Legacy obligation with no locked rate cleanly defaults to current settings rate for IDR."""
        mock_db = MagicMock()
        mock_db.admins.find_one = AsyncMock(return_value=self.worker)
        mock_db.wage_settlements.find_one = AsyncMock(return_value=None)

        ob_doc = {
            "_id": ObjectId("670868f123456789abcdef16"),
            "worker_id": "w_10",
            "obligation_number": "WOB-LEGACY",
            "total_amount_le": 100.0,
            "paid_amount_le": 0.0,
            "currency": "EGP",
            "status": "accrued",
            # No locked_exchange_rate, no order_id
        }
        find_ob_mock = MagicMock()
        find_ob_mock.sort.return_value.to_list = AsyncMock(return_value=[ob_doc])
        mock_db.wage_obligations.find.return_value = find_ob_mock

        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.employee_wages.insert_one = AsyncMock()
        mock_db.wage_settlements.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.wage_obligations.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        mock_db.audit_logs.insert_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 1})
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357})

        payload = WageSettlementCreateInput(
            worker_id="w_10",
            amount_le=100.0,
            payment_currency="IDR",
            payment_method="bank_transfer",
            # settlement_rate omitted
        )

        with patch("server.db", mock_db), \
             patch("server.client.start_session", AsyncMock(side_effect=pymongo.errors.ConfigurationError("Standalone"))), \
             patch("server.is_standalone_fallback_permitted", return_value=True):
            res = await admin_create_wage_settlement(payload, self.admin)

        self.assertIsNotNone(res)
        st_call = mock_db.wage_settlements.insert_one.call_args[0][0]
        self.assertEqual(st_call["settlement_rate"], 357.0)
        self.assertIsNone(st_call["order_historical_rate"])
        self.assertEqual(st_call["payout_amount"], 35700.0)

    async def test_settings_rate_change_updates_default_wage_settlement_rate(self):
        """Settings rate changed to 500 after order creation updates default wage settlement rate to 500."""
        mock_db = MagicMock()
        mock_db.admins.find_one = AsyncMock(return_value=self.worker)
        mock_db.wage_settlements.find_one = AsyncMock(return_value=None)

        ob_doc = {
            "_id": ObjectId("670868f123456789abcdef17"),
            "worker_id": "w_10",
            "obligation_number": "WOB-004",
            "total_amount_le": 100.0,
            "paid_amount_le": 0.0,
            "currency": "EGP",
            "status": "accrued",
            "locked_exchange_rate": 357.0,
        }
        find_ob_mock = MagicMock()
        find_ob_mock.sort.return_value.to_list = AsyncMock(return_value=[ob_doc])
        mock_db.wage_obligations.find.return_value = find_ob_mock

        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.employee_wages.insert_one = AsyncMock()
        mock_db.wage_settlements.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.wage_obligations.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        mock_db.audit_logs.insert_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 1})
        # Settings rate is changed to 500
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 500})

        payload = WageSettlementCreateInput(
            worker_id="w_10",
            amount_le=100.0,
            payment_currency="IDR",
            payment_method="bank_transfer",
        )

        with patch("server.db", mock_db), \
             patch("server.client.start_session", AsyncMock(side_effect=pymongo.errors.ConfigurationError("Standalone"))), \
             patch("server.is_standalone_fallback_permitted", return_value=True):
            res = await admin_create_wage_settlement(payload, self.admin)

        self.assertIsNotNone(res)
        # Transaction and settlement must use current settings rate 500
        txn_call = mock_db.finance_transactions.insert_one.call_args[0][0]
        self.assertEqual(txn_call["exchange_rate"], 500.0)
        self.assertEqual(txn_call["amount"], 50000.0)

        st_call = mock_db.wage_settlements.insert_one.call_args[0][0]
        self.assertEqual(st_call["settlement_rate"], 500.0)
        self.assertEqual(st_call["order_historical_rate"], 357.0)
        self.assertEqual(st_call["payout_amount"], 50000.0)
        self.assertFalse(st_call["is_rate_override"])

    async def test_partial_idr_settlement_leaves_correct_remaining_le_liability(self):
        """Partial IDR payment reduces obligation strictly in LE and leaves exact remaining LE balance."""
        mock_db = MagicMock()
        mock_db.admins.find_one = AsyncMock(return_value=self.worker)
        mock_db.wage_settlements.find_one = AsyncMock(return_value=None)

        ob_doc = {
            "_id": ObjectId("670868f123456789abcdef18"),
            "worker_id": "w_10",
            "obligation_number": "WOB-005",
            "total_amount_le": 200.0,
            "paid_amount_le": 0.0,
            "currency": "EGP",
            "status": "accrued",
            "locked_exchange_rate": 357.0,
        }
        find_ob_mock = MagicMock()
        find_ob_mock.sort.return_value.to_list = AsyncMock(return_value=[ob_doc])
        mock_db.wage_obligations.find.return_value = find_ob_mock

        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.employee_wages.insert_one = AsyncMock()
        mock_db.wage_settlements.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.wage_obligations.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        mock_db.audit_logs.insert_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 1})
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357})

        # Settle partial 75 LE out of 200 LE in IDR
        payload = WageSettlementCreateInput(
            worker_id="w_10",
            amount_le=75.0,
            payment_currency="IDR",
            payment_method="bank_transfer",
        )

        with patch("server.db", mock_db), \
             patch("server.client.start_session", AsyncMock(side_effect=pymongo.errors.ConfigurationError("Standalone"))), \
             patch("server.is_standalone_fallback_permitted", return_value=True):
            res = await admin_create_wage_settlement(payload, self.admin)

        self.assertIsNotNone(res)
        # Bank account deducted in IDR: 75 * 357 = 26775 IDR
        txn_call = mock_db.finance_transactions.insert_one.call_args[0][0]
        self.assertEqual(txn_call["account"], "IDR")
        self.assertEqual(txn_call["amount"], 26775.0)

        # Obligation updated: paid_amount_le becomes 75.0, status becomes partially_paid
        ob_call = mock_db.wage_obligations.update_one.call_args[0][1]
        self.assertEqual(ob_call["$set"]["paid_amount_le"], 75.0)
        self.assertEqual(ob_call["$set"]["status"], "partially_paid")

    async def test_customized_actual_idr_payout_with_variance_and_reason(self):
        """Customized IDR nominal (e.g. transfer rounding) validates variance, logs audit, and preserves exact LE liability."""
        mock_db = MagicMock()
        mock_db.admins.find_one = AsyncMock(return_value=self.worker)
        mock_db.wage_settlements.find_one = AsyncMock(return_value=None)

        ob_doc = {
            "_id": ObjectId("670868f123456789abcdef19"),
            "worker_id": "w_10",
            "obligation_number": "WOB-006",
            "total_amount_le": 100.0,
            "paid_amount_le": 0.0,
            "currency": "EGP",
            "status": "accrued",
            "locked_exchange_rate": 357.0,
        }
        find_ob_mock = MagicMock()
        find_ob_mock.sort.return_value.to_list = AsyncMock(return_value=[ob_doc])
        mock_db.wage_obligations.find.return_value = find_ob_mock

        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.employee_wages.insert_one = AsyncMock()
        mock_db.wage_settlements.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.wage_obligations.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        mock_db.audit_logs.insert_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 1})
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357})

        # Standard is 100 * 357 = 35700. Admin disburses 36000 (+300 variance)
        payload = WageSettlementCreateInput(
            worker_id="w_10",
            amount_le=100.0,
            payment_currency="IDR",
            payment_method="bank_transfer",
            actual_payout_amount=36000.0,
            notes="Pembulatan transfer bank BCA",
        )

        with patch("server.db", mock_db), \
             patch("server.client.start_session", AsyncMock(side_effect=pymongo.errors.ConfigurationError("Standalone"))), \
             patch("server.is_standalone_fallback_permitted", return_value=True):
            res = await admin_create_wage_settlement(payload, self.admin)

        self.assertIsNotNone(res)
        # Finance transaction deducted actual payout: 36000 IDR
        txn_call = mock_db.finance_transactions.insert_one.call_args[0][0]
        self.assertEqual(txn_call["amount"], 36000.0)

        # Settlement document records both standard and actual payout and variance
        st_call = mock_db.wage_settlements.insert_one.call_args[0][0]
        self.assertEqual(st_call["payout_amount"], 36000.0)
        self.assertEqual(st_call["standard_payout_amount"], 35700.0)
        self.assertEqual(st_call["variance_idr"], 300.0)
        self.assertEqual(st_call["amount_le"], 100.0)

        # Obligation liability reduction remains strictly 100 LE
        ob_call = mock_db.wage_obligations.update_one.call_args[0][1]
        self.assertEqual(ob_call["$set"]["paid_amount_le"], 100.0)
        self.assertEqual(ob_call["$set"]["status"], "paid")

        # Audit log was created for payout variance
        variance_logs = [c for c in mock_db.audit_logs.insert_one.call_args_list if c[0][0].get("action") == "wage_settlement_payout_variance"]
        self.assertEqual(len(variance_logs), 1)
        self.assertEqual(variance_logs[0][0][0]["metadata"]["variance_idr"], 300.0)

    async def test_customized_actual_idr_payout_with_negative_variance(self):
        """Customized IDR nominal with negative variance (e.g. transfer fee deduction) validates negative variance, logs audit, and preserves exact LE liability."""
        mock_db = MagicMock()
        mock_db.admins.find_one = AsyncMock(return_value=self.worker)
        mock_db.wage_settlements.find_one = AsyncMock(return_value=None)

        ob_doc = {
            "_id": ObjectId("670868f123456789abcdef20"),
            "worker_id": "w_10",
            "obligation_number": "WOB-008",
            "total_amount_le": 100.0,
            "paid_amount_le": 0.0,
            "currency": "EGP",
            "status": "accrued",
            "locked_exchange_rate": 357.0,
        }
        find_ob_mock = MagicMock()
        find_ob_mock.sort.return_value.to_list = AsyncMock(return_value=[ob_doc])
        mock_db.wage_obligations.find.return_value = find_ob_mock

        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.employee_wages.insert_one = AsyncMock()
        mock_db.wage_settlements.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.wage_obligations.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        mock_db.audit_logs.insert_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 1})
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357})

        # Standard is 100 * 357 = 35700. Admin disburses 35500 (-200 variance due to bank transfer deduction)
        payload = WageSettlementCreateInput(
            worker_id="w_10",
            amount_le=100.0,
            payment_currency="IDR",
            payment_method="bank_transfer",
            actual_payout_amount=35500.0,
            notes="Potongan biaya administrasi transfer bank",
        )

        with patch("server.db", mock_db), \
             patch("server.client.start_session", AsyncMock(side_effect=pymongo.errors.ConfigurationError("Standalone"))), \
             patch("server.is_standalone_fallback_permitted", return_value=True):
            res = await admin_create_wage_settlement(payload, self.admin)

        self.assertIsNotNone(res)
        # Finance transaction deducted actual payout: 35500 IDR
        txn_call = mock_db.finance_transactions.insert_one.call_args[0][0]
        self.assertEqual(txn_call["amount"], 35500.0)
        self.assertEqual(txn_call["currency"], "IDR")
        self.assertEqual(txn_call["account"], "IDR")
        self.assertEqual(txn_call["category"], "Pekerja")

        # Settlement document records both standard and actual payout and variance
        st_call = mock_db.wage_settlements.insert_one.call_args[0][0]
        self.assertEqual(st_call["payout_amount"], 35500.0)
        self.assertEqual(st_call["standard_payout_amount"], 35700.0)
        self.assertEqual(st_call["variance_idr"], -200.0)
        self.assertEqual(st_call["amount_le"], 100.0)

        # Obligation liability reduction remains strictly 100 LE
        ob_call = mock_db.wage_obligations.update_one.call_args[0][1]
        self.assertEqual(ob_call["$set"]["paid_amount_le"], 100.0)
        self.assertEqual(ob_call["$set"]["status"], "paid")

        # Audit log was created for payout variance
        variance_logs = [c for c in mock_db.audit_logs.insert_one.call_args_list if c[0][0].get("action") == "wage_settlement_payout_variance"]
        self.assertEqual(len(variance_logs), 1)
        self.assertEqual(variance_logs[0][0][0]["metadata"]["variance_idr"], -200.0)
        self.assertEqual(variance_logs[0][0][0]["metadata"]["override_reason"], "Potongan biaya administrasi transfer bank")

    async def test_customized_actual_idr_payout_rejection_without_reason(self):
        """Customized IDR nominal with variance requires explanation (notes or override_reason)."""
        mock_db = MagicMock()
        mock_db.admins.find_one = AsyncMock(return_value=self.worker)
        mock_db.wage_settlements.find_one = AsyncMock(return_value=None)
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357})

        ob_doc = {
            "_id": ObjectId("670868f123456789abcdef1a"),
            "worker_id": "w_10",
            "total_amount_le": 100.0,
            "paid_amount_le": 0.0,
            "locked_exchange_rate": 357.0,
        }
        find_ob_mock = MagicMock()
        find_ob_mock.sort.return_value.to_list = AsyncMock(return_value=[ob_doc])
        mock_db.wage_obligations.find.return_value = find_ob_mock

        payload = WageSettlementCreateInput(
            worker_id="w_10",
            amount_le=100.0,
            payment_currency="IDR",
            actual_payout_amount=36000.0,  # Variance +300 without reason or notes
            notes="",
        )

        with patch("server.db", mock_db):
            with self.assertRaises(HTTPException) as ctx:
                await admin_create_wage_settlement(payload, self.admin)
            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("Alasan/keterangan wajib diisi", ctx.exception.detail)

    async def test_customized_actual_idr_payout_invalid_nominal_rejected(self):
        """Negative or non-finite actual IDR payout is rejected with HTTP 422."""
        mock_db = MagicMock()
        mock_db.admins.find_one = AsyncMock(return_value=self.worker)
        mock_db.wage_settlements.find_one = AsyncMock(return_value=None)
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357})

        ob_doc = {
            "_id": ObjectId("670868f123456789abcdef1b"),
            "worker_id": "w_10",
            "total_amount_le": 100.0,
            "paid_amount_le": 0.0,
            "locked_exchange_rate": 357.0,
        }
        find_ob_mock = MagicMock()
        find_ob_mock.sort.return_value.to_list = AsyncMock(return_value=[ob_doc])
        mock_db.wage_obligations.find.return_value = find_ob_mock

        payload = WageSettlementCreateInput(
            worker_id="w_10",
            amount_le=100.0,
            payment_currency="IDR",
            actual_payout_amount=-500.0,  # Negative nominal
            notes="Invalid test",
        )

        with patch("server.db", mock_db):
            with self.assertRaises(HTTPException) as ctx:
                await admin_create_wage_settlement(payload, self.admin)
            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("angka positif yang valid", ctx.exception.detail)

    async def test_duplicate_submission_with_idempotency_key_prevents_duplicate_settlement(self):
        """Duplicate request with same idempotency key returns existing settlement without duplicate expense."""
        mock_db = MagicMock()
        mock_db.admins.find_one = AsyncMock(return_value=self.worker)

        existing_settlement = {
            "_id": ObjectId("670868f123456789abcdef1c"),
            "settlement_number": "WST-202610-0010",
            "worker_id": "w_10",
            "amount_le": 100.0,
            "payment_method": "cash",
            "payout_currency": "EGP",
            "payout_amount": 100.0,
            "idempotency_key": "idem-key-12345",
            "status": "recorded",
        }
        mock_db.wage_settlements.find_one = AsyncMock(return_value=existing_settlement)

        payload = WageSettlementCreateInput(
            worker_id="w_10",
            amount_le=100.0,
            payment_currency="EGP",
            payment_method="cash",
            idempotency_key="idem-key-12345",
        )

        with patch("server.db", mock_db):
            res = await admin_create_wage_settlement(payload, self.admin)

        self.assertEqual(res["settlement_number"], "WST-202610-0010")
        # No new finance transactions or settlements inserted
        mock_db.finance_transactions.insert_one.assert_not_called()
        mock_db.wage_settlements.insert_one.assert_not_called()

    async def test_settlement_failure_compensating_rollback_leaves_consistent_state(self):
        """Failure during settlement (e.g. concurrency update conflict) triggers compensating cleanup."""
        mock_db = MagicMock()
        mock_db.admins.find_one = AsyncMock(return_value=self.worker)
        mock_db.wage_settlements.find_one = AsyncMock(return_value=None)

        ob_doc = {
            "_id": ObjectId("670868f123456789abcdef1d"),
            "worker_id": "w_10",
            "obligation_number": "WOB-007",
            "total_amount_le": 100.0,
            "paid_amount_le": 0.0,
            "currency": "EGP",
            "status": "accrued",
            "locked_exchange_rate": 357.0,
        }
        find_ob_mock = MagicMock()
        find_ob_mock.sort.return_value.to_list = AsyncMock(return_value=[ob_doc])
        mock_db.wage_obligations.find.return_value = find_ob_mock

        inserted_txn_id = ObjectId()
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=inserted_txn_id))
        mock_db.employee_wages.insert_one = AsyncMock()
        mock_db.wage_settlements.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.finance_transactions.update_one = AsyncMock()
        # Simulate optimistic concurrency conflict: modified_count == 0
        mock_db.wage_obligations.update_one = AsyncMock(return_value=MagicMock(modified_count=0))
        mock_db.finance_transactions.delete_one = AsyncMock()
        mock_db.employee_wages.delete_many = AsyncMock()
        mock_db.wage_settlements.delete_one = AsyncMock()
        mock_db.wage_obligations.update_many = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 1})
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357})

        payload = WageSettlementCreateInput(
            worker_id="w_10",
            amount_le=100.0,
            payment_currency="IDR",
            payment_method="bank_transfer",
        )

        with patch("server.db", mock_db), \
             patch("server.client.start_session", AsyncMock(side_effect=pymongo.errors.ConfigurationError("Standalone"))), \
             patch("server.is_standalone_fallback_permitted", return_value=True):
            with self.assertRaises(HTTPException) as ctx:
                await admin_create_wage_settlement(payload, self.admin)
            self.assertEqual(ctx.exception.status_code, 409)

        # Confirm compensating deletion was invoked
        mock_db.finance_transactions.delete_one.assert_called()
        mock_db.employee_wages.delete_many.assert_called()

    async def _call_settlement_asgi(self, payload_dict):
        """Dispatches an ASGI HTTP POST request to /api/admin/wages/settlements through FastAPI app."""
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/admin/wages/settlements",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 80),
        }
        body_bytes = json.dumps(payload_dict).encode("utf-8")
        messages = []

        async def receive():
            return {"type": "http.request", "body": body_bytes, "more_body": False}

        async def send(msg):
            messages.append(msg)

        await app(scope, receive, send)

        status = None
        body_chunks = []
        for m in messages:
            if m["type"] == "http.response.start":
                status = m["status"]
            elif m["type"] == "http.response.body":
                body_chunks.append(m.get("body", b""))
        body_str = b"".join(body_chunks).decode("utf-8")
        return status, body_str

    async def test_unauthorized_user_without_finance_role_rejected_at_endpoint(self):
        """Endpoint-level authorization test: Authenticated user without Finance or Owner permission is rejected with HTTP 403."""
        mock_db = MagicMock()
        unauthorized_admin = {
            "id": "emp_carpenter_1",
            "name": "Carpenter Non-Finance",
            "role": "employee",
            "permissions": {"access_finance": False, "manage_settings": False},
        }

        # Snapshot prior dependency overrides to maintain test isolation
        saved_overrides = dict(app.dependency_overrides)
        dummy_dep = lambda: "unrelated_dependency"
        app.dependency_overrides[dummy_dep] = lambda: "unrelated_value"

        try:
            app.dependency_overrides[get_current_admin] = lambda: unauthorized_admin
            with patch("server.db", mock_db):
                payload = {
                    "worker_id": "w_10",
                    "amount_le": 100.0,
                    "payment_currency": "IDR",
                    "settlement_rate": 357.0,
                }
                status, body_str = await self._call_settlement_asgi(payload)

            self.assertEqual(status, 403)
            self.assertIn("Akses ditolak: Membutuhkan akses keuangan atau owner", body_str)
            # Ensure zero persistence writes occurred
            mock_db.finance_transactions.insert_one.assert_not_called()
            mock_db.wage_settlements.insert_one.assert_not_called()
            mock_db.wage_obligations.update_one.assert_not_called()
            mock_db.employee_wages.insert_one.assert_not_called()

            # Isolation regression assertion: unrelated pre-existing overrides remain intact
            self.assertIn(dummy_dep, app.dependency_overrides)
            self.assertEqual(app.dependency_overrides[dummy_dep](), "unrelated_value")
        finally:
            # Restore previous state without clearing unrelated overrides
            app.dependency_overrides.clear()
            app.dependency_overrides.update(saved_overrides)

    async def test_unauthenticated_call_to_settlement_endpoint_rejected(self):
        """Endpoint-level authorization test: Unauthenticated request without token is rejected with HTTP 401."""
        mock_db = MagicMock()
        # Snapshot prior dependency overrides to maintain test isolation
        saved_overrides = dict(app.dependency_overrides)
        dummy_dep = lambda: "unrelated_unauth_dependency"
        app.dependency_overrides[dummy_dep] = lambda: "unrelated_unauth_value"

        try:
            # Remove only the auth override if present, preserving unrelated overrides
            app.dependency_overrides.pop(get_current_admin, None)
            with patch("server.db", mock_db):
                payload = {
                    "worker_id": "w_10",
                    "amount_le": 100.0,
                    "payment_currency": "EGP",
                }
                status, body_str = await self._call_settlement_asgi(payload)

            self.assertEqual(status, 401)
            self.assertIn("Tidak terautentikasi", body_str)
            # Ensure zero persistence writes occurred
            mock_db.finance_transactions.insert_one.assert_not_called()
            mock_db.wage_settlements.insert_one.assert_not_called()
            mock_db.wage_obligations.update_one.assert_not_called()
            mock_db.employee_wages.insert_one.assert_not_called()

            # Isolation regression assertion: unrelated pre-existing overrides remain intact
            self.assertIn(dummy_dep, app.dependency_overrides)
            self.assertEqual(app.dependency_overrides[dummy_dep](), "unrelated_unauth_value")
        finally:
            # Restore previous state without clearing unrelated overrides
            app.dependency_overrides.clear()
            app.dependency_overrides.update(saved_overrides)


class TestPhase1MapsRequirement(unittest.TestCase):
    """Verifies that Google Maps URLs are strictly validated and mandated for delivery orders
    while remaining optional for pickup orders.
    """

    def test_delivery_order_requires_maps_url(self):
        """Delivery order with empty maps URL is rejected with HTTP 400."""
        with self.assertRaises(HTTPException) as ctx:
            validate_and_normalize_maps_url("", "delivery")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Link Google Maps lokasi pengiriman wajib diisi", ctx.exception.detail)

        with self.assertRaises(HTTPException) as ctx2:
            validate_and_normalize_maps_url(None, "delivery")
        self.assertEqual(ctx2.exception.status_code, 400)

    def test_pickup_order_allows_empty_maps_url(self):
        """Pickup order with empty or omitted maps URL is valid and returns empty string."""
        self.assertEqual(validate_and_normalize_maps_url("", "pickup"), "")
        self.assertEqual(validate_and_normalize_maps_url(None, "pickup"), "")

    def test_valid_google_maps_urls_pass_and_normalize(self):
        """Valid Google Maps URLs with or without https:// pass and normalize."""
        # Shortlink without scheme gets auto-prefixed
        self.assertEqual(
            validate_and_normalize_maps_url("maps.app.goo.gl/xyz123", "delivery"),
            "https://maps.app.goo.gl/xyz123"
        )
        # Full URL with scheme passes
        self.assertEqual(
            validate_and_normalize_maps_url("https://www.google.com/maps/place/Cairo", "delivery"),
            "https://www.google.com/maps/place/Cairo"
        )
        # Query format passes
        self.assertEqual(
            validate_and_normalize_maps_url("https://maps.google.com/?q=30.0444,31.2357", "delivery"),
            "https://maps.google.com/?q=30.0444,31.2357"
        )

    def test_invalid_urls_rejected_for_both_delivery_and_pickup(self):
        """Non-Google URLs are rejected with HTTP 400."""
        with self.assertRaises(HTTPException) as ctx:
            validate_and_normalize_maps_url("https://example.com/not-maps", "delivery")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Link Maps harus berupa link Google Maps yang valid", ctx.exception.detail)

        with self.assertRaises(HTTPException) as ctx2:
            validate_and_normalize_maps_url("https://example.com/not-maps", "pickup")
        self.assertEqual(ctx2.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
