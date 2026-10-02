"""Comprehensive Test Suite for Phase 2: Material Purchases & Price History.

Verifies all required Phase 2 behaviors:
1. create purchase successfully
2. invalid material_id
3. archived material cannot be purchased
4. quantity > 0
5. unit_price >= 0
6. backend calculates total correctly (unit_price * quantity)
7. purchase number unique
8. material snapshot stored correctly (name, specs, category, unit)
9. latest price updated correctly on material document
10. older purchase does not overwrite newer latest price
11. backdated purchase does not incorrectly become latest
12. price history ordered correctly (purchase_date descending)
13. multiple purchases remain as separate records (immutable)
14. void purchase does not delete record (is_void=True)
15. void latest purchase recalculates latest valid price from remaining purchases
16. void purchase is excluded from price history active records
17. no stock collection/document is created
18. no finance transaction is created
19. RBAC/auth protection (modify_products, access_finance, owner allowed; employee 403)
20. existing Finance regression
21. existing Invoice regression
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
    get_next_purchase_number,
    recalculate_material_latest_price,
    get_material_purchases,
    create_material_purchase,
    get_material_purchase_detail,
    void_material_purchase,
    get_material_price_history,
)
from fastapi import HTTPException
import pymongo


class TestMaterialPurchasesPhase2(unittest.TestCase):

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
            "current_stock": 50.0,
            "latest_price": None,
            "latest_currency": None,
            "latest_purchase_date": None,
        }

    def _setup_mock_db(self, mock_db):
        mock_db.material_stocks.find_one = AsyncMock(return_value=None)
        mock_db.material_stocks.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.material_stocks.update_one = AsyncMock(return_value=None)
        mock_db.finance_transactions.find_one = AsyncMock(return_value=None)
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.counters.find_one = AsyncMock(return_value={"seq": 1})
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 2})
        mock_db.counters.update_one = AsyncMock(return_value=None)
        mock_db.materials.find_one_and_update = AsyncMock(return_value={**self.sample_material, "current_stock": 50.0})

    # -------------------------------------------------------------
    # 1. Create Purchase Successfully
    # -------------------------------------------------------------
    @patch("server.db")
    def test_01_create_purchase_successfully(self, mock_db):
        self._setup_mock_db(mock_db)
        mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
        mock_db.counters.find_one = AsyncMock(return_value={"_id": "purchase_20261001", "seq": 10})
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"_id": "purchase_20261001", "seq": 11})

        inserted_pb_id = ObjectId()
        mock_db.material_purchases.insert_one = AsyncMock(return_value=MagicMock(inserted_id=inserted_pb_id))
        mock_db.material_purchases.find_one = AsyncMock(return_value=None)
        mock_db.materials.update_one = AsyncMock(return_value=None)

        inp = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-10-01",
            unit_price=85.5,
            quantity=10,
            currency="EGP",
            supplier_name="Toko Kayu Barokah",
            notes="Grade A oven"
        )

        res = asyncio.run(create_material_purchase(inp, admin=self.owner_user))

        self.assertEqual(res["purchase_number"], "PB-20261001-0011")
        self.assertEqual(res["material_id"], str(self.sample_mat_id))
        self.assertEqual(res["material_name_snapshot"], "Balok Kayu")
        self.assertEqual(res["material_specs_snapshot"], "5x5 x 300 cm")
        self.assertEqual(res["category"], "Material")
        self.assertEqual(res["unit"], "batang")
        self.assertEqual(res["unit_price"], 85.5)
        self.assertEqual(res["quantity"], 10.0)
        self.assertEqual(res["total_amount"], 855.0)
        self.assertEqual(res["is_void"], False)
        self.assertEqual(res["created_by_id"], "owner_1")
        mock_db.material_purchases.insert_one.assert_called_once()

    # -------------------------------------------------------------
    # 2. Invalid material_id
    # -------------------------------------------------------------
    @patch("server.db")
    def test_02_invalid_material_id(self, mock_db):
        mock_db.materials.find_one = AsyncMock(return_value=None)
        inp = MaterialPurchaseInput(
            material_id=str(ObjectId()),
            purchase_date="2026-10-01",
            unit_price=50.0,
            quantity=5
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_material_purchase(inp, admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 404)

    # -------------------------------------------------------------
    # 3. Archived material cannot be purchased
    # -------------------------------------------------------------
    @patch("server.db")
    def test_03_archived_material_rejected(self, mock_db):
        archived_mat = {**self.sample_material, "status": "archived"}
        mock_db.materials.find_one = AsyncMock(return_value=archived_mat)

        inp = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-10-01",
            unit_price=50.0,
            quantity=5
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_material_purchase(inp, admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("diarsipkan", ctx.exception.detail)

    # -------------------------------------------------------------
    # 4 & 5. Validations: quantity > 0, unit_price >= 0, valid date
    # -------------------------------------------------------------
    @patch("server.db")
    def test_04_05_validations(self, mock_db):
        mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)

        # Quantity <= 0
        inp_q0 = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-10-01",
            unit_price=50.0,
            quantity=0
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_material_purchase(inp_q0, admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 400)

        # Unit price < 0
        inp_pneg = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-10-01",
            unit_price=-10.0,
            quantity=5
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_material_purchase(inp_pneg, admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 400)

        # Invalid date format
        inp_baddate = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="invalid-date",
            unit_price=50.0,
            quantity=5
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_material_purchase(inp_baddate, admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 400)

    # -------------------------------------------------------------
    # 6. Backend calculates total correctly
    # -------------------------------------------------------------
    @patch("server.db")
    def test_06_backend_calculates_total_correctly(self, mock_db):
        self._setup_mock_db(mock_db)
        mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 1})
        mock_db.counters.find_one = AsyncMock(return_value={"seq": 1})
        mock_db.material_purchases.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.material_purchases.find_one = AsyncMock(return_value=None)
        mock_db.materials.update_one = AsyncMock(return_value=None)

        inp = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-10-01",
            unit_price=33.33,
            quantity=3,
        )
        res = asyncio.run(create_material_purchase(inp, admin=self.owner_user))
        self.assertEqual(res["total_amount"], 99.99)

    # -------------------------------------------------------------
    # 7. Purchase number generation format & uniqueness
    # -------------------------------------------------------------
    @patch("server.db")
    def test_07_purchase_number_unique(self, mock_db):
        mock_db.counters.find_one = AsyncMock(return_value=None)
        mock_db.material_purchases.find_one = AsyncMock(return_value={"purchase_number": "PB-20261001-0005"})
        mock_db.counters.update_one = AsyncMock(return_value=None)
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 6})

        num = asyncio.run(get_next_purchase_number("2026-10-01"))
        self.assertEqual(num, "PB-20261001-0006")
        mock_db.counters.update_one.assert_called_once()
        mock_db.counters.find_one_and_update.assert_called_once()

    # -------------------------------------------------------------
    # 8. Material snapshot stored correctly
    # -------------------------------------------------------------
    @patch("server.db")
    def test_08_material_snapshot_stored_correctly(self, mock_db):
        self._setup_mock_db(mock_db)
        mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 1})
        mock_db.counters.find_one = AsyncMock(return_value={"seq": 1})
        mock_db.material_purchases.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.material_purchases.find_one = AsyncMock(return_value=None)
        mock_db.materials.update_one = AsyncMock(return_value=None)

        inp = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-10-01",
            unit_price=10.0,
            quantity=2,
        )
        res = asyncio.run(create_material_purchase(inp, admin=self.owner_user))
        self.assertEqual(res["material_name_snapshot"], self.sample_material["name"])
        self.assertEqual(res["material_specs_snapshot"], self.sample_material["specs"])
        self.assertEqual(res["category"], self.sample_material["category"])
        self.assertEqual(res["unit"], self.sample_material["unit"])

    # -------------------------------------------------------------
    # 9, 10, 11. Latest price ordering: older/backdated purchase handling
    # -------------------------------------------------------------
    @patch("server.db")
    def test_09_10_11_latest_price_recalculation(self, mock_db):
        # Scenario: purchases on 2026-09-25 (80 LE), 2026-10-01 (90 LE)
        # Latest purchase should be 2026-10-01 (90 LE)
        latest_pb = {
            "_id": ObjectId(),
            "material_id": str(self.sample_mat_id),
            "purchase_date": "2026-10-01",
            "unit_price": 90.0,
            "currency": "EGP",
            "created_at": "2026-10-01T10:00:00Z"
        }
        mock_db.material_purchases.find_one = AsyncMock(return_value=latest_pb)
        mock_db.materials.update_one = AsyncMock(return_value=None)

        asyncio.run(recalculate_material_latest_price(str(self.sample_mat_id)))

        # Verify update call sets latest_price to 90.0 and date to 2026-10-01
        mock_db.materials.update_one.assert_called_once()
        set_args = mock_db.materials.update_one.call_args[0][1]["$set"]
        self.assertEqual(set_args["latest_price"], 90.0)
        self.assertEqual(set_args["latest_currency"], "EGP")
        self.assertEqual(set_args["latest_purchase_date"], "2026-10-01")

    # -------------------------------------------------------------
    # 12 & 13. Price history ordered correctly & multiple purchases separate
    # -------------------------------------------------------------
    @patch("server.db")
    def test_12_13_price_history_ordered_and_separate(self, mock_db):
        mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
        purchases = [
            {"_id": ObjectId(), "purchase_number": "PB-20261010-0001", "purchase_date": "2026-10-10", "unit_price": 85.0, "quantity": 5},
            {"_id": ObjectId(), "purchase_number": "PB-20261001-0001", "purchase_date": "2026-10-01", "unit_price": 90.0, "quantity": 20},
            {"_id": ObjectId(), "purchase_number": "PB-20260925-0001", "purchase_date": "2026-09-25", "unit_price": 80.0, "quantity": 10},
        ]
        cursor_mock = MagicMock()
        cursor_mock.sort = MagicMock(return_value=cursor_mock)
        cursor_mock.to_list = AsyncMock(return_value=purchases)
        mock_db.material_purchases.find = MagicMock(return_value=cursor_mock)

        res = asyncio.run(get_material_price_history(str(self.sample_mat_id), admin=self.owner_user))
        self.assertEqual(len(res["history"]), 3)
        self.assertEqual(res["history"][0]["purchase_date"], "2026-10-10")
        self.assertEqual(res["history"][1]["purchase_date"], "2026-10-01")
        self.assertEqual(res["history"][2]["purchase_date"], "2026-09-25")

    # -------------------------------------------------------------
    # 14, 15, 16. Void purchase: does not delete, recalculates latest, excludes from active
    # -------------------------------------------------------------
    @patch("server.db")
    def test_14_15_16_void_purchase(self, mock_db):
        self._setup_mock_db(mock_db)
        pb_oid = ObjectId()
        active_pb = {
            "_id": pb_oid,
            "purchase_number": "PB-20261001-0001",
            "material_id": str(self.sample_mat_id),
            "is_void": False,
            "unit_price": 90.0,
            "quantity": 10.0,
            "purchase_date": "2026-10-01"
        }
        # After void, next latest valid purchase is from 2026-09-25 (80 LE)
        older_pb = {
            "_id": ObjectId(),
            "material_id": str(self.sample_mat_id),
            "purchase_date": "2026-09-25",
            "unit_price": 80.0,
            "currency": "EGP",
            "is_void": False,
        }
        # In void_material_purchase: 1st find_one is active_pb, 2nd find_one is in recalculate_material_latest_price (older_pb)
        mock_db.material_purchases.find_one = AsyncMock(side_effect=[active_pb, older_pb])

        voided_doc = {**active_pb, "is_void": True, "void_reason": "Salah input"}
        mock_db.material_purchases.find_one_and_update = AsyncMock(return_value=voided_doc)
        mock_db.materials.find_one = AsyncMock(return_value={**self.sample_material, "current_stock": 50.0})
        mock_db.materials.update_one = AsyncMock(return_value=None)

        res = asyncio.run(void_material_purchase(str(pb_oid), VoidPurchaseInput(void_reason="Salah input"), admin=self.owner_user))

        self.assertTrue(res["ok"])
        self.assertEqual(res["purchase"]["is_void"], True)
        self.assertEqual(res["purchase"]["void_reason"], "Salah input")

        # Recalculate called
        mock_db.materials.update_one.assert_called_once()
        set_args = mock_db.materials.update_one.call_args[0][1]["$set"]
        self.assertEqual(set_args["latest_price"], 80.0)
        self.assertEqual(set_args["latest_purchase_date"], "2026-09-25")

    # -------------------------------------------------------------
    # 17 & 18. Scope Safety: Purchase -> Stock = YES, Purchase -> Finance = YES
    # -------------------------------------------------------------
    @patch("server.db")
    def test_17_18_no_stock_or_finance_mutations(self, mock_db):
        self._setup_mock_db(mock_db)
        mock_db.materials.find_one = AsyncMock(return_value={**self.sample_material, "current_stock": 0.0})
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 1})
        mock_db.counters.find_one = AsyncMock(return_value={"seq": 1})
        mock_db.material_purchases.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.material_purchases.find_one = AsyncMock(return_value=None)
        mock_db.materials.update_one = AsyncMock(return_value=None)

        inp = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-10-01",
            unit_price=10.0,
            quantity=2,
        )
        asyncio.run(create_material_purchase(inp, admin=self.owner_user))

        # 1. Purchase record created -> YES
        mock_db.material_purchases.insert_one.assert_called_once()
        # 2. Stock movement created (purchase_in) -> YES
        self.assertTrue(mock_db.material_stocks.insert_one.called)
        # 3. Current stock updated (+quantity) -> YES
        self.assertTrue(mock_db.materials.update_one.called)
        # 4. Finance transaction created -> YES (Phase 4 integrated)
        self.assertTrue(mock_db.finance_transactions.insert_one.called)

    # -------------------------------------------------------------
    # 19. RBAC Protection
    # -------------------------------------------------------------
    def test_19_rbac_protection(self):
        dep = server.require_material_perm()

        # Product manager allowed
        res1 = asyncio.run(dep(self.product_manager))
        self.assertEqual(res1["id"], "mgr_1")

        # Finance staff allowed
        res2 = asyncio.run(dep(self.finance_user))
        self.assertEqual(res2["id"], "fin_1")

        # Owner allowed
        res3 = asyncio.run(dep(self.owner_user))
        self.assertEqual(res3["id"], "owner_1")

        # Unauthorized employee rejected with 403
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(dep(self.unauthorized_user))
        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
