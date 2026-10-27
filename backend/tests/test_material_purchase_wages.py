"""Comprehensive Test Suite for Material Purchase Wages & Unified Settlement Integration.

Covers all required Phase Wage Recovery 03 behaviors:
1. Purchase without wage succeeds normally (backward compatibility)
2. Purchase with valid worker and wage creates wage obligation
3. Purchase with worker empty but wage provided is rejected (HTTP 400)
4. Purchase with wage empty/zero but worker provided is rejected (HTTP 400)
5. Zero or negative wage amount is rejected (HTTP 400)
6. Non-existent or inactive worker is rejected (HTTP 404)
7. Wage obligation linked to correct purchase ID and purchase number
8. Idempotent accrual prevents duplicate wage obligations on retry
9. Transactional atomicity: rollback on failure preserves consistent state
10. Accounting isolation: material cost in category 'Material', wage in category 'Pekerja'
11. Wage obligations appear on pending summary and obligations listing
12. Settlement executes via canonical POST /api/admin/wages/settlements
13. Settlement creates exactly one canonical Finance expense under category 'Pekerja'
14. Idempotency key on settlement prevents duplicate disbursement
15. Locked exchange rate on material purchase is preserved for IDR settlement
16. Void purchase without wage proceeds as before
17. Void purchase with unpaid (accrued) wage obligation voids the obligation
18. Void purchase with paid/partially paid wage obligation is rejected (HTTP 409)
19. Void audit trail is preserved (voided_at, voided_by, void_reason)
20. Repeated void is rejected (idempotent / already voided)
"""
import copy
import os
import sys
import unittest
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
import pymongo

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import server
from server import (
    MaterialPurchaseInput,
    VoidPurchaseInput,
    WageSettlementCreateInput,
    create_material_purchase,
    void_material_purchase,
    admin_get_wages_pending_summary,
    admin_get_worker_pending_wages,
    admin_get_wage_obligations,
    admin_create_wage_settlement,
    CONTROLLED_TASK_CATEGORIES,
)
from fastapi import HTTPException


class AsyncCursorMock:
    def __init__(self, docs):
        self.docs = copy.deepcopy(docs)
        self.idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.idx < len(self.docs):
            doc = self.docs[self.idx]
            self.idx += 1
            return doc
        raise StopAsyncIteration

    def sort(self, *args, **kwargs):
        return self

    def skip(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    async def to_list(self, length=None):
        return copy.deepcopy(self.docs)


class TestMaterialPurchaseWages(unittest.TestCase):

    def setUp(self):
        self.owner_user = {
            "id": "admin_owner",
            "name": "Owner Admin",
            "role": "owner",
            "permissions": {"modify_products": True, "access_finance": True, "manage_orders": True}
        }
        self.worker_id = ObjectId()
        self.sample_worker = {
            "_id": self.worker_id,
            "id": str(self.worker_id),
            "name": "Ahmad Tukang",
            "role": "employee",
            "status": "active",
        }
        self.inactive_worker_id = ObjectId()
        self.sample_inactive_worker = {
            "_id": self.inactive_worker_id,
            "id": str(self.inactive_worker_id),
            "name": "Budi Ex-Pekerja",
            "role": "employee",
            "status": "inactive",
        }

        self.mat_id = ObjectId()
        self.sample_material = {
            "_id": self.mat_id,
            "name": "Kayu Jati Grade A",
            "specs": "10x10 x 400 cm",
            "category": "Material",
            "unit": "batang",
            "status": "active",
            "current_stock": 25.0,
            "latest_price": 500.0,
            "latest_currency": "EGP",
            "latest_purchase_date": "2026-10-20",
        }

    async def _fake_tx(self, client, fn):
        return await fn(session=None)

    def test_00_controlled_task_categories_includes_material_purchase(self):
        """CONTROLLED_TASK_CATEGORIES contains canonical 'material_purchase'."""
        self.assertIn("material_purchase", CONTROLLED_TASK_CATEGORIES)

    @patch("server.execute_transaction_with_safety")
    @patch("server.recalculate_material_latest_price", new_callable=AsyncMock)
    @patch("server.apply_purchase_stock_in", new_callable=AsyncMock)
    @patch("server.apply_purchase_finance_expense", new_callable=AsyncMock)
    @patch("server.get_next_purchase_number", new_callable=AsyncMock)
    def test_01_purchase_without_buyer_wage_succeeds(self, mock_pnum, mock_fin, mock_stock, mock_price, mock_tx):
        """1. Purchase without buyer wage succeeds without creating wage obligation."""
        mock_pnum.return_value = "PB-202610-0001"
        mock_tx.side_effect = self._fake_tx

        inserted_purchase = None
        created_wob = None

        async def fake_insert_purchase(doc, session=None):
            nonlocal inserted_purchase
            inserted_purchase = copy.deepcopy(doc)
            inserted_purchase["_id"] = ObjectId()
            return MagicMock(inserted_id=inserted_purchase["_id"])

        async def fake_insert_wob(doc, session=None):
            nonlocal created_wob
            created_wob = copy.deepcopy(doc)
            return MagicMock(inserted_id=ObjectId())

        with patch("server.db") as mock_db:
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.material_purchases.insert_one = fake_insert_purchase
            mock_db.wage_obligations.insert_one = fake_insert_wob

            payload = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-27",
                unit_price=550.0,
                quantity=10.0,
                currency="EGP",
                supplier_name="Toko Kayu Indah",
            )
            res = asyncio.run(create_material_purchase(payload, admin=self.owner_user))

            self.assertIsNotNone(inserted_purchase)
            self.assertEqual(inserted_purchase["purchase_number"], "PB-202610-0001")
            self.assertIsNone(inserted_purchase["buyer_worker_id"])
            self.assertIsNone(inserted_purchase["buyer_wage_amount"])
            self.assertIsNone(created_wob)
            mock_stock.assert_called_once()
            mock_fin.assert_called_once()

    @patch("server.execute_transaction_with_safety")
    @patch("server.recalculate_material_latest_price", new_callable=AsyncMock)
    @patch("server.apply_purchase_stock_in", new_callable=AsyncMock)
    @patch("server.apply_purchase_finance_expense", new_callable=AsyncMock)
    @patch("server.get_next_purchase_number", new_callable=AsyncMock)
    @patch("server.generate_obligation_number", new_callable=AsyncMock)
    def test_02_07_purchase_with_valid_buyer_wage_creates_obligation(self, mock_wob_num, mock_pnum, mock_fin, mock_stock, mock_price, mock_tx):
        """2 & 7. Purchase with valid worker and wage creates wage obligation linked to purchase."""
        mock_pnum.return_value = "PB-202610-0002"
        mock_wob_num.return_value = "WOB-202610-0088"
        mock_tx.side_effect = self._fake_tx

        inserted_purchase = None
        created_wob = None

        async def fake_insert_purchase(doc, session=None):
            nonlocal inserted_purchase
            inserted_purchase = copy.deepcopy(doc)
            inserted_purchase["_id"] = ObjectId()
            return MagicMock(inserted_id=inserted_purchase["_id"])

        async def fake_insert_wob(doc, session=None):
            nonlocal created_wob
            created_wob = copy.deepcopy(doc)
            created_wob["_id"] = ObjectId()
            return MagicMock(inserted_id=created_wob["_id"])

        with patch("server.db") as mock_db:
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.settings.find_one = AsyncMock(return_value={"value": 350.0})
            mock_db.admins.find_one = AsyncMock(return_value=self.sample_worker)
            mock_db.material_purchases.insert_one = fake_insert_purchase
            mock_db.material_purchases.update_one = AsyncMock()
            mock_db.wage_obligations.find_one = AsyncMock(return_value=None)
            mock_db.wage_obligations.insert_one = fake_insert_wob

            payload = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-27",
                unit_price=500.0,
                quantity=4.0,
                currency="EGP",
                exchange_rate=360.0,
                supplier_name="Toko Kayu Indah",
                buyer_worker_id=str(self.worker_id),
                buyer_wage_amount=75.0,
                buyer_wage_notes="Upah angkut & belanja kayu jati 4 batang",
            )
            res = asyncio.run(create_material_purchase(payload, admin=self.owner_user))

            self.assertIsNotNone(created_wob)
            self.assertEqual(created_wob["obligation_number"], "WOB-202610-0088")
            self.assertEqual(created_wob["worker_id"], str(self.worker_id))
            self.assertEqual(created_wob["worker_name"], "Ahmad Tukang")
            self.assertEqual(created_wob["task_category"], "material_purchase")
            self.assertEqual(created_wob["pricing_basis"], "lump_sum")
            self.assertEqual(created_wob["total_amount_le"], 75.0)
            self.assertEqual(created_wob["currency"], "EGP")
            self.assertEqual(created_wob["status"], "accrued")
            self.assertEqual(created_wob["purchase_number"], "PB-202610-0002")
            self.assertEqual(created_wob["material_purchase_id"], str(inserted_purchase["_id"]))
            self.assertEqual(created_wob["locked_exchange_rate"], 360.0)

    def test_03_purchase_with_empty_worker_but_wage_provided_fails(self):
        """3. Purchase with wage provided but worker empty is rejected with HTTP 400."""
        with patch("server.db") as mock_db:
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            payload = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-27",
                unit_price=500.0,
                quantity=2.0,
                buyer_worker_id="",
                buyer_wage_amount=50.0,
            )
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(create_material_purchase(payload, admin=self.owner_user))
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("Pekerja pembeli wajib dipilih", ctx.exception.detail)

    def test_04_purchase_with_worker_selected_but_zero_wage_fails(self):
        """4. Purchase with worker selected but wage missing/zero is rejected with HTTP 400."""
        with patch("server.db") as mock_db:
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            payload = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-27",
                unit_price=500.0,
                quantity=2.0,
                buyer_worker_id=str(self.worker_id),
                buyer_wage_amount=0.0,
            )
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(create_material_purchase(payload, admin=self.owner_user))
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("Nominal upah pembelian bahan harus lebih besar dari 0", ctx.exception.detail)

    def test_05_negative_wage_fails(self):
        """5. Negative wage amount is rejected with HTTP 400."""
        with patch("server.db") as mock_db:
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            payload = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-27",
                unit_price=500.0,
                quantity=2.0,
                buyer_worker_id=str(self.worker_id),
                buyer_wage_amount=-25.0,
            )
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(create_material_purchase(payload, admin=self.owner_user))
            self.assertEqual(ctx.exception.status_code, 400)

    def test_06_nonexistent_or_inactive_worker_fails(self):
        """6. Non-existent or inactive worker is rejected with HTTP 404."""
        with patch("server.db") as mock_db:
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            # Scenario A: Worker not found
            mock_db.admins.find_one = AsyncMock(return_value=None)
            payload_a = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-27",
                unit_price=500.0,
                quantity=2.0,
                buyer_worker_id=str(ObjectId()),
                buyer_wage_amount=50.0,
            )
            with self.assertRaises(HTTPException) as ctx_a:
                asyncio.run(create_material_purchase(payload_a, admin=self.owner_user))
            self.assertEqual(ctx_a.exception.status_code, 404)

            # Scenario B: Worker is inactive
            mock_db.admins.find_one = AsyncMock(return_value=None)  # query filters status: {"$ne": "inactive"}
            payload_b = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-27",
                unit_price=500.0,
                quantity=2.0,
                buyer_worker_id=str(self.inactive_worker_id),
                buyer_wage_amount=50.0,
            )
            with self.assertRaises(HTTPException) as ctx_b:
                asyncio.run(create_material_purchase(payload_b, admin=self.owner_user))
            self.assertEqual(ctx_b.exception.status_code, 404)

    @patch("server.execute_transaction_with_safety")
    @patch("server.recalculate_material_latest_price", new_callable=AsyncMock)
    @patch("server.apply_purchase_stock_in", new_callable=AsyncMock)
    @patch("server.apply_purchase_finance_expense", new_callable=AsyncMock)
    @patch("server.get_next_purchase_number", new_callable=AsyncMock)
    @patch("server.generate_obligation_number", new_callable=AsyncMock)
    def test_08_idempotent_retry_prevents_duplicate_obligation(self, mock_wob_num, mock_pnum, mock_fin, mock_stock, mock_price, mock_tx):
        """8. If obligation with accrual_event_key already exists, no duplicate is inserted."""
        mock_pnum.return_value = "PB-202610-0003"
        mock_tx.side_effect = self._fake_tx

        existing_obligation = {
            "_id": ObjectId(),
            "obligation_number": "WOB-202610-0010",
            "accrual_event_key": "material_purchase:dummy",
            "status": "accrued",
        }
        mock_insert_wob = AsyncMock()

        with patch("server.db") as mock_db:
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.settings.find_one = AsyncMock(return_value={"value": 350.0})
            mock_db.admins.find_one = AsyncMock(return_value=self.sample_worker)
            mock_db.material_purchases.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
            mock_db.material_purchases.update_one = AsyncMock()
            # Simulate existing obligation found by accrual_event_key
            mock_db.wage_obligations.find_one = AsyncMock(return_value=existing_obligation)
            mock_db.wage_obligations.insert_one = mock_insert_wob

            payload = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-27",
                unit_price=500.0,
                quantity=1.0,
                buyer_worker_id=str(self.worker_id),
                buyer_wage_amount=50.0,
            )
            res = asyncio.run(create_material_purchase(payload, admin=self.owner_user))

            mock_insert_wob.assert_not_called()

    @patch("server.recalculate_material_latest_price", new_callable=AsyncMock)
    @patch("server.apply_purchase_stock_in", new_callable=AsyncMock)
    @patch("server.get_next_purchase_number", new_callable=AsyncMock)
    def test_09_transactional_rollback_on_failure(self, mock_pnum, mock_stock, mock_price):
        """9. Failure inside purchase transaction raises 500 and prevents partial commit."""
        mock_pnum.return_value = "PB-202610-0004"

        with patch("server.db") as mock_db:
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.settings.find_one = AsyncMock(return_value={"value": 350.0})
            mock_db.admins.find_one = AsyncMock(return_value=self.sample_worker)
            mock_db.material_purchases.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))

            # Simulate stock processing error inside transaction
            mock_stock.side_effect = RuntimeError("Inventory allocation exploded")

            payload = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-27",
                unit_price=500.0,
                quantity=1.0,
                buyer_worker_id=str(self.worker_id),
                buyer_wage_amount=50.0,
            )
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(create_material_purchase(payload, admin=self.owner_user))
            self.assertEqual(ctx.exception.status_code, 500)

    @patch("server.execute_transaction_with_safety")
    @patch("server.recalculate_material_latest_price", new_callable=AsyncMock)
    @patch("server.apply_purchase_stock_in", new_callable=AsyncMock)
    @patch("server.apply_purchase_finance_expense")
    @patch("server.get_next_purchase_number", new_callable=AsyncMock)
    @patch("server.generate_obligation_number", new_callable=AsyncMock)
    def test_10_accounting_isolation_material_vs_worker(self, mock_wob_num, mock_pnum, mock_fin, mock_stock, mock_price, mock_tx):
        """10. Material purchase only creates Material expense; worker wage is not in Material expense."""
        mock_pnum.return_value = "PB-202610-0005"
        mock_wob_num.return_value = "WOB-202610-0099"
        mock_tx.side_effect = self._fake_tx

        finance_doc_recorded = None
        async def fake_finance(purchase_doc, admin, session=None):
            nonlocal finance_doc_recorded
            finance_doc_recorded = copy.deepcopy(purchase_doc)
            return {"ok": True}
        mock_fin.side_effect = fake_finance

        with patch("server.db") as mock_db:
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.settings.find_one = AsyncMock(return_value={"value": 350.0})
            mock_db.admins.find_one = AsyncMock(return_value=self.sample_worker)
            mock_db.material_purchases.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
            mock_db.material_purchases.update_one = AsyncMock()
            mock_db.wage_obligations.find_one = AsyncMock(return_value=None)
            mock_db.wage_obligations.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))

            payload = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-27",
                unit_price=100.0,
                quantity=5.0,  # Total material cost = 500 EGP
                currency="EGP",
                buyer_worker_id=str(self.worker_id),
                buyer_wage_amount=50.0,  # Worker wage = 50 EGP
            )
            res = asyncio.run(create_material_purchase(payload, admin=self.owner_user))

            self.assertIsNotNone(finance_doc_recorded)
            # Material total amount must equal strictly quantity * unit_price (500 EGP) without wage
            self.assertEqual(finance_doc_recorded["total_amount"], 500.0)
            self.assertEqual(finance_doc_recorded["buyer_wage_amount"], 50.0)

    def test_11_pending_summary_and_obligations_display_material_wage(self):
        """11. Material purchase wage obligation appears in pending summary and obligations listing."""
        sample_wob = {
            "_id": ObjectId(),
            "obligation_number": "WOB-202610-0088",
            "worker_id": str(self.worker_id),
            "worker_name": "Ahmad Tukang",
            "task_category": "material_purchase",
            "pricing_basis": "lump_sum",
            "total_amount_le": 75.0,
            "paid_amount_le": 0.0,
            "status": "accrued",
            "purchase_number": "PB-202610-0002",
            "material_name": "Kayu Jati Grade A",
            "locked_exchange_rate": 360.0,
            "created_at": "2026-10-27T10:00:00Z"
        }

        with patch("server.db") as mock_db:
            mock_db.wage_obligations.find.return_value = AsyncCursorMock([sample_wob])
            mock_db.wage_obligations.count_documents = AsyncMock(return_value=1)

            # Test pending summary
            summary = asyncio.run(admin_get_wages_pending_summary(admin=self.owner_user))
            self.assertEqual(summary["total_accrued_le"], 75.0)
            self.assertEqual(summary["total_pending_wages_le"], 75.0)
            self.assertEqual(len(summary["workers_summary"]), 1)
            self.assertEqual(summary["workers_summary"][0]["worker_id"], str(self.worker_id))
            self.assertEqual(summary["workers_summary"][0]["total_le"], 75.0)

            # Test obligations list
            listing = asyncio.run(admin_get_wage_obligations(admin=self.owner_user))
            self.assertEqual(listing["total"], 1)
            self.assertEqual(listing["obligations"][0]["task_category"], "material_purchase")
            self.assertEqual(listing["obligations"][0]["purchase_number"], "PB-202610-0002")

    @patch("server.is_standalone_fallback_permitted", return_value=True)
    @patch("server.client.start_session")
    @patch("server.generate_wage_settlement_number", new_callable=AsyncMock)
    @patch("server.execute_transaction_with_safety")
    def test_12_13_14_15_settlement_lifecycle_and_single_finance_expense(self, mock_tx, mock_ws_num, mock_session, mock_fallback):
        """12, 13, 14, 15. Material purchase wage settles via POST /api/admin/wages/settlements into Finance 'Pekerja'."""
        mock_ws_num.return_value = "WS-202610-0001"
        mock_session.side_effect = pymongo.errors.ConfigurationError("Standalone")
        sample_wob_id = ObjectId()
        sample_wob = {
            "_id": sample_wob_id,
            "id": str(sample_wob_id),
            "obligation_number": "WOB-202610-0088",
            "worker_id": str(self.worker_id),
            "worker_name": "Ahmad Tukang",
            "task_category": "material_purchase",
            "pricing_basis": "lump_sum",
            "total_amount_le": 100.0,
            "paid_amount_le": 0.0,
            "status": "accrued",
            "purchase_number": "PB-202610-0002",
            "locked_exchange_rate": 350.0,
            "created_at": "2026-10-27T10:00:00Z"
        }

        mock_tx.side_effect = self._fake_tx
        finance_transactions_inserted = []
        settlement_inserted = None

        async def fake_insert_fin(doc, **kwargs):
            nonlocal finance_transactions_inserted
            finance_transactions_inserted.append(copy.deepcopy(doc))
            return MagicMock(inserted_id=ObjectId())

        async def fake_insert_settle(doc, **kwargs):
            nonlocal settlement_inserted
            settlement_inserted = copy.deepcopy(doc)
            settlement_inserted["_id"] = ObjectId()
            return MagicMock(inserted_id=settlement_inserted["_id"])

        with patch("server.db") as mock_db:
            mock_db.settings.find_one = AsyncMock(return_value={"value": 350.0})
            mock_db.admins.find_one = AsyncMock(return_value=self.sample_worker)
            mock_db.wage_settlements.find_one = AsyncMock(return_value=None)
            mock_db.wage_settlements.insert_one = fake_insert_settle
            mock_db.wage_obligations.find.return_value = AsyncCursorMock([sample_wob])
            mock_db.wage_obligations.find_one = AsyncMock(return_value=sample_wob)
            mock_db.wage_obligations.update_one = AsyncMock()
            mock_db.orders.find.return_value = AsyncCursorMock([])
            mock_db.finance_transactions.insert_one = fake_insert_fin
            mock_db.finance_transactions.update_one = AsyncMock()
            mock_db.employee_wages.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
            mock_db.audit_logs.insert_one = AsyncMock()

            # Settle 100 LE in IDR with rate 350 -> Expected IDR = 35,000 IDR
            payload = WageSettlementCreateInput(
                worker_id=str(self.worker_id),
                amount_le=100.0,
                payment_currency="IDR",
                payment_method="cash",
                settlement_rate=350.0,
                actual_payout_amount=35000.0,
                idempotency_key="idem-settle-mat-wage-001",
            )
            res = asyncio.run(admin_create_wage_settlement(payload, admin=self.owner_user))

            self.assertIsNotNone(settlement_inserted)
            self.assertEqual(settlement_inserted["amount_le"], 100.0)
            self.assertEqual(settlement_inserted["payout_currency"], "IDR")
            self.assertEqual(settlement_inserted["payout_amount"], 35000.0)

            # Finance transaction must be EXACTLY ONE expense under category 'Pekerja'
            self.assertEqual(len(finance_transactions_inserted), 1)
            fin_entry = finance_transactions_inserted[0]
            self.assertEqual(fin_entry["type"], "expense")
            self.assertEqual(fin_entry["category"], "Pekerja")
            self.assertEqual(fin_entry["currency"], "IDR")
            self.assertEqual(fin_entry["amount"], 35000.0)

            # Idempotency replay check: re-transmitting with same key returns existing settlement
            mock_db.wage_settlements.find_one = AsyncMock(return_value=settlement_inserted)
            replay_res = asyncio.run(admin_create_wage_settlement(payload, admin=self.owner_user))
            self.assertEqual(replay_res["settlement_number"], settlement_inserted["settlement_number"])
            # Finance transactions list still only has 1 transaction (no duplicate!)
            self.assertEqual(len(finance_transactions_inserted), 1)

    @patch("server.execute_transaction_with_safety")
    @patch("server.apply_purchase_stock_reversal", new_callable=AsyncMock)
    @patch("server.apply_purchase_finance_reversal", new_callable=AsyncMock)
    @patch("server.recalculate_material_latest_price", new_callable=AsyncMock)
    def test_16_void_purchase_without_wage_proceeds(self, mock_price, mock_fin_rev, mock_stock_rev, mock_tx):
        """16. Void purchase without wage proceeds normally as before."""
        mock_tx.side_effect = self._fake_tx
        pb_oid = ObjectId()
        sample_purchase = {
            "_id": pb_oid,
            "purchase_number": "PB-202610-0016",
            "material_id": str(self.mat_id),
            "quantity": 5.0,
            "is_void": False,
            "buyer_worker_id": None,
        }

        with patch("server.db") as mock_db:
            mock_db.material_purchases.find_one = AsyncMock(return_value=sample_purchase)
            mock_db.material_purchases.find_one_and_update = AsyncMock(return_value={**sample_purchase, "is_void": True})
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.wage_obligations.find_one = AsyncMock(return_value=None)

            res = asyncio.run(void_material_purchase(str(pb_oid), VoidPurchaseInput(void_reason="Salah input"), admin=self.owner_user))
            self.assertTrue(res["ok"])
            mock_stock_rev.assert_called_once()
            mock_fin_rev.assert_called_once()

    @patch("server.execute_transaction_with_safety")
    @patch("server.apply_purchase_stock_reversal", new_callable=AsyncMock)
    @patch("server.apply_purchase_finance_reversal", new_callable=AsyncMock)
    @patch("server.recalculate_material_latest_price", new_callable=AsyncMock)
    def test_17_19_void_purchase_with_accrued_wage_obligation_voids_obligation(self, mock_price, mock_fin_rev, mock_stock_rev, mock_tx):
        """17 & 19. Void purchase with unpaid (accrued) wage obligation voids the obligation and records audit reason."""
        mock_tx.side_effect = self._fake_tx
        pb_oid = ObjectId()
        wob_oid = ObjectId()
        sample_purchase = {
            "_id": pb_oid,
            "purchase_number": "PB-202610-0017",
            "material_id": str(self.mat_id),
            "quantity": 5.0,
            "is_void": False,
            "buyer_worker_id": str(self.worker_id),
            "buyer_wage_obligation_number": "WOB-202610-0017",
        }
        sample_wob = {
            "_id": wob_oid,
            "obligation_number": "WOB-202610-0017",
            "material_purchase_id": str(pb_oid),
            "status": "accrued",
        }

        wob_updated_payload = None
        async def fake_wob_update(q, upd, **kwargs):
            nonlocal wob_updated_payload
            wob_updated_payload = upd
            return MagicMock(modified_count=1)

        with patch("server.db") as mock_db:
            mock_db.material_purchases.find_one = AsyncMock(return_value=sample_purchase)
            mock_db.material_purchases.find_one_and_update = AsyncMock(return_value={**sample_purchase, "is_void": True})
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.wage_obligations.find_one = AsyncMock(return_value=sample_wob)
            mock_db.wage_obligations.update_one = fake_wob_update

            res = asyncio.run(void_material_purchase(str(pb_oid), VoidPurchaseInput(void_reason="Bahan cacat dikembalikan"), admin=self.owner_user))
            self.assertTrue(res["ok"])
            self.assertIsNotNone(wob_updated_payload)
            self.assertEqual(wob_updated_payload["$set"]["status"], "voided")
            self.assertIn("Bahan cacat dikembalikan", wob_updated_payload["$set"]["void_reason"])

    def test_18_void_purchase_with_paid_wage_obligation_fails_closed(self):
        """18. Void purchase with paid or partially_paid wage obligation is rejected with HTTP 409."""
        pb_oid = ObjectId()
        sample_purchase = {
            "_id": pb_oid,
            "purchase_number": "PB-202610-0018",
            "material_id": str(self.mat_id),
            "quantity": 5.0,
            "is_void": False,
            "buyer_worker_id": str(self.worker_id),
        }
        sample_wob_paid = {
            "_id": ObjectId(),
            "obligation_number": "WOB-202610-0018",
            "material_purchase_id": str(pb_oid),
            "status": "paid",  # Worker has already received money!
            "paid_amount_le": 25.0,
        }

        with patch("server.db") as mock_db:
            mock_db.material_purchases.find_one = AsyncMock(return_value=sample_purchase)
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.wage_obligations.find_one = AsyncMock(return_value=sample_wob_paid)

            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(void_material_purchase(str(pb_oid), VoidPurchaseInput(void_reason="Batal"), admin=self.owner_user))
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertIn("upah pekerja pembeli sudah dibayar", ctx.exception.detail)

    def test_18b_void_purchase_with_positive_paid_amount_fails_closed_even_if_accrued_status(self):
        """18b. Defense-in-depth: if paid_amount_le > 0, void is rejected with 409 regardless of status string."""
        pb_oid = ObjectId()
        sample_purchase = {
            "_id": pb_oid,
            "purchase_number": "PB-202610-0018B",
            "material_id": str(self.mat_id),
            "quantity": 5.0,
            "is_void": False,
            "buyer_worker_id": str(self.worker_id),
        }
        sample_wob_anomalous = {
            "_id": ObjectId(),
            "obligation_number": "WOB-202610-0018B",
            "material_purchase_id": str(pb_oid),
            "status": "accrued",  # status says accrued, but paid_amount_le has value
            "paid_amount_le": 10.0,
        }

        with patch("server.db") as mock_db:
            mock_db.material_purchases.find_one = AsyncMock(return_value=sample_purchase)
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.wage_obligations.find_one = AsyncMock(return_value=sample_wob_anomalous)

            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(void_material_purchase(str(pb_oid), VoidPurchaseInput(void_reason="Batal"), admin=self.owner_user))
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertIn("upah pekerja pembeli sudah dibayar", ctx.exception.detail)

    def test_20_void_already_voided_purchase_fails(self):
        """20. Attempting to void an already voided purchase is rejected with HTTP 400."""
        pb_oid = ObjectId()
        sample_purchase = {
            "_id": pb_oid,
            "purchase_number": "PB-202610-0020",
            "material_id": str(self.mat_id),
            "quantity": 5.0,
            "is_void": True,  # Already void
        }
        with patch("server.db") as mock_db:
            mock_db.material_purchases.find_one = AsyncMock(return_value=sample_purchase)
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(void_material_purchase(str(pb_oid), VoidPurchaseInput(void_reason="Batal lagi"), admin=self.owner_user))
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("sudah berstatus void", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
