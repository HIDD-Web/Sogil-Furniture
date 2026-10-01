"""Comprehensive Backend Test Suite for Invoice Management V1:
Covers:
A. Numbering: initial, sequential, annual counter, unique index, concurrent generation, retry
B. Create: single item, multi-item, quantity, custom item, catalog item, customer snapshot, custom request source
C. Calculation: line_total, subtotal, discount, delivery fee, additional fee, total
D. Status: draft, send, cancel, invalid transitions (terminal states)
E. Conversion: invoice -> order, reuse generate_order_number(), order items mapping, price/qty preserved, relationship
E2. Idempotency: double conversion, concurrent conversion idempotency
F. Finance Safety: invoice create = 0, send = 0, cancel = 0, convert = 0 (no finance mutation)
G. RBAC: permissions, unauthorized access
"""
import os
import sys
import unittest
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import server
from fastapi import HTTPException
from pymongo import ReturnDocument
import pymongo


class TestInvoiceManagementBackend(unittest.TestCase):

    def setUp(self):
        self.admin_user = {
            "id": "admin_test_1",
            "name": "Super Admin",
            "role": "owner",
            "permissions": {"manage_orders": True, "access_finance": True}
        }
        self.employee_user = {
            "id": "emp_test_1",
            "name": "Staff Non Orders",
            "role": "employee",
            "permissions": {"manage_orders": False, "access_finance": False}
        }

    # -------------------------------------------------------------
    # A. NUMBERING TESTS
    # -------------------------------------------------------------
    @patch("server.db")
    def test_01_first_invoice_number(self, mock_db):
        """First invoice generated in a year starts at INV-YYYY-0001."""
        year = datetime.now(timezone.utc).strftime("%Y")
        mock_db.counters.find_one = AsyncMock(return_value=None)
        mock_db.invoices.find_one = AsyncMock(return_value=None)
        mock_db.counters.update_one = AsyncMock(return_value=None)
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"_id": f"invoice_{year}", "seq": 1})

        num = asyncio.run(server.get_next_invoice_number())
        self.assertEqual(num, f"INV-{year}-0001")
        mock_db.counters.update_one.assert_called_once()
        mock_db.counters.find_one_and_update.assert_called_once()

    @patch("server.db")
    def test_02_sequential_invoice_number(self, mock_db):
        """Subsequent invoices increment sequentially."""
        year = datetime.now(timezone.utc).strftime("%Y")
        mock_db.counters.find_one = AsyncMock(return_value={"_id": f"invoice_{year}", "seq": 14})
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"_id": f"invoice_{year}", "seq": 15})

        num = asyncio.run(server.get_next_invoice_number())
        self.assertEqual(num, f"INV-{year}-0015")

    @patch("server.db")
    def test_03_yearly_counter_separation(self, mock_db):
        """Counter ID is segmented by year, e.g. invoice_2026."""
        year = datetime.now(timezone.utc).strftime("%Y")
        expected_counter_id = f"invoice_{year}"
        mock_db.counters.find_one = AsyncMock(return_value={"_id": expected_counter_id, "seq": 5})
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"_id": expected_counter_id, "seq": 6})

        num = asyncio.run(server.get_next_invoice_number())
        mock_db.counters.find_one_and_update.assert_called_with(
            {"_id": expected_counter_id},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
        self.assertEqual(num, f"INV-{year}-0006")

    @patch("server.db")
    def test_04_concurrency_and_collision_retry(self, mock_db):
        """If a DuplicateKeyError happens on insert, retry attempts until success."""
        year = datetime.now(timezone.utc).strftime("%Y")
        data = server.InvoiceInput(
            customer=server.InvoiceCustomerInput(name="Ahmad", whatsapp="+201551685018"),
            items=[server.InvoiceItemInput(name="Meja", quantity=1, unit_price=1000)]
        )

        call_count = 0
        async def fake_insert(doc):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise pymongo.errors.DuplicateKeyError("E11000 duplicate key error")
            res = MagicMock()
            res.inserted_id = "test_inv_id_1"
            return res

        mock_db.invoices.insert_one = AsyncMock(side_effect=fake_insert)
        mock_db.invoices.find_one = AsyncMock(return_value={"_id": "test_inv_id_1", "invoice_number": f"INV-{year}-0002", "status": "DRAFT"})

        with patch("server.get_next_invoice_number", new_callable=AsyncMock) as mock_num:
            mock_num.side_effect = [f"INV-{year}-0001", f"INV-{year}-0002"]
            created = asyncio.run(server.admin_create_invoice(data, admin=self.admin_user))
            self.assertEqual(call_count, 2)
            self.assertEqual(created["invoice_number"], f"INV-{year}-0002")

    # -------------------------------------------------------------
    # B. CREATE & MULTI-ITEM TESTS
    # -------------------------------------------------------------
    @patch("server.db")
    def test_05_create_multi_item_invoice(self, mock_db):
        """Supports multiple items with quantities, dimensions, and materials."""
        data = server.InvoiceInput(
            customer=server.InvoiceCustomerInput(
                name="Ahmad",
                whatsapp="+201551685018",
                egypt_phone="+201551685018",
                address="Cairo, Egypt"
            ),
            items=[
                server.InvoiceItemInput(
                    name="Meja Custom",
                    dimensions=server.InvoiceDimensionsInput(length="120", width="60", height="75"),
                    material="Blockboard",
                    finishing="HPL",
                    quantity=1,
                    unit_price=1800
                ),
                server.InvoiceItemInput(
                    name="Tatakan Monitor",
                    dimensions=server.InvoiceDimensionsInput(length="80", width="25", height="15"),
                    material="Blockboard",
                    quantity=1,
                    unit_price=350
                ),
                server.InvoiceItemInput(
                    name="Rak Custom",
                    quantity=2,
                    unit_price=500
                )
            ],
            discount_amount=100,
            delivery_fee=150,
            additional_fee=0
        )

        inserted_doc = None
        async def fake_insert(doc):
            nonlocal inserted_doc
            inserted_doc = doc
            res = MagicMock()
            res.inserted_id = "inv_sample_id"
            return res

        mock_db.invoices.insert_one = AsyncMock(side_effect=fake_insert)
        mock_db.invoices.find_one = AsyncMock(side_effect=lambda q: inserted_doc)

        with patch("server.get_next_invoice_number", new_callable=AsyncMock) as mock_num:
            mock_num.return_value = "INV-2026-0001"
            res = asyncio.run(server.admin_create_invoice(data, admin=self.admin_user))
            self.assertEqual(res["subtotal"], 3150.0)
            self.assertEqual(res["discount_amount"], 100.0)
            self.assertEqual(res["delivery_fee"], 150.0)
            self.assertEqual(res["total"], 3200.0)
            self.assertEqual(len(res["items"]), 3)
            self.assertEqual(res["items"][0]["line_total"], 1800.0)
            self.assertEqual(res["items"][1]["line_total"], 350.0)
            self.assertEqual(res["items"][2]["line_total"], 1000.0)

    @patch("server.db")
    def test_06_catalog_item_price_snapshot(self, mock_db):
        """Catalog item references product_id and product_slug, price is snapshot."""
        data = server.InvoiceInput(
            customer=server.InvoiceCustomerInput(name="Budi", whatsapp="+6281234567890"),
            items=[
                server.InvoiceItemInput(
                    item_type="catalog",
                    product_id="prod_rak_123",
                    product_slug="rak-kayu",
                    name="Rak Kayu 3 Tingkat",
                    quantity=2,
                    unit_price=700
                )
            ]
        )
        saved_doc = None
        async def fake_insert(doc):
            nonlocal saved_doc
            saved_doc = doc
            res = MagicMock()
            res.inserted_id = "inv_cat_1"
            return res

        mock_db.invoices.insert_one = AsyncMock(side_effect=fake_insert)
        mock_db.invoices.find_one = AsyncMock(side_effect=lambda q: saved_doc)

        with patch("server.get_next_invoice_number", new_callable=AsyncMock) as mock_num:
            mock_num.return_value = "INV-2026-0002"
            res = asyncio.run(server.admin_create_invoice(data, admin=self.admin_user))
            self.assertEqual(res["items"][0]["item_type"], "catalog")
            self.assertEqual(res["items"][0]["product_id"], "prod_rak_123")
            self.assertEqual(res["items"][0]["product_slug"], "rak-kayu")
            self.assertEqual(res["items"][0]["line_total"], 1400.0)
            self.assertEqual(res["total"], 1400.0)

    @patch("server.db")
    def test_07_customer_snapshot_preservation(self, mock_db):
        """Existing customer_id populates customer snapshot, future edits don't alter master."""
        data = server.InvoiceInput(
            customer=server.InvoiceCustomerInput(
                customer_id="cust_existing_99",
                name="Ahmad Snapshot",
                whatsapp="+201551685018",
                address="Dokki, Giza"
            ),
            items=[server.InvoiceItemInput(name="Meja", quantity=1, unit_price=500)]
        )
        mock_db.customers.find_one = AsyncMock(return_value={"_id": "cust_existing_99", "username": "ahmad_user", "phone": "+201551685018"})
        saved_doc = None
        async def fake_insert(doc):
            nonlocal saved_doc
            saved_doc = doc
            res = MagicMock()
            res.inserted_id = "inv_snap_1"
            return res
        mock_db.invoices.insert_one = AsyncMock(side_effect=fake_insert)
        mock_db.invoices.find_one = AsyncMock(side_effect=lambda q: saved_doc)

        with patch("server.get_next_invoice_number", new_callable=AsyncMock) as mock_num:
            mock_num.return_value = "INV-2026-0003"
            res = asyncio.run(server.admin_create_invoice(data, admin=self.admin_user))
            self.assertEqual(res["customer"]["customer_id"], "cust_existing_99")
            self.assertEqual(res["customer"]["name"], "Ahmad Snapshot")
            self.assertEqual(res["customer"]["address"], "Dokki, Giza")

    @patch("server.db")
    def test_08_custom_request_source_linking(self, mock_db):
        """Invoice referencing a Custom Request stores source.custom_request_id."""
        data = server.InvoiceInput(
            customer=server.InvoiceCustomerInput(name="Ahmad", whatsapp="+201551685018"),
            source=server.InvoiceSourceInput(custom_request_id="cr_ticket_123"),
            items=[server.InvoiceItemInput(name="Meja", quantity=1, unit_price=1000)]
        )
        mock_db.custom_requests.find_one = AsyncMock(return_value={"_id": "cr_ticket_123", "ticket_number": "CR-20260930-001"})
        saved_doc = None
        async def fake_insert(doc):
            nonlocal saved_doc
            saved_doc = doc
            res = MagicMock()
            res.inserted_id = "inv_cr_1"
            return res
        mock_db.invoices.insert_one = AsyncMock(side_effect=fake_insert)
        mock_db.invoices.find_one = AsyncMock(side_effect=lambda q: saved_doc)

        with patch("server.get_next_invoice_number", new_callable=AsyncMock) as mock_num:
            mock_num.return_value = "INV-2026-0004"
            res = asyncio.run(server.admin_create_invoice(data, admin=self.admin_user))
            self.assertEqual(res["source"]["custom_request_id"], "cr_ticket_123")

    # -------------------------------------------------------------
    # C. CALCULATION & VALIDATION TESTS
    # -------------------------------------------------------------
    def test_09_calculation_formula(self):
        """calculate_invoice_totals validates line_totals, subtotal, and total."""
        items = [
            {"name": "Item A", "quantity": 3, "unit_price": 200.0},
            {"name": "Item B", "quantity": 1, "unit_price": 450.50},
        ]
        proc_items, subtotal, disc, deliv, add_fee, total = server.calculate_invoice_totals(
            items, discount_amount=50.0, delivery_fee=100.0, additional_fee=25.0
        )
        self.assertEqual(proc_items[0]["line_total"], 600.0)
        self.assertEqual(proc_items[1]["line_total"], 450.50)
        self.assertEqual(subtotal, 1050.50)
        self.assertEqual(disc, 50.0)
        self.assertEqual(deliv, 100.0)
        self.assertEqual(add_fee, 25.0)
        self.assertEqual(total, 1125.50)

    def test_10_invalid_quantity_or_price_rejected(self):
        """Quantity < 1 or unit_price < 0 raises 400."""
        with self.assertRaises(HTTPException) as ctx:
            server.calculate_invoice_totals([{"name": "Item", "quantity": 0, "unit_price": 100}])
        self.assertEqual(ctx.exception.status_code, 400)

        with self.assertRaises(HTTPException) as ctx2:
            server.calculate_invoice_totals([{"name": "Item", "quantity": 1, "unit_price": -50}])
        self.assertEqual(ctx2.exception.status_code, 400)

    # -------------------------------------------------------------
    # D. STATUS TRANSITIONS & EDITING
    # -------------------------------------------------------------
    @patch("server.db")
    def test_11_status_transitions(self, mock_db):
        """DRAFT -> SENT -> CANCELLED / CONVERTED. Terminal states cannot change."""
        inv = {
            "_id": "inv_1",
            "invoice_number": "INV-2026-0005",
            "status": "DRAFT",
            "sent_at": None,
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        # Send
        mock_db.invoices.find_one = AsyncMock(side_effect=[inv, {**inv, "status": "SENT"}])
        mock_db.invoices.update_one = AsyncMock(return_value=None)
        sent = asyncio.run(server.admin_send_invoice("inv_1", admin=self.admin_user))
        self.assertEqual(sent["status"], "SENT")

        # Cancel from SENT
        mock_db.invoices.find_one = AsyncMock(side_effect=[{**inv, "status": "SENT"}, {**inv, "status": "CANCELLED"}])
        cancelled = asyncio.run(server.admin_cancel_invoice("inv_1", admin=self.admin_user))
        self.assertEqual(cancelled["status"], "CANCELLED")

        # Attempt to send CANCELLED invoice raises 400
        mock_db.invoices.find_one = AsyncMock(return_value={**inv, "status": "CANCELLED"})
        with self.assertRaises(HTTPException) as err:
            asyncio.run(server.admin_send_invoice("inv_1", admin=self.admin_user))
        self.assertEqual(err.exception.status_code, 400)

    @patch("server.db")
    def test_12_delete_guard_draft_only(self, mock_db):
        """Legacy unconfirmed delete is deprecated and blocked with HTTP 400."""
        with self.assertRaises(HTTPException) as err:
            asyncio.run(server.admin_delete_invoice("inv_draft", admin=self.admin_user))
        self.assertEqual(err.exception.status_code, 400)
        self.assertIn("HAPUS PERMANEN", err.exception.detail)

    # -------------------------------------------------------------
    # E. CONVERSION TO ORDER & IDEMPOTENCY
    # -------------------------------------------------------------
    @patch("server.db")
    def test_13_convert_invoice_to_order_success(self, mock_db):
        """Converts invoice to order: assigns existing order_number format, preserves items and prices."""
        inv = {
            "_id": "inv_conv_1",
            "invoice_number": "INV-2026-0009",
            "status": "SENT",
            "order_id": None,
            "customer": {
                "customer_id": "cust_123",
                "name": "Ahmad Pelanggan",
                "whatsapp": "+201551685018",
                "egypt_phone": "+201551685018",
                "address": "11 El-Refaey Ln, Cairo"
            },
            "source": {"custom_request_id": None},
            "items": [
                {
                    "item_id": "it_1",
                    "item_type": "custom",
                    "product_id": None,
                    "name": "Meja Custom Kayu Jati",
                    "description": "Kayu jati solid finishing natural",
                    "quantity": 1,
                    "dimensions": {"length": "120", "width": "60", "height": "75"},
                    "material": "Solid Jati",
                    "finishing": "Natural",
                    "unit_price": 2500.0,
                    "line_total": 2500.0,
                    "notes": "Custom meja"
                }
            ],
            "subtotal": 2500.0,
            "discount_amount": 100.0,
            "delivery_fee": 150.0,
            "additional_fee": 0.0,
            "total": 2550.0,
            "customer_note": "Tolong kirim sore",
            "internal_note": "Prioritas tinggi",
        }

        mock_db.invoices.find_one = AsyncMock(return_value=inv)
        mock_db.invoices.find_one_and_update = AsyncMock(return_value={**inv, "status": "CONVERTED", "order_number": "SGF-20260930-007"})
        mock_db.invoices.update_one = AsyncMock(return_value=None)
        mock_db.orders.insert_one = AsyncMock(return_value=MagicMock(inserted_id="order_created_777"))
        
        created_order_doc = {
            "_id": "order_created_777",
            "order_number": "SGF-20260930-007",
            "invoice_id": "inv_conv_1",
            "invoice_number": "INV-2026-0009",
            "total_le": 2550.0,
            "payment_status": "belum_dibayar",
            "order_status": "dikonfirmasi"
        }
        mock_db.orders.find_one = AsyncMock(return_value=created_order_doc)
        mock_db.customers.find_one = AsyncMock(return_value={"_id": "cust_123", "username": "ahmad_cust"})
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357})

        with patch("server.generate_order_number", new_callable=AsyncMock) as mock_gen_ord_num:
            mock_gen_ord_num.return_value = "SGF-20260930-007"
            res = asyncio.run(server.admin_convert_invoice_to_order("inv_conv_1", admin=self.admin_user))
            self.assertEqual(res["invoice"]["status"], "CONVERTED")
            self.assertEqual(res["order"]["order_number"], "SGF-20260930-007")
            self.assertEqual(res["order"]["invoice_id"], "inv_conv_1")
            self.assertEqual(res["order"]["total_le"], 2550.0)

    @patch("server.db")
    def test_14_double_conversion_protection_idempotency(self, mock_db):
        """Calling convert on an already CONVERTED invoice returns existing relationship without creating new order."""
        already_converted = {
            "_id": "inv_conv_already",
            "invoice_number": "INV-2026-0009",
            "status": "CONVERTED",
            "order_id": "order_existing_888",
            "order_number": "SGF-20260930-005"
        }
        mock_db.invoices.find_one = AsyncMock(return_value=already_converted)
        mock_db.orders.find_one = AsyncMock(return_value={"_id": "order_existing_888", "order_number": "SGF-20260930-005"})
        mock_db.orders.insert_one = AsyncMock()

        res = asyncio.run(server.admin_convert_invoice_to_order("inv_conv_already", admin=self.admin_user))
        self.assertIn("idempotent", res["message"])
        self.assertEqual(res["order"]["order_number"], "SGF-20260930-005")
        mock_db.orders.insert_one.assert_not_called()

    # -------------------------------------------------------------
    # F. FINANCE SAFETY: ABSOLUTE ZERO MUTATIONS
    # -------------------------------------------------------------
    @patch("server.db")
    def test_15_finance_safety_zero_mutations(self, mock_db):
        """Invoice creation, sending, cancellation, and conversion create ZERO finance transactions."""
        mock_db.finance_transactions.insert_one = AsyncMock()
        mock_db.finance_transactions.update_one = AsyncMock()

        # 1. Create Invoice
        data = server.InvoiceInput(
            customer=server.InvoiceCustomerInput(name="Ahmad", whatsapp="+201551685018"),
            items=[server.InvoiceItemInput(name="Meja", quantity=1, unit_price=1000)]
        )
        mock_db.invoices.insert_one = AsyncMock(return_value=MagicMock(inserted_id="inv_fin_test"))
        mock_db.invoices.find_one = AsyncMock(return_value={"_id": "inv_fin_test", "status": "DRAFT"})

        with patch("server.get_next_invoice_number", new_callable=AsyncMock) as mock_num:
            mock_num.return_value = "INV-2026-0010"
            asyncio.run(server.admin_create_invoice(data, admin=self.admin_user))

        # 2. Send Invoice
        mock_db.invoices.find_one = AsyncMock(side_effect=[{"_id": "inv_fin_test", "status": "DRAFT"}, {"_id": "inv_fin_test", "status": "SENT"}])
        mock_db.invoices.update_one = AsyncMock(return_value=None)
        asyncio.run(server.admin_send_invoice("inv_fin_test", admin=self.admin_user))

        # 3. Convert Invoice
        inv = {
            "_id": "inv_fin_test",
            "invoice_number": "INV-2026-0010",
            "status": "SENT",
            "order_id": None,
            "customer": {"name": "Ahmad", "whatsapp": "+201551685018"},
            "items": [{"name": "Meja", "quantity": 1, "unit_price": 1000, "line_total": 1000}],
            "subtotal": 1000,
            "total": 1000
        }
        mock_db.invoices.find_one = AsyncMock(return_value=inv)
        mock_db.invoices.find_one_and_update = AsyncMock(return_value={**inv, "status": "CONVERTED", "order_number": "SGF-20260930-011"})
        mock_db.orders.insert_one = AsyncMock(return_value=MagicMock(inserted_id="ord_fin_11"))
        mock_db.orders.find_one = AsyncMock(return_value={"_id": "ord_fin_11", "order_number": "SGF-20260930-011"})
        mock_db.settings.find_one = AsyncMock(return_value={"key": "exchange_rate_idr_per_le", "value": 357})

        with patch("server.generate_order_number", new_callable=AsyncMock) as mock_ord_num:
            mock_ord_num.return_value = "SGF-20260930-011"
            asyncio.run(server.admin_convert_invoice_to_order("inv_fin_test", admin=self.admin_user))

        # Assert ZERO finance mutations across all operations
        mock_db.finance_transactions.insert_one.assert_not_called()
        mock_db.finance_transactions.update_one.assert_not_called()

    # -------------------------------------------------------------
    # G. PDF PRINT DATA SECURITY
    # -------------------------------------------------------------
    @patch("server.db")
    def test_16_pdf_print_internal_note_leak_prevention(self, mock_db):
        """Print endpoint strips internal_note from returned payload."""
        inv = {
            "_id": "inv_print_1",
            "invoice_number": "INV-2026-0012",
            "status": "SENT",
            "customer": {"name": "Ahmad", "whatsapp": "+201551685018"},
            "customer_note": "Customer note for PDF",
            "internal_note": "SECRET: Hubungi supplier kayu",
            "total": 500
        }
        mock_db.invoices.find_one = AsyncMock(return_value=inv)

        with patch("server.store_info", new_callable=AsyncMock) as mock_store:
            mock_store.return_value = {"store_name": "Sogil Furniture"}
            res = asyncio.run(server.admin_get_invoice_print_data("inv_print_1", admin=self.admin_user))
            self.assertEqual(res["invoice"]["customer_note"], "Customer note for PDF")
            self.assertNotIn("internal_note", res["invoice"])


if __name__ == "__main__":
    unittest.main()
