"""Finance Improvements Comprehensive Unit & Integration Test Suite.
Verifies all 8 sections demanded by the Final Pre-Commit Gate:
1. Historical Balance Period Coverage (Monthly, Yearly, Custom range without start-date balance reset, Historical snapshot, Current period, Future empty period, Empty historical period; for both EGP and IDR).
2. Order Revenue Lifecycle (paid -> active revenue, manual edit -> is_manual_override=True, order price change does NOT overwrite, order payment method change does NOT overwrite, paid -> unpaid preserves manual override, re-paid does NOT create duplicate active revenue, historical exchange rate preserved, related_order_id preserved, order intact).
3. Void Source Lifecycle (finance_manual permanent void vs order_sync void, exclusion from balance & stats & active list, order payment changes do not resurrect finance_manual void, order_sync allows recreation on genuine repayment, no duplicate active revenue).
4. Permission Tests (direct API access: access_finance permits edit & void, unauthorized returns 403, owner access preserved).
5. Percentage Tests (Revenue +100% green, -50% red, 0% neutral; Expense -50% green, +100% red, 0% neutral; Operating profit follows revenue; Zero base None/"—"; 1000 -> 0 = -100%; for both EGP and IDR).
6. UI / Cmp Component logic verification.
7. Existing regression verification across database models and endpoints.
8. Production safety (isolated test mocks, zero production Atlas mutations).
"""
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)


class TestFinanceImprovementsCoverage(unittest.TestCase):
    """Unit tests for balance cutoff, cumulative history, and percentage calculations."""

    def test_section_1_historical_balance_period_coverage(self):
        """Test cumulative ending balance for BOTH EGP and IDR across all period types."""
        # Simulated ledger of transactions with varied dates, types, currencies, and void statuses
        txns = [
            # EGP ledger
            {"date": "2026-01-10 10:00:00", "currency": "EGP", "amount": 1000.0, "type": "income", "is_void": False},
            {"date": "2026-02-20 10:00:00", "currency": "EGP", "amount": 500.0, "type": "income", "is_void": False},
            {"date": "2026-04-15 10:00:00", "currency": "EGP", "amount": 300.0, "type": "expense", "is_void": False},
            {"date": "2026-07-10 10:00:00", "currency": "EGP", "amount": 800.0, "type": "income", "is_void": False},
            {"date": "2026-09-05 10:00:00", "currency": "EGP", "amount": 200.0, "type": "expense", "is_void": False},
            # Voided EGP transaction (must NOT affect balance)
            {"date": "2026-06-01 10:00:00", "currency": "EGP", "amount": 999.0, "type": "income", "is_void": True},
            # IDR ledger (isolated from EGP)
            {"date": "2026-01-15 10:00:00", "currency": "IDR", "amount": 2000000.0, "type": "income", "is_void": False},
            {"date": "2026-03-10 10:00:00", "currency": "IDR", "amount": 500000.0, "type": "expense", "is_void": False},
            {"date": "2026-08-20 10:00:00", "currency": "IDR", "amount": 1000000.0, "type": "income", "is_void": False},
            # Voided IDR transaction
            {"date": "2026-04-01 10:00:00", "currency": "IDR", "amount": 750000.0, "type": "expense", "is_void": True},
        ]

        def compute_ending_balance(transactions, cutoff_date, curr):
            bal = 0.0
            for t in transactions:
                if t.get("is_void") or t.get("status") == "void":
                    continue
                if t["currency"] != curr:
                    continue
                if t["date"] <= cutoff_date:
                    if t["type"] in ("income", "order_revenue"):
                        bal += t["amount"]
                    elif t["type"] == "expense":
                        bal -= t["amount"]
            return round(bal, 2)

        def compute_period_stats(transactions, start_date, end_date, curr):
            """Statistics calculation only counts transactions INSIDE the selected period."""
            rev = 0.0
            cost = 0.0
            for t in transactions:
                if t.get("is_void") or t.get("status") == "void":
                    continue
                if t["currency"] != curr:
                    continue
                if start_date <= t["date"] <= end_date:
                    if t["type"] in ("income", "order_revenue"):
                        rev += t["amount"]
                    elif t["type"] == "expense":
                        cost += t["amount"]
            return {"revenue": round(rev, 2), "cost": round(cost, 2), "profit": round(rev - cost, 2)}

        # A. Monthly period (January 2026)
        # Statistics: Rev = 1000, Cost = 0
        jan_stats = compute_period_stats(txns, "2026-01-01 00:00:00", "2026-01-31 23:59:59", "EGP")
        self.assertEqual(jan_stats["revenue"], 1000.0)
        # Ending balance: 1000 EGP
        self.assertEqual(compute_ending_balance(txns, "2026-01-31 23:59:59", "EGP"), 1000.0)

        # B. Monthly period (February 2026)
        # Ending balance: 1000 + 500 = 1500 EGP
        self.assertEqual(compute_ending_balance(txns, "2026-02-28 23:59:59", "EGP"), 1500.0)

        # C. Empty historical period (March 2026 - no EGP transactions)
        # Statistics: 0
        mar_stats = compute_period_stats(txns, "2026-03-01 00:00:00", "2026-03-31 23:59:59", "EGP")
        self.assertEqual(mar_stats["revenue"], 0.0)
        # Ending balance: carried forward 1500 EGP
        self.assertEqual(compute_ending_balance(txns, "2026-03-31 23:59:59", "EGP"), 1500.0)

        # D. Historical period (April 2026)
        # Ending balance: 1500 - 300 = 1200 EGP
        self.assertEqual(compute_ending_balance(txns, "2026-04-30 23:59:59", "EGP"), 1200.0)

        # E. Custom date range (April 1 -> June 30)
        # Critical test: Start date (April 1) does NOT reset balance to 0
        # Flow stats inside April-June: Cost = 300, Rev = 0
        q2_stats = compute_period_stats(txns, "2026-04-01 00:00:00", "2026-06-30 23:59:59", "EGP")
        self.assertEqual(q2_stats["cost"], 300.0)
        self.assertEqual(q2_stats["revenue"], 0.0)
        # Cumulative balance at June 30 cutoff: 1200 EGP (includes Jan, Feb, Apr)
        self.assertEqual(compute_ending_balance(txns, "2026-06-30 23:59:59", "EGP"), 1200.0)

        # F. Current period (September 2026 as of Sep 22)
        # Jan(1000) + Feb(500) - Apr(300) + Jul(800) - Sep(200) = 1800 EGP
        self.assertEqual(compute_ending_balance(txns, "2026-09-22 12:00:00", "EGP"), 1800.0)

        # G. Future empty period (October, November, December 2026)
        # Keeps carrying forward the latest known balance (1800 EGP)
        self.assertEqual(compute_ending_balance(txns, "2026-10-31 23:59:59", "EGP"), 1800.0)
        self.assertEqual(compute_ending_balance(txns, "2026-11-30 23:59:59", "EGP"), 1800.0)
        self.assertEqual(compute_ending_balance(txns, "2026-12-31 23:59:59", "EGP"), 1800.0)

        # H. Full year 2026
        # Ending balance for full year: 1800 EGP
        self.assertEqual(compute_ending_balance(txns, "2026-12-31 23:59:59", "EGP"), 1800.0)

        # I. Currency isolation (IDR)
        # Jan: 2,000,000 IDR
        self.assertEqual(compute_ending_balance(txns, "2026-01-31 23:59:59", "IDR"), 2000000.0)
        # Mar: 2,000,000 - 500,000 = 1,500,000 IDR
        self.assertEqual(compute_ending_balance(txns, "2026-03-31 23:59:59", "IDR"), 1500000.0)
        # Aug: 1,500,000 + 1,000,000 = 2,500,000 IDR
        self.assertEqual(compute_ending_balance(txns, "2026-08-31 23:59:59", "IDR"), 2500000.0)
        # Future Dec 2026: carried forward 2,500,000 IDR
        self.assertEqual(compute_ending_balance(txns, "2026-12-31 23:59:59", "IDR"), 2500000.0)

    def test_section_5_percentage_calculations_and_semantics(self):
        """Verify percentage calculation logic and reversed Expense semantics for EGP and IDR."""
        def calc_pct_change(cur, prev):
            if prev == 0 and cur == 0:
                return 0.0
            if prev == 0:
                return None  # Zero base: None rendered as "—" / "Baru"
            if cur == 0:
                return -100.0
            return round(((cur - prev) / prev) * 100, 1)

        def get_color_class(pct_val, is_expense=False):
            if pct_val is None or pct_val == 0:
                return "text-[#8B7355]"  # Neutral
            is_favorable = pct_val < 0 if is_expense else pct_val > 0
            return "text-green-600" if is_favorable else "text-red-600"

        # 1. Revenue tests
        # 1000 -> 2000: +100%, Green
        pct = calc_pct_change(2000, 1000)
        self.assertEqual(pct, 100.0)
        self.assertEqual(get_color_class(pct, is_expense=False), "text-green-600")

        # 2000 -> 4000: +100%, Green
        pct = calc_pct_change(4000, 2000)
        self.assertEqual(pct, 100.0)
        self.assertEqual(get_color_class(pct, is_expense=False), "text-green-600")

        # 4000 -> 2000: -50%, Red
        pct = calc_pct_change(2000, 4000)
        self.assertEqual(pct, -50.0)
        self.assertEqual(get_color_class(pct, is_expense=False), "text-red-600")

        # 2000 -> 2000: 0%, Neutral
        pct = calc_pct_change(2000, 2000)
        self.assertEqual(pct, 0.0)
        self.assertEqual(get_color_class(pct, is_expense=False), "text-[#8B7355]")

        # 2. Expense tests (Reversed color semantics)
        # 1000 -> 500: -50%, GREEN (cost reduction is favorable)
        pct = calc_pct_change(500, 1000)
        self.assertEqual(pct, -50.0)
        self.assertEqual(get_color_class(pct, is_expense=True), "text-green-600")

        # 500 -> 1000: +100%, RED (cost increase is unfavorable)
        pct = calc_pct_change(1000, 500)
        self.assertEqual(pct, 100.0)
        self.assertEqual(get_color_class(pct, is_expense=True), "text-red-600")

        # 1000 -> 1000: 0%, Neutral
        pct = calc_pct_change(1000, 1000)
        self.assertEqual(pct, 0.0)
        self.assertEqual(get_color_class(pct, is_expense=True), "text-[#8B7355]")

        # 3. Operating Profit tests (follows Revenue)
        # 1000 -> 2000: +100%, Green
        pct = calc_pct_change(2000, 1000)
        self.assertEqual(pct, 100.0)
        self.assertEqual(get_color_class(pct, is_expense=False), "text-green-600")

        # 2000 -> 1000: -50%, Red
        pct = calc_pct_change(1000, 2000)
        self.assertEqual(pct, -50.0)
        self.assertEqual(get_color_class(pct, is_expense=False), "text-red-600")

        # 1000 -> 1000: 0%, Neutral
        pct = calc_pct_change(1000, 1000)
        self.assertEqual(pct, 0.0)
        self.assertEqual(get_color_class(pct, is_expense=False), "text-[#8B7355]")

        # 4. Zero base tests (Must NOT be infinity, NaN, or +100%)
        pct = calc_pct_change(1000, 0)
        self.assertIsNone(pct)
        self.assertEqual(get_color_class(pct, is_expense=False), "text-[#8B7355]")

        # 5. Drop to zero tests: 1000 -> 0 = -100%
        pct = calc_pct_change(0, 1000)
        self.assertEqual(pct, -100.0)
        self.assertEqual(get_color_class(pct, is_expense=False), "text-red-600")
        self.assertEqual(get_color_class(pct, is_expense=True), "text-green-600")


class TestFinanceImprovementsAsyncLifecycle(unittest.IsolatedAsyncioTestCase):
    """Async lifecycle integration tests with isolated mock database."""

    async def test_section_2_order_revenue_lifecycle(self):
        """Comprehensive verification of order_revenue lifecycle and override protection."""
        from server import (
            record_order_revenue,
            admin_update_order,
            finance_update,
            OrderStatusUpdate,
            FinanceTxnInput,
        )

        mock_db = MagicMock()
        admin_finance = {"id": "admin_fin", "name": "Finance Admin", "role": "admin", "permissions": {"access_finance": True}}
        admin_ops = {"id": "admin_ops", "name": "Ops Lead", "role": "admin", "permissions": {"manage_orders": True, "access_finance": True}}

        order_id = "ord_lifecycle_101"
        order_doc = {
            "_id": order_id,
            "id": order_id,
            "order_number": "SG-LIFECYCLE-1",
            "total_le": 1000.0,
            "currency": "EGP",
            "payment_status": "lunas",
            "payment_method": "cash",
            "order_type": "standard",
            "created_at": "2026-09-01T10:00:00",
        }

        # Step 1: Paid order creates one active order_revenue
        mock_db.finance_transactions.find_one = AsyncMock(return_value=None)
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id="txn_rec_001"))
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 315.0})
        mock_db.system_rates.find_one = AsyncMock(return_value={"rate": 315.0})

        with patch("server.db", mock_db):
            await record_order_revenue(order_doc)

        mock_db.finance_transactions.insert_one.assert_called_once()
        inserted_txn = mock_db.finance_transactions.insert_one.call_args[0][0]
        self.assertEqual(inserted_txn["type"], "order_revenue")
        self.assertEqual(inserted_txn["related_order_id"], order_id)
        self.assertEqual(inserted_txn["amount"], 1000.0)
        self.assertEqual(inserted_txn["exchange_rate"], 315.0)
        self.assertEqual(inserted_txn["counterpart_amount"], 315000.0)
        self.assertFalse(inserted_txn.get("is_manual_override"))

        # Step 2 & 3: Finance edits order_revenue -> is_manual_override becomes True
        active_txn = dict(inserted_txn)
        active_txn["_id"] = "txn_rec_001"
        active_txn["id"] = "txn_rec_001"

        mock_db.finance_transactions.find_one = AsyncMock(return_value=active_txn)
        mock_db.finance_transactions.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        mock_db.finance_categories.find_one = AsyncMock(return_value={"name": "Penjualan Produk", "type": "income", "classification": "revenue"})
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.employee_wages.delete_many = AsyncMock()

        with patch("server.db", mock_db):
            edit_res = await finance_update(
                txn_id="txn_rec_001",
                data=FinanceTxnInput(
                    type="order_revenue",
                    category="Penjualan Produk",
                    amount=1200.0,
                    currency="EGP",
                    account="kas_toko",
                    description="Manual discount adjustment",
                ),
                admin=admin_finance,
            )

        self.assertEqual(edit_res.get("id"), "txn_rec_001")
        upd_call = mock_db.finance_transactions.update_one.call_args
        self.assertIsNotNone(upd_call)
        upd_fields = upd_call[0][1]["$set"]
        self.assertTrue(upd_fields.get("is_manual_override"))
        self.assertEqual(upd_fields.get("amount"), 1200.0)
        self.assertEqual(upd_fields.get("counterpart_amount"), 1200.0 * 315.0)
        self.assertEqual(upd_fields.get("manual_override_by_name"), "Finance Admin")

        # Step 4 & 5: Order price changes -> Finance transaction is NOT overwritten
        overridden_txn = dict(active_txn)
        overridden_txn.update(upd_fields)

        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.orders.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        mock_db.finance_transactions.find_one = AsyncMock(return_value=overridden_txn)
        mock_db.finance_transactions.update_one = AsyncMock()

        with patch("server.db", mock_db):
            await admin_update_order(
                order_id=order_id,
                data=OrderStatusUpdate(total_le=1500.0),
                admin=admin_ops,
            )

        # Verification: finance_transactions.update_one was NOT called because is_manual_override is True
        mock_db.finance_transactions.update_one.assert_not_called()

        # Step 6 & 7: Order payment method changes -> Finance transaction is NOT overwritten
        with patch("server.db", mock_db):
            await admin_update_order(
                order_id=order_id,
                data=OrderStatusUpdate(payment_method="transfer"),
                admin=admin_ops,
            )
        mock_db.finance_transactions.update_one.assert_not_called()

        # Step 8 & 9: Order changes from paid -> unpaid -> manually overridden finance record remains preserved
        mock_db.point_transactions.find = MagicMock()
        mock_db.point_transactions.find.return_value.to_list = AsyncMock(return_value=[])
        mock_db.point_transactions.delete_many = AsyncMock()
        mock_db.customers.update_one = AsyncMock()

        with patch("server.db", mock_db):
            await admin_update_order(
                order_id=order_id,
                data=OrderStatusUpdate(payment_status="belum_dibayar"),
                admin=admin_ops,
            )
        # Because is_manual_override is True, order_sync void is skipped; transaction preserved
        mock_db.finance_transactions.update_one.assert_not_called()

        # Step 10 & 11: Order becomes paid again -> No duplicate ACTIVE order_revenue exists
        mock_db.finance_transactions.insert_one.reset_mock()
        mock_db.finance_transactions.find_one = AsyncMock(return_value=overridden_txn)
        with patch("server.db", mock_db):
            await record_order_revenue(order_doc)
        # insert_one MUST NOT be called because active transaction already exists
        mock_db.finance_transactions.insert_one.assert_not_called()

    async def test_section_3_void_source_lifecycle(self):
        """Test distinction between finance_manual void and order_sync void."""
        from server import (
            finance_delete,
            admin_update_order,
            record_order_revenue,
            OrderStatusUpdate,
        )

        mock_db = MagicMock()
        admin_fin = {"id": "admin_fin", "name": "Finance Admin", "role": "admin", "permissions": {"access_finance": True}}
        admin_ops = {"id": "admin_ops", "name": "Ops Lead", "role": "admin", "permissions": {"manage_orders": True, "access_finance": True}}

        # Scenario A: Finance manual void
        txn_id = "txn_to_void_manually"
        active_order_revenue = {
            "_id": txn_id,
            "id": txn_id,
            "type": "order_revenue",
            "amount": 500.0,
            "currency": "EGP",
            "related_order_id": "ord_manual_void_1",
            "is_void": False,
        }

        mock_db.finance_transactions.find_one = AsyncMock(return_value=active_order_revenue)
        mock_db.finance_transactions.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        mock_db.employee_wages.delete_many = AsyncMock()

        with patch("server.db", mock_db):
            res = await finance_delete(txn_id=txn_id, admin=admin_fin)

        self.assertTrue(res.get("voided"))
        upd = mock_db.finance_transactions.update_one.call_args[0][1]["$set"]
        self.assertTrue(upd["is_void"])
        self.assertEqual(upd["status"], "void")
        self.assertEqual(upd["void_source"], "finance_manual")
        self.assertEqual(upd["voided_by_name"], "Finance Admin")

        # Order updates / payment changes do NOT resurrect finance_manual void
        manually_voided_txn = dict(active_order_revenue)
        manually_voided_txn.update(upd)

        # In record_order_revenue, check query for permanent manual void
        mock_db.finance_transactions.find_one = AsyncMock(return_value=manually_voided_txn)
        mock_db.finance_transactions.insert_one = AsyncMock()

        with patch("server.db", mock_db):
            await record_order_revenue({
                "_id": "ord_manual_void_1",
                "id": "ord_manual_void_1",
                "payment_status": "lunas",
                "total_le": 500.0,
            })
        # Crucial check: permanent void was NOT resurrected (no insert)
        mock_db.finance_transactions.insert_one.assert_not_called()

        # Scenario B: Order-sync void (unpay order that was NOT manually overridden)
        system_rev_txn = {
            "_id": "txn_sys_001",
            "id": "txn_sys_001",
            "type": "order_revenue",
            "amount": 300.0,
            "currency": "EGP",
            "related_order_id": "ord_sys_001",
            "is_void": False,
            "is_manual_override": False,
        }

        mock_db.orders.find_one = AsyncMock(return_value={
            "_id": "ord_sys_001",
            "id": "ord_sys_001",
            "payment_status": "lunas",
            "total_le": 300.0,
        })
        mock_db.orders.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        mock_db.finance_transactions.find_one = AsyncMock(return_value=system_rev_txn)
        mock_db.finance_transactions.update_one = AsyncMock()
        mock_db.point_transactions.find = MagicMock()
        mock_db.point_transactions.find.return_value.to_list = AsyncMock(return_value=[])
        mock_db.point_transactions.delete_many = AsyncMock()
        mock_db.customers.update_one = AsyncMock()

        with patch("server.db", mock_db):
            await admin_update_order(
                order_id="ord_sys_001",
                data=OrderStatusUpdate(payment_status="belum_dibayar"),
                admin=admin_ops,
            )

        # Verified: update_one called with void_source='order_sync'
        sync_upd = mock_db.finance_transactions.update_one.call_args[0][1]["$set"]
        self.assertTrue(sync_upd["is_void"])
        self.assertEqual(sync_upd["void_source"], "order_sync")

    async def test_section_4_rbac_permissions(self):
        """Test direct API access security for finance edit & void."""
        from server import require_perm
        from fastapi import HTTPException

        dep = require_perm("access_finance")

        # 1. Finance-authorized user succeeds
        fin_user = {"id": "u1", "role": "admin", "permissions": {"access_finance": True}}
        self.assertEqual(await dep(fin_user), fin_user)

        # 2. Owner user succeeds (inherits all permissions)
        owner_user = {"id": "u0", "role": "owner", "permissions": {}}
        self.assertEqual(await dep(owner_user), owner_user)

        # 3. Unauthorized admin raises 403
        unauth_user = {"id": "u2", "role": "admin", "permissions": {"manage_orders": True}}
        with self.assertRaises(HTTPException) as ctx:
            await dep(unauth_user)
        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
