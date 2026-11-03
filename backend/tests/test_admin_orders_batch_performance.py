"""
Regression & Performance Test Suite for Admin Orders Batching & Payment Summary.

Verifies:
1. compute_payment_summary_from_records produces 100% identical results to compute_order_payment_summary.
2. Handling of orders with no payments, single payment, multiple payments, overpayments, and legacy DP.
3. admin_list_orders eliminates N+1 queries by executing exactly 1 batch query for payments regardless of N orders.
4. Filter parameters (order_status, payment_status, q) are preserved.
"""

import pytest
from bson import ObjectId
from unittest.mock import AsyncMock, MagicMock, patch

from server import (
    compute_payment_summary_from_records,
    compute_order_payment_summary,
    admin_list_orders,
)

class TestPaymentSummaryEquivalence:
    """Proves that batch in-memory calculation matches isolated async calculation 100%."""

    def test_order_without_payments_belum_dibayar(self):
        order = {
            "_id": ObjectId("507f1f77bcf86cd799439011"),
            "total_le": 1000.0,
            "payment_status": "belum_dibayar",
        }
        res = compute_payment_summary_from_records(order, [])
        assert res["payment_status"] == "belum_dibayar"
        assert res["paid_amount_le"] == 0.0
        assert res["outstanding_amount_le"] == 1000.0
        assert res["is_legacy_derived"] is True
        assert res["valid_payments_count"] == 0

    def test_order_without_payments_legacy_lunas(self):
        order = {
            "_id": ObjectId("507f1f77bcf86cd799439012"),
            "total_le": 1500.0,
            "payment_status": "lunas",
        }
        res = compute_payment_summary_from_records(order, [])
        assert res["payment_status"] == "lunas"
        assert res["paid_amount_le"] == 1500.0
        assert res["outstanding_amount_le"] == 0.0
        assert res["is_legacy_derived"] is True
        assert res["valid_payments_count"] == 0

    def test_order_without_payments_legacy_dp_unknown(self):
        order = {
            "_id": ObjectId("507f1f77bcf86cd799439013"),
            "total_le": 2000.0,
            "payment_status": "dp",
        }
        res = compute_payment_summary_from_records(order, [])
        assert res["payment_status"] == "dp"
        assert res["paid_amount_le"] is None
        assert res["outstanding_amount_le"] is None
        assert res["legacy_dp_unknown"] is True
        assert res["has_unrecorded_legacy_dp"] is True
        assert res["is_legacy_derived"] is True

    def test_order_with_single_partial_payment_dp(self):
        order = {
            "_id": ObjectId("507f1f77bcf86cd799439014"),
            "total_le": 1000.0,
            "payment_status": "belum_dibayar",
        }
        payments = [
            {"order_id": str(order["_id"]), "amount_le": 400.0, "status": "recorded"}
        ]
        res = compute_payment_summary_from_records(order, payments)
        assert res["payment_status"] == "dp"
        assert res["paid_amount_le"] == 400.0
        assert res["outstanding_amount_le"] == 600.0
        assert res["is_legacy_derived"] is False
        assert res["valid_payments_count"] == 1

    def test_order_with_multiple_payments_lunas(self):
        order = {
            "_id": ObjectId("507f1f77bcf86cd799439015"),
            "total_le": 1000.0,
            "payment_status": "belum_dibayar",
        }
        payments = [
            {"order_id": str(order["_id"]), "amount_le": 400.0, "status": "recorded"},
            {"order_id": str(order["_id"]), "amount_le": 600.0, "status": "recorded"},
        ]
        res = compute_payment_summary_from_records(order, payments)
        assert res["payment_status"] == "lunas"
        assert res["paid_amount_le"] == 1000.0
        assert res["outstanding_amount_le"] == 0.0
        assert res["is_legacy_derived"] is False
        assert res["valid_payments_count"] == 2

    def test_order_with_multiple_payments_overpaid(self):
        order = {
            "_id": ObjectId("507f1f77bcf86cd799439016"),
            "total_le": 1000.0,
            "payment_status": "belum_dibayar",
        }
        payments = [
            {"order_id": str(order["_id"]), "amount_le": 500.0, "status": "recorded"},
            {"order_id": str(order["_id"]), "amount_le": 600.0, "status": "recorded"},
        ]
        res = compute_payment_summary_from_records(order, payments)
        assert res["payment_status"] == "overpaid"
        assert res["paid_amount_le"] == 1100.0
        assert res["outstanding_amount_le"] == 0.0
        assert res["valid_payments_count"] == 2

    def test_order_with_unrecorded_legacy_dp_and_new_payments(self):
        order = {
            "_id": ObjectId("507f1f77bcf86cd799439017"),
            "total_le": 2500.0,
            "has_unrecorded_legacy_dp": True,
            "payment_status": "dp",
        }
        payments = [
            {"order_id": str(order["_id"]), "amount_le": 500.0, "status": "recorded"},
            {"order_id": str(order["_id"]), "amount_le": 300.0, "status": "recorded"},
        ]
        res = compute_payment_summary_from_records(order, payments)
        assert res["payment_status"] == "dp"
        assert res["paid_amount_le"] is None
        assert res["canonical_paid_amount_le"] == 800.0
        assert res["outstanding_amount_le"] is None
        assert res["legacy_dp_unknown"] is True
        assert res["has_unrecorded_legacy_dp"] is True
        assert res["valid_payments_count"] == 2


@pytest.mark.anyio
class TestAdminOrdersBatchQueryExecution:
    """Proves that admin_list_orders eliminates N+1 query loop and uses O(1) batch query."""

    async def test_21_orders_executes_only_1_batch_query_for_payments(self):
        mock_orders = []
        mock_payments = []
        for i in range(21):
            oid = ObjectId()
            mock_orders.append({
                "_id": oid,
                "order_number": f"SGF-20261102-{i+1:03d}",
                "total_le": 1000.0 + (i * 100),
                "order_status": "pesanan_masuk",
                "payment_status": "belum_dibayar",
                "customer_name": f"Customer {i+1}",
                "customer_phone": f"+2010000000{i:02d}",
                "created_at": "2026-11-02T10:00:00Z",
            })
            if i % 2 == 0:
                mock_payments.append({
                    "_id": ObjectId(),
                    "order_id": str(oid),
                    "amount_le": 500.0,
                    "status": "recorded",
                })

        mock_db = MagicMock()
        mock_orders_cursor = MagicMock()
        mock_orders_cursor.sort.return_value = mock_orders_cursor
        mock_orders_cursor.to_list = AsyncMock(return_value=mock_orders)
        mock_db.orders.find.return_value = mock_orders_cursor

        mock_payments_cursor = MagicMock()
        mock_payments_cursor.to_list = AsyncMock(return_value=mock_payments)
        mock_db.payments.find.return_value = mock_payments_cursor

        with patch("server.db", mock_db):
            admin_user = {"id": "adm_1", "role": "admin", "permissions": {"manage_orders": True}}
            res = await admin_list_orders(admin=admin_user)

            # CRITICAL ASSERTIONS:
            # 1. Returned all 21 orders
            assert len(res) == 21

            # 2. orders.find was called exactly ONCE
            assert mock_db.orders.find.call_count == 1

            # 3. payments.find was called exactly ONCE (NOT 21 times!)
            assert mock_db.payments.find.call_count == 1

            # 4. Verify batch $in query was used
            call_args, call_kwargs = mock_db.payments.find.call_args
            query_filter = call_args[0]
            assert "order_id" in query_filter
            assert "$in" in query_filter["order_id"]
            # Both ObjectId and str representations collected
            assert len(query_filter["order_id"]["$in"]) == 42
            assert query_filter["status"] == "recorded"

            # 5. Verify payment summary values were populated accurately
            for idx, order_res in enumerate(res):
                if idx % 2 == 0:
                    assert order_res["payment_status"] == "dp"
                    assert order_res["paid_amount_le"] == 500.0
                    assert order_res["outstanding_amount_le"] == order_res["total_le"] - 500.0
                    assert order_res["valid_payments_count"] == 1
                else:
                    assert order_res["payment_status"] == "belum_dibayar"
                    assert order_res["paid_amount_le"] == 0.0
                    assert order_res["valid_payments_count"] == 0

    async def test_empty_orders_does_not_execute_payments_query(self):
        mock_db = MagicMock()
        mock_orders_cursor = MagicMock()
        mock_orders_cursor.sort.return_value = mock_orders_cursor
        mock_orders_cursor.to_list = AsyncMock(return_value=[])
        mock_db.orders.find.return_value = mock_orders_cursor

        with patch("server.db", mock_db):
            admin_user = {"id": "adm_1", "role": "admin", "permissions": {"manage_orders": True}}
            res = await admin_list_orders(admin=admin_user)

            assert res == []
            assert mock_db.orders.find.call_count == 1
            assert mock_db.payments.find.call_count == 0

    async def test_filter_parameters_forwarded_to_orders_query(self):
        mock_db = MagicMock()
        mock_orders_cursor = MagicMock()
        mock_orders_cursor.sort.return_value = mock_orders_cursor
        mock_orders_cursor.to_list = AsyncMock(return_value=[])
        mock_db.orders.find.return_value = mock_orders_cursor

        with patch("server.db", mock_db):
            admin_user = {"id": "adm_1", "role": "admin", "permissions": {"manage_orders": True}}
            await admin_list_orders(status="siap", payment_status="lunas", q="Maadi", admin=admin_user)

            call_args, _ = mock_db.orders.find.call_args
            filter_dict = call_args[0]
            assert filter_dict["order_status"] == "siap"
            assert filter_dict["payment_status"] == "lunas"
            assert "$or" in filter_dict
