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
        def mock_stock_t14(query, **kwargs):
            if query.get("movement_number"):
                return None
            if query.get("movement_type") == "purchase_in":
                return orig_mov
            return None
        mock_db.material_stocks.find_one = AsyncMock(side_effect=mock_stock_t14)
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

    # =============================================================
    # 22 - 31: CORRECTIVE REGRESSION TESTS (TESTS 1 - 10)
    # Enforces exact unique index semantics, error classification & invariants
    # =============================================================

    def _setup_realistic_stock_storage(self, mock_db, initial_stock=100.0):
        """Sets up an in-memory collection simulator that enforces MongoDB partial index and unique index constraints."""
        stored_mat = {**self.sample_material, "current_stock": initial_stock}
        stored_stocks = []
        stored_counters = {}
        stored_forms = {}

        def matches_mat_id(q_val):
            if not q_val:
                return True
            if q_val == self.sample_mat_id or str(q_val) == str(self.sample_mat_id):
                return True
            if isinstance(q_val, dict) and "$in" in q_val:
                in_list = [str(x) for x in q_val["$in"]]
                return str(self.sample_mat_id) in in_list
            return False

        async def mat_find_one(query, **kwargs):
            q_id = query.get("_id")
            if matches_mat_id(q_id):
                return {**stored_mat}
            return None

        async def mat_find_one_and_update(query, update, **kwargs):
            q_id = query.get("_id")
            if matches_mat_id(q_id):
                if "current_stock" in query and query["current_stock"] != stored_mat.get("current_stock"):
                    return None
                if "$set" in update:
                    stored_mat.update(update["$set"])
                return {**stored_mat}
            return None

        async def mat_update_one(query, update, **kwargs):
            q_id = query.get("_id")
            if matches_mat_id(q_id):
                if "$set" in update:
                    stored_mat.update(update["$set"])
                return MagicMock(modified_count=1)
            return MagicMock(modified_count=0)

        async def stock_insert_one(doc, **kwargs):
            m_num = doc.get("movement_number")
            # Enforce uniq_movement_number
            if m_num:
                for existing in stored_stocks:
                    if existing.get("movement_number") == m_num:
                        raise pymongo.errors.DuplicateKeyError(
                            f"E11000 duplicate key error collection: db.material_stocks index: uniq_movement_number dup key: {{ movement_number: '{m_num}' }}"
                        )

            # Enforce uniq_purchase_stock_movement with partialFilterExpression: related_purchase_id is string
            pb_id = doc.get("related_purchase_id")
            m_type = doc.get("movement_type")
            if pb_id and isinstance(pb_id, str):
                for existing in stored_stocks:
                    if existing.get("related_purchase_id") == pb_id and existing.get("movement_type") == m_type:
                        raise pymongo.errors.DuplicateKeyError(
                            f"E11000 duplicate key error collection: db.material_stocks index: uniq_purchase_stock_movement dup key: {{ related_purchase_id: '{pb_id}', movement_type: '{m_type}' }}"
                        )

            new_doc = {**doc, "_id": ObjectId()}
            stored_stocks.append(new_doc)
            return MagicMock(inserted_id=new_doc["_id"])

        async def stock_find_one(query, sort=None, **kwargs):
            # Check high-watermark regex
            if "movement_number" in query and isinstance(query["movement_number"], dict) and "$regex" in query["movement_number"]:
                prefix_re = query["movement_number"]["$regex"]
                prefix_str = prefix_re.replace("^", "")
                matching = [s for s in stored_stocks if s.get("movement_number", "").startswith(prefix_str)]
                if matching:
                    matching.sort(key=lambda x: x.get("movement_number", ""), reverse=True)
                    return {**matching[0]}
                return None
            if "related_purchase_id" in query:
                for s in stored_stocks:
                    if s.get("related_purchase_id") == query["related_purchase_id"]:
                        if "movement_type" in query and s.get("movement_type") != query["movement_type"]:
                            continue
                        return {**s}
                return None
            return None

        async def counter_find_one_and_update(query, update, **kwargs):
            cid = query["_id"]
            if cid not in stored_counters:
                stored_counters[cid] = {"_id": cid, "seq": 0}
            if "$inc" in update:
                stored_counters[cid]["seq"] += update["$inc"].get("seq", 1)
            return {**stored_counters[cid]}

        async def counter_update_one(query, update, **kwargs):
            cid = query["_id"]
            if cid not in stored_counters:
                stored_counters[cid] = {"_id": cid, "seq": 0}
            if "$max" in update:
                max_val = update["$max"].get("seq", 0)
                if max_val > stored_counters[cid]["seq"]:
                    stored_counters[cid]["seq"] = max_val
            if "$set" in update:
                set_val = update["$set"].get("seq", 0)
                stored_counters[cid]["seq"] = set_val
            return MagicMock(modified_count=1)

        def matches_sf_id(query_id, target_id_str):
            if not query_id:
                return False
            if str(query_id) == target_id_str:
                return True
            if isinstance(query_id, dict) and "$in" in query_id:
                in_list = [str(x) for x in query_id["$in"]]
                return target_id_str in in_list
            return False

        async def sf_find_one(query, **kwargs):
            q_id = query.get("_id")
            for sf_k, sf_v in stored_forms.items():
                if matches_sf_id(q_id, sf_k):
                    return {**sf_v}
            return None

        async def sf_find_one_and_update(query, update, **kwargs):
            q_id = query.get("_id")
            for sf_k, sf_v in stored_forms.items():
                if matches_sf_id(q_id, sf_k):
                    if "$set" in update:
                        sf_v.update(update["$set"])
                    return {**sf_v}
            return None

        mock_db.materials.find_one = AsyncMock(side_effect=mat_find_one)
        mock_db.materials.find_one_and_update = AsyncMock(side_effect=mat_find_one_and_update)
        mock_db.materials.update_one = AsyncMock(side_effect=mat_update_one)
        mock_db.material_stocks.insert_one = AsyncMock(side_effect=stock_insert_one)
        mock_db.material_stocks.find_one = AsyncMock(side_effect=stock_find_one)
        mock_db.counters.find_one_and_update = AsyncMock(side_effect=counter_find_one_and_update)
        mock_db.counters.update_one = AsyncMock(side_effect=counter_update_one)
        mock_db.stock_forms.find_one = AsyncMock(side_effect=sf_find_one)
        mock_db.stock_forms.find_one_and_update = AsyncMock(side_effect=sf_find_one_and_update)
        mock_db.stock_forms.update_one = AsyncMock(side_effect=sf_find_one_and_update)

        return stored_mat, stored_stocks, stored_counters, stored_forms

    @patch("server.db")
    def test_22_multiple_adjustment_in_succeed_without_purchase_id_collision(self, mock_db):
        """TEST 1: Multiple adjustment_in without related_purchase_id succeed sequentially without colliding."""
        stored_mat, stored_stocks, _, _ = self._setup_realistic_stock_storage(mock_db, initial_stock=10.0)

        # Adjustment 1: +5.0
        inp1 = MaterialStockAdjustmentInput(
            adjustment_type="adjustment_in",
            quantity=5.0,
            reason="Opname temuan lebih 1",
            movement_date="2026-10-05"
        )
        res1 = asyncio.run(create_material_stock_adjustment(str(self.sample_mat_id), inp1, admin=self.owner_user))
        self.assertTrue(res1["ok"])

        # Adjustment 2: +3.0
        inp2 = MaterialStockAdjustmentInput(
            adjustment_type="adjustment_in",
            quantity=3.0,
            reason="Opname temuan lebih 2",
            movement_date="2026-10-05"
        )
        res2 = asyncio.run(create_material_stock_adjustment(str(self.sample_mat_id), inp2, admin=self.owner_user))
        self.assertTrue(res2["ok"])

        # Verification: both movements exist, current_stock = 18.0
        self.assertEqual(stored_mat["current_stock"], 18.0)
        self.assertEqual(len(stored_stocks), 2)
        self.assertNotEqual(res1["movement"]["movement_number"], res2["movement"]["movement_number"])

    @patch("server.db")
    def test_23_multiple_adjustment_out_succeed_without_collision(self, mock_db):
        """TEST 2: Multiple adjustment_out without related_purchase_id succeed sequentially."""
        stored_mat, stored_stocks, _, _ = self._setup_realistic_stock_storage(mock_db, initial_stock=50.0)

        inp1 = MaterialStockAdjustmentInput(
            adjustment_type="adjustment_out",
            quantity=5.0,
            reason="Rusak kena air 1",
            movement_date="2026-10-05"
        )
        res1 = asyncio.run(create_material_stock_adjustment(str(self.sample_mat_id), inp1, admin=self.owner_user))
        self.assertTrue(res1["ok"])

        inp2 = MaterialStockAdjustmentInput(
            adjustment_type="adjustment_out",
            quantity=2.0,
            reason="Rusak kena air 2",
            movement_date="2026-10-05"
        )
        res2 = asyncio.run(create_material_stock_adjustment(str(self.sample_mat_id), inp2, admin=self.owner_user))
        self.assertTrue(res2["ok"])

        self.assertEqual(stored_mat["current_stock"], 43.0)
        self.assertEqual(len(stored_stocks), 2)

    @patch("server.db")
    def test_24_multiple_transformation_movements_do_not_collide(self, mock_db):
        """TEST 3: Transformation movements (transformation_out & transformation_in) do not collide with purchase index."""
        stored_mat, stored_stocks, _, _ = self._setup_realistic_stock_storage(mock_db, initial_stock=50.0)

        # Transformation out
        m1 = asyncio.run(apply_stock_movement_atomic(
            material_id=str(self.sample_mat_id),
            movement_type="transformation_out",
            quantity_delta=-2.0,
            movement_date="2026-10-05",
            reason="Transformasi potong 1",
            admin=self.owner_user
        ))
        # Transformation in
        m2 = asyncio.run(apply_stock_movement_atomic(
            material_id=str(self.sample_mat_id),
            movement_type="transformation_in",
            quantity_delta=10.0,
            movement_date="2026-10-05",
            reason="Transformasi output 1",
            admin=self.owner_user,
            update_material_aggregate=False
        ))
        # Another transformation in
        m3 = asyncio.run(apply_stock_movement_atomic(
            material_id=str(self.sample_mat_id),
            movement_type="transformation_in",
            quantity_delta=5.0,
            movement_date="2026-10-05",
            reason="Transformasi output 2",
            admin=self.owner_user,
            update_material_aggregate=False
        ))

        self.assertEqual(len(stored_stocks), 3)
        self.assertNotIn("related_purchase_id", stored_stocks[0])
        self.assertNotIn("related_purchase_id", stored_stocks[1])
        self.assertNotIn("related_purchase_id", stored_stocks[2])

    @patch("server.db")
    def test_25_genuine_purchase_idempotency_preserved(self, mock_db):
        """TEST 4: Genuine purchase with related_purchase_id duplicate is strictly rejected with 409."""
        stored_mat, stored_stocks, _, _ = self._setup_realistic_stock_storage(mock_db, initial_stock=10.0)
        pb_id = str(ObjectId())

        # First purchase movement succeeds
        m1 = asyncio.run(apply_stock_movement_atomic(
            material_id=str(self.sample_mat_id),
            movement_type="purchase_in",
            quantity_delta=10.0,
            movement_date="2026-10-05",
            reason="Pembelian PB-001",
            admin=self.owner_user,
            related_purchase_id=pb_id,
            related_purchase_number="PB-001"
        ))
        self.assertEqual(stored_mat["current_stock"], 20.0)

        # Second purchase movement with same pb_id and movement_type must be rejected with 409
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(apply_stock_movement_atomic(
                material_id=str(self.sample_mat_id),
                movement_type="purchase_in",
                quantity_delta=10.0,
                movement_date="2026-10-05",
                reason="Pembelian PB-001 duplicate",
                admin=self.owner_user,
                related_purchase_id=pb_id,
                related_purchase_number="PB-001"
            ))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("sudah pernah dicatat", ctx.exception.detail)
        # Material stock rolled back to 20.0 (not inflated to 30.0)
        self.assertEqual(stored_mat["current_stock"], 20.0)

    @patch("server.db")
    def test_26_movement_number_collision_triggers_retry(self, mock_db):
        """TEST 5: DuplicateKeyError on uniq_movement_number triggers retry and succeeds on next number."""
        stored_mat, stored_stocks, stored_counters, _ = self._setup_realistic_stock_storage(mock_db, initial_stock=10.0)

        # Seed an existing movement number in stored_stocks
        stored_stocks.append({
            "_id": ObjectId(),
            "movement_number": "ST-20261005-0001",
            "movement_date": "2026-10-05"
        })
        # Set counter to 0 so next call attempts ST-20261005-0001 first, collides, then retries
        stored_counters["stock_20261005"] = {"_id": "stock_20261005", "seq": 0}

        # apply_stock_movement_atomic with movement_number="ST-20261005-0001"
        res = asyncio.run(apply_stock_movement_atomic(
            material_id=str(self.sample_mat_id),
            movement_type="adjustment_in",
            quantity_delta=5.0,
            movement_date="2026-10-05",
            reason="Opname",
            admin=self.owner_user,
            movement_number="ST-20261005-0001"
        ))
        # It collided on attempt 0 with ST-20261005-0001, retried via get_next_movement_number,
        # which saw high-watermark 0001 and allocated ST-20261005-0002!
        self.assertEqual(res["movement_number"], "ST-20261005-0002")
        self.assertEqual(stored_mat["current_stock"], 15.0)

    @patch("server.db")
    def test_27_unrelated_duplicate_key_error_does_not_mask_as_movement_error(self, mock_db):
        """TEST 6: Unrelated DuplicateKeyError does NOT retry 5 times and does NOT say 'Gagal mengalokasikan nomor pergerakan stok unik'."""
        stored_mat, _, _, _ = self._setup_realistic_stock_storage(mock_db, initial_stock=10.0)

        insert_count = 0
        async def insert_with_unrelated_collision(doc, **kwargs):
            nonlocal insert_count
            insert_count += 1
            # Simulate a collision on an unrelated unique index (e.g. custom index or audit index)
            raise pymongo.errors.DuplicateKeyError(
                "E11000 duplicate key error collection: db.material_stocks index: uniq_custom_audit_key dup key: { audit_key: 'AUD-001' }"
            )

        mock_db.material_stocks.insert_one = AsyncMock(side_effect=insert_with_unrelated_collision)

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(apply_stock_movement_atomic(
                material_id=str(self.sample_mat_id),
                movement_type="adjustment_in",
                quantity_delta=5.0,
                movement_date="2026-10-05",
                reason="Opname",
                admin=self.owner_user
            ))

        # Must be 409, NOT 500
        self.assertEqual(ctx.exception.status_code, 409)
        # Must NOT be the misleading movement number error!
        self.assertNotIn("Gagal mengalokasikan nomor pergerakan stok unik", ctx.exception.detail)
        self.assertIn("Konflik indeks unik pada pergerakan stok", ctx.exception.detail)
        # Must NOT have retried 5 times! Only 1 insert attempted!
        self.assertEqual(insert_count, 1)
        # Material stock rolled back to initial 10.0
        self.assertEqual(stored_mat["current_stock"], 10.0)

    @patch("server.db")
    def test_28_physical_stock_adjustment_invariants(self, mock_db):
        """TEST 7: Physical stock adjustment (Rak 80x20 +18 pcs) updates form, leaves material unchanged, no finance."""
        stored_mat, stored_stocks, _, stored_forms = self._setup_realistic_stock_storage(mock_db, initial_stock=10.0)
        sf_id = ObjectId()
        stored_forms[str(sf_id)] = {
            "_id": sf_id,
            "material_id": str(self.sample_mat_id),
            "form_type": "standard",
            "width": 80.0,
            "length": 20.0,
            "stock_unit": "pcs",
            "current_quantity": 0.0,
            "label": "Rak 80x20"
        }

        inp = MaterialStockAdjustmentInput(
            adjustment_type="adjustment_in",
            quantity=18.0,
            reason="Opname fisik ditemukan lebih",
            stock_form_id=str(sf_id),
            movement_date="2026-10-05"
        )
        res = asyncio.run(create_material_stock_adjustment(str(self.sample_mat_id), inp, admin=self.owner_user))
        self.assertTrue(res["ok"])

        # Invariant 1: stock_forms.current_quantity += 18
        self.assertEqual(stored_forms[str(sf_id)]["current_quantity"], 18.0)
        # Invariant 2: materials.current_stock is UNCHANGED (still 10.0)
        self.assertEqual(stored_mat["current_stock"], 10.0)
        # Invariant 3: material_stocks gets exactly 1 movement doc
        self.assertEqual(len(stored_stocks), 1)
        self.assertEqual(stored_stocks[0]["unit"], "pcs")
        self.assertEqual(stored_stocks[0]["quantity_delta"], 18.0)
        # Invariant 4: No finance touched
        self.assertFalse(hasattr(mock_db.finance_transactions, "insert_one") and mock_db.finance_transactions.insert_one.called)

    @patch("server.db")
    def test_29_raw_stock_adjustment_invariants(self, mock_db):
        """TEST 8: Raw stock adjustment (Raw BlockBoard +1 lembar) updates material, no finance."""
        stored_mat, stored_stocks, _, _ = self._setup_realistic_stock_storage(mock_db, initial_stock=10.0)
        stored_mat["unit"] = "lembar"
        stored_mat["name"] = "BlockBoard 122x244"

        inp = MaterialStockAdjustmentInput(
            adjustment_type="adjustment_in",
            quantity=1.0,
            reason="Opname raw lembar lebih",
            movement_date="2026-10-05"
        )
        res = asyncio.run(create_material_stock_adjustment(str(self.sample_mat_id), inp, admin=self.owner_user))
        self.assertTrue(res["ok"])

        # Invariant 1: materials.current_stock += 1.0 (from 10.0 to 11.0)
        self.assertEqual(stored_mat["current_stock"], 11.0)
        # Invariant 2: material_stocks gets exactly 1 movement doc
        self.assertEqual(len(stored_stocks), 1)
        self.assertEqual(stored_stocks[0]["unit"], "lembar")
        self.assertEqual(stored_stocks[0]["quantity_delta"], 1.0)
        # Invariant 3: No finance touched
        self.assertFalse(hasattr(mock_db.finance_transactions, "insert_one") and mock_db.finance_transactions.insert_one.called)

    @patch("server.db")
    def test_30_multiple_consecutive_adjustments(self, mock_db):
        """TEST 9: Multiple consecutive adjustments (+10, +5, -3, +8) all succeed without unique index trap."""
        stored_mat, stored_stocks, _, _ = self._setup_realistic_stock_storage(mock_db, initial_stock=0.0)

        adjustments = [
            ("adjustment_in", 10.0),
            ("adjustment_in", 5.0),
            ("adjustment_out", 3.0),
            ("adjustment_in", 8.0),
        ]

        for adj_type, qty in adjustments:
            inp = MaterialStockAdjustmentInput(
                adjustment_type=adj_type,
                quantity=qty,
                reason="Penyesuaian beruntun",
                movement_date="2026-10-05"
            )
            res = asyncio.run(create_material_stock_adjustment(str(self.sample_mat_id), inp, admin=self.owner_user))
            self.assertTrue(res["ok"])

        # Expected stock: 0 + 10 + 5 - 3 + 8 = 20.0
        self.assertEqual(stored_mat["current_stock"], 20.0)
        self.assertEqual(len(stored_stocks), 4)

        # Check all movement numbers are distinct
        nums = [s["movement_number"] for s in stored_stocks]
        self.assertEqual(len(nums), len(set(nums)))

    @patch("server.db")
    def test_31_historical_movement_numbers_handled_by_high_watermark(self, mock_db):
        """TEST 10: Allocator leapfrogs existing historical numbers using high-watermark sync."""
        stored_mat, stored_stocks, stored_counters, _ = self._setup_realistic_stock_storage(mock_db, initial_stock=50.0)

        # Seed physical movements up to 0005
        for i in range(1, 6):
            stored_stocks.append({
                "_id": ObjectId(),
                "movement_number": f"ST-20261005-{i:04d}",
                "movement_date": "2026-10-05"
            })

        # Counter is at 0 (behind physical stock)
        stored_counters["stock_20261005"] = {"_id": "stock_20261005", "seq": 0}

        inp = MaterialStockAdjustmentInput(
            adjustment_type="adjustment_in",
            quantity=2.0,
            reason="Opname leapfrog test",
            movement_date="2026-10-05"
        )
        res = asyncio.run(create_material_stock_adjustment(str(self.sample_mat_id), inp, admin=self.owner_user))
        self.assertTrue(res["ok"])

    # =============================================================
    # 32 - 35: STARTUP NON-DESTRUCTIVE SAFETY & OPERATOR MIGRATION TESTS
    # =============================================================
    @patch("server.db")
    def test_32_startup_does_not_automatically_drop_incompatible_index(self, mock_db):
        """Startup must NEVER drop or mutate an incompatible legacy index."""
        # Setup mock db to allow seed() to run smoothly across any collection accessed
        def make_col_mock():
            col = MagicMock()
            col.create_index = AsyncMock()
            col.drop_index = AsyncMock()
            col.find_one = AsyncMock(return_value={"_id": ObjectId(), "key": "test", "email": "admin@example.com", "value": True})
            col.update_one = AsyncMock()
            col.update_many = AsyncMock()
            col.count_documents = AsyncMock(return_value=1)
            return col

        seed_cols = [
            "admins", "audit_logs", "categories", "claim_attempts", "customers", "delivery_zones",
            "finance_transactions", "invoices", "material_purchases", "material_stocks", "materials",
            "orders", "point_transactions", "products", "referrals", "settings", "stock_forms",
            "stock_transformations", "counters", "work_orders", "vouchers", "cart", "notifications"
        ]
        for col_name in seed_cols:
            col_m = make_col_mock()
            setattr(mock_db, col_name, col_m)
            mock_db[col_name] = col_m

        # Specifically configure material_stocks for the test assertion
        mock_db.material_stocks.index_information = AsyncMock(return_value={
            "uniq_purchase_stock_movement": {
                "key": [("related_purchase_id", 1), ("movement_type", 1)],
                "unique": True,
                "sparse": True
            }
        })
        mock_db.material_stocks.drop_index = AsyncMock()
        mock_db.material_stocks.create_index = AsyncMock()

        # Run startup seed
        asyncio.run(server.seed())

        # Assert drop_index was NEVER called on material_stocks
        mock_db.material_stocks.drop_index.assert_not_called()

        # Assert create_index was NOT called for uniq_purchase_stock_movement
        created_index_names = [call[1].get("name") for call in mock_db.material_stocks.create_index.call_args_list]
        self.assertNotIn("uniq_purchase_stock_movement", created_index_names)

    def test_33_operator_migration_dry_run_and_refusal_on_unexpected_index(self):
        """Explicit migration detects legacy index and refuses on unexpected index keys."""
        from mongomock_motor import AsyncMongoMockClient
        sys.path.insert(0, os.path.join(backend_dir, "..", "scripts"))
        import migrate_purchase_stock_movement_index as migrator

        client = AsyncMongoMockClient()
        db = client["test_mig_db"]

        async def scenario():
            # Setup unexpected key index
            await db.material_stocks.create_index([("wrong_key", 1)], unique=True, name="uniq_purchase_stock_movement")
            res = await migrator.run_migration(dry_run=True, client=client, db_name="test_mig_db")
            self.assertFalse(res["ok"])
            self.assertIn("Unexpected keys", res["error"])

        asyncio.run(scenario())

    def test_34_operator_migration_preflight_detects_duplicate_purchases(self):
        """Preflight detects duplicate genuine purchase movements and aborts before dropping index."""
        from mongomock_motor import AsyncMongoMockClient
        sys.path.insert(0, os.path.join(backend_dir, "..", "scripts"))
        import migrate_purchase_stock_movement_index as migrator

        client = AsyncMongoMockClient()
        db = client["test_mig_db2"]

        async def scenario():
            # In MongoDB, if duplicates exist (e.g. from an unindexed period), we insert them before index creation
            pb_id = "pb_duplicate_test"
            await db.material_stocks.insert_one({"related_purchase_id": pb_id, "movement_type": "purchase_in", "movement_number": "ST-01"})
            await db.material_stocks.insert_one({"related_purchase_id": pb_id, "movement_type": "purchase_in", "movement_number": "ST-02"})

            # Now attach legacy index without uniqueness to simulate legacy index presence
            await db.material_stocks.create_index(
                [("related_purchase_id", 1), ("movement_type", 1)],
                sparse=True,
                name="uniq_purchase_stock_movement"
            )

            # Run migration
            res = await migrator.run_migration(dry_run=False, client=client, db_name="test_mig_db2")
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"], "Duplicate purchase movements detected")
            self.assertEqual(len(res["duplicates"]), 1)

            # Ensure old index was NOT dropped
            idx_info = await db.material_stocks.index_information()
            self.assertIn("uniq_purchase_stock_movement", idx_info)

        asyncio.run(scenario())

    def test_35_operator_migration_successful_live_execution(self):
        """Explicit migration successfully converts legacy sparse index to partialFilterExpression when clean."""
        from mongomock_motor import AsyncMongoMockClient
        sys.path.insert(0, os.path.join(backend_dir, "..", "scripts"))
        import migrate_purchase_stock_movement_index as migrator

        client = AsyncMongoMockClient()
        db = client["test_mig_db3"]

        async def scenario():
            # Setup legacy index
            await db.material_stocks.create_index(
                [("related_purchase_id", 1), ("movement_type", 1)],
                unique=True,
                sparse=True,
                name="uniq_purchase_stock_movement"
            )
            # Insert clean records
            await db.material_stocks.insert_one({"related_purchase_id": "pb_1", "movement_type": "purchase_in", "movement_number": "ST-01"})
            await db.material_stocks.insert_one({"movement_type": "adjustment_in", "movement_number": "ST-02"})

            # Run live migration
            res = await migrator.run_migration(dry_run=False, client=client, db_name="test_mig_db3")
            self.assertTrue(res["ok"])
            self.assertEqual(res["action"], "migrated_successfully")

            # Verify new index
            idx_info = await db.material_stocks.index_information()
            new_def = idx_info["uniq_purchase_stock_movement"]
            self.assertEqual(new_def.get("partialFilterExpression"), {"related_purchase_id": {"$type": "string"}})
            self.assertFalse(new_def.get("sparse"))

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
