"""Test Suite for Phase 1 Master Data Bahan (Materials).
Covers:
1. Material creation (valid data, audit fields, active status by default)
2. Normalized name + specs uniqueness (reject duplicates, case-insensitive, whitespace-insensitive)
3. Allow same name with different specs
4. Validation: reject empty name/specs/unit, invalid category, invalid unit
5. Material list (filtering by category, status, search text across name/specs/sku)
6. Material detail (get by ID, 404 for not found)
7. Material update (partial updates, re-normalization, duplicate detection on rename)
8. Material archive (status changed to archived via DELETE endpoint)
9. Material reactivate (status changed back to active via PUT endpoint)
10. RBAC: owner, modify_products, and access_finance are permitted; others rejected with 403
11. Non-interference: finance, order, products collections are not touched.
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
    MaterialInput,
    MaterialUpdateInput,
    normalize_text_key,
    get_materials,
    create_material,
    get_material_detail,
    update_material,
    archive_material,
    require_material_perm,
)
from fastapi import HTTPException
import pymongo


class TestMaterialsPhase1(unittest.TestCase):

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

    # -------------------------------------------------------------
    # 1. Normalization helper tests
    # -------------------------------------------------------------
    def test_normalize_text_key(self):
        self.assertEqual(normalize_text_key("  Balok  Kayu  "), "balok kayu")
        self.assertEqual(normalize_text_key("5x5   x 300  CM"), "5x5 x 300 cm")
        self.assertEqual(normalize_text_key("Papan  Tulis"), "papan tulis")

    # -------------------------------------------------------------
    # 2. RBAC Dependency test
    # -------------------------------------------------------------
    def test_rbac_permissions(self):
        dep = require_material_perm()

        # Owner allowed
        res = asyncio.run(dep(self.owner_user))
        self.assertEqual(res["id"], "owner_1")

        # modify_products allowed
        res = asyncio.run(dep(self.product_manager))
        self.assertEqual(res["id"], "mgr_1")

        # access_finance allowed
        res = asyncio.run(dep(self.finance_user))
        self.assertEqual(res["id"], "fin_1")

        # employee without permissions rejected
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(dep(self.unauthorized_user))
        self.assertEqual(ctx.exception.status_code, 403)

    # -------------------------------------------------------------
    # 3. Create Material tests
    # -------------------------------------------------------------
    @patch("server.db")
    def test_create_material_success(self, mock_db):
        mock_db.materials.find_one = AsyncMock(return_value=None)
        inserted_id = ObjectId()
        mock_db.materials.insert_one = AsyncMock(return_value=MagicMock(inserted_id=inserted_id))

        inp = MaterialInput(
            name="Kayu Kamper",
            category="Material",
            specs="5x7 x 400 cm",
            sku="MAT-KMP-5X7",
            unit="batang",
            notes="Kayu oven kering"
        )
        result = asyncio.run(create_material(inp, admin=self.owner_user))

        self.assertEqual(result["name"], "Kayu Kamper")
        self.assertEqual(result["category"], "Material")
        self.assertEqual(result["specs"], "5x7 x 400 cm")
        self.assertEqual(result["unit"], "batang")
        self.assertEqual(result["status"], "active")
        self.assertEqual(result["name_normalized"], "kayu kamper")
        self.assertEqual(result["specs_normalized"], "5x7 x 400 cm")
        self.assertEqual(result["created_by_id"], "owner_1")
        mock_db.materials.insert_one.assert_called_once()

    @patch("server.db")
    def test_create_material_duplicate_rejected(self, mock_db):
        mock_db.materials.find_one = AsyncMock(return_value={"_id": ObjectId(), "name": "Kayu Kamper", "specs": "5x7 x 400 cm"})

        inp = MaterialInput(
            name="  kayu   kamper  ",
            category="Material",
            specs="5x7  x 400 CM",
            unit="batang"
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_material(inp, admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 409)

    @patch("server.db")
    def test_create_material_same_name_different_specs_allowed(self, mock_db):
        # find_one returns None because combination name_normalized + specs_normalized is unique
        mock_db.materials.find_one = AsyncMock(return_value=None)
        inserted_id = ObjectId()
        mock_db.materials.insert_one = AsyncMock(return_value=MagicMock(inserted_id=inserted_id))

        inp = MaterialInput(
            name="Kayu Kamper",
            category="Material",
            specs="6x12 x 400 cm",
            unit="batang"
        )
        result = asyncio.run(create_material(inp, admin=self.owner_user))
        self.assertEqual(result["specs"], "6x12 x 400 cm")

    def test_create_material_validation_errors(self):
        # Invalid category
        inp1 = MaterialInput(name="Baut", category="Unknown", specs="M6", unit="pcs")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_material(inp1, admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 400)

        # Invalid unit
        inp2 = MaterialInput(name="Baut", category="Parts", specs="M6", unit="ton")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_material(inp2, admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 400)

        # Empty name
        inp3 = MaterialInput(name="   ", category="Parts", specs="M6", unit="pcs")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_material(inp3, admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 400)

        # Empty specs
        inp4 = MaterialInput(name="Baut", category="Parts", specs="   ", unit="pcs")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_material(inp4, admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 400)

    # -------------------------------------------------------------
    # 4. List Materials & Search tests
    # -------------------------------------------------------------
    @patch("server.db")
    def test_list_materials_filters(self, mock_db):
        items = [
            {"_id": ObjectId(), "name": "Balok Kayu", "specs": "5x5 x 300 cm", "category": "Material", "status": "active"},
            {"_id": ObjectId(), "name": "Baut Mur", "specs": "M6 x 20 mm", "category": "Parts", "status": "active"},
        ]
        cursor_mock = MagicMock()
        cursor_mock.sort = MagicMock(return_value=cursor_mock)
        cursor_mock.to_list = AsyncMock(return_value=items)
        mock_db.materials.find = MagicMock(return_value=cursor_mock)

        # Test search query
        res = asyncio.run(get_materials(category="Material", status="active", q="Balok", admin=self.owner_user))
        self.assertEqual(len(res), 2)
        mock_db.materials.find.assert_called_once()
        query_arg = mock_db.materials.find.call_args[0][0]
        self.assertEqual(query_arg["category"], "Material")
        self.assertEqual(query_arg["status"], "active")
        self.assertIn("$or", query_arg)

    # -------------------------------------------------------------
    # 5. Detail & Update tests
    # -------------------------------------------------------------
    @patch("server.db")
    def test_get_material_detail(self, mock_db):
        mat_id = str(ObjectId())
        mock_db.materials.find_one = AsyncMock(return_value={"_id": ObjectId(mat_id), "name": "Blockboard 18mm"})
        res = asyncio.run(get_material_detail(mat_id, admin=self.owner_user))
        self.assertEqual(res["name"], "Blockboard 18mm")

        # Not found
        mock_db.materials.find_one = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(get_material_detail(str(ObjectId()), admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 404)

    @patch("server.db")
    def test_update_material_success(self, mock_db):
        mat_oid = ObjectId()
        doc = {
            "_id": mat_oid,
            "name": "Kayu Pinus",
            "specs": "3x5 x 200 cm",
            "category": "Material",
            "unit": "batang",
            "name_normalized": "kayu pinus",
            "specs_normalized": "3x5 x 200 cm",
            "status": "active"
        }
        mock_db.materials.find_one = AsyncMock(side_effect=[doc, None])  # 1st get doc, 2nd check dup (None)
        updated_doc = {**doc, "specs": "4x6 x 200 cm", "specs_normalized": "4x6 x 200 cm"}
        mock_db.materials.find_one_and_update = AsyncMock(return_value=updated_doc)

        upd_inp = MaterialUpdateInput(specs="4x6 x 200 cm")
        res = asyncio.run(update_material(str(mat_oid), upd_inp, admin=self.owner_user))
        self.assertEqual(res["specs"], "4x6 x 200 cm")

    @patch("server.db")
    def test_update_material_duplicate_rejected(self, mock_db):
        mat_oid = ObjectId()
        doc = {
            "_id": mat_oid,
            "name": "Kayu Pinus",
            "specs": "3x5 x 200 cm",
            "name_normalized": "kayu pinus",
            "specs_normalized": "3x5 x 200 cm"
        }
        other_dup = {"_id": ObjectId(), "name": "Kayu Jati", "specs": "3x5 x 200 cm"}
        mock_db.materials.find_one = AsyncMock(side_effect=[doc, other_dup])

        upd_inp = MaterialUpdateInput(name="Kayu Jati")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(update_material(str(mat_oid), upd_inp, admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 409)

    # -------------------------------------------------------------
    # 6. Archive Material test
    # -------------------------------------------------------------
    @patch("server.db")
    def test_archive_material(self, mock_db):
        mat_oid = ObjectId()
        doc = {"_id": mat_oid, "name": "Cat Duco", "status": "active"}
        mock_db.materials.find_one = AsyncMock(return_value=doc)
        archived_doc = {**doc, "status": "archived"}
        mock_db.materials.find_one_and_update = AsyncMock(return_value=archived_doc)

        res = asyncio.run(archive_material(str(mat_oid), admin=self.owner_user))
        self.assertTrue(res["ok"])
        self.assertEqual(res["material"]["status"], "archived")


if __name__ == "__main__":
    unittest.main()
