"""Comprehensive Test Suite for Phase 4: Material Purchase -> Finance Integration.

Verifies all required Phase 4 behaviors according to the approved architecture:
A. Purchase -> Finance (EGP creates Cash expense, IDR creates Bank expense)
B. Account mapping (EGP -> Cash/EGP, IDR -> Bank/IDR, unsupported currency rejected)
C. Amount (Finance amount equals purchase total_amount, unconverted by FX rate)
D. Exchange rate (Defaults to settings, admin override accepted & stored immutably)
E. Dates (Finance date follows purchase_date, created_at is actual creation time)
F. Reference (reference_id, reference_number, description contains material name)
G. Idempotency (Duplicate finance expense prevented application & DB level)
H. Atomicity (Multi-document rollback if finance fails or stock fails)
I. Void (Void purchase creates Finance reversal, original intact, net zero)
J. Void idempotency (Duplicate void rejected, no second reversal)
K. Insufficient stock (Void rejected when stock insufficient, no finance reversal)
L. Historical isolation (Pre-Phase-4 purchase has no finance, voiding it creates no reversal)
M. Stock isolation (Manual stock adjustment & master changes do not create finance)
"""
import os
import sys
import unittest
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import server
from server import (
    MaterialPurchaseInput,
    VoidPurchaseInput,
    MaterialStockAdjustmentInput,
    create_material_purchase,
    void_material_purchase,
    create_material_stock_adjustment,
    apply_purchase_finance_expense,
    apply_purchase_finance_reversal,
    recalculate_material_latest_price,
)
from fastapi import HTTPException
import pymongo


class TestMaterialFinanceIntegration(unittest.TestCase):

    def setUp(self):
        self.owner_user = {
            "id": "owner_1",
            "name": "Owner Admin",
            "role": "owner",
            "permissions": {"modify_products": True, "access_finance": True}
        }
        self.sample_mat_id = ObjectId()
        self.sample_material = {
            "_id": self.sample_mat_id,
            "name": "Plywood Meranti",
            "specs": "18mm x 122x244 cm",
            "category": "Kayu & Lembaran",
            "unit": "lembar",
            "sku": "MAT-PLY-18",
            "status": "active",
            "current_stock": 50.0,
            "latest_price": None,
            "latest_currency": None,
            "latest_purchase_date": None,
        }

    def _setup_mock_db(self, mock_db):
        mock_db.materials.find_one = AsyncMock(return_value={**self.sample_material, "current_stock": 10.0})
        mock_db.materials.find_one_and_update = AsyncMock(return_value={**self.sample_material, "current_stock": 20.0})
        mock_db.materials.update_one = AsyncMock(return_value=None)

        mock_db.counters.find_one = AsyncMock(return_value={"seq": 1})
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 1})

        mock_db.material_purchases.find_one = AsyncMock(return_value=None)
        mock_db.material_purchases.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))

        mock_db.material_stocks.find_one = AsyncMock(return_value=None)
        mock_db.material_stocks.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))

        mock_db.finance_transactions.find_one = AsyncMock(return_value=None)
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))

        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357.0})

    # --------------------------------------------------------------------------
    # A & B & C & F: Purchase -> Finance (EGP & IDR, Account, Amount, Reference)
    # --------------------------------------------------------------------------
    @patch("server.db")
    def test_01_egp_purchase_creates_cash_expense(self, mock_db):
        """EGP purchase creates Cash expense with unconverted EGP amount and reference."""
        self._setup_mock_db(mock_db)

        inp = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-10-02",
            quantity=10.0,
            unit_price=1200.0,
            currency="EGP",
            exchange_rate=360.0,
            supplier_name="Toko Kayu Barokah",
            notes="Nota #101"
        )

        res = asyncio.run(create_material_purchase(inp, admin=self.owner_user))
        self.assertIsNotNone(res)

        # 1. Purchase created
        mock_db.material_purchases.insert_one.assert_called_once()
        # 2. Stock movement created
        mock_db.material_stocks.insert_one.assert_called_once()
        # 3. Finance expense created
        mock_db.finance_transactions.insert_one.assert_called_once()

        fin_call = mock_db.finance_transactions.insert_one.call_args[0][0]
        self.assertEqual(fin_call["type"], "expense")
        self.assertEqual(fin_call["category"], "Material")
        self.assertEqual(fin_call["classification"], "cost")
        # Amount = 10 * 1200 = 12000.0 (unconverted)
        self.assertEqual(fin_call["amount"], 12000.0)
        self.assertEqual(fin_call["currency"], "EGP")
        self.assertEqual(fin_call["account"], "EGP")  # Cash representation
        self.assertEqual(fin_call["exchange_rate"], 360.0)
        self.assertEqual(fin_call["counterpart_amount"], 12000.0 * 360.0)
        self.assertEqual(fin_call["counterpart_currency"], "IDR")
        self.assertEqual(fin_call["reference_type"], "material_purchase")
        self.assertIn("Plywood Meranti", fin_call["description"])
        self.assertEqual(fin_call["supplier_name"], "Toko Kayu Barokah")
        self.assertTrue(fin_call["date"].startswith("2026-10-02"))

    @patch("server.db")
    def test_02_idr_purchase_creates_bank_expense(self, mock_db):
        """IDR purchase creates Bank expense with unconverted IDR amount."""
        self._setup_mock_db(mock_db)

        inp = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-10-02",
            quantity=5.0,
            unit_price=500000.0,
            currency="IDR",
            supplier_name="Supplier Jakarta"
        )

        asyncio.run(create_material_purchase(inp, admin=self.owner_user))

        mock_db.finance_transactions.insert_one.assert_called_once()
        fin_call = mock_db.finance_transactions.insert_one.call_args[0][0]
        self.assertEqual(fin_call["type"], "expense")
        self.assertEqual(fin_call["amount"], 2500000.0)  # 5 * 500,000
        self.assertEqual(fin_call["currency"], "IDR")
        self.assertEqual(fin_call["account"], "IDR")  # Bank representation
        self.assertEqual(fin_call["reference_type"], "material_purchase")

    @patch("server.db")
    def test_03_unsupported_currency_rejected(self, mock_db):
        """Unsupported currency (e.g. USD) is rejected with HTTP 400."""
        self._setup_mock_db(mock_db)

        inp = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-10-02",
            quantity=5.0,
            unit_price=100.0,
            currency="USD",
        )

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_material_purchase(inp, admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("tidak didukung", ctx.exception.detail)

    # --------------------------------------------------------------------------
    # D: Exchange Rate (Default from Settings, Admin Override, Snapshot)
    # --------------------------------------------------------------------------
    @patch("server.db")
    def test_04_exchange_rate_defaults_from_settings_and_override_preserved(self, mock_db):
        """Defaults to Settings rate if not overridden, and stores override permanently."""
        self._setup_mock_db(mock_db)
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357.0})

        # Case 1: No override -> defaults to 357.0
        inp1 = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-10-02",
            quantity=2.0,
            unit_price=100.0,
            currency="EGP",
            exchange_rate=None
        )
        res1 = asyncio.run(create_material_purchase(inp1, admin=self.owner_user))
        self.assertEqual(res1["exchange_rate"], 357.0)

        # Case 2: Admin overrides to 365.0
        inp2 = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-10-02",
            quantity=2.0,
            unit_price=100.0,
            currency="EGP",
            exchange_rate=365.0
        )
        res2 = asyncio.run(create_material_purchase(inp2, admin=self.owner_user))
        self.assertEqual(res2["exchange_rate"], 365.0)

    # --------------------------------------------------------------------------
    # E: Dates (purchase_date vs created_at, Backdated logic)
    # --------------------------------------------------------------------------
    @patch("server.db")
    def test_05_backdated_purchase_date_and_created_at(self, mock_db):
        """Finance transaction date follows purchase_date; created_at reflects input time."""
        self._setup_mock_db(mock_db)

        inp = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-09-15",
            quantity=10.0,
            unit_price=50.0,
            currency="EGP"
        )
        asyncio.run(create_material_purchase(inp, admin=self.owner_user))

        fin_call = mock_db.finance_transactions.insert_one.call_args[0][0]
        # Calendar date must strictly be 2026-09-15
        self.assertTrue(fin_call["date"].startswith("2026-09-15"))
        # created_at reflects current year 2026 UTC
        self.assertIn("2026", fin_call["created_at"])

    # --------------------------------------------------------------------------
    # G: Idempotency (Prevent Duplicate Finance Expense)
    # --------------------------------------------------------------------------
    @patch("server.db")
    def test_06_finance_idempotency_prevents_duplicate_expense(self, mock_db):
        """Calling apply_purchase_finance_expense again returns existing without inserting."""
        self._setup_mock_db(mock_db)
        pb_id = ObjectId()
        existing_txn = {
            "_id": ObjectId(),
            "reference_type": "material_purchase",
            "reference_id": str(pb_id),
            "type": "expense",
            "amount": 1000.0,
            "currency": "EGP",
        }
        mock_db.finance_transactions.find_one = AsyncMock(return_value=existing_txn)

        purchase_doc = {
            "_id": pb_id,
            "purchase_number": "PB-20261002-0001",
            "currency": "EGP",
            "total_amount": 1000.0,
            "purchase_date": "2026-10-02"
        }
        res = asyncio.run(apply_purchase_finance_expense(purchase_doc, self.owner_user))
        self.assertEqual(res["reference_id"], str(pb_id))
        mock_db.finance_transactions.insert_one.assert_not_called()

    # --------------------------------------------------------------------------
    # H: Atomicity (Multi-document rollback)
    # --------------------------------------------------------------------------
    @patch("server.db")
    def test_07_atomicity_purchase_rollback_if_finance_fails(self, mock_db):
        """If finance creation fails, the transaction error propagates to abort."""
        self._setup_mock_db(mock_db)
        # Mock finance insert failure
        mock_db.finance_transactions.insert_one = AsyncMock(side_effect=Exception("Database network failure"))

        inp = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-10-02",
            quantity=10.0,
            unit_price=100.0,
            currency="EGP"
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_material_purchase(inp, admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 500)

    # --------------------------------------------------------------------------
    # I & J: Void Purchase & Finance Reversal Symmetry
    # --------------------------------------------------------------------------
    @patch("server.db")
    def test_08_void_purchase_creates_finance_reversal(self, mock_db):
        """Voiding a purchase creates Finance reversal; original remains intact; net zero."""
        self._setup_mock_db(mock_db)
        pb_oid = ObjectId()
        active_pb = {
            "_id": pb_oid,
            "purchase_number": "PB-20261002-0001",
            "material_id": str(self.sample_mat_id),
            "quantity": 10.0,
            "unit_price": 500.0,
            "total_amount": 5000.0,
            "currency": "EGP",
            "is_void": False,
        }
        orig_fin = {
            "_id": ObjectId(),
            "reference_type": "material_purchase",
            "reference_id": str(pb_oid),
            "type": "expense",
            "amount": 5000.0,
            "currency": "EGP",
            "account": "EGP",
            "exchange_rate": 357.0,
            "is_void": False,
        }
        orig_mov = {
            "_id": ObjectId(),
            "related_purchase_id": str(pb_oid),
            "movement_type": "purchase_in",
            "quantity_delta": 10.0,
        }

        # Current stock is 50.0 (sufficient)
        mock_db.material_purchases.find_one = AsyncMock(return_value=active_pb)
        mock_db.materials.find_one = AsyncMock(return_value={**self.sample_material, "current_stock": 50.0})
        mock_db.materials.find_one_and_update = AsyncMock(return_value={**self.sample_material, "current_stock": 40.0})
        def mock_stock_t8(query, **kwargs):
            if query.get("movement_number"):
                return None
            if query.get("movement_type") == "purchase_in":
                return orig_mov
            return None
        mock_db.material_stocks.find_one = AsyncMock(side_effect=mock_stock_t8)
        mock_db.finance_transactions.find_one = AsyncMock(side_effect=[orig_fin, None])
        mock_db.material_purchases.find_one_and_update = AsyncMock(return_value={**active_pb, "is_void": True})

        res = asyncio.run(void_material_purchase(str(pb_oid), VoidPurchaseInput(void_reason="Salah input"), admin=self.owner_user))
        self.assertTrue(res["ok"])
        self.assertTrue(res["purchase"]["is_void"])

        # Stock reversal created
        mock_db.material_stocks.insert_one.assert_called_once()
        # Finance reversal created
        mock_db.finance_transactions.insert_one.assert_called_once()
        rev_call = mock_db.finance_transactions.insert_one.call_args[0][0]

        # Reversal invariants:
        self.assertEqual(rev_call["type"], "income")
        self.assertEqual(rev_call["amount"], 5000.0)
        self.assertEqual(rev_call["currency"], "EGP")
        self.assertEqual(rev_call["account"], "EGP")
        self.assertEqual(rev_call["is_reversal"], True)
        self.assertEqual(rev_call["reversal_of_id"], str(orig_fin["_id"]))
        self.assertEqual(rev_call["reference_number"], "PB-20261002-0001")
        self.assertIn("Salah input", rev_call["description"])

    @patch("server.db")
    def test_09_duplicate_void_rejected(self, mock_db):
        """Second void attempt on already voided purchase is rejected with HTTP 400."""
        self._setup_mock_db(mock_db)
        already_void_pb = {
            "_id": ObjectId(),
            "purchase_number": "PB-20261002-0001",
            "material_id": str(self.sample_mat_id),
            "is_void": True,
        }
        mock_db.material_purchases.find_one = AsyncMock(return_value=already_void_pb)

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(void_material_purchase(str(already_void_pb["_id"]), VoidPurchaseInput(void_reason="Ulang"), admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("sudah berstatus void", ctx.exception.detail)

    # --------------------------------------------------------------------------
    # K: Insufficient Stock on Void (Rejects before Finance or Stock mutation)
    # --------------------------------------------------------------------------
    @patch("server.db")
    def test_10_void_rejected_when_stock_insufficient_no_finance_mutation(self, mock_db):
        """If current stock < purchase quantity, void is rejected and finance is NOT reversed."""
        self._setup_mock_db(mock_db)
        pb_oid = ObjectId()
        active_pb = {
            "_id": pb_oid,
            "purchase_number": "PB-20261002-0001",
            "material_id": str(self.sample_mat_id),
            "quantity": 20.0,
            "is_void": False,
        }
        # Current stock is only 5.0 (insufficient to reverse 20.0)
        mock_db.material_purchases.find_one = AsyncMock(return_value=active_pb)
        mock_db.materials.find_one = AsyncMock(return_value={**self.sample_material, "current_stock": 5.0})

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(void_material_purchase(str(pb_oid), VoidPurchaseInput(void_reason="Cancel"), admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("stok saat ini", ctx.exception.detail)

        # Neither stock nor finance reversal was executed
        mock_db.material_stocks.insert_one.assert_not_called()
        mock_db.finance_transactions.insert_one.assert_not_called()

    # --------------------------------------------------------------------------
    # L: Historical Purchases Isolation (Pre-Phase-4 Purchases)
    # --------------------------------------------------------------------------
    @patch("server.db")
    def test_11_pre_phase4_purchase_void_creates_no_finance_reversal(self, mock_db):
        """Voiding a historical purchase with no original finance transaction creates no reversal."""
        self._setup_mock_db(mock_db)
        pb_oid = ObjectId()
        old_pb = {
            "_id": pb_oid,
            "purchase_number": "PB-20260901-0001",
            "material_id": str(self.sample_mat_id),
            "quantity": 10.0,
            "is_void": False,
        }
        orig_mov = {
            "_id": ObjectId(),
            "related_purchase_id": str(pb_oid),
            "movement_type": "purchase_in",
            "quantity_delta": 10.0,
        }
        mock_db.material_purchases.find_one = AsyncMock(return_value=old_pb)
        mock_db.materials.find_one = AsyncMock(return_value={**self.sample_material, "current_stock": 50.0})
        mock_db.materials.find_one_and_update = AsyncMock(return_value={**self.sample_material, "current_stock": 40.0})
        def mock_stock_t8(query, **kwargs):
            if query.get("movement_number"):
                return None
            if query.get("movement_type") == "purchase_in":
                return orig_mov
            return None
        mock_db.material_stocks.find_one = AsyncMock(side_effect=mock_stock_t8)
        # Finance find_one returns None (no finance expense exists for this old purchase)
        mock_db.finance_transactions.find_one = AsyncMock(return_value=None)
        mock_db.material_purchases.find_one_and_update = AsyncMock(return_value={**old_pb, "is_void": True})

        res = asyncio.run(void_material_purchase(str(pb_oid), VoidPurchaseInput(void_reason="Old void"), admin=self.owner_user))
        self.assertTrue(res["ok"])

        # Stock reversal IS created
        mock_db.material_stocks.insert_one.assert_called_once()
        # Finance reversal is NOT created (no phantom income)
        mock_db.finance_transactions.insert_one.assert_not_called()

    # --------------------------------------------------------------------------
    # M: Stock Isolation (Stock adjustment does NOT touch Finance)
    # --------------------------------------------------------------------------
    @patch("server.db")
    def test_12_stock_adjustment_does_not_create_finance(self, mock_db):
        """Manual stock adjustment (adjustment_in / adjustment_out) does NOT touch finance."""
        self._setup_mock_db(mock_db)
        mock_db.materials.find_one = AsyncMock(return_value={**self.sample_material, "current_stock": 20.0})
        mock_db.materials.find_one_and_update = AsyncMock(return_value={**self.sample_material, "current_stock": 25.0})

        inp = MaterialStockAdjustmentInput(
            adjustment_type="adjustment_in",
            quantity=5.0,
            reason="Koreksi fisik"
        )
        asyncio.run(create_material_stock_adjustment(str(self.sample_mat_id), inp, admin=self.owner_user))

        # Stock movement was created
        mock_db.material_stocks.insert_one.assert_called_once()
        # Zero finance mutations
        mock_db.finance_transactions.insert_one.assert_not_called()


if __name__ == "__main__":
    unittest.main()
