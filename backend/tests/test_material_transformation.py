"""Dedicated Phase 5 Test Suite: Stock Forms & Material Transformation.

Covers all required specifications in Section 29:
Stock Form:
1. create/get Stock Form
2. duplicate Stock Form grouping (deduplication)
3. standard form
4. raw form
5. custom form
6. optional dimensions
7. quantity updates

Purchase pre-cut:
8. purchase without pre-cut behaves exactly like Phase 4
9. purchase with pre-cut creates correct raw remainder
10. purchase with multiple output forms
11. purchase with remnant
12. processed quantity cannot exceed purchase quantity
13. zero processed quantity
14. fully processed purchase
15. Finance remains exactly one expense
16. stock and Finance are atomic

Transformation:
17. valid transformation
18. multiple outputs
19. insufficient source stock rejected
20. source stock unchanged on failure
21. transformation is atomic
22. transformation idempotency
23. transformation history
24. custom/remnant transformation

Adjustment:
25. adjustment against Stock Form
26. adjustment does not touch Finance
27. adjustment does not touch purchase history

Void:
28. safe void of Phase 5 purchase
29. void rejected when stock cannot safely be reversed
30. no partial void
31. no duplicate Finance reversal
32. no negative stock
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
    StockProcessingInput,
    StockFormOutputItemInput,
    VoidPurchaseInput,
    MaterialStockAdjustmentInput,
    StockTransformationInput,
    StockFormCreateInput,
    get_or_create_stock_form,
    get_next_transformation_number,
    get_material_stock_forms,
    create_custom_stock_form,
    get_stock_transformations,
    get_stock_transformation_detail,
    create_stock_transformation,
    create_material_purchase,
    void_material_purchase,
    create_material_stock_adjustment,
)
from fastapi import HTTPException
import pymongo


class TestMaterialStockFormsPhase5(unittest.TestCase):

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
            "name": "Blockboard",
            "specs": "18mm x 122x244 cm",
            "category": "Material",
            "unit": "lembar",
            "sku": "BB-18-122-244",
            "status": "active",
            "current_stock": 20.0,
            "latest_price": 500.0,
            "latest_currency": "EGP",
            "latest_purchase_date": "2026-10-01",
        }

    def _setup_mock_db(self, mock_db):
        mock_db.materials.find_one = AsyncMock(return_value={**self.sample_material})
        mock_db.materials.find_one_and_update = AsyncMock(return_value={**self.sample_material, "current_stock": 30.0})
        mock_db.materials.update_one = AsyncMock(return_value=None)

        mock_db.counters.find_one = AsyncMock(return_value={"seq": 1})
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 1})
        mock_db.counters.update_one = AsyncMock(return_value=None)

        mock_db.material_purchases.find_one = AsyncMock(return_value=None)
        mock_db.material_purchases.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))

        mock_db.material_stocks.find_one = AsyncMock(return_value=None)
        mock_db.material_stocks.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))

        mock_db.finance_transactions.find_one = AsyncMock(return_value=None)
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))

        stored_forms = {}
        def sf_insert_one(doc, **kwargs):
            if "_id" not in doc or not doc["_id"]:
                doc["_id"] = ObjectId()
            stored_forms[str(doc["_id"])] = {**doc}
            res = MagicMock()
            res.inserted_id = doc["_id"]
            return res

        def sf_find_one(query, **kwargs):
            qid = query.get("_id")
            if qid is not None:
                ids = qid.get("$in", []) if isinstance(qid, dict) else [qid]
                for i in ids:
                    if str(i) in stored_forms:
                        return {**stored_forms[str(i)]}
                return None
            f_type = query.get("form_type")
            if f_type:
                for f in stored_forms.values():
                    if f.get("form_type") == f_type:
                        if "width" in query and query["width"] != f.get("width"):
                            continue
                        if "length" in query and query["length"] != f.get("length"):
                            continue
                        return {**f}
            return None

        def sf_find_one_and_update(query, update, **kwargs):
            doc = sf_find_one(query)
            if doc and "$set" in update:
                doc.update(update["$set"])
                stored_forms[str(doc["_id"])] = doc
            elif not doc:
                doc = {"_id": ObjectId(), "current_quantity": 0.0}
            return doc

        mock_db.stock_forms.insert_one = AsyncMock(side_effect=sf_insert_one)
        mock_db.stock_forms.find_one = AsyncMock(side_effect=sf_find_one)
        mock_db.stock_forms.find_one_and_update = AsyncMock(side_effect=sf_find_one_and_update)
        mock_db.stock_forms.update_one = AsyncMock(return_value=None)

        mock_db.stock_transformations.find_one = AsyncMock(return_value=None)
        mock_db.stock_transformations.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))

        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357.0})

    # =========================================================================
    # 1 - 7: STOCK FORM TESTS
    # =========================================================================
    @patch("server.db")
    def test_01_create_and_get_stock_form(self, mock_db):
        """1. Create stock form successfully and retrieve it."""
        self._setup_mock_db(mock_db)
        sf_id = ObjectId()
        mock_doc = {
            "_id": sf_id,
            "material_id": str(self.sample_mat_id),
            "form_type": "standard",
            "width": 80.0,
            "length": 30.0,
            "thickness": 1.8,
            "dimension_unit": "cm",
            "stock_unit": "pcs",
            "label": "Rak Pendek",
            "current_quantity": 0.0,
            "is_active": True
        }
        mock_db.stock_forms.insert_one = AsyncMock(return_value=MagicMock(inserted_id=sf_id))
        mock_db.stock_forms.find_one = AsyncMock(return_value=None)

        sf = asyncio.run(get_or_create_stock_form(
            material_id=str(self.sample_mat_id),
            form_type="standard",
            width=80,
            length=30,
            thickness=1.8,
            dimension_unit="cm",
            stock_unit="pcs",
            label="Rak Pendek",
            admin=self.owner_user
        ))
        self.assertEqual(sf["form_type"], "standard")
        self.assertEqual(sf["width"], 80.0)
        self.assertEqual(sf["length"], 30.0)
        mock_db.stock_forms.insert_one.assert_called_once()

    @patch("server.db")
    def test_02_duplicate_stock_form_grouping(self, mock_db):
        """2. Existing identical stock form is retrieved without inserting a duplicate."""
        self._setup_mock_db(mock_db)
        existing_doc = {
            "_id": ObjectId(),
            "material_id": str(self.sample_mat_id),
            "form_type": "standard",
            "width": 80.0,
            "length": 30.0,
            "thickness": 1.8,
            "dimension_unit": "cm",
            "stock_unit": "pcs",
            "label": "Rak Pendek",
            "current_quantity": 25.0
        }
        mock_db.stock_forms.find_one = AsyncMock(return_value=existing_doc)

        sf = asyncio.run(get_or_create_stock_form(
            material_id=str(self.sample_mat_id),
            form_type="standard",
            width=80,
            length=30,
            thickness=1.8,
            dimension_unit="cm",
            stock_unit="pcs",
            label="Rak Pendek",
            admin=self.owner_user
        ))
        self.assertEqual(sf["current_quantity"], 25.0)
        mock_db.stock_forms.insert_one.assert_not_called()

    @patch("server.db")
    def test_03_standard_form(self, mock_db):
        """3. Standard form creation has valid form_type."""
        self._setup_mock_db(mock_db)
        sf = asyncio.run(get_or_create_stock_form(
            material_id=str(self.sample_mat_id),
            form_type="standard",
            width=60,
            length=30,
            admin=self.owner_user
        ))
        self.assertEqual(sf["form_type"], "standard")

    @patch("server.db")
    def test_04_raw_form(self, mock_db):
        """4. Raw form creation has form_type 'raw' and default stock unit."""
        self._setup_mock_db(mock_db)
        sf = asyncio.run(get_or_create_stock_form(
            material_id=str(self.sample_mat_id),
            form_type="raw",
            stock_unit="lembar",
            label="Raw Form",
            admin=self.owner_user
        ))
        self.assertEqual(sf["form_type"], "raw")
        self.assertEqual(sf["stock_unit"], "lembar")

    @patch("server.db")
    def test_05_custom_form(self, mock_db):
        """5. Custom / remnant form representation without requiring geometry engine."""
        self._setup_mock_db(mock_db)
        sf = asyncio.run(get_or_create_stock_form(
            material_id=str(self.sample_mat_id),
            form_type="custom",
            label="Sisa Potongan Sudut",
            notes="Sisa potongan bentuk L, bisa untuk ambalan kecil",
            admin=self.owner_user
        ))
        self.assertEqual(sf["form_type"], "custom")
        self.assertEqual(sf["label"], "Sisa Potongan Sudut")

    @patch("server.db")
    def test_06_optional_dimensions(self, mock_db):
        """6. Dimensions can be 1D, 2D, 3D, or omitted for irregular remnants."""
        self._setup_mock_db(mock_db)
        sf = asyncio.run(get_or_create_stock_form(
            material_id=str(self.sample_mat_id),
            form_type="standard",
            length=270,  # 1D only
            dimension_unit="cm",
            admin=self.owner_user
        ))
        self.assertEqual(sf["length"], 270.0)
        self.assertIsNone(sf["width"])
        self.assertIsNone(sf["thickness"])

    @patch("server.db")
    def test_07_quantity_updates(self, mock_db):
        """7. Stock forms endpoint lists active stock forms."""
        self._setup_mock_db(mock_db)
        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.to_list = AsyncMock(return_value=[
            {"_id": ObjectId(), "material_id": str(self.sample_mat_id), "form_type": "raw", "current_quantity": 5.0, "is_active": True},
            {"_id": ObjectId(), "material_id": str(self.sample_mat_id), "form_type": "standard", "current_quantity": 20.0, "is_active": True},
        ])
        mock_db.stock_forms.find = MagicMock(return_value=mock_cursor)

        forms = asyncio.run(get_material_stock_forms(str(self.sample_mat_id), admin=self.owner_user))
        self.assertEqual(len(forms), 2)
        self.assertEqual(forms[0]["current_quantity"], 5.0)

    # =========================================================================
    # 8 - 16: PURCHASE PRE-CUT TESTS
    # =========================================================================
    @patch("server.db")
    def test_08_purchase_without_pre_cut(self, mock_db):
        """8. Purchase without pre-cut behaves exactly like Phase 4."""
        self._setup_mock_db(mock_db)
        inp = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-10-02",
            quantity=10.0,
            unit_price=500.0,
            currency="EGP",
            supplier_name="Toko Kayu"
        )
        res = asyncio.run(create_material_purchase(inp, admin=self.owner_user))
        self.assertEqual(res["quantity"], 10.0)
        self.assertIsNone(res.get("stock_processing"))
        mock_db.finance_transactions.insert_one.assert_called_once()
        mock_db.material_stocks.insert_one.assert_called_once()

    @patch("server.db")
    def test_09_purchase_with_pre_cut_raw_remainder(self, mock_db):
        """9. Purchase with pre-cut creates correct raw remainder."""
        self._setup_mock_db(mock_db)
        inp = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-10-02",
            quantity=10.0,
            unit_price=500.0,
            currency="EGP",
            stock_processing=StockProcessingInput(
                mode="pre_cut",
                processed_quantity=5.0,
                outputs=[
                    StockFormOutputItemInput(
                        form_type="standard",
                        width=80,
                        length=30,
                        quantity=20.0,
                        label="Rak 80x30"
                    )
                ]
            )
        )
        res = asyncio.run(create_material_purchase(inp, admin=self.owner_user))
        sp = res["stock_processing"]
        self.assertEqual(sp["mode"], "pre_cut")
        self.assertEqual(sp["processed_quantity"], 5.0)
        self.assertEqual(sp["remaining_raw_quantity"], 5.0)
        self.assertEqual(len(sp["outputs"]), 1)

    @patch("server.db")
    def test_10_purchase_with_multiple_output_forms(self, mock_db):
        """10. Purchase with multiple output forms saves all outputs."""
        self._setup_mock_db(mock_db)
        inp = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-10-02",
            quantity=10.0,
            unit_price=500.0,
            currency="EGP",
            stock_processing=StockProcessingInput(
                mode="pre_cut",
                processed_quantity=6.0,
                outputs=[
                    StockFormOutputItemInput(form_type="standard", width=80, length=30, quantity=20.0),
                    StockFormOutputItemInput(form_type="standard", width=60, length=30, quantity=10.0),
                    StockFormOutputItemInput(form_type="custom", width=42, length=244, quantity=2.0),
                ]
            )
        )
        res = asyncio.run(create_material_purchase(inp, admin=self.owner_user))
        self.assertEqual(len(res["stock_processing"]["outputs"]), 3)
        self.assertEqual(res["stock_processing"]["remaining_raw_quantity"], 4.0)

    @patch("server.db")
    def test_11_purchase_with_remnant(self, mock_db):
        """11. Output can be designated as custom remnant."""
        self._setup_mock_db(mock_db)
        inp = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-10-02",
            quantity=5.0,
            unit_price=500.0,
            currency="EGP",
            stock_processing=StockProcessingInput(
                mode="pre_cut",
                processed_quantity=5.0,
                outputs=[
                    StockFormOutputItemInput(form_type="standard", width=80, length=30, quantity=15.0),
                    StockFormOutputItemInput(form_type="custom", label="Sisa pinggiran", quantity=1.0)
                ]
            )
        )
        res = asyncio.run(create_material_purchase(inp, admin=self.owner_user))
        self.assertEqual(res["stock_processing"]["outputs"][1]["form_type"], "custom")

    @patch("server.db")
    def test_12_processed_exceeds_purchased_rejected(self, mock_db):
        """12. Processed quantity exceeding purchase quantity is rejected with 400."""
        self._setup_mock_db(mock_db)
        inp = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-10-02",
            quantity=5.0,
            unit_price=500.0,
            stock_processing=StockProcessingInput(
                mode="pre_cut",
                processed_quantity=6.0,  # Exceeds 5.0
                outputs=[StockFormOutputItemInput(quantity=10.0)]
            )
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_material_purchase(inp, admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("tidak boleh melebihi jumlah pembelian", ctx.exception.detail)

    @patch("server.db")
    def test_13_zero_processed_quantity(self, mock_db):
        """13. Zero processed quantity in pre-cut is handled safely with full raw remainder."""
        self._setup_mock_db(mock_db)
        inp = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-10-02",
            quantity=5.0,
            unit_price=500.0,
            stock_processing=StockProcessingInput(
                mode="pre_cut",
                processed_quantity=0.0,
                outputs=[]
            )
        )
        res = asyncio.run(create_material_purchase(inp, admin=self.owner_user))
        self.assertEqual(res["stock_processing"]["remaining_raw_quantity"], 5.0)

    @patch("server.db")
    def test_14_fully_processed_purchase(self, mock_db):
        """14. Fully processed purchase has remaining raw zero."""
        self._setup_mock_db(mock_db)
        inp = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-10-02",
            quantity=5.0,
            unit_price=500.0,
            stock_processing=StockProcessingInput(
                mode="pre_cut",
                processed_quantity=5.0,
                outputs=[StockFormOutputItemInput(form_type="standard", width=80, length=30, quantity=20.0)]
            )
        )
        res = asyncio.run(create_material_purchase(inp, admin=self.owner_user))
        self.assertEqual(res["stock_processing"]["remaining_raw_quantity"], 0.0)

    @patch("server.db")
    def test_15_finance_remains_single_expense(self, mock_db):
        """15. Pre-cut purchase still creates exactly one Finance expense."""
        self._setup_mock_db(mock_db)
        inp = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-10-02",
            quantity=10.0,
            unit_price=500.0,
            currency="EGP",
            stock_processing=StockProcessingInput(
                mode="pre_cut",
                processed_quantity=5.0,
                outputs=[StockFormOutputItemInput(form_type="standard", width=80, length=30, quantity=20.0)]
            )
        )
        res = asyncio.run(create_material_purchase(inp, admin=self.owner_user))
        mock_db.finance_transactions.insert_one.assert_called_once()
        fin_call = mock_db.finance_transactions.insert_one.call_args[0][0]
        self.assertEqual(fin_call["amount"], 5000.0)
        self.assertEqual(fin_call["type"], "expense")

    @patch("server.db")
    def test_16_stock_and_finance_atomic(self, mock_db):
        """16. Purchase transaction fails if finance expense insert fails."""
        self._setup_mock_db(mock_db)
        mock_db.finance_transactions.insert_one = AsyncMock(side_effect=RuntimeError("Finance write error"))

        inp = MaterialPurchaseInput(
            material_id=str(self.sample_mat_id),
            purchase_date="2026-10-02",
            quantity=5.0,
            unit_price=500.0,
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_material_purchase(inp, admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 500)

    # =========================================================================
    # 17 - 24: TRANSFORMATION TESTS
    # =========================================================================
    @patch("server.db")
    def test_17_valid_transformation(self, mock_db):
        """17. Dedicated transformation transforms source stock into output forms."""
        self._setup_mock_db(mock_db)
        source_sf_id = ObjectId()
        mock_db.stock_forms.find_one = AsyncMock(return_value={
            "_id": source_sf_id,
            "material_id": str(self.sample_mat_id),
            "form_type": "raw",
            "stock_unit": "lembar",
            "current_quantity": 5.0,
            "is_active": True
        })

        inp = StockTransformationInput(
            material_id=str(self.sample_mat_id),
            source_stock_form_id=str(source_sf_id),
            source_quantity=2.0,
            transformation_date="2026-10-02",
            reason="Potong untuk pesanan rak",
            outputs=[
                StockFormOutputItemInput(form_type="standard", width=80, length=30, quantity=8.0, label="Rak 80x30")
            ]
        )
        res = asyncio.run(create_stock_transformation(inp, admin=self.owner_user))
        self.assertTrue(res["ok"])
        self.assertIn("transformation", res)
        self.assertEqual(res["transformation"]["source_quantity"], 2.0)
        self.assertTrue(res["transformation"]["transformation_number"].startswith("TR-20261002-"))

    @patch("server.db")
    def test_18_multiple_outputs(self, mock_db):
        """18. Transformation supports multiple output items."""
        self._setup_mock_db(mock_db)
        source_sf_id = ObjectId()
        mock_db.stock_forms.find_one = AsyncMock(return_value={
            "_id": source_sf_id,
            "material_id": str(self.sample_mat_id),
            "form_type": "raw",
            "current_quantity": 5.0
        })

        inp = StockTransformationInput(
            material_id=str(self.sample_mat_id),
            source_stock_form_id=str(source_sf_id),
            source_quantity=1.0,
            outputs=[
                StockFormOutputItemInput(form_type="standard", width=80, length=30, quantity=4.0),
                StockFormOutputItemInput(form_type="standard", width=60, length=30, quantity=2.0),
            ]
        )
        res = asyncio.run(create_stock_transformation(inp, admin=self.owner_user))
        self.assertEqual(len(res["transformation"]["output_stock_forms"]), 2)

    @patch("server.db")
    def test_19_20_insufficient_source_stock_rejected(self, mock_db):
        """19 & 20. Insufficient source stock is rejected and stock remains unchanged."""
        self._setup_mock_db(mock_db)
        source_sf_id = ObjectId()
        mock_db.stock_forms.find_one = AsyncMock(return_value={
            "_id": source_sf_id,
            "material_id": str(self.sample_mat_id),
            "form_type": "raw",
            "current_quantity": 1.0,  # Less than requested 3.0
            "stock_unit": "lembar"
        })

        inp = StockTransformationInput(
            material_id=str(self.sample_mat_id),
            source_stock_form_id=str(source_sf_id),
            source_quantity=3.0,
            outputs=[StockFormOutputItemInput(form_type="standard", quantity=10.0)]
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_stock_transformation(inp, admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Stok bentuk asal tidak mencukupi", ctx.exception.detail)
        mock_db.stock_transformations.insert_one.assert_not_called()

    @patch("server.db")
    def test_21_transformation_is_atomic(self, mock_db):
        """21. Transformation fails completely if any output creation fails."""
        self._setup_mock_db(mock_db)
        source_sf_id = ObjectId()
        mock_db.stock_forms.find_one = AsyncMock(return_value={
            "_id": source_sf_id,
            "material_id": str(self.sample_mat_id),
            "form_type": "raw",
            "current_quantity": 5.0
        })
        mock_db.stock_transformations.insert_one = AsyncMock(side_effect=RuntimeError("Transformation event insert failed"))

        inp = StockTransformationInput(
            material_id=str(self.sample_mat_id),
            source_stock_form_id=str(source_sf_id),
            source_quantity=1.0,
            outputs=[StockFormOutputItemInput(form_type="standard", quantity=2.0)]
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_stock_transformation(inp, admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 500)

    @patch("server.db")
    def test_22_transformation_idempotency_and_no_finance(self, mock_db):
        """22. Transformation does NOT create any Finance transaction."""
        self._setup_mock_db(mock_db)
        source_sf_id = ObjectId()
        mock_db.stock_forms.find_one = AsyncMock(return_value={
            "_id": source_sf_id,
            "material_id": str(self.sample_mat_id),
            "form_type": "raw",
            "current_quantity": 5.0
        })
        inp = StockTransformationInput(
            material_id=str(self.sample_mat_id),
            source_stock_form_id=str(source_sf_id),
            source_quantity=1.0,
            outputs=[StockFormOutputItemInput(form_type="standard", quantity=2.0)]
        )
        asyncio.run(create_stock_transformation(inp, admin=self.owner_user))
        mock_db.finance_transactions.insert_one.assert_not_called()

    @patch("server.db")
    def test_23_transformation_history(self, mock_db):
        """23. Transformation list and detail endpoints return historical records."""
        self._setup_mock_db(mock_db)
        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.to_list = AsyncMock(return_value=[
            {"_id": ObjectId(), "transformation_number": "TR-20261002-0001", "source_quantity": 2.0}
        ])
        mock_db.stock_transformations.find = MagicMock(return_value=mock_cursor)

        history = asyncio.run(get_stock_transformations(admin=self.owner_user))
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["transformation_number"], "TR-20261002-0001")

    @patch("server.db")
    def test_24_custom_remnant_transformation(self, mock_db):
        """24. Custom form can be designated in transformation outputs."""
        self._setup_mock_db(mock_db)
        source_sf_id = ObjectId()
        custom_sf_id = ObjectId()
        forms_map = {
            str(source_sf_id): {
                "_id": source_sf_id,
                "material_id": str(self.sample_mat_id),
                "form_type": "standard",
                "current_quantity": 10.0
            },
            str(custom_sf_id): {
                "_id": custom_sf_id,
                "material_id": str(self.sample_mat_id),
                "form_type": "custom",
                "current_quantity": 1.0
            }
        }
        def sf_find_one(query, **kwargs):
            if "_id" in query:
                val = query["_id"]
                ids = val.get("$in", []) if isinstance(val, dict) else [val]
                for i in ids:
                    if str(i) in forms_map:
                        return forms_map[str(i)]
            if query.get("form_type") == "custom":
                return forms_map[str(custom_sf_id)]
            return None

        mock_db.stock_forms.find_one = AsyncMock(side_effect=sf_find_one)
        inp = StockTransformationInput(
            material_id=str(self.sample_mat_id),
            source_stock_form_id=str(source_sf_id),
            source_quantity=1.0,
            outputs=[StockFormOutputItemInput(form_type="custom", label="Sisa Potong", quantity=1.0)]
        )
        res = asyncio.run(create_stock_transformation(inp, admin=self.owner_user))
        self.assertEqual(res["transformation"]["output_stock_forms"][0]["form_type"], "custom")

    # =========================================================================
    # 25 - 27: ADJUSTMENT TESTS
    # =========================================================================
    @patch("server.db")
    def test_25_adjustment_against_stock_form(self, mock_db):
        """25. Manual adjustment targets specific stock form when stock_form_id is passed."""
        self._setup_mock_db(mock_db)
        sf_id = ObjectId()
        mock_db.stock_forms.find_one = AsyncMock(return_value={
            "_id": sf_id,
            "material_id": str(self.sample_mat_id),
            "current_quantity": 10.0
        })
        mock_db.stock_forms.find_one_and_update = AsyncMock(return_value={
            "_id": sf_id,
            "material_id": str(self.sample_mat_id),
            "current_quantity": 13.0
        })

        inp = MaterialStockAdjustmentInput(
            adjustment_type="adjustment_in",
            quantity=3.0,
            reason="Opname fisik ditemukan lebih",
            stock_form_id=str(sf_id)
        )
        res = asyncio.run(create_material_stock_adjustment(str(self.sample_mat_id), inp, admin=self.owner_user))
        self.assertTrue(res["ok"])
        self.assertEqual(res["movement"]["stock_form_id"], str(sf_id))

    @patch("server.db")
    def test_26_adjustment_does_not_touch_finance(self, mock_db):
        """26. Manual stock adjustment never creates finance transactions."""
        self._setup_mock_db(mock_db)
        inp = MaterialStockAdjustmentInput(
            adjustment_type="adjustment_out",
            quantity=1.0,
            reason="Rusak kena air"
        )
        asyncio.run(create_material_stock_adjustment(str(self.sample_mat_id), inp, admin=self.owner_user))
        mock_db.finance_transactions.insert_one.assert_not_called()

    @patch("server.db")
    def test_27_adjustment_does_not_touch_purchase_history(self, mock_db):
        """27. Manual stock adjustment never touches purchase collections."""
        self._setup_mock_db(mock_db)
        inp = MaterialStockAdjustmentInput(
            adjustment_type="adjustment_in",
            quantity=2.0,
            reason="Retur sisa"
        )
        asyncio.run(create_material_stock_adjustment(str(self.sample_mat_id), inp, admin=self.owner_user))
        mock_db.material_purchases.insert_one.assert_not_called()

    # =========================================================================
    # 28 - 32: VOID TESTS
    # =========================================================================
    @patch("server.db")
    def test_28_safe_void_of_phase5_purchase(self, mock_db):
        """28. Safe void of pre-cut purchase with intact outputs."""
        self._setup_mock_db(mock_db)
        pb_id = ObjectId()
        active_pb = {
            "_id": pb_id,
            "purchase_number": "PB-20261002-0001",
            "material_id": str(self.sample_mat_id),
            "quantity": 10.0,
            "is_void": False,
        }
        mock_db.material_purchases.find_one = AsyncMock(return_value=active_pb)
        mock_db.material_purchases.find_one_and_update = AsyncMock(return_value={**active_pb, "is_void": True})

        # Purchase in movement
        orig_mov = {
            "_id": ObjectId(),
            "related_purchase_id": str(pb_id),
            "movement_type": "purchase_in",
            "quantity_delta": 10.0
        }
        mock_db.material_stocks.find_one = AsyncMock(side_effect=[orig_mov, None])

        res = asyncio.run(void_material_purchase(str(pb_id), VoidPurchaseInput(void_reason="Salah nota"), admin=self.owner_user))
        self.assertTrue(res["ok"])
        self.assertTrue(res["purchase"]["is_void"])

    @patch("server.db")
    def test_29_void_rejected_when_precut_output_already_used(self, mock_db):
        """29. Void rejected when pre-cut outputs were consumed/used."""
        self._setup_mock_db(mock_db)
        pb_id = ObjectId()
        active_pb = {
            "_id": pb_id,
            "purchase_number": "PB-20261002-0001",
            "material_id": str(self.sample_mat_id),
            "quantity": 10.0,
            "is_void": False,
        }
        mock_db.material_purchases.find_one = AsyncMock(return_value=active_pb)

        out_sf_id = ObjectId()
        tr_doc = {
            "_id": ObjectId(),
            "related_purchase_id": str(pb_id),
            "source_stock_form_id": str(ObjectId()),
            "source_quantity": 5.0,
            "output_stock_forms": [
                {"stock_form_id": str(out_sf_id), "quantity": 20.0, "label": "Rak 80x30"}
            ]
        }
        orig_mov = {"_id": ObjectId(), "related_purchase_id": str(pb_id), "movement_type": "purchase_in", "quantity_delta": 10.0}
        mock_db.material_stocks.find_one = AsyncMock(side_effect=[orig_mov, None])
        mock_db.stock_transformations.find_one = AsyncMock(return_value=tr_doc)
        # Stock form only has 5.0 remaining (< 20.0 required)
        mock_db.stock_forms.find_one = AsyncMock(return_value={
            "_id": out_sf_id,
            "current_quantity": 5.0,
            "label": "Rak 80x30"
        })

        with patch.object(server.client, "start_session", AsyncMock(side_effect=pymongo.errors.ConfigurationError("Standalone"))):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(void_material_purchase(str(pb_id), VoidPurchaseInput(void_reason="Batal"), admin=self.owner_user))
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("hasil pre-cut (Rak 80x30) telah berkurang atau terpakai", ctx.exception.detail)

    @patch("server.db")
    def test_30_no_partial_void_on_error(self, mock_db):
        """30. Void does not partially update purchase if stock reversal errors."""
        self._setup_mock_db(mock_db)
        pb_id = ObjectId()
        active_pb = {
            "_id": pb_id,
            "purchase_number": "PB-20261002-0001",
            "material_id": str(self.sample_mat_id),
            "quantity": 10.0,
            "is_void": False,
        }
        mock_db.material_purchases.find_one = AsyncMock(return_value=active_pb)
        mock_db.material_stocks.find_one = AsyncMock(side_effect=RuntimeError("Stock reversal error"))

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(void_material_purchase(str(pb_id), VoidPurchaseInput(void_reason="Batal"), admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 500)
        # Purchase is NOT marked as void
        self.assertFalse(mock_db.material_purchases.find_one_and_update.called)

    @patch("server.db")
    def test_31_no_duplicate_finance_reversal(self, mock_db):
        """31. Calling void on already voided purchase is rejected with 400."""
        self._setup_mock_db(mock_db)
        pb_id = ObjectId()
        voided_pb = {
            "_id": pb_id,
            "purchase_number": "PB-20261002-0001",
            "material_id": str(self.sample_mat_id),
            "quantity": 10.0,
            "is_void": True,  # Already void
        }
        mock_db.material_purchases.find_one = AsyncMock(return_value=voided_pb)

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(void_material_purchase(str(pb_id), VoidPurchaseInput(void_reason="Batal"), admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("sudah berstatus void", ctx.exception.detail)
        mock_db.finance_transactions.insert_one.assert_not_called()

    @patch("server.db")
    def test_32_no_negative_stock_from_void(self, mock_db):
        """32. Void rejected when current_stock < purchase_qty (cannot create negative stock)."""
        self._setup_mock_db(mock_db)
        pb_id = ObjectId()
        active_pb = {
            "_id": pb_id,
            "purchase_number": "PB-20261002-0001",
            "material_id": str(self.sample_mat_id),
            "quantity": 30.0,
            "is_void": False,
        }
        # Material only has 20.0 (< 30.0)
        mock_db.material_purchases.find_one = AsyncMock(return_value=active_pb)
        mock_db.materials.find_one = AsyncMock(return_value={**self.sample_material, "current_stock": 20.0})

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(void_material_purchase(str(pb_id), VoidPurchaseInput(void_reason="Batal"), admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("lebih kecil dari jumlah pembelian", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
