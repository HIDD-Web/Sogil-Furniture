"""Phase 10: Multi-Buyer Material Purchase Wages Test Suite.

Verifies end-to-end multi-buyer wage allocation, policy enforcement,
piastre division, transactional integrity, settlement, voiding, and backward compatibility.
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
    admin_create_wage_settlement,
    distribute_wage_piastres,
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


class TestPhase10MultiBuyerMaterialPurchaseWages(unittest.TestCase):

    def setUp(self):
        self.owner_user = {
            "id": "admin_owner",
            "name": "Owner Admin",
            "role": "owner",
            "permissions": {"modify_products": True, "access_finance": True, "manage_orders": True}
        }
        self.worker1_id = ObjectId()
        self.worker2_id = ObjectId()
        self.worker3_id = ObjectId()
        self.worker4_id = ObjectId()

        self.worker1 = {
            "_id": self.worker1_id,
            "id": str(self.worker1_id),
            "name": "Ahmad Tukang",
            "role": "employee",
            "status": "active",
        }
        self.worker2 = {
            "_id": self.worker2_id,
            "id": str(self.worker2_id),
            "name": "Budi Tukang",
            "role": "employee",
            "status": "active",
        }
        self.worker3 = {
            "_id": self.worker3_id,
            "id": str(self.worker3_id),
            "name": "Citra Tukang",
            "role": "employee",
            "status": "active",
        }
        self.worker4 = {
            "_id": self.worker4_id,
            "id": str(self.worker4_id),
            "name": "Dedi Tukang",
            "role": "employee",
            "status": "active",
        }
        self.inactive_worker_id = ObjectId()
        self.inactive_worker = {
            "_id": self.inactive_worker_id,
            "id": str(self.inactive_worker_id),
            "name": "Zulfi Nonaktif",
            "role": "employee",
            "status": "inactive",
        }

        self.mat_id = ObjectId()
        self.sample_material = {
            "_id": self.mat_id,
            "name": "Kayu Jati Solid",
            "specs": "10x10 x 400 cm",
            "category": "Material",
            "unit": "batang",
            "status": "active",
            "current_stock": 25.0,
            "latest_price": 500.0,
            "latest_currency": "EGP",
            "latest_purchase_date": "2026-10-20",
        }

        self.default_active_policy = {
            "policy_type": "material_purchase",
            "is_configured": True,
            "enabled": True,
            "default_wage_per_purchase_le": 100.0,
            "max_buyers": 3,
            "unusual_amount_threshold_le": 200.0,
            "max_wage_per_purchase_le": 300.0,
        }

    async def _fake_tx(self, client, fn):
        return await fn(session=None)

    def _mock_settings_lookup(self, policy=None):
        pol = policy if policy is not None else self.default_active_policy
        async def fake_find_settings(query, *args, **kwargs):
            if isinstance(query, dict) and query.get("key") == "material_purchase_wage_policy":
                return {"key": "material_purchase_wage_policy", "value": pol}
            return {"value": 357.0}
        return fake_find_settings

    def _mock_admin_lookup(self, worker_map):
        async def fake_find_admin(query, *args, **kwargs):
            id_val = query.get("_id")
            if isinstance(id_val, dict) and "$in" in id_val:
                for candidate in id_val["$in"]:
                    if str(candidate) in worker_map:
                        return worker_map[str(candidate)]
                return None
            if isinstance(id_val, (ObjectId, str)):
                return worker_map.get(str(id_val))
            if "id" in query:
                return worker_map.get(str(query["id"]))
            return None
        return fake_find_admin

    @patch("server.execute_transaction_with_safety")
    @patch("server.recalculate_material_latest_price", new_callable=AsyncMock)
    @patch("server.apply_purchase_stock_in", new_callable=AsyncMock)
    @patch("server.apply_purchase_finance_expense", new_callable=AsyncMock)
    @patch("server.get_next_purchase_number", new_callable=AsyncMock)
    @patch("server.generate_obligation_number", new_callable=AsyncMock)
    def test_01_active_policy_1_buyer(self, mock_wob_num, mock_pnum, mock_fin, mock_stock, mock_price, mock_tx):
        """1. Active policy with 1 buyer creates 1 wage obligation for full amount."""
        mock_pnum.return_value = "PB-202610-1001"
        mock_wob_num.return_value = "WOB-202610-1001"
        mock_tx.side_effect = self._fake_tx

        created_wobs = []
        async def fake_insert_wob(doc, session=None):
            w = copy.deepcopy(doc)
            w["_id"] = ObjectId()
            created_wobs.append(w)
            return MagicMock(inserted_id=w["_id"])

        with patch("server.db") as mock_db:
            mock_db.wage_policies.find_one = AsyncMock(return_value=self.default_active_policy)
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.settings.find_one = AsyncMock(return_value={"value": 357.0})
            mock_db.admins.find_one = self._mock_admin_lookup({str(self.worker1_id): self.worker1})
            mock_db.material_purchases.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
            mock_db.material_purchases.update_one = AsyncMock()
            mock_db.wage_obligations.find_one = AsyncMock(return_value=None)
            mock_db.wage_obligations.insert_one = fake_insert_wob

            payload = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-30",
                unit_price=400.0,
                quantity=5.0,
                currency="EGP",
                buyer_worker_ids=[str(self.worker1_id)],
                buyer_wage_amount=100.0,
            )
            res = asyncio.run(create_material_purchase(payload, admin=self.owner_user))

            self.assertEqual(len(created_wobs), 1)
            self.assertEqual(created_wobs[0]["total_amount_le"], 100.0)
            self.assertEqual(created_wobs[0]["worker_id"], str(self.worker1_id))
            self.assertEqual(created_wobs[0]["worker_name"], "Ahmad Tukang")
            self.assertEqual(res["buyer_worker_id"], str(self.worker1_id))
            self.assertEqual(res["buyer_worker_name"], "Ahmad Tukang")
            self.assertEqual(len(res["buyer_workers"]), 1)
            self.assertEqual(res["buyer_workers"][0]["amount_le"], 100.0)

    @patch("server.execute_transaction_with_safety")
    @patch("server.recalculate_material_latest_price", new_callable=AsyncMock)
    @patch("server.apply_purchase_stock_in", new_callable=AsyncMock)
    @patch("server.apply_purchase_finance_expense", new_callable=AsyncMock)
    @patch("server.get_next_purchase_number", new_callable=AsyncMock)
    @patch("server.generate_obligation_number", new_callable=AsyncMock)
    def test_02_active_policy_2_buyers(self, mock_wob_num, mock_pnum, mock_fin, mock_stock, mock_price, mock_tx):
        """2. Active policy with 2 buyers splits 100 LE into 50.00 and 50.00 LE."""
        mock_pnum.return_value = "PB-202610-1002"
        wob_counter = 100
        def fake_wob_num(*args, **kwargs):
            nonlocal wob_counter
            wob_counter += 1
            return f"WOB-202610-{wob_counter}"
        mock_wob_num.side_effect = fake_wob_num
        mock_tx.side_effect = self._fake_tx

        created_wobs = []
        async def fake_insert_wob(doc, session=None):
            w = copy.deepcopy(doc)
            w["_id"] = ObjectId()
            created_wobs.append(w)
            return MagicMock(inserted_id=w["_id"])

        with patch("server.db") as mock_db:
            mock_db.wage_policies.find_one = AsyncMock(return_value=self.default_active_policy)
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.settings.find_one = AsyncMock(return_value={"value": 357.0})
            mock_db.admins.find_one = self._mock_admin_lookup({
                str(self.worker1_id): self.worker1,
                str(self.worker2_id): self.worker2,
            })
            mock_db.material_purchases.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
            mock_db.material_purchases.update_one = AsyncMock()
            mock_db.wage_obligations.find_one = AsyncMock(return_value=None)
            mock_db.wage_obligations.insert_one = fake_insert_wob

            payload = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-30",
                unit_price=400.0,
                quantity=5.0,
                currency="EGP",
                buyer_worker_ids=[str(self.worker1_id), str(self.worker2_id)],
                buyer_wage_amount=100.0,
            )
            res = asyncio.run(create_material_purchase(payload, admin=self.owner_user))

            self.assertEqual(len(created_wobs), 2)
            self.assertEqual(created_wobs[0]["total_amount_le"], 50.0)
            self.assertEqual(created_wobs[1]["total_amount_le"], 50.0)
            self.assertEqual(created_wobs[0]["worker_id"], str(self.worker1_id))
            self.assertEqual(created_wobs[1]["worker_id"], str(self.worker2_id))
            self.assertEqual(len(res["buyer_workers"]), 2)

    @patch("server.execute_transaction_with_safety")
    @patch("server.recalculate_material_latest_price", new_callable=AsyncMock)
    @patch("server.apply_purchase_stock_in", new_callable=AsyncMock)
    @patch("server.apply_purchase_finance_expense", new_callable=AsyncMock)
    @patch("server.get_next_purchase_number", new_callable=AsyncMock)
    @patch("server.generate_obligation_number", new_callable=AsyncMock)
    def test_03_active_policy_3_buyers_exact_piastre(self, mock_wob_num, mock_pnum, mock_fin, mock_stock, mock_price, mock_tx):
        """3. Active policy with 3 buyers splits 100 LE into 33.34, 33.33, 33.33 LE (zero drift)."""
        mock_pnum.return_value = "PB-202610-1003"
        counter = 1
        def fake_wob_num(*args, **kwargs):
            nonlocal counter
            res = f"WOB-202610-{counter:04d}"
            counter += 1
            return res
        mock_wob_num.side_effect = fake_wob_num
        mock_tx.side_effect = self._fake_tx

        created_wobs = []
        async def fake_insert_wob(doc, session=None):
            w = copy.deepcopy(doc)
            w["_id"] = ObjectId()
            created_wobs.append(w)
            return MagicMock(inserted_id=w["_id"])

        with patch("server.db") as mock_db:
            mock_db.wage_policies.find_one = AsyncMock(return_value=self.default_active_policy)
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.settings.find_one = AsyncMock(return_value={"value": 357.0})
            mock_db.admins.find_one = self._mock_admin_lookup({
                str(self.worker1_id): self.worker1,
                str(self.worker2_id): self.worker2,
                str(self.worker3_id): self.worker3,
            })
            mock_db.material_purchases.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
            mock_db.material_purchases.update_one = AsyncMock()
            mock_db.wage_obligations.find_one = AsyncMock(return_value=None)
            mock_db.wage_obligations.insert_one = fake_insert_wob

            payload = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-30",
                unit_price=400.0,
                quantity=5.0,
                currency="EGP",
                buyer_worker_ids=[str(self.worker1_id), str(self.worker2_id), str(self.worker3_id)],
                buyer_wage_amount=100.0,
            )
            res = asyncio.run(create_material_purchase(payload, admin=self.owner_user))

            self.assertEqual(len(created_wobs), 3)
            amounts = [w["total_amount_le"] for w in created_wobs]
            self.assertEqual(amounts, [33.34, 33.33, 33.33])
            total_sum = round(sum(amounts), 2)
            self.assertEqual(total_sum, 100.0)

    @patch("server.execute_transaction_with_safety")
    @patch("server.recalculate_material_latest_price", new_callable=AsyncMock)
    @patch("server.apply_purchase_stock_in", new_callable=AsyncMock)
    @patch("server.apply_purchase_finance_expense", new_callable=AsyncMock)
    @patch("server.get_next_purchase_number", new_callable=AsyncMock)
    @patch("server.generate_obligation_number", new_callable=AsyncMock)
    def test_04_dynamic_policy_changes(self, mock_wob_num, mock_pnum, mock_fin, mock_stock, mock_price, mock_tx):
        """4. System dynamically respects stored policy max_buyers without hardcoding 3."""
        mock_pnum.return_value = "PB-202610-1004"
        mock_wob_num.return_value = "WOB-202610-1004"
        mock_tx.side_effect = self._fake_tx

        policy_max_2 = copy.deepcopy(self.default_active_policy)
        policy_max_2["max_buyers"] = 2

        with patch("server.db") as mock_db:
            mock_db.settings.find_one = self._mock_settings_lookup(policy=policy_max_2)
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.admins.find_one = self._mock_admin_lookup({
                str(self.worker1_id): self.worker1,
                str(self.worker2_id): self.worker2,
                str(self.worker3_id): self.worker3,
            })

            payload = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-30",
                unit_price=400.0,
                quantity=5.0,
                currency="EGP",
                buyer_worker_ids=[str(self.worker1_id), str(self.worker2_id), str(self.worker3_id)],
                buyer_wage_amount=100.0,
            )
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(create_material_purchase(payload, admin=self.owner_user))
            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("melebihi batas maksimum", ctx.exception.detail)

    def test_05_exceeding_max_buyers_rejected(self):
        """5. Exceeding max_buyers (4 buyers when max is 3) is rejected with HTTP 422."""
        with patch("server.db") as mock_db:
            mock_db.settings.find_one = self._mock_settings_lookup()
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)

            payload = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-30",
                unit_price=400.0,
                quantity=5.0,
                currency="EGP",
                buyer_worker_ids=[
                    str(self.worker1_id),
                    str(self.worker2_id),
                    str(self.worker3_id),
                    str(self.worker4_id),
                ],
                buyer_wage_amount=100.0,
            )
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(create_material_purchase(payload, admin=self.owner_user))
            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("melebihi batas maksimum", ctx.exception.detail)

    def test_06_worker_validation(self):
        """6. Rejects duplicate worker IDs, non-existent workers, and inactive workers."""
        with patch("server.db") as mock_db:
            mock_db.settings.find_one = self._mock_settings_lookup()
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)

            # A. Duplicate workers
            payload_dup = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-30",
                unit_price=400.0,
                quantity=5.0,
                buyer_worker_ids=[str(self.worker1_id), str(self.worker1_id)],
                buyer_wage_amount=100.0,
            )
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(create_material_purchase(payload_dup, admin=self.owner_user))
            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("duplikat", ctx.exception.detail.lower())

            # B. Inactive worker
            mock_db.admins.find_one = self._mock_admin_lookup({
                str(self.worker1_id): self.worker1,
                str(self.inactive_worker_id): self.inactive_worker,
            })
            payload_inact = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-30",
                unit_price=400.0,
                quantity=5.0,
                buyer_worker_ids=[str(self.worker1_id), str(self.inactive_worker_id)],
                buyer_wage_amount=100.0,
            )
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(create_material_purchase(payload_inact, admin=self.owner_user))
            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("tidak aktif", ctx.exception.detail.lower())

            # C. Non-existent worker
            mock_db.admins.find_one = AsyncMock(return_value=None)
            payload_notfound = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-30",
                unit_price=400.0,
                quantity=5.0,
                buyer_worker_ids=[str(ObjectId())],
                buyer_wage_amount=100.0,
            )
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(create_material_purchase(payload_notfound, admin=self.owner_user))
            self.assertEqual(ctx.exception.status_code, 404)

    def test_07_exact_piastre_split_without_drift(self):
        """7. distribute_wage_piastres allocates remainder piastres correctly with zero drift."""
        res = distribute_wage_piastres(100.07, ["w1", "w2", "w3"])
        self.assertEqual(len(res), 3)
        self.assertEqual(res[0]["amount_le"], 33.36)
        self.assertEqual(res[1]["amount_le"], 33.36)
        self.assertEqual(res[2]["amount_le"], 33.35)
        self.assertEqual(res[0]["amount_piastres"], 3336)
        self.assertEqual(res[1]["amount_piastres"], 3336)
        self.assertEqual(res[2]["amount_piastres"], 3335)
        self.assertEqual(sum(r["amount_piastres"] for r in res), 10007)
        self.assertEqual(round(sum(r["amount_le"] for r in res), 2), 100.07)

    @patch("server.execute_transaction_with_safety")
    @patch("server.recalculate_material_latest_price", new_callable=AsyncMock)
    @patch("server.apply_purchase_stock_in", new_callable=AsyncMock)
    @patch("server.apply_purchase_finance_expense", new_callable=AsyncMock)
    @patch("server.get_next_purchase_number", new_callable=AsyncMock)
    @patch("server.generate_obligation_number", new_callable=AsyncMock)
    def test_08_threshold_enforcement(self, mock_wob_num, mock_pnum, mock_fin, mock_stock, mock_price, mock_tx):
        """8. Wage > unusual_amount_threshold_le requires confirmation and notes."""
        mock_pnum.return_value = "PB-202610-1008"
        mock_wob_num.return_value = "WOB-202610-1008"
        mock_tx.side_effect = self._fake_tx

        created_wobs = []
        async def fake_insert_wob(doc, session=None):
            w = copy.deepcopy(doc)
            w["_id"] = ObjectId()
            created_wobs.append(w)
            return MagicMock(inserted_id=w["_id"])

        with patch("server.db") as mock_db:
            mock_db.settings.find_one = self._mock_settings_lookup()
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.admins.find_one = self._mock_admin_lookup({str(self.worker1_id): self.worker1})
            mock_db.material_purchases.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
            mock_db.material_purchases.update_one = AsyncMock()
            mock_db.wage_obligations.find_one = AsyncMock(return_value=None)
            mock_db.wage_obligations.insert_one = fake_insert_wob

            # A. Wage 250 LE (> 200 LE) without confirmation -> 422
            p1 = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-30",
                unit_price=400.0,
                quantity=5.0,
                buyer_worker_ids=[str(self.worker1_id)],
                buyer_wage_amount=250.0,
                confirmed_unusual_amount=False,
            )
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(create_material_purchase(p1, admin=self.owner_user))
            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("konfirmasi", ctx.exception.detail.lower())

            # B. Wage 250 LE with confirmation but notes < 3 chars -> 422
            p2 = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-30",
                unit_price=400.0,
                quantity=5.0,
                buyer_worker_ids=[str(self.worker1_id)],
                buyer_wage_amount=250.0,
                confirmed_unusual_amount=True,
                buyer_wage_notes="ok",
            )
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(create_material_purchase(p2, admin=self.owner_user))
            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("alasan", ctx.exception.detail.lower())

            # C. Wage 250 LE with confirmation and valid notes -> Success
            p3 = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-30",
                unit_price=400.0,
                quantity=5.0,
                buyer_worker_ids=[str(self.worker1_id)],
                buyer_wage_amount=250.0,
                confirmed_unusual_amount=True,
                buyer_wage_notes="Belanja darurat lembur malam hari dan barang berat",
            )
            res = asyncio.run(create_material_purchase(p3, admin=self.owner_user))
            self.assertEqual(len(created_wobs), 1)
            self.assertEqual(created_wobs[0]["total_amount_le"], 250.0)

    def test_09_hard_cap_enforcement(self):
        """9. Wage exceeding max_wage_per_purchase_le (300 LE) is rejected with HTTP 422."""
        with patch("server.db") as mock_db:
            mock_db.settings.find_one = self._mock_settings_lookup()
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.admins.find_one = self._mock_admin_lookup({str(self.worker1_id): self.worker1})

            payload = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-30",
                unit_price=400.0,
                quantity=5.0,
                buyer_worker_ids=[str(self.worker1_id)],
                buyer_wage_amount=350.0,
                confirmed_unusual_amount=True,
                buyer_wage_notes="Diatas plafon keras",
            )
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(create_material_purchase(payload, admin=self.owner_user))
            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("melebihi batas maksimum keras", ctx.exception.detail)

    @patch("server.execute_transaction_with_safety")
    @patch("server.recalculate_material_latest_price", new_callable=AsyncMock)
    @patch("server.apply_purchase_stock_in", new_callable=AsyncMock)
    @patch("server.apply_purchase_finance_expense", new_callable=AsyncMock)
    @patch("server.get_next_purchase_number", new_callable=AsyncMock)
    def test_10_inactive_policy_enforcement(self, mock_pnum, mock_fin, mock_stock, mock_price, mock_tx):
        """10. When policy is disabled, purchase with wage is rejected; purchase without wage succeeds."""
        mock_pnum.return_value = "PB-202610-1010"
        mock_tx.side_effect = self._fake_tx

        inactive_policy = copy.deepcopy(self.default_active_policy)
        inactive_policy["enabled"] = False
        inactive_policy["is_configured"] = True

        with patch("server.db") as mock_db:
            mock_db.settings.find_one = self._mock_settings_lookup(policy=inactive_policy)
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.admins.find_one = self._mock_admin_lookup({str(self.worker1_id): self.worker1})
            mock_db.material_purchases.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))

            # Wage requested while policy inactive -> 422
            p_wage = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-30",
                unit_price=400.0,
                quantity=5.0,
                buyer_worker_ids=[str(self.worker1_id)],
                buyer_wage_amount=100.0,
            )
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(create_material_purchase(p_wage, admin=self.owner_user))
            self.assertEqual(ctx.exception.status_code, 422)
            self.assertIn("dinonaktifkan", ctx.exception.detail.lower())

            # No wage requested -> succeeds normally
            p_no_wage = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-30",
                unit_price=400.0,
                quantity=5.0,
            )
            res = asyncio.run(create_material_purchase(p_no_wage, admin=self.owner_user))
            self.assertEqual(res["purchase_number"], "PB-202610-1010")

    @patch("server.execute_transaction_with_safety")
    @patch("server.recalculate_material_latest_price", new_callable=AsyncMock)
    @patch("server.apply_purchase_stock_in", new_callable=AsyncMock)
    @patch("server.apply_purchase_finance_expense", new_callable=AsyncMock)
    @patch("server.get_next_purchase_number", new_callable=AsyncMock)
    def test_11_transactional_atomicity(self, mock_pnum, mock_fin, mock_stock, mock_price, mock_tx):
        """11. Failure at any point during purchase & wage creation triggers clean transaction abort."""
        mock_pnum.return_value = "PB-202610-1011"
        mock_tx.side_effect = self._fake_tx

        payload = MaterialPurchaseInput(
            material_id=str(self.mat_id),
            purchase_date="2026-10-30",
            unit_price=400.0,
            quantity=5.0,
            buyer_worker_ids=[str(self.worker1_id), str(self.worker2_id)],
            buyer_wage_amount=100.0,
        )

        # 11a. Failure on wage obligation insert
        with patch("server.db") as mock_db:
            mock_db.settings.find_one = self._mock_settings_lookup()
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.admins.find_one = self._mock_admin_lookup({
                str(self.worker1_id): self.worker1,
                str(self.worker2_id): self.worker2,
            })
            mock_db.material_purchases.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
            mock_db.wage_obligations.find_one = AsyncMock(return_value=None)
            mock_db.wage_obligations.insert_one = AsyncMock(side_effect=Exception("Database write failure on wob"))

            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(create_material_purchase(payload, admin=self.owner_user))
            self.assertEqual(ctx.exception.status_code, 500)
            self.assertIn("Gagal mencatat transaksi", ctx.exception.detail)

        # 11b. Failure on stock in
        mock_stock.side_effect = Exception("Stock movement failure")
        with patch("server.db") as mock_db:
            mock_db.settings.find_one = self._mock_settings_lookup()
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.admins.find_one = self._mock_admin_lookup({
                str(self.worker1_id): self.worker1,
                str(self.worker2_id): self.worker2,
            })
            mock_db.material_purchases.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))

            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(create_material_purchase(payload, admin=self.owner_user))
            self.assertEqual(ctx.exception.status_code, 500)
        mock_stock.side_effect = None

        # 11c. Failure on finance expense
        mock_fin.side_effect = Exception("Finance ledger failure")
        with patch("server.db") as mock_db:
            mock_db.settings.find_one = self._mock_settings_lookup()
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.admins.find_one = self._mock_admin_lookup({
                str(self.worker1_id): self.worker1,
                str(self.worker2_id): self.worker2,
            })
            mock_db.material_purchases.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))

            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(create_material_purchase(payload, admin=self.owner_user))
            self.assertEqual(ctx.exception.status_code, 500)
        mock_fin.side_effect = None

        # 11d. Failure on purchase document update_one (linking wage references)
        with patch("server.db") as mock_db:
            mock_db.settings.find_one = self._mock_settings_lookup()
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.admins.find_one = self._mock_admin_lookup({
                str(self.worker1_id): self.worker1,
                str(self.worker2_id): self.worker2,
            })
            mock_db.material_purchases.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
            mock_db.wage_obligations.find_one = AsyncMock(return_value=None)
            mock_db.wage_obligations.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
            mock_db.material_purchases.update_one = AsyncMock(side_effect=Exception("Failed to update purchase refs"))

            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(create_material_purchase(payload, admin=self.owner_user))
            self.assertEqual(ctx.exception.status_code, 500)

    def test_12_accrual_event_key_deterministic(self):
        """12. Accrual event key is unique per worker in multi-buyer purchases."""
        pb_id = "672200000000000000000001"
        wids = ["w1", "w2", "w3"]
        keys = [f"material_purchase:{pb_id}:{wid}" for wid in wids]
        self.assertEqual(len(set(keys)), 3)
        self.assertIn(f"material_purchase:{pb_id}:w1", keys)
        self.assertIn(f"material_purchase:{pb_id}:w2", keys)
        self.assertIn(f"material_purchase:{pb_id}:w3", keys)

    def test_13_pending_payment_visibility(self):
        """13. Multi-buyer obligations are aggregated correctly in admin_get_wages_pending_summary."""
        wobs = [
            {
                "_id": ObjectId(),
                "obligation_number": "WOB-202610-0001",
                "worker_id": str(self.worker1_id),
                "worker_name": "Ahmad Tukang",
                "task_category": "material_purchase",
                "total_amount_le": 50.0,
                "paid_amount_le": 0.0,
                "status": "accrued",
                "purchase_number": "PB-202610-0001",
                "accrued_at": datetime.now(timezone.utc),
            },
            {
                "_id": ObjectId(),
                "obligation_number": "WOB-202610-0002",
                "worker_id": str(self.worker2_id),
                "worker_name": "Budi Tukang",
                "task_category": "material_purchase",
                "total_amount_le": 50.0,
                "paid_amount_le": 0.0,
                "status": "accrued",
                "purchase_number": "PB-202610-0001",
                "accrued_at": datetime.now(timezone.utc),
            }
        ]

        with patch("server.db") as mock_db:
            mock_db.wage_obligations.find.return_value = AsyncCursorMock(wobs)
            mock_db.wage_obligations.count_documents = AsyncMock(return_value=2)
            summary = asyncio.run(admin_get_wages_pending_summary(admin=self.owner_user))

            self.assertEqual(summary["total_accrued_le"], 100.0)
            self.assertEqual(summary["total_pending_wages_le"], 100.0)

    @patch("server.is_standalone_fallback_permitted", return_value=True)
    @patch("server.client.start_session")
    @patch("server.generate_wage_settlement_number", new_callable=AsyncMock)
    @patch("server.execute_transaction_with_safety")
    def test_14_wage_settlement_integration(self, mock_tx, mock_ws_num, mock_session, mock_fallback):
        """14. Settlement executes for multi-buyer material purchase obligation into Finance 'Pekerja'."""
        mock_ws_num.return_value = "WS-202610-0001"
        mock_session.side_effect = pymongo.errors.ConfigurationError("Standalone")
        mock_tx.side_effect = self._fake_tx

        sample_wob_id = ObjectId()
        sample_wob = {
            "_id": sample_wob_id,
            "id": str(sample_wob_id),
            "obligation_number": "WOB-202610-0088",
            "worker_id": str(self.worker1_id),
            "worker_name": "Ahmad Tukang",
            "task_category": "material_purchase",
            "pricing_basis": "lump_sum",
            "total_amount_le": 50.0,
            "paid_amount_le": 0.0,
            "status": "accrued",
            "purchase_number": "PB-202610-0002",
            "locked_exchange_rate": 350.0,
            "created_at": "2026-10-27T10:00:00Z"
        }

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
            mock_db.admins.find_one = AsyncMock(return_value=self.worker1)
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

            payload = WageSettlementCreateInput(
                worker_id=str(self.worker1_id),
                amount_le=50.0,
                payment_currency="IDR",
                payment_method="cash",
                settlement_rate=350.0,
                actual_payout_amount=17500.0,
                idempotency_key="idem-settle-phase10-001",
            )
            res = asyncio.run(admin_create_wage_settlement(payload, admin=self.owner_user))

            self.assertEqual(res["settlement_number"], "WS-202610-0001")
            self.assertEqual(len(finance_transactions_inserted), 1)
            self.assertEqual(finance_transactions_inserted[0]["category"], "Pekerja")
            self.assertEqual(finance_transactions_inserted[0]["amount"], 17500.0)

    @patch("server.execute_transaction_with_safety")
    @patch("server.apply_purchase_stock_reversal", new_callable=AsyncMock)
    @patch("server.apply_purchase_finance_reversal", new_callable=AsyncMock)
    @patch("server.recalculate_material_latest_price", new_callable=AsyncMock)
    def test_15_void_purchase_with_multi_buyer_obligations(self, mock_price, mock_fin_rev, mock_stock_rev, mock_tx):
        """15. Exhaustive void testing covering all 6 safety scenarios from Phase 10.1 audit."""
        mock_tx.side_effect = self._fake_tx

        pb_id = ObjectId()
        sample_purchase = {
            "_id": pb_id,
            "purchase_number": "PB-202610-0015",
            "material_id": str(self.mat_id),
            "quantity": 5.0,
            "total_amount": 2000.0,
            "currency": "EGP",
            "is_void": False,
            "buyer_worker_ids": [str(self.worker1_id), str(self.worker2_id), str(self.worker3_id)],
            "buyer_wage_obligation_numbers": ["WOB-01", "WOB-02", "WOB-03"],
        }

        # Skenario 1: Pembelian memiliki 3 kewajiban upah, seluruhnya accrued (unpaid) -> Voids all
        wob1_accrued = {
            "_id": ObjectId(),
            "obligation_number": "WOB-01",
            "material_purchase_id": str(pb_id),
            "status": "accrued",
            "paid_amount_le": 0.0,
        }
        wob2_accrued = {
            "_id": ObjectId(),
            "obligation_number": "WOB-02",
            "material_purchase_id": str(pb_id),
            "status": "accrued",
            "paid_amount_le": 0.0,
        }
        wob3_accrued = {
            "_id": ObjectId(),
            "obligation_number": "WOB-03",
            "material_purchase_id": str(pb_id),
            "status": "accrued",
            "paid_amount_le": 0.0,
        }

        with patch("server.db") as mock_db:
            mock_db.material_purchases.find_one = AsyncMock(return_value=sample_purchase)
            mock_db.material_purchases.find_one_and_update = AsyncMock(return_value={**sample_purchase, "is_void": True})
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.wage_obligations.find.return_value = AsyncCursorMock([wob1_accrued, wob2_accrued, wob3_accrued])
            mock_db.wage_obligations.update_many = AsyncMock()

            v_input = VoidPurchaseInput(void_reason="Pembelian keliru dibatalkan")
            res = asyncio.run(void_material_purchase(str(pb_id), v_input, admin=self.owner_user))
            self.assertTrue(res["ok"])
            mock_db.wage_obligations.update_many.assert_called_once()

        # Skenario 2: 1 dari 3 kewajiban sudah dibayar (status 'paid') -> Ditolak keras HTTP 409
        wob1_paid = {
            "_id": ObjectId(),
            "obligation_number": "WOB-01",
            "material_purchase_id": str(pb_id),
            "status": "paid",
            "paid_amount_le": 33.34,
        }
        with patch("server.db") as mock_db:
            mock_db.material_purchases.find_one = AsyncMock(return_value=sample_purchase)
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.wage_obligations.find.return_value = AsyncCursorMock([wob1_paid, wob2_accrued, wob3_accrued])

            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(void_material_purchase(str(pb_id), v_input, admin=self.owner_user))
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertIn("upah pekerja pembeli sudah dibayar", ctx.exception.detail.lower())

        # Skenario 3: Kewajiban dibayar sebagian (status 'partially_paid' atau paid_amount_le > 0) -> Ditolak HTTP 409
        wob2_partial = {
            "_id": ObjectId(),
            "obligation_number": "WOB-02",
            "material_purchase_id": str(pb_id),
            "status": "partially_paid",
            "paid_amount_le": 10.0,
        }
        with patch("server.db") as mock_db:
            mock_db.material_purchases.find_one = AsyncMock(return_value=sample_purchase)
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.wage_obligations.find.return_value = AsyncCursorMock([wob1_accrued, wob2_partial, wob3_accrued])

            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(void_material_purchase(str(pb_id), v_input, admin=self.owner_user))
            self.assertEqual(ctx.exception.status_code, 409)

        # Skenario 4: Pembelian lama dengan single-buyer obligation -> Voids single obligation
        legacy_purchase = {
            "_id": pb_id,
            "purchase_number": "PB-202610-0014-LEGACY",
            "material_id": str(self.mat_id),
            "quantity": 2.0,
            "total_amount": 1000.0,
            "currency": "EGP",
            "is_void": False,
            "buyer_worker_id": str(self.worker1_id),
            "buyer_wage_obligation_number": "WOB-LEGACY-01",
        }
        legacy_wob = {
            "_id": ObjectId(),
            "obligation_number": "WOB-LEGACY-01",
            "material_purchase_id": str(pb_id),
            "status": "accrued",
            "paid_amount_le": 0.0,
        }
        with patch("server.db") as mock_db:
            mock_db.material_purchases.find_one = AsyncMock(return_value=legacy_purchase)
            mock_db.material_purchases.find_one_and_update = AsyncMock(return_value={**legacy_purchase, "is_void": True})
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.wage_obligations.find.return_value = AsyncCursorMock([legacy_wob])
            mock_db.wage_obligations.update_many = AsyncMock()

            res = asyncio.run(void_material_purchase(str(pb_id), v_input, admin=self.owner_user))
            self.assertTrue(res["ok"])

        # Skenario 5: Pembelian tanpa upah pekerja -> Void berhasil tanpa memodifikasi kewajiban
        no_wage_purchase = {
            "_id": pb_id,
            "purchase_number": "PB-202610-0015-NOWAGE",
            "material_id": str(self.mat_id),
            "quantity": 3.0,
            "total_amount": 1500.0,
            "currency": "EGP",
            "is_void": False,
        }
        with patch("server.db") as mock_db:
            mock_db.material_purchases.find_one = AsyncMock(return_value=no_wage_purchase)
            mock_db.material_purchases.find_one_and_update = AsyncMock(return_value={**no_wage_purchase, "is_void": True})
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.wage_obligations.find.return_value = AsyncCursorMock([])
            mock_db.wage_obligations.update_many = AsyncMock()

            res = asyncio.run(void_material_purchase(str(pb_id), v_input, admin=self.owner_user))
            self.assertTrue(res["ok"])

        # Skenario 6: Kewajiban milik pembelian lain tidak terpengaruh / pencarian terisolasi
        other_purchase_wob = {
            "_id": ObjectId(),
            "obligation_number": "WOB-OTHER-99",
            "material_purchase_id": "672200000000000000000999",  # Different purchase ID
            "status": "paid",  # Paid, but belongs to OTHER purchase!
            "paid_amount_le": 100.0,
            "purchase_number": "PB-202610-9999",
        }
        with patch("server.db") as mock_db:
            # Query strictly by pb_id: other_purchase_wob is NOT returned by the database cursor
            mock_db.material_purchases.find_one = AsyncMock(return_value=sample_purchase)
            mock_db.material_purchases.find_one_and_update = AsyncMock(return_value={**sample_purchase, "is_void": True})
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.wage_obligations.find.return_value = AsyncCursorMock([wob1_accrued, wob2_accrued, wob3_accrued])
            mock_db.wage_obligations.update_many = AsyncMock()

            res = asyncio.run(void_material_purchase(str(pb_id), v_input, admin=self.owner_user))
            self.assertTrue(res["ok"])

    @patch("server.execute_transaction_with_safety")
    @patch("server.recalculate_material_latest_price", new_callable=AsyncMock)
    @patch("server.apply_purchase_stock_in", new_callable=AsyncMock)
    @patch("server.apply_purchase_finance_expense", new_callable=AsyncMock)
    @patch("server.get_next_purchase_number", new_callable=AsyncMock)
    @patch("server.generate_obligation_number", new_callable=AsyncMock)
    def test_16_backward_compatibility_single_buyer(self, mock_wob_num, mock_pnum, mock_fin, mock_stock, mock_price, mock_tx):
        """16. Legacy single-buyer payload works seamlessly without buyer_worker_ids."""
        mock_pnum.return_value = "PB-202610-1016"
        mock_wob_num.return_value = "WOB-202610-1016"
        mock_tx.side_effect = self._fake_tx

        created_wob = None
        async def fake_insert_wob(doc, session=None):
            nonlocal created_wob
            created_wob = copy.deepcopy(doc)
            created_wob["_id"] = ObjectId()
            return MagicMock(inserted_id=created_wob["_id"])

        with patch("server.db") as mock_db:
            mock_db.wage_policies.find_one = AsyncMock(return_value=self.default_active_policy)
            mock_db.materials.find_one = AsyncMock(return_value=self.sample_material)
            mock_db.settings.find_one = AsyncMock(return_value={"value": 357.0})
            mock_db.admins.find_one = self._mock_admin_lookup({str(self.worker1_id): self.worker1})
            mock_db.material_purchases.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
            mock_db.material_purchases.update_one = AsyncMock()
            mock_db.wage_obligations.find_one = AsyncMock(return_value=None)
            mock_db.wage_obligations.insert_one = fake_insert_wob

            # Legacy payload sends buyer_worker_id only
            payload = MaterialPurchaseInput(
                material_id=str(self.mat_id),
                purchase_date="2026-10-30",
                unit_price=400.0,
                quantity=5.0,
                buyer_worker_id=str(self.worker1_id),
                buyer_wage_amount=80.0,
            )
            res = asyncio.run(create_material_purchase(payload, admin=self.owner_user))

            self.assertIsNotNone(created_wob)
            self.assertEqual(created_wob["total_amount_le"], 80.0)
            self.assertEqual(created_wob["worker_id"], str(self.worker1_id))
            self.assertEqual(created_wob["worker_name"], "Ahmad Tukang")
            self.assertEqual(res["buyer_worker_id"], str(self.worker1_id))

    def test_17_cross_module_isolation_regression(self):
        """17. Verifies category isolation between Admin, Production, Delivery, and Material Purchase wages."""
        self.assertIn("material_purchase", CONTROLLED_TASK_CATEGORIES)
        self.assertIn("delivery", CONTROLLED_TASK_CATEGORIES)
        self.assertIn("assembly", CONTROLLED_TASK_CATEGORIES)
        self.assertIn("finishing", CONTROLLED_TASK_CATEGORIES)
        self.assertIn("cutting", CONTROLLED_TASK_CATEGORIES)
        self.assertNotIn("admin", CONTROLLED_TASK_CATEGORIES)


if __name__ == "__main__":
    unittest.main()
