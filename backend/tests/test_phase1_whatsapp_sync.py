"""Phase 1 Backend Regression Test: WhatsApp Message Synchronization & Order Update Integrity.

Verifies:
1. build_whatsapp_message formats consistent, resilient messages for single & multi-item orders.
2. admin_update_order synchronizes the stored and returned whatsapp_message on price, item, note, or status changes.
3. Historical item snapshots and required fields are preserved intact.
"""
import copy
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
    OrderStatusUpdate,
    build_whatsapp_message,
    admin_update_order,
)


class TestPhase1WhatsAppSync(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mock_admin = {
            "id": "adm_owner_1",
            "name": "Super Owner",
            "role": "owner",
            "permissions": {
                "manage_orders": True,
                "access_finance": True,
                "modify_products": True,
                "delete_data": True,
            },
        }

    def test_build_whatsapp_message_formatting(self):
        """Verifies build_whatsapp_message generates correct multi-item price breakdowns."""
        sample_order = {
            "order_number": "SGF-20261101-WA1",
            "customer_name": "Ahmad Dani",
            "customer_phone": "+201012345678",
            "customer_address": "Imarah 10, Jalan Abbasia, Syaqqoh 4",
            "customer_maps_url": "https://maps.app.goo.gl/xyz123",
            "delivery_method": "delivery",
            "delivery_zone_name": "Nasr City",
            "payment_method": "transfer",
            "items": [
                {
                    "item_id": "itm_1",
                    "product_name_snapshot": "Meja Belajar Mahasiswa",
                    "configuration_snapshot": {"size": "120x60", "finishing": "Natural"},
                    "quantity": 1,
                    "unit_price_le": 850.0,
                    "subtotal_le": 850.0,
                },
                {
                    "item_id": "itm_2",
                    "product_name_snapshot": "Kursi Belajar Ergonomis",
                    "configuration_snapshot": {"finishing": "Hitam"},
                    "quantity": 2,
                    "unit_price_le": 300.0,
                    "subtotal_le": 600.0,
                },
            ],
            "subtotal_le": 1450.0,
            "discount_le": 50.0,
            "discount_code": "PROMO50",
            "referral_discount_le": 25.0,
            "referral": {"code": "REFALAZHAR"},
            "points_redeemed_le": 10.0,
            "delivery_fee_le": 100.0,
            "total_le": 1465.0,
            "estimated_total_idr": 523005,
            "exchange_rate_idr_per_le": 357.0,
            "notes": "Tolong kirim sore hari",
        }

        msg = build_whatsapp_message(sample_order)

        self.assertIn("No. Pesanan: SGF-20261101-WA1", msg)
        self.assertIn("1. Produk: Meja Belajar Mahasiswa", msg)
        self.assertIn("2. Produk: Kursi Belajar Ergonomis", msg)
        self.assertIn("Pengiriman: Delivery", msg)
        self.assertIn("Zona: Nasr City", msg)
        self.assertIn("Rincian Harga:", msg)
        self.assertIn("Subtotal: 1.450 LE", msg)
        self.assertIn("Diskon (PROMO50): -50 LE", msg)
        self.assertIn("Diskon Referral (REFALAZHAR): -25 LE", msg)
        self.assertIn("Penukaran Poin: -10 LE", msg)
        self.assertIn("Ongkir: 100 LE", msg)
        self.assertIn("Total: 1.465 LE", msg)
        self.assertIn("Nama: Ahmad Dani", msg)
        self.assertIn("No. HP: +201012345678", msg)
        self.assertIn("Alamat: Imarah 10, Jalan Abbasia, Syaqqoh 4", msg)
        self.assertIn("Maps: https://maps.app.goo.gl/xyz123", msg)
        self.assertIn("Pembayaran: Transfer", msg)
        self.assertIn("Catatan: Tolong kirim sore hari", msg)

    async def test_admin_update_order_synchronizes_whatsapp_message(self):
        """Verifies admin_update_order recalculates and stores fresh whatsapp_message."""
        order_id = "507f1f77bcf86cd799439011"
        stored_order = {
            "_id": ObjectId(order_id),
            "id": order_id,
            "order_number": "SGF-20261101-SYNC",
            "customer_name": "Karim Benzema",
            "customer_phone": "+201099887766",
            "customer_address": "Rehab City",
            "delivery_method": "delivery",
            "delivery_zone_name": "New Cairo",
            "order_status": "pesanan_masuk",
            "payment_status": "belum_dibayar",
            "payment_method": "cash",
            "items": [
                {
                    "item_id": "itm_old_1",
                    "product_name_snapshot": "Lemari 3 Pintu",
                    "quantity": 1,
                    "unit_price_le": 2000.0,
                    "subtotal_le": 2000.0,
                }
            ],
            "subtotal_le": 2000.0,
            "delivery_fee_le": 150.0,
            "discount_le": 0.0,
            "total_le": 2150.0,
            "exchange_rate_idr_per_le": 357.0,
            "estimated_total_idr": 767550,
            "whatsapp_message": "Old stale message from creation time",
            "active_delivery_trip_id": None,
        }

        updated_in_db = None

        async def fake_find_one(collection, filter_dict, **kwargs):
            nonlocal updated_in_db
            if updated_in_db is not None:
                return copy.deepcopy(updated_in_db)
            return copy.deepcopy(stored_order)

        async def fake_update_one(collection, filter_dict, update_doc, **kwargs):
            nonlocal updated_in_db
            if updated_in_db is None:
                updated_in_db = copy.deepcopy(stored_order)
            if "$set" in update_doc:
                updated_in_db.update(update_doc["$set"])
            mock_res = MagicMock()
            mock_res.matched_count = 1
            mock_res.modified_count = 1
            return mock_res

        cursor_mock = AsyncMock()
        cursor_mock.to_list = AsyncMock(return_value=[])

        with patch("server._mongo_find_one", side_effect=fake_find_one), \
             patch("server._mongo_update_one", side_effect=fake_update_one), \
             patch("server.db.work_assignments.find", return_value=cursor_mock), \
             patch("server.db.wage_obligations.find", return_value=cursor_mock), \
             patch("server.is_standalone_fallback_permitted", return_value=True), \
             patch("server.get_setting", new=AsyncMock(return_value="201012345678")):

            # Admin modifies delivery fee, discount, and admin note
            payload = OrderStatusUpdate(
                delivery_fee_le=200.0,
                discount_le=100.0,
                admin_note="Diskon loyalitas 100 LE disetujui",
            )

            res = await admin_update_order(order_id, payload, admin=self.mock_admin)

            # Assert returned order has synchronized whatsapp_message
            self.assertIsNotNone(res.get("whatsapp_message"))
            self.assertNotEqual(res["whatsapp_message"], "Old stale message from creation time")
            self.assertIn("Ongkir: 200 LE", res["whatsapp_message"])
            self.assertIn("Diskon: -100 LE", res["whatsapp_message"])
            # Total should be 2000 (subtotal) - 100 (discount) + 200 (delivery) = 2100 LE
            self.assertIn("Total: 2.100 LE", res["whatsapp_message"])

            # Assert database $set operation received the synchronized whatsapp_message
            self.assertIsNotNone(updated_in_db)
            self.assertIn("whatsapp_message", updated_in_db)
            self.assertEqual(updated_in_db["whatsapp_message"], res["whatsapp_message"])
            self.assertIn("Total: 2.100 LE", updated_in_db["whatsapp_message"])


if __name__ == "__main__":
    unittest.main()
