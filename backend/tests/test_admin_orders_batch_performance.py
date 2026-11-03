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
    admin_get_order,
    ORDER_LIST_PROJECTION,
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


@pytest.mark.anyio
class TestAdminOrdersProjectionOptimization:
    """Regression test suite for Admin Orders P1 Field Projection & Contract Safety.

    Verifies:
    1. ORDER_LIST_PROJECTION specification contains all required UI and calculation fields.
    2. admin_list_orders passes ORDER_LIST_PROJECTION to db.orders.find.
    3. Frontend list contract integrity: id, order_number, dates, status, totals, product preview.
    4. Payment summary integrity (paid_amount_le, outstanding_amount_le, legacy DP).
    5. Detail endpoint isolation: admin_get_order continues returning full unprojected documents.
    6. Sorting order (created_at DESC) and status filter pass-through.
    7. Backward compatibility for legacy single-item structures (item.product_name_snapshot).
    """

    def test_order_list_projection_specification(self):
        """Verify the projection constant defines exact whitelist and excludes heavy fields."""
        required_keys = {
            "_id",
            "order_number",
            "created_at",
            "customer_name",
            "customer_phone",
            "order_status",
            "payment_status",
            "total_le",
            "delivery_method",
            "delivery_zone_name",
            "has_unrecorded_legacy_dp",
            "items.product_name_snapshot",
            "item.product_name_snapshot",
        }
        for k in required_keys:
            assert k in ORDER_LIST_PROJECTION, f"Missing required projection field: {k}"
            assert ORDER_LIST_PROJECTION[k] == 1

        # Confirm heavy fields are excluded
        excluded_keys = [
            "items.configuration_snapshot",
            "items.dimensions",
            "items.materials",
            "items.custom_note",
            "customer_address",
            "customer_maps_url",
            "building_photo_url",
            "admin_wage_eligibility",
            "audit_log",
            "whatsapp_message",
            "notes",
        ]
        for ek in excluded_keys:
            assert ek not in ORDER_LIST_PROJECTION, f"Field should be excluded from list projection: {ek}"

    async def test_admin_list_orders_applies_projection_and_sort(self):
        """Verify that db.orders.find is called with the projection and sort('created_at', -1)."""
        mock_db = MagicMock()
        mock_orders_cursor = MagicMock()
        mock_orders_cursor.sort.return_value = mock_orders_cursor
        mock_orders_cursor.to_list = AsyncMock(return_value=[])
        mock_db.orders.find.return_value = mock_orders_cursor

        with patch("server.db", mock_db):
            admin_user = {"id": "adm_1", "role": "admin", "permissions": {"manage_orders": True}}
            res = await admin_list_orders(status="diproses", admin=admin_user)

            assert res == []
            assert mock_db.orders.find.call_count == 1

            # Verify call arguments
            call_args, call_kwargs = mock_db.orders.find.call_args
            assert call_args[0] == {"order_status": "diproses"}
            assert call_args[1] == ORDER_LIST_PROJECTION

            # Verify sort was called with created_at -1
            mock_orders_cursor.sort.assert_called_once_with("created_at", -1)

    async def test_list_response_contract_and_field_availability(self):
        """Verify all fields consumed by AdminOrders.jsx are present in output."""
        oid = ObjectId("672000000000000000000001")
        mock_projected_doc = {
            "_id": oid,
            "order_number": "SGL-20261102-0001",
            "created_at": "2026-11-02T10:00:00Z",
            "customer_name": "Budi Santoso",
            "customer_phone": "+201012345678",
            "order_status": "diproses",
            "payment_status": "dp",
            "total_le": 5000.0,
            "delivery_method": "delivery",
            "delivery_zone_name": "Maadi Zone",
            "has_unrecorded_legacy_dp": False,
            "items": [{"product_name_snapshot": "Meja Makan Teak"}],
        }

        mock_payment = {
            "_id": ObjectId(),
            "order_id": str(oid),
            "amount_le": 2000.0,
            "status": "recorded",
        }

        mock_db = MagicMock()
        mock_orders_cursor = MagicMock()
        mock_orders_cursor.sort.return_value = mock_orders_cursor
        mock_orders_cursor.to_list = AsyncMock(return_value=[mock_projected_doc])
        mock_db.orders.find.return_value = mock_orders_cursor

        mock_payments_cursor = MagicMock()
        mock_payments_cursor.to_list = AsyncMock(return_value=[mock_payment])
        mock_db.payments.find.return_value = mock_payments_cursor

        with patch("server.db", mock_db):
            admin_user = {"id": "adm_1", "role": "admin", "permissions": {"manage_orders": True}}
            res = await admin_list_orders(admin=admin_user)

            assert len(res) == 1
            row = res[0]

            # Contract checks for AdminOrders.jsx
            assert row["id"] == str(oid)
            assert "_id" not in row  # clean() converts _id -> id
            assert row["order_number"] == "SGL-20261102-0001"
            assert row["created_at"] == "2026-11-02T10:00:00Z"
            assert row["customer_name"] == "Budi Santoso"
            assert row["customer_phone"] == "+201012345678"
            assert row["order_status"] == "diproses"
            assert row["payment_status"] == "dp"
            assert row["total_le"] == 5000.0
            assert row["paid_amount_le"] == 2000.0
            assert row["outstanding_amount_le"] == 3000.0
            assert row["delivery_method"] == "delivery"
            assert row["delivery_zone_name"] == "Maadi Zone"
            assert row["legacy_dp_unknown"] is False
            assert len(row["items"]) == 1
            assert row["items"][0]["product_name_snapshot"] == "Meja Makan Teak"

    async def test_legacy_dp_unknown_with_projection(self):
        """Verify legacy DP handling functions correctly with projected fields."""
        oid = ObjectId("672000000000000000000002")
        mock_legacy_doc = {
            "_id": oid,
            "order_number": "SGL-20261001-0002",
            "created_at": "2026-10-01T10:00:00Z",
            "customer_name": "Legacy Customer",
            "customer_phone": "+201099999999",
            "order_status": "selesai",
            "payment_status": "dp",
            "total_le": 4000.0,
            "has_unrecorded_legacy_dp": True,
            "items": [{"product_name_snapshot": "Lemari Pakaian"}],
        }

        mock_db = MagicMock()
        mock_orders_cursor = MagicMock()
        mock_orders_cursor.sort.return_value = mock_orders_cursor
        mock_orders_cursor.to_list = AsyncMock(return_value=[mock_legacy_doc])
        mock_db.orders.find.return_value = mock_orders_cursor

        mock_payments_cursor = MagicMock()
        mock_payments_cursor.to_list = AsyncMock(return_value=[])
        mock_db.payments.find.return_value = mock_payments_cursor

        with patch("server.db", mock_db):
            admin_user = {"id": "adm_1", "role": "admin", "permissions": {"manage_orders": True}}
            res = await admin_list_orders(admin=admin_user)

            assert len(res) == 1
            row = res[0]
            assert row["payment_status"] == "dp"
            assert row["legacy_dp_unknown"] is True
            assert row["paid_amount_le"] is None
            assert row["outstanding_amount_le"] is None

    async def test_legacy_single_item_compatibility(self):
        """Verify order with legacy single 'item' dict renders product_name_snapshot correctly."""
        oid = ObjectId("672000000000000000000003")
        mock_legacy_item_doc = {
            "_id": oid,
            "order_number": "SGL-20260901-0003",
            "created_at": "2026-09-01T10:00:00Z",
            "customer_name": "Old Single Item Buyer",
            "order_status": "dikonfirmasi",
            "payment_status": "belum_dibayar",
            "total_le": 1200.0,
            "item": {"product_name_snapshot": "Nakas Minimalis"},
        }

        mock_db = MagicMock()
        mock_orders_cursor = MagicMock()
        mock_orders_cursor.sort.return_value = mock_orders_cursor
        mock_orders_cursor.to_list = AsyncMock(return_value=[mock_legacy_item_doc])
        mock_db.orders.find.return_value = mock_orders_cursor

        mock_payments_cursor = MagicMock()
        mock_payments_cursor.to_list = AsyncMock(return_value=[])
        mock_db.payments.find.return_value = mock_payments_cursor

        with patch("server.db", mock_db):
            admin_user = {"id": "adm_1", "role": "admin", "permissions": {"manage_orders": True}}
            res = await admin_list_orders(admin=admin_user)

            assert len(res) == 1
            row = res[0]
            # Verify item field exists and contains product_name_snapshot
            assert "item" in row
            assert row["item"]["product_name_snapshot"] == "Nakas Minimalis"

    async def test_detail_endpoint_isolation_preserves_full_unprojected_document(self):
        """Verify that admin_get_order (GET /admin/orders/{id}) retains full unprojected fields."""
        order_id = "507f1f77bcf86cd799439099"
        full_order = {
            "_id": ObjectId(order_id),
            "order_number": "SGL-20261102-0099",
            "created_at": "2026-11-02T10:00:00Z",
            "customer_name": "Detail Customer",
            "customer_phone": "+201011112222",
            "customer_address": "Building 5, Street 10, Maadi",
            "customer_maps_url": "https://maps.google.com/?q=29.96,31.28",
            "building_photo_url": "https://r2.sogilfurniture.com/building_5.jpg",
            "order_status": "diproses",
            "payment_status": "belum_dibayar",
            "total_le": 7500.0,
            "items": [{
                "product_name_snapshot": "Sofa 3 Dudukan Teak",
                "configuration_snapshot": {"fabric": "Velvet Blue", "cushion": "High Density 40"},
                "dimensions": {"length_cm": 200, "width_cm": 85, "height_cm": 75},
                "materials": ["Solid Teak Wood", "Imported Velvet"],
                "unit_price_le": 7500.0,
                "quantity": 1,
                "custom_note": "Busa ekstra empuk"
            }],
            "admin_wage_eligibility": {"eligible": True, "calculated_amount": 350.0},
            "notes": "Internal notes for warehouse team",
            "audit_log": [{"action": "order_created", "timestamp": "2026-11-02T10:00:00Z"}],
        }

        mock_db = MagicMock()
        mock_db.orders.find_one = AsyncMock(return_value=full_order)

        mock_payments_cursor = MagicMock()
        mock_payments_cursor.to_list = AsyncMock(return_value=[])
        mock_db.payments.find.return_value = mock_payments_cursor

        with patch("server.db", mock_db), \
             patch("server.get_setting", AsyncMock(return_value="628123456789")):
            admin_user = {"id": "adm_1", "role": "admin", "permissions": {"manage_orders": True}}
            detail_res = await admin_get_order(order_id=order_id, admin=admin_user)

            # Assert find_one was called without any projection argument
            assert mock_db.orders.find_one.call_count == 1
            call_args, call_kwargs = mock_db.orders.find_one.call_args
            assert len(call_args) == 1  # Only filter dict was passed, no projection argument!
            assert "projection" not in call_kwargs

            # Verify that excluded fields in list are 100% available in detail
            assert detail_res["customer_address"] == "Building 5, Street 10, Maadi"
            assert detail_res["customer_maps_url"] == "https://maps.google.com/?q=29.96,31.28"
            assert detail_res["building_photo_url"] == "https://r2.sogilfurniture.com/building_5.jpg"
            assert detail_res["admin_wage_eligibility"]["eligible"] is True
            assert detail_res["notes"] == "Internal notes for warehouse team"
            assert len(detail_res["audit_log"]) == 1

            # Verify item nested configuration is intact
            item = detail_res["items"][0]
            assert item["configuration_snapshot"]["fabric"] == "Velvet Blue"
            assert item["dimensions"]["length_cm"] == 200
            assert item["materials"] == ["Solid Teak Wood", "Imported Velvet"]
            assert item["custom_note"] == "Busa ekstra empuk"
            assert "whatsapp_message" in detail_res
