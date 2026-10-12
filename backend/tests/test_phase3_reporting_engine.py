"""Comprehensive automated test suite for Phase 3.B.7 — Reporting Engine & Metric Reconciliation.

Covers all required Phase 3.B.7 test scenarios with exact numeric assertions:
B7-TC-01: An active order with partial cash payment (advance vs. revenue).
B7-TC-02: An active order with overpayment and available customer credit.
B7-TC-03: A handed-over order with outstanding receivable.
B7-TC-04: Non-cash credit settlement applied to a second order (zero cash inflow).
B7-TC-05: Customer credit cash refund decreases cash and liability, not operating cost.
B7-TC-06: Legacy 'dp' order with unknown historical paid amount.
B7-TC-07: Positive and negative finance adjustments within the same period.
B7-TC-08: Handover in September, Adjustment created in October (OD-B7-01: period of created_at).
B7-TC-09: September historical report remains unchanged after October adjustment (no restatement).
B7-TC-10: Multiple adjustments and opposite-signed compensation adjustment.
B7-TC-11: Post-handover cancellation preserves immutable revenue snapshot in completed period.
B7-TC-12: Voided payments and voided finance transactions excluded from all metrics.
B7-TC-13: Non-sales income separated from furniture sales revenue (Owner Decision A).
B7-TC-14: Operating expenses exclude liability settlements and credit refunds.
B7-TC-15: Strict EGP and IDR currency isolation (no cross-currency summing).
B7-TC-16: Zero duplicate counting across payments, allocations, finance transactions, and credit events.
B7-TC-17: Legacy 'order_revenue' cash compatibility without premature revenue recognition.
B7-TC-18: Empty period queries return zero balances and clean metrics without errors.
B7-TC-19: Cutoff-based point-in-time ending balances (as_of) ignore future transactions.
B7-TC-20: Internal account transfer correctly reflects cash movement between accounts.
"""

import asyncio
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId

from server import (
    _stats_for,
    _compute_balances,
    finance_stats,
)


class TestPhase3B7ReportingEngine(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.admin_finance = {
            "id": "admin_fin_01",
            "name": "Finance Head",
            "role": "admin",
            "permissions": {"access_finance": True},
        }

    def _setup_mock_db(self, mock_db):
        """Sets up default empty collections for db mocks."""
        mock_find_txns = MagicMock()
        mock_find_txns.to_list = AsyncMock(return_value=[])
        mock_db.finance_transactions.find.return_value = mock_find_txns

        mock_find_orders = MagicMock()
        mock_find_orders.to_list = AsyncMock(return_value=[])
        mock_db.orders.find.return_value = mock_find_orders

        mock_find_adjs = MagicMock()
        mock_find_adjs.to_list = AsyncMock(return_value=[])
        mock_db.finance_adjustments.find.return_value = mock_find_adjs

        mock_find_cce = MagicMock()
        mock_find_cce.to_list = AsyncMock(return_value=[])
        mock_db.customer_credit_events.find.return_value = mock_find_cce

        mock_find_pmts = MagicMock()
        mock_find_pmts.to_list = AsyncMock(return_value=[])
        mock_db.payments.find.return_value = mock_find_pmts

    # -------------------------------------------------------------------------
    # Scenario 1: Active order with partial cash payment
    # -------------------------------------------------------------------------
    async def test_b7_tc01_active_order_partial_cash_payment(self):
        """Active order (status='diproses') with partial cash payment increases customer advances, not sales revenue."""
        mock_db = MagicMock()
        order_id = "670868f123456789abcdef01"

        txns = [
            {"type": "order_payment", "account": "EGP", "currency": "EGP", "amount": 1200.0, "is_void": False, "status": "recorded", "date": "2026-10-05T10:00:00Z"}
        ]
        orders = [
            {"_id": ObjectId(order_id), "order_number": "SO-001", "order_status": "diproses", "total_le": 3000.0}
        ]
        pmts = [
            {"order_id": order_id, "amount_le": 1200.0, "status": "recorded"}
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

        egp = stats["EGP"]
        self.assertEqual(egp["real_cash_inflow"], 1200.0)
        self.assertEqual(egp["sales_revenue"], 0.0)  # NOT recognized yet
        self.assertEqual(egp["customer_advances"], 1200.0)  # Deposit liability
        self.assertEqual(egp["accounts_receivable"], 0.0)
        self.assertEqual(egp["cash_flow"], 1200.0)

    # -------------------------------------------------------------------------
    # Scenario 2: Active order with overpayment and available credit
    # -------------------------------------------------------------------------
    async def test_b7_tc02_active_order_with_overpayment_and_credit(self):
        """Overpayment (5000 LE on 3000 LE order): cash=5000, advances=3000 (order paid), credit=2000, revenue=0."""
        mock_db = MagicMock()
        order_id = "670868f123456789abcdef02"

        txns = [
            {"type": "order_payment", "account": "EGP", "currency": "EGP", "amount": 5000.0, "is_void": False, "status": "recorded", "date": "2026-10-05T10:00:00Z"}
        ]
        orders = [
            {"_id": ObjectId(order_id), "order_number": "SO-002", "order_status": "diproses", "total_le": 3000.0}
        ]
        pmts = [
            {"order_id": order_id, "amount_le": 3000.0, "status": "recorded"}
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
        # Aggregate returns 2000 available credit
        mock_db.customer_credit_events.aggregate.return_value.to_list = AsyncMock(return_value=[{"total": 2000.0}])

        with patch("server.db", mock_db):
            stats = await _stats_for("2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z")

        egp = stats["EGP"]
        self.assertEqual(egp["real_cash_inflow"], 5000.0)
        self.assertEqual(egp["customer_advances"], 3000.0)
        self.assertEqual(egp["available_customer_credit"], 2000.0)
        self.assertEqual(egp["sales_revenue"], 0.0)

    # -------------------------------------------------------------------------
    # Scenario 3: Handed-over order with outstanding receivable
    # -------------------------------------------------------------------------
    async def test_b7_tc03_handed_over_order_with_receivable(self):
        """Order handed over (recognized 4000 LE) with 1500 LE paid produces 2500 LE receivable."""
        mock_db = MagicMock()
        order_id = "670868f123456789abcdef03"

        txns = [
            {"type": "order_payment", "account": "EGP", "currency": "EGP", "amount": 1500.0, "is_void": False, "status": "recorded", "date": "2026-10-02T10:00:00Z"}
        ]
        orders = [
            {
                "_id": ObjectId(order_id),
                "order_number": "SO-003",
                "order_status": "selesai",
                "completed_at": "2026-10-10T12:00:00Z",
                "recognized_revenue_le": 4000.0,
                "total_le": 4000.0
            }
        ]
        pmts = [
            {"order_id": order_id, "amount_le": 1500.0, "status": "recorded"}
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

        egp = stats["EGP"]
        self.assertEqual(egp["sales_revenue"], 4000.0)
        self.assertEqual(egp["real_cash_inflow"], 1500.0)
        self.assertEqual(egp["accounts_receivable"], 2500.0)
        self.assertEqual(egp["customer_advances"], 0.0)

    # -------------------------------------------------------------------------
    # Scenario 4: Non-cash credit settlement applied to a second order
    # -------------------------------------------------------------------------
    async def test_b7_tc04_non_cash_credit_settlement(self):
        """Credit settlement (payment_method='customer_credit') yields 0.00 cash inflow and discharges receivable."""
        mock_db = MagicMock()
        order_id = "670868f123456789abcdef04"

        txns = [
            {"type": "credit_settlement", "classification": "credit_settlement", "account": "EGP", "amount": 1000.0, "is_void": False, "status": "recorded", "date": "2026-10-12T10:00:00Z"}
        ]
        orders = [
            {
                "_id": ObjectId(order_id),
                "order_number": "SO-004",
                "order_status": "selesai",
                "completed_at": "2026-10-10T12:00:00Z",
                "recognized_revenue_le": 1000.0,
                "total_le": 1000.0
            }
        ]
        pmts = [
            {"order_id": order_id, "amount_le": 1000.0, "payment_method": "customer_credit", "status": "recorded"}
        ]
        cc_events = [
            {"event_type": "credit_applied", "currency": "EGP", "signed_amount": -1000.0, "created_at": "2026-10-12T10:00:00Z"}
        ]

        async def gen_txns(*args, **kwargs):
            for t in txns: yield t
        async def gen_orders(*args, **kwargs):
            for o in orders: yield o
        async def gen_pmts(*args, **kwargs):
            for p in pmts: yield p
        async def gen_cce(*args, **kwargs):
            for c in cc_events: yield c
        async def gen_empty(*args, **kwargs):
            if False: yield {}

        mock_db.finance_transactions.find = gen_txns
        mock_db.orders.find = gen_orders
        mock_db.payments.find = gen_pmts
        mock_db.customer_credit_events.find = gen_cce
        mock_db.finance_adjustments.find = gen_empty
        mock_db.customer_credit_events.aggregate.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db):
            stats = await _stats_for("2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z")

        egp = stats["EGP"]
        self.assertEqual(egp["real_cash_inflow"], 0.0)  # ZERO cash movement
        self.assertEqual(egp["credit_applied"], 1000.0)  # Tracked in credit consumption
        self.assertEqual(egp["sales_revenue"], 1000.0)
        self.assertEqual(egp["accounts_receivable"], 0.0)  # Fully settled by credit

    # -------------------------------------------------------------------------
    # Scenario 5: Customer credit cash refund
    # -------------------------------------------------------------------------
    async def test_b7_tc05_customer_credit_cash_refund(self):
        """Credit refund is a cash outflow that extinguishes liability; operating cost is strictly 0.00."""
        mock_db = MagicMock()
        txns = [
            {"type": "refund", "classification": "liability_settlement", "account": "EGP", "amount": 500.0, "is_void": False, "status": "recorded", "date": "2026-10-15T10:00:00Z"}
        ]
        cce = [
            {"event_type": "credit_refunded", "currency": "EGP", "signed_amount": -500.0, "created_at": "2026-10-15T10:00:00Z"}
        ]

        async def gen_txns(*args, **kwargs):
            for t in txns: yield t
        async def gen_cce(*args, **kwargs):
            for c in cce: yield c
        async def gen_empty(*args, **kwargs):
            if False: yield {}

        mock_db.finance_transactions.find = gen_txns
        mock_db.customer_credit_events.find = gen_cce
        mock_db.orders.find = gen_empty
        mock_db.payments.find = gen_empty
        mock_db.finance_adjustments.find = gen_empty
        mock_db.customer_credit_events.aggregate.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db):
            stats = await _stats_for("2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z")

        egp = stats["EGP"]
        self.assertEqual(egp["real_cash_outflow"], 500.0)
        self.assertEqual(egp["credit_refunded"], 500.0)
        self.assertEqual(egp["operating_cost"], 0.0)  # NOT an expense
        self.assertEqual(egp["cash_flow"], -500.0)

    # -------------------------------------------------------------------------
    # Scenario 6: Legacy dp order with unknown historical paid amount
    # -------------------------------------------------------------------------
    async def test_b7_tc06_legacy_dp_order_with_unknown_payments(self):
        """Legacy order marked 'dp' with 0 recorded payments does not synthesize advances or credits."""
        mock_db = MagicMock()
        orders = [
            {"_id": ObjectId("670868f123456789abcdef06"), "order_number": "SO-LEGACY-01", "order_status": "diproses", "payment_status": "dp", "total_le": 2000.0}
        ]

        async def gen_orders(*args, **kwargs):
            for o in orders: yield o
        async def gen_empty(*args, **kwargs):
            if False: yield {}

        mock_db.orders.find = gen_orders
        mock_db.finance_transactions.find = gen_empty
        mock_db.payments.find = gen_empty
        mock_db.finance_adjustments.find = gen_empty
        mock_db.customer_credit_events.find = gen_empty
        mock_db.customer_credit_events.aggregate.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db):
            stats = await _stats_for("2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z")

        egp = stats["EGP"]
        self.assertEqual(egp["customer_advances"], 0.0)  # No synthetic payment doc
        self.assertEqual(egp["sales_revenue"], 0.0)

    # -------------------------------------------------------------------------
    # Scenario 7: Positive and negative finance adjustments
    # -------------------------------------------------------------------------
    async def test_b7_tc07_positive_and_negative_finance_adjustments(self):
        """Positive (+300) and negative (-100) adjustments in period apply algebraically to sales revenue."""
        mock_db = MagicMock()
        adjs = [
            {"amount": 300.0, "currency": "EGP", "is_void": False, "created_at": "2026-10-11T10:00:00Z"},
            {"amount": -100.0, "currency": "EGP", "is_void": False, "created_at": "2026-10-12T10:00:00Z"},
        ]

        async def gen_adjs(*args, **kwargs):
            for a in adjs: yield a
        async def gen_empty(*args, **kwargs):
            if False: yield {}

        mock_db.finance_adjustments.find = gen_adjs
        mock_db.finance_transactions.find = gen_empty
        mock_db.orders.find = gen_empty
        mock_db.payments.find = gen_empty
        mock_db.customer_credit_events.find = gen_empty
        mock_db.customer_credit_events.aggregate.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db):
            stats = await _stats_for("2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z")

        egp = stats["EGP"]
        self.assertEqual(egp["sales_revenue"], 200.0)

    # -------------------------------------------------------------------------
    # Scenario 8 & 9: Handover in September, Adjustment in October (OD-B7-01: No Restatement)
    # -------------------------------------------------------------------------
    async def test_b7_tc08_09_handover_september_adjustment_october_no_restatement(self):
        """Handover on Sep 20 (5000 LE) and adjustment on Oct 10 (-500 LE): Sep is 5000, Oct is -500."""
        mock_db = MagicMock()
        order_id = "670868f123456789abcdef08"
        orders = [
            {
                "_id": ObjectId(order_id),
                "order_number": "SO-008",
                "order_status": "selesai",
                "completed_at": "2026-09-20T12:00:00Z",
                "recognized_revenue_le": 5000.0
            }
        ]
        adjs = [
            {
                "order_id": order_id,
                "amount": -500.0,
                "currency": "EGP",
                "is_void": False,
                "created_at": "2026-10-10T12:00:00Z"
            }
        ]

        async def gen_orders(q, *args, **kwargs):
            c_filter = q.get("completed_at", {})
            gte = c_filter.get("$gte")
            lte = c_filter.get("$lte")
            for o in orders:
                if gte and o["completed_at"] < gte:
                    continue
                if lte and o["completed_at"] > lte:
                    continue
                yield o

        async def gen_adjs(q, *args, **kwargs):
            c_filter = q.get("created_at", {})
            gte = c_filter.get("$gte")
            lte = c_filter.get("$lte")
            for a in adjs:
                if gte and a["created_at"] < gte:
                    continue
                if lte and a["created_at"] > lte:
                    continue
                yield a

        async def gen_empty(*args, **kwargs):
            if False: yield {}

        mock_db.orders.find = gen_orders
        mock_db.finance_adjustments.find = gen_adjs
        mock_db.finance_transactions.find = gen_empty
        mock_db.payments.find = gen_empty
        mock_db.customer_credit_events.find = gen_empty
        mock_db.customer_credit_events.aggregate.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db):
            # Query September period
            stats_sep = await _stats_for("2026-09-01T00:00:00Z", "2026-09-30T23:59:59Z")
            # Query October period
            stats_oct = await _stats_for("2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z")

        # September retained its 5000 LE snapshot (no restatement!)
        self.assertEqual(stats_sep["EGP"]["sales_revenue"], 5000.0)
        # October reports the -500 LE adjustment
        self.assertEqual(stats_oct["EGP"]["sales_revenue"], -500.0)

    # -------------------------------------------------------------------------
    # Scenario 10: Multiple adjustments and opposite-signed compensation
    # -------------------------------------------------------------------------
    async def test_b7_tc10_compensating_adjustments(self):
        """Adjustment of -400 compensated by +400 nets to 0.00."""
        mock_db = MagicMock()
        adjs = [
            {"amount": -400.0, "currency": "EGP", "is_void": False, "created_at": "2026-10-05T10:00:00Z"},
            {"amount": 400.0, "currency": "EGP", "is_void": False, "created_at": "2026-10-06T10:00:00Z"},
        ]

        async def gen_adjs(*args, **kwargs):
            for a in adjs: yield a
        async def gen_empty(*args, **kwargs):
            if False: yield {}

        mock_db.finance_adjustments.find = gen_adjs
        mock_db.finance_transactions.find = gen_empty
        mock_db.orders.find = gen_empty
        mock_db.payments.find = gen_empty
        mock_db.customer_credit_events.find = gen_empty
        mock_db.customer_credit_events.aggregate.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db):
            stats = await _stats_for("2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z")

        self.assertEqual(stats["EGP"]["sales_revenue"], 0.0)

    # -------------------------------------------------------------------------
    # Scenario 11: Post-handover cancellation preserves revenue snapshot
    # -------------------------------------------------------------------------
    async def test_b7_tc11_cancellation_preserves_revenue_snapshot(self):
        """Order handed over in period then cancelled (status='dibatalkan') still retains recognized_revenue_le."""
        mock_db = MagicMock()
        orders = [
            {
                "_id": ObjectId("670868f123456789abcdef11"),
                "order_number": "SO-011",
                "order_status": "dibatalkan",
                "completed_at": "2026-10-05T12:00:00Z",
                "recognized_revenue_le": 2800.0
            }
        ]

        async def gen_orders(*args, **kwargs):
            for o in orders: yield o
        async def gen_empty(*args, **kwargs):
            if False: yield {}

        mock_db.orders.find = gen_orders
        mock_db.finance_transactions.find = gen_empty
        mock_db.payments.find = gen_empty
        mock_db.finance_adjustments.find = gen_empty
        mock_db.customer_credit_events.find = gen_empty
        mock_db.customer_credit_events.aggregate.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db):
            stats = await _stats_for("2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z")

        self.assertEqual(stats["EGP"]["sales_revenue"], 2800.0)

    # -------------------------------------------------------------------------
    # Scenario 12: Voided payments and voided transactions excluded
    # -------------------------------------------------------------------------
    async def test_b7_tc12_voided_records_excluded(self):
        """Voided transactions (is_void=True) and voided payments (status='voided') are excluded."""
        mock_db = MagicMock()
        order_id = "670868f123456789abcdef12"

        txns = [
            {"type": "order_payment", "amount": 1000.0, "is_void": True, "status": "void", "account": "EGP", "date": "2026-10-05T10:00:00Z"},
            {"type": "income", "amount": 500.0, "is_void": True, "status": "void", "account": "EGP", "date": "2026-10-05T10:00:00Z"},
        ]
        pmts = [
            {"order_id": order_id, "amount_le": 1000.0, "status": "voided"}
        ]
        orders = [
            {"_id": ObjectId(order_id), "order_status": "diproses", "total_le": 2000.0}
        ]

        async def gen_txns(*args, **kwargs):
            # Simulate mongo query filter: is_void != True
            for t in txns:
                if not t.get("is_void"): yield t
        async def gen_orders(*args, **kwargs):
            for o in orders: yield o
        async def gen_pmts(*args, **kwargs):
            for p in pmts:
                if p.get("status") == "recorded": yield p
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

        egp = stats["EGP"]
        self.assertEqual(egp["real_cash_inflow"], 0.0)
        self.assertEqual(egp["other_income"], 0.0)
        self.assertEqual(egp["customer_advances"], 0.0)

    # -------------------------------------------------------------------------
    # Scenario 13: Non-sales income separated from sales revenue (Owner Decision A)
    # -------------------------------------------------------------------------
    async def test_b7_tc13_non_sales_income_separated_from_sales_revenue(self):
        """Arbitrary non-sales income is placed in other_income; strictly excluded from sales_revenue."""
        mock_db = MagicMock()
        txns = [
            {"type": "income", "classification": "revenue", "account": "EGP", "amount": 750.0, "is_void": False, "status": "recorded", "date": "2026-10-08T10:00:00Z"}
        ]

        async def gen_txns(*args, **kwargs):
            for t in txns: yield t
        async def gen_empty(*args, **kwargs):
            if False: yield {}

        mock_db.finance_transactions.find = gen_txns
        mock_db.orders.find = gen_empty
        mock_db.payments.find = gen_empty
        mock_db.finance_adjustments.find = gen_empty
        mock_db.customer_credit_events.find = gen_empty
        mock_db.customer_credit_events.aggregate.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db):
            stats = await _stats_for("2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z")

        egp = stats["EGP"]
        self.assertEqual(egp["sales_revenue"], 0.0)  # Pure sales revenue is 0
        self.assertEqual(egp["other_income"], 750.0)  # Captured in other_income
        self.assertEqual(egp["total_revenue"], 750.0)

    # -------------------------------------------------------------------------
    # Scenario 14: Operating expenses excluding liability settlements
    # -------------------------------------------------------------------------
    async def test_b7_tc14_operating_expenses_exclude_liability_settlement(self):
        """Operational expense of 400 LE is cost; credit refund of 200 LE is cash outflow, not cost."""
        mock_db = MagicMock()
        txns = [
            {"type": "expense", "classification": "cost", "account": "EGP", "amount": 400.0, "is_void": False, "status": "recorded", "date": "2026-10-09T10:00:00Z"},
            {"type": "refund", "classification": "liability_settlement", "account": "EGP", "amount": 200.0, "is_void": False, "status": "recorded", "date": "2026-10-09T11:00:00Z"},
        ]

        async def gen_txns(*args, **kwargs):
            for t in txns: yield t
        async def gen_empty(*args, **kwargs):
            if False: yield {}

        mock_db.finance_transactions.find = gen_txns
        mock_db.orders.find = gen_empty
        mock_db.payments.find = gen_empty
        mock_db.finance_adjustments.find = gen_empty
        mock_db.customer_credit_events.find = gen_empty
        mock_db.customer_credit_events.aggregate.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db):
            stats = await _stats_for("2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z")

        egp = stats["EGP"]
        self.assertEqual(egp["operating_cost"], 400.0)  # Only the operational cost
        self.assertEqual(egp["real_cash_outflow"], 600.0)  # Both cash outflows
        self.assertEqual(egp["cash_flow"], -600.0)

    # -------------------------------------------------------------------------
    # Scenario 15: Strict EGP and IDR currency isolation
    # -------------------------------------------------------------------------
    async def test_b7_tc15_strict_currency_isolation(self):
        """EGP transactions and IDR transactions populate their respective buckets with zero cross-leakage."""
        mock_db = MagicMock()
        txns = [
            {"type": "order_payment", "account": "EGP", "currency": "EGP", "amount": 1000.0, "is_void": False, "status": "recorded", "date": "2026-10-05T10:00:00Z"},
            {"type": "income", "account": "IDR", "currency": "IDR", "amount": 5000000.0, "is_void": False, "status": "recorded", "date": "2026-10-05T10:00:00Z"},
        ]

        async def gen_txns(*args, **kwargs):
            for t in txns: yield t
        async def gen_empty(*args, **kwargs):
            if False: yield {}

        mock_db.finance_transactions.find = gen_txns
        mock_db.orders.find = gen_empty
        mock_db.payments.find = gen_empty
        mock_db.finance_adjustments.find = gen_empty
        mock_db.customer_credit_events.find = gen_empty
        mock_db.customer_credit_events.aggregate.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db):
            stats = await _stats_for("2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z")

        self.assertEqual(stats["EGP"]["real_cash_inflow"], 1000.0)
        self.assertEqual(stats["EGP"]["other_income"], 0.0)

        self.assertEqual(stats["IDR"]["real_cash_inflow"], 5000000.0)
        self.assertEqual(stats["IDR"]["other_income"], 5000000.0)

    # -------------------------------------------------------------------------
    # Scenario 16: Zero duplicate counting across collections
    # -------------------------------------------------------------------------
    async def test_b7_tc16_no_duplicate_counting_across_collections(self):
        """Cash receipt, credit minting, and credit settlement on order 1 do not inflate metrics."""
        mock_db = MagicMock()
        order_id = "670868f123456789abcdef16"

        txns = [
            # Cash payment 2000
            {"type": "order_payment", "account": "EGP", "currency": "EGP", "amount": 2000.0, "is_void": False, "status": "recorded", "date": "2026-10-01T10:00:00Z"},
            # Non-cash credit settlement 500
            {"type": "credit_settlement", "account": "EGP", "currency": "EGP", "amount": 500.0, "is_void": False, "status": "recorded", "date": "2026-10-02T10:00:00Z"},
        ]
        orders = [
            {
                "_id": ObjectId(order_id),
                "order_number": "SO-016",
                "order_status": "selesai",
                "completed_at": "2026-10-05T12:00:00Z",
                "recognized_revenue_le": 2500.0
            }
        ]
        pmts = [
            {"order_id": order_id, "amount_le": 2000.0, "payment_method": "cash", "status": "recorded"},
            {"order_id": order_id, "amount_le": 500.0, "payment_method": "customer_credit", "status": "recorded"},
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

        egp = stats["EGP"]
        self.assertEqual(egp["real_cash_inflow"], 2000.0)  # Only the real cash payment
        self.assertEqual(egp["sales_revenue"], 2500.0)  # Full handover snapshot
        self.assertEqual(egp["accounts_receivable"], 0.0)  # 2500 recognized - 2500 discharged = 0

    # -------------------------------------------------------------------------
    # Scenario 17: Legacy order_revenue cash compatibility without premature revenue
    # -------------------------------------------------------------------------
    async def test_b7_tc17_legacy_order_revenue_cash_compatibility(self):
        """Historical order_revenue records count toward real_cash_inflow and legacy revenue alias."""
        mock_db = MagicMock()
        txns = [
            {"type": "order_revenue", "account": "EGP", "currency": "EGP", "amount": 1800.0, "is_void": False, "status": "recorded", "date": "2026-10-03T10:00:00Z"}
        ]

        async def gen_txns(*args, **kwargs):
            for t in txns: yield t
        async def gen_empty(*args, **kwargs):
            if False: yield {}

        mock_db.finance_transactions.find = gen_txns
        mock_db.orders.find = gen_empty
        mock_db.payments.find = gen_empty
        mock_db.finance_adjustments.find = gen_empty
        mock_db.customer_credit_events.find = gen_empty
        mock_db.customer_credit_events.aggregate.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db):
            stats = await _stats_for("2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z")

        egp = stats["EGP"]
        self.assertEqual(egp["real_cash_inflow"], 1800.0)
        self.assertEqual(egp["sales_revenue"], 0.0)  # Pure Phase 3 sales revenue is 0
        self.assertEqual(egp["revenue"], 1800.0)  # Backward compatibility alias preserved

    # -------------------------------------------------------------------------
    # Scenario 18: Empty periods and boundary cases
    # -------------------------------------------------------------------------
    async def test_b7_tc18_empty_period_returns_clean_zero_metrics(self):
        """Empty period returns 0.0 for all numeric metrics without exceptions or division errors."""
        mock_db = MagicMock()
        async def gen_empty(*args, **kwargs):
            if False: yield {}

        mock_db.finance_transactions.find = gen_empty
        mock_db.orders.find = gen_empty
        mock_db.payments.find = gen_empty
        mock_db.finance_adjustments.find = gen_empty
        mock_db.customer_credit_events.find = gen_empty
        mock_db.customer_credit_events.aggregate.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db):
            stats = await _stats_for("2026-11-01T00:00:00Z", "2026-11-30T23:59:59Z")

        for cur in ("EGP", "IDR"):
            self.assertEqual(stats[cur]["real_cash_inflow"], 0.0)
            self.assertEqual(stats[cur]["real_cash_outflow"], 0.0)
            self.assertEqual(stats[cur]["cash_flow"], 0.0)
            self.assertEqual(stats[cur]["sales_revenue"], 0.0)
            self.assertEqual(stats[cur]["operating_cost"], 0.0)
            self.assertEqual(stats[cur]["operating_profit"], 0.0)
            self.assertEqual(stats[cur]["accounts_receivable"], 0.0)

    # -------------------------------------------------------------------------
    # Scenario 19: Cutoff-based point-in-time ending balances (as_of)
    # -------------------------------------------------------------------------
    async def test_b7_tc19_as_of_cutoff_ending_balances(self):
        """_compute_balances with as_of cutoff ignores future transactions."""
        mock_db = MagicMock()
        txns = [
            {"type": "order_revenue", "account": "EGP", "amount": 1000.0, "date": "2026-09-15T10:00:00Z"},
            {"type": "order_revenue", "account": "EGP", "amount": 2000.0, "date": "2026-10-15T10:00:00Z"},
        ]

        async def gen_txns(q, *args, **kwargs):
            date_filter = q.get("date", {})
            lte = date_filter.get("$lte")
            for t in txns:
                if lte and t["date"] > lte:
                    continue
                yield t

        mock_db.finance_transactions.find = gen_txns

        with patch("server.db", mock_db):
            # As of end of September
            bal_sep = await _compute_balances(as_of="2026-09-30T23:59:59Z")
            # As of end of October
            bal_oct = await _compute_balances(as_of="2026-10-31T23:59:59Z")

        self.assertEqual(bal_sep["EGP"], 1000.0)
        self.assertEqual(bal_oct["EGP"], 3000.0)

    # -------------------------------------------------------------------------
    # Scenario 20: Internal account transfer cash movements
    # -------------------------------------------------------------------------
    async def test_b7_tc20_internal_transfer_cash_movement(self):
        """Transfer from IDR to EGP reflects cash outflow in IDR and cash inflow in EGP."""
        mock_db = MagicMock()
        txns = [
            {
                "type": "transfer",
                "from_account": "IDR",
                "to_account": "EGP",
                "from_amount": 357000.0,
                "to_amount": 1000.0,
                "is_void": False,
                "status": "recorded",
                "date": "2026-10-10T10:00:00Z"
            }
        ]

        async def gen_txns(*args, **kwargs):
            for t in txns: yield t
        async def gen_empty(*args, **kwargs):
            if False: yield {}

        mock_db.finance_transactions.find = gen_txns
        mock_db.orders.find = gen_empty
        mock_db.payments.find = gen_empty
        mock_db.finance_adjustments.find = gen_empty
        mock_db.customer_credit_events.find = gen_empty
        mock_db.customer_credit_events.aggregate.return_value.to_list = AsyncMock(return_value=[])

        with patch("server.db", mock_db):
            stats = await _stats_for("2026-10-01T00:00:00Z", "2026-10-31T23:59:59Z")

        self.assertEqual(stats["IDR"]["real_cash_outflow"], 357000.0)
        self.assertEqual(stats["IDR"]["cash_flow"], -357000.0)

        self.assertEqual(stats["EGP"]["real_cash_inflow"], 1000.0)
        self.assertEqual(stats["EGP"]["cash_flow"], 1000.0)


if __name__ == "__main__":
    unittest.main()
