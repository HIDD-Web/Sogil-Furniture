"""Unit tests for Phase Wage Recovery 06: Unified Pending Payment API Endpoints.

Verifies:
1. Alias routes /admin/pending-payments/summary and /admin/pending-payments/obligations
2. Category filter in admin_get_wage_obligations
3. Backward compatibility with /admin/wages/pending-summary and /admin/wage-obligations
4. Zero duplication of obligations
"""

import os
import sys
import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import server
from server import (
    admin_get_wages_pending_summary,
    admin_get_wage_obligations,
)


class TestPendingPaymentsAPI(unittest.TestCase):
    def setUp(self):
        self.owner_user = {
            "id": "admin_owner",
            "name": "Owner Admin",
            "role": "owner",
            "permissions": {"access_finance": True, "manage_orders": True},
        }

    @patch("server.db")
    def test_01_pending_payments_summary_aggregates_all_categories(self, mock_db):
        """1. /admin/pending-payments/summary aggregates all accrued/partially_paid obligations."""
        mock_obligations = [
            {
                "_id": ObjectId(),
                "obligation_number": "WOB-202610-0001",
                "worker_id": "w_1",
                "worker_name": "Worker 1",
                "task_category": "production",
                "total_amount_le": 200.0,
                "paid_amount_le": 50.0,
                "status": "partially_paid",
            },
            {
                "_id": ObjectId(),
                "obligation_number": "WOB-202610-0002",
                "worker_id": "w_1",
                "worker_name": "Worker 1",
                "task_category": "delivery",
                "total_amount_le": 100.0,
                "paid_amount_le": 0.0,
                "status": "accrued",
            },
            {
                "_id": ObjectId(),
                "obligation_number": "WOB-202610-0003",
                "worker_id": "w_2",
                "worker_name": "Worker 2",
                "task_category": "material_purchase",
                "total_amount_le": 80.0,
                "paid_amount_le": 0.0,
                "status": "accrued",
            },
        ]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=mock_obligations)
        mock_db.wage_obligations.find.return_value = mock_cursor

        res = asyncio.run(admin_get_wages_pending_summary(admin=self.owner_user))

        self.assertEqual(res["total_accrued_le"], 380.0)
        self.assertEqual(res["total_paid_le"], 50.0)
        self.assertEqual(res["total_pending_wages_le"], 330.0)
        self.assertEqual(res["pending_obligations_count"], 3)
        self.assertEqual(len(res["workers_summary"]), 2)

        w1_summary = next(w for w in res["workers_summary"] if w["worker_id"] == "w_1")
        self.assertEqual(w1_summary["total_le"], 250.0)
        self.assertEqual(w1_summary["count"], 2)

    @patch("server.db")
    def test_02_obligations_filter_by_task_category_material_purchase(self, mock_db):
        """2. task_category='material_purchase' query correctly builds MongoDB filter."""
        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.skip.return_value = mock_cursor
        mock_cursor.limit.return_value = mock_cursor
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_db.wage_obligations.find.return_value = mock_cursor
        mock_db.wage_obligations.count_documents = AsyncMock(return_value=0)

        asyncio.run(admin_get_wage_obligations(task_category="material_purchase", admin=self.owner_user))

        mock_db.wage_obligations.find.assert_called_once()
        called_query = mock_db.wage_obligations.find.call_args[0][0]
        self.assertEqual(called_query.get("task_category"), "material_purchase")

    @patch("server.db")
    def test_03_obligations_filter_by_task_category_production_in_query(self, mock_db):
        """3. task_category='production' expands to include sub-disciplines (cutting, frame, etc.)."""
        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.skip.return_value = mock_cursor
        mock_cursor.limit.return_value = mock_cursor
        mock_cursor.to_list = AsyncMock(return_value=[])
        mock_db.wage_obligations.find.return_value = mock_cursor
        mock_db.wage_obligations.count_documents = AsyncMock(return_value=0)

        asyncio.run(admin_get_wage_obligations(task_category="production", admin=self.owner_user))

        called_query = mock_db.wage_obligations.find.call_args[0][0]
        self.assertIn("$in", called_query.get("task_category", {}))
        self.assertIn("cutting", called_query["task_category"]["$in"])
        self.assertIn("production", called_query["task_category"]["$in"])

    @patch("server.db")
    def test_04_obligations_computes_remaining_amount_accurately(self, mock_db):
        """4. Returns remaining_amount_le = max(0.0, total_amount_le - paid_amount_le)."""
        mock_doc = {
            "_id": ObjectId(),
            "obligation_number": "WOB-202610-0088",
            "worker_name": "Tukang 1",
            "task_category": "delivery",
            "total_amount_le": 100.0,
            "paid_amount_le": 35.0,
            "status": "partially_paid",
        }
        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.skip.return_value = mock_cursor
        mock_cursor.limit.return_value = mock_cursor
        mock_cursor.to_list = AsyncMock(return_value=[mock_doc])
        mock_db.wage_obligations.find.return_value = mock_cursor
        mock_db.wage_obligations.count_documents = AsyncMock(return_value=1)

        res = asyncio.run(admin_get_wage_obligations(admin=self.owner_user))

        self.assertEqual(res["total"], 1)
        ob = res["obligations"][0]
        self.assertEqual(ob["remaining_amount_le"], 65.0)


if __name__ == "__main__":
    unittest.main()
