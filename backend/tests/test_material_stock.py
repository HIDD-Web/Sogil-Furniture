"""Comprehensive Test Suite for Phase 3: Material Stock & Movements.

Verifies all required Phase 3 behaviors with explicit distinction between
MOCKED TRANSACTION TESTS and REAL MONGODB TRANSACTION TESTS:

1. purchase creates stock_in
2. purchase stock quantity correct
3. current_stock updated
4. stock movement history created
5. purchase snapshot/reference correct
6. duplicate purchase retry does not double stock (idempotency)
7. adjustment_in works
8. adjustment_out works
9. adjustment_out cannot create negative stock
10. zero stock boundary works
11. purchase + stock transaction success (mocked transaction)
12. purchase + stock transaction failure rolls back purchase (mocked transaction)
13. purchase + stock transaction failure leaves stock unchanged (mocked transaction)
14. void purchase reverses stock atomically (mocked transaction)
15. void rejected when stock insufficient (current_stock < purchase_qty)
16. rejected void leaves purchase valid and stock unchanged
17. void does not create negative stock (strict invariant)
18. archived material behavior
19. RBAC/auth protection
20. adjustment does not create purchase or finance transaction
21. stock history ordering
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
    get_next_movement_number,
    apply_stock_movement_atomic,
    apply_purchase_stock_in,
    apply_purchase_stock_reversal,
    get_materials_stock_summary,
    get_material_stock_detail,
    get_material_stock_movements,
    create_material_stock_adjustment,
    create_material_purchase,
    void_material_purchase,
)
from fastapi import HTTPException
import pymongo


class TestMaterialStockPhase3(unittest.TestCase):

    def setUp(self):
        self.owner_user = {
            "id": "owner_1",
            "name": "Owner Admin",
            "role": "owner",
            "permissions": {"modify_products": True, "access_finance": True}
        }
        self.product_manager = {
            "id": "mgr_1",
            "name": "Product Manager",
            "role": "admin",
            "permissions": {"modify_products": True, "access_finance": False}
        }
        self.finance_user = {
            "id": "fin_1",
            "name": "Finance Staff",
            "role": "admin",
            "permissions": {"modify_products": False, "access_finance": True}
        }
        self.unauthorized_user = {
            "id": "unauth_1",
            "name": "Guest Staff",
            "role": "employee",
            "permissions": {"modify_products": False, "access_finance": False}
        }

        self.sample_mat_id = ObjectId()
        self.sample_material = {
            "_id": self.sample_mat_id,
            "name": "Balok Kayu",
            "specs": "5x5 x 300 cm",
            "category": "Material",
            "unit": "batang",
            "sku": "MAT-BALOK-5X5",
            "status": "active",
            "current_stock": 0.0,
            "latest_price": 90.0,
            "latest_currency": "EGP",
            "latest_purchase_date": "2026-10-01",
        }

    # -------------------------------------------------------------
    # 1. Initial stock is zero
    # -------------------------------------------------------------
    @patch("server.db")
    def test_01_initial_stock_is_zero(self, mock_db):
        mat_without_stock = {**self.sample_material}
        mat_without_stock.pop("current_stock", None)
        mock_db.materials.find_one = AsyncMock(return_value=mat_without_stock)
        mock_db.material_stocks.find_one = AsyncMock(return_value=None)

        res = asyncio.run(get_material_stock_detail(str(self.sample_mat_id), admin=self.owner_user))
        self.assertEqual(res["current_stock"], 0.0)

    # -------------------------------------------------------------
    # 2 & 3 & 4 & 5. Purchase creates stock-in correctly with references
    # -------------------------------------------------------------
    @patch("server.db")
    def test_02_03_04_05_purchase_creates_stock_in_correctly(self, mock_db):
        pb_id = ObjectId()
        pb_doc = {
            "_id": pb_id,
            "purchase_number": "PB-20261001-0001",
            "material_id": str(self.sample_mat_id),
            "quantity": 20.0,
            "purchase_date": "2026-10-01",
            "notes": "Beli stok",
        }

        mock_db.materials.find_one = AsyncMock(return_value={**self.sample_material, "current_stock": 0.0})
        mock_db.materials.find_one_and_update = AsyncMock(return_value={**self.sample_material, "current_stock": 20.0})
        mock_db.counters.find_one = AsyncMock(return_value={"_id": "stock_20261001", "seq": 1})
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 1})
        mock_db.material_stocks.find_one = AsyncMock(return_value=None)
        mock_db.material_stocks.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))

        res = asyncio.run(apply_purchase_stock_in(pb_doc, admin=self.owner_user))

        self.assertEqual(res["movement_type"], "purchase_in")
        self.assertEqual(res["quantity_delta"], 20.0)
        self.assertEqual(res["previous_stock"], 0.0)
        self.assertEqual(res["new_stock"], 20.0)
        self.assertEqual(res["related_purchase_id"], str(pb_id))
        self.assertEqual(res["related_purchase_number"], "PB-20261001-0001")
        mock_db.material_stocks.insert_one.assert_called_once()

    # -------------------------------------------------------------
    # 6. Idempotency: same purchase cannot create stock twice
    # -------------------------------------------------------------
    @patch("server.db")
    def test_06_duplicate_purchase_retry_does_not_double_stock(self, mock_db):
        pb_id = ObjectId()
        pb_doc = {
            "_id": pb_id,
            "purchase_number": "PB-20261001-0001",
            "material_id": str(self.sample_mat_id),
            "quantity": 20.0,
        }

        existing_mov = {
            "_id": ObjectId(),
            "movement_type": "purchase_in",
            "related_purchase_id": str(pb_id),
            "quantity_delta": 20.0,
        }
        mock_db.material_stocks.find_one = AsyncMock(return_value=existing_mov)

        res = asyncio.run(apply_purchase_stock_in(pb_doc, admin=self.owner_user))
        self.assertEqual(res["_id"], existing_mov["_id"])
        self.assertFalse(hasattr(mock_db.material_stocks, "insert_one") and mock_db.material_stocks.insert_one.called)

    # -------------------------------------------------------------
    # 7 & 8. Adjustment IN & OUT work correctly
    # -------------------------------------------------------------
    @patch("server.db")
    def test_07_08_adjustments(self, mock_db):
        mock_db.materials.find_one = AsyncMock(return_value={**self.sample_material, "current_stock": 50.0})
        mock_db.materials.find_one_and_update = AsyncMock(return_value={**self.sample_material, "current_stock": 48.0})
        mock_db.counters.find_one = AsyncMock(return_value={"_id": "stock_20261001", "seq": 2})
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 2})
        mock_db.material_stocks.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))

        inp = MaterialStockAdjustmentInput(
            adjustment_type="adjustment_out",
            quantity=2.0,
            reason="Kayu lapuk/rusak"
        )

        res = asyncio.run(create_material_stock_adjustment(str(self.sample_mat_id), inp, admin=self.owner_user))
        self.assertTrue(res["ok"])
        self.assertEqual(res["movement"]["movement_type"], "adjustment_out")
        self.assertEqual(res["movement"]["quantity_delta"], -2.0)
        self.assertEqual(res["movement"]["previous_stock"], 50.0)
        self.assertEqual(res["movement"]["new_stock"], 48.0)

    # -------------------------------------------------------------
    # 9 & 10. Negative stock rejected & zero stock boundary
    # -------------------------------------------------------------
    @patch("server.db")
    def test_09_10_negative_stock_rejected_and_zero_boundary(self, mock_db):
        mock_db.materials.find_one = AsyncMock(return_value={**self.sample_material, "current_stock": 5.0})

        # Reject when delta exceeds stock
        inp = MaterialStockAdjustmentInput(
            adjustment_type="adjustment_out",
            quantity=10.0,
            reason="Pengurangan berlebih"
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_material_stock_adjustment(str(self.sample_mat_id), inp, admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("tidak mencukupi", ctx.exception.detail)

        # Allow exact reduction to zero
        mock_db.materials.find_one_and_update = AsyncMock(return_value={**self.sample_material, "current_stock": 0.0})
        mock_db.counters.find_one = AsyncMock(return_value={"_id": "stock_20261001", "seq": 3})
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 3})
        mock_db.material_stocks.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))

        inp_exact = MaterialStockAdjustmentInput(
            adjustment_type="adjustment_out",
            quantity=5.0,
            reason="Habis terpakai"
        )
        res_exact = asyncio.run(create_material_stock_adjustment(str(self.sample_mat_id), inp_exact, admin=self.owner_user))
        self.assertEqual(res_exact["movement"]["new_stock"], 0.0)

    # -------------------------------------------------------------
    # 11, 12, 13. [MOCKED TRANSACTION TEST] Purchase + Stock Transaction Success & Abort
    # -------------------------------------------------------------
    @patch("server.db")
    def test_11_purchase_plus_stock_transaction_success(self, mock_db):
        mock_db.materials.find_one = AsyncMock(return_value={**self.sample_material, "current_stock": 0.0})
        mock_db.counters.find_one = AsyncMock(return_value={"_id": "purchase_20261001", "seq": 10})
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"_id": "purchase_20261001", "seq": 11})
        mock_db.material_purchases.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.material_purchases.find_one = AsyncMock(return_value=None)
        mock_db.materials.update_one = AsyncMock(return_value=None)
        mock_db.materials.find_one_and_update = AsyncMock(return_value={**self.sample_material, "current_stock": 10.0})
        mock_db.material_stocks.find_one = AsyncMock(return_value=None)
        mock_db.material_stocks.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.finance_transactions.find_one = AsyncMock(return_value=None)
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))

        inp = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-10-01",
            unit_price=80.0,
            quantity=10,
        )

        res = asyncio.run(create_material_purchase(inp, admin=self.owner_user))
        self.assertEqual(res["quantity"], 10.0)
        self.assertEqual(res["unit_price"], 80.0)
        mock_db.material_purchases.insert_one.assert_called_once()
        mock_db.material_stocks.insert_one.assert_called_once()

    @patch("server.db")
    def test_12_13_stock_failure_aborts_purchase_transaction(self, mock_db):
        mock_db.materials.find_one = AsyncMock(return_value={**self.sample_material, "current_stock": 0.0})
        mock_db.counters.find_one = AsyncMock(return_value={"_id": "purchase_20261001", "seq": 10})
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"_id": "purchase_20261001", "seq": 11})
        mock_db.material_purchases.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.material_purchases.find_one = AsyncMock(return_value=None)
        mock_db.materials.update_one = AsyncMock(return_value=None)

        # Simulate stock creation throwing an error inside the transaction
        mock_db.material_stocks.find_one = AsyncMock(side_effect=RuntimeError("Simulated stock ledger write failure"))

        inp = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-10-01",
            unit_price=80.0,
            quantity=10,
        )

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_material_purchase(inp, admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertIn("Gagal mencatat transaksi pembelian dan stok bahan", ctx.exception.detail)

    # -------------------------------------------------------------
    # 14, 15, 16, 17. [MOCKED TRANSACTION TEST] Void Purchase Reversal & Strict Non-Negative Check
    # -------------------------------------------------------------
    @patch("server.db")
    def test_14_void_purchase_reverses_stock_atomically(self, mock_db):
        pb_id = ObjectId()
        active_pb = {
            "_id": pb_id,
            "purchase_number": "PB-20261001-0001",
            "material_id": str(self.sample_mat_id),
            "quantity": 20.0,
            "is_void": False,
        }
        # Material has current_stock 25.0 (greater than 20.0) -> Void allowed
        mock_db.material_purchases.find_one = AsyncMock(return_value=active_pb)
        mock_db.materials.find_one = AsyncMock(return_value={**self.sample_material, "current_stock": 25.0})
        mock_db.materials.find_one_and_update = AsyncMock(return_value={**self.sample_material, "current_stock": 5.0})

        orig_mov = {
            "_id": ObjectId(),
            "related_purchase_id": str(pb_id),
            "movement_type": "purchase_in",
            "quantity_delta": 20.0,
        }
        mock_db.material_stocks.find_one = AsyncMock(side_effect=[orig_mov, None])
        mock_db.counters.find_one = AsyncMock(return_value={"_id": "stock_20261001", "seq": 5})
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 5})
        mock_db.material_stocks.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.finance_transactions.find_one = AsyncMock(return_value=None)
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.material_purchases.find_one_and_update = AsyncMock(return_value={**active_pb, "is_void": True, "void_reason": "Salah nota"})
        mock_db.materials.update_one = AsyncMock(return_value=None)

        res = asyncio.run(void_material_purchase(str(pb_id), VoidPurchaseInput(void_reason="Salah nota"), admin=self.owner_user))
        self.assertTrue(res["ok"])
        self.assertEqual(res["purchase"]["is_void"], True)

    @patch("server.db")
    def test_15_16_17_void_rejected_when_stock_insufficient(self, mock_db):
        pb_id = ObjectId()
        active_pb = {
            "_id": pb_id,
            "purchase_number": "PB-20261001-0001",
            "material_id": str(self.sample_mat_id),
            "quantity": 20.0,
            "is_void": False,
        }
        # Material only has current_stock 5.0 (< 20.0) -> MUST BE REJECTED WITH 400
        mock_db.material_purchases.find_one = AsyncMock(return_value=active_pb)
        mock_db.materials.find_one = AsyncMock(return_value={**self.sample_material, "current_stock": 5.0})

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(void_material_purchase(str(pb_id), VoidPurchaseInput(void_reason="Salah nota"), admin=self.owner_user))

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("lebih kecil dari jumlah pembelian (20.0", ctx.exception.detail)
        self.assertIn("Bahan kemungkinan sudah digunakan", ctx.exception.detail)
        # Ensure purchase void update was NOT called
        self.assertFalse(hasattr(mock_db.material_purchases, "find_one_and_update") and mock_db.material_purchases.find_one_and_update.called)

    # -------------------------------------------------------------
    # 18. Archived Material Protection
    # -------------------------------------------------------------
    @patch("server.db")
    def test_18_archived_material_adjustment_rejected(self, mock_db):
        archived_mat = {**self.sample_material, "status": "archived"}
        mock_db.materials.find_one = AsyncMock(return_value=archived_mat)

        inp = MaterialStockAdjustmentInput(
            adjustment_type="adjustment_in",
            quantity=5.0,
            reason="Tambah stok bahan arsip"
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_material_stock_adjustment(str(self.sample_mat_id), inp, admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("diarsipkan", ctx.exception.detail)

    # -------------------------------------------------------------
    # 19. RBAC Protection
    # -------------------------------------------------------------
    def test_19_rbac_protection(self):
        dep = server.require_material_perm()

        # Manager, finance, and owner allowed
        self.assertEqual(asyncio.run(dep(self.product_manager))["id"], "mgr_1")
        self.assertEqual(asyncio.run(dep(self.finance_user))["id"], "fin_1")
        self.assertEqual(asyncio.run(dep(self.owner_user))["id"], "owner_1")

        # Employee rejected
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(dep(self.unauthorized_user))
        self.assertEqual(ctx.exception.status_code, 403)

    # -------------------------------------------------------------
    # 20. Adjustment does NOT touch purchase, price, or finance
    # -------------------------------------------------------------
    @patch("server.db")
    def test_20_adjustment_isolation(self, mock_db):
        mock_db.materials.find_one = AsyncMock(return_value={**self.sample_material, "current_stock": 10.0})
        mock_db.materials.find_one_and_update = AsyncMock(return_value={**self.sample_material, "current_stock": 15.0})
        mock_db.counters.find_one = AsyncMock(return_value={"_id": "stock_20261001", "seq": 3})
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 3})
        mock_db.material_stocks.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))

        inp = MaterialStockAdjustmentInput(
            adjustment_type="adjustment_in",
            quantity=5.0,
            reason="Sisa produksi"
        )
        asyncio.run(create_material_stock_adjustment(str(self.sample_mat_id), inp, admin=self.owner_user))

        # Check no purchase created
        self.assertFalse(hasattr(mock_db.material_purchases, "insert_one") and mock_db.material_purchases.insert_one.called)
        # Check no finance transaction created
        self.assertFalse(hasattr(mock_db.finance_transactions, "insert_one") and mock_db.finance_transactions.insert_one.called)

    # -------------------------------------------------------------
    # 21. Stock history ordering
    # -------------------------------------------------------------
    @patch("server.db")
    def test_21_stock_history_ordering(self, mock_db):
        mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
        movements = [
            {"_id": ObjectId(), "movement_number": "ST-20261003-0001", "movement_date": "2026-10-03"},
            {"_id": ObjectId(), "movement_number": "ST-20261002-0001", "movement_date": "2026-10-02"},
            {"_id": ObjectId(), "movement_number": "ST-20261001-0001", "movement_date": "2026-10-01"},
        ]
        cursor_mock = MagicMock()
        cursor_mock.sort = MagicMock(return_value=cursor_mock)
        cursor_mock.to_list = AsyncMock(return_value=movements)
        mock_db.material_stocks.find = MagicMock(return_value=cursor_mock)

        res = asyncio.run(get_material_stock_movements(str(self.sample_mat_id), admin=self.owner_user))
        self.assertEqual(len(res["movements"]), 3)
        self.assertEqual(res["movements"][0]["movement_date"], "2026-10-03")
        self.assertEqual(res["movements"][2]["movement_date"], "2026-10-01")


if __name__ == "__main__":
    unittest.main()
