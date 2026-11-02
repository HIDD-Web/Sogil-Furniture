"""Phase 2 Backend Unit & Regression Tests: Checkout, Address, Delivery Maps & Building Photo.

Verifies:
1. validate_and_normalize_maps_url requires valid Google Maps link for delivery, optional for pickup.
2. validate_building_photo_url validates safe file storage paths and URLs, rejecting invalid protocols and lengths.
3. upload_building_photo enforces extension whitelist, size ceiling (10MB), Pillow integrity verification, and R2 key structure.
4. create_order and _create_invoice_order safely persist building_photo_url without binary/base64 bloat.
"""
import asyncio
import io
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException, UploadFile, Request
from PIL import Image
from mongomock_motor import AsyncMongoMockClient

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import server
from server import (
    OrderInput,
    validate_and_normalize_maps_url,
    validate_building_photo_url,
    upload_building_photo,
    get_client_ip,
    check_building_photo_rate_limit,
    reserve_upload_quota,
    rollback_upload_quota,
    download_file,
)


class TestPhase2MapsAndPhotoValidation(unittest.IsolatedAsyncioTestCase):
    def test_maps_validation_delivery_required(self):
        """Verifies delivery orders strictly require valid Google Maps links."""
        # Missing or empty maps url raises 400
        with self.assertRaises(HTTPException) as ctx:
            validate_and_normalize_maps_url(None, "delivery")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Link Google Maps lokasi pengiriman wajib diisi", ctx.exception.detail)

        with self.assertRaises(HTTPException) as ctx:
            validate_and_normalize_maps_url("   ", "delivery")
        self.assertEqual(ctx.exception.status_code, 400)

        # Invalid domains raise 400
        with self.assertRaises(HTTPException) as ctx:
            validate_and_normalize_maps_url("https://bing.com/maps/123", "delivery")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("harus berupa link Google Maps yang valid", ctx.exception.detail)

        with self.assertRaises(HTTPException) as ctx:
            validate_and_normalize_maps_url("https://malicious-site.com/phishing", "delivery")
        self.assertEqual(ctx.exception.status_code, 400)

        # Valid Google Maps links pass and normalize
        valid_app = "https://maps.app.goo.gl/abcdef123"
        self.assertEqual(validate_and_normalize_maps_url(valid_app, "delivery"), valid_app)

        valid_full = "https://www.google.com/maps/place/Cairo/@30.0444,31.2357,12z"
        self.assertEqual(validate_and_normalize_maps_url(valid_full, "delivery"), valid_full)

        # Missing protocol is auto-prefixed with https://
        valid_noprotocol = "maps.app.goo.gl/xyz987"
        self.assertEqual(
            validate_and_normalize_maps_url(valid_noprotocol, "delivery"),
            "https://maps.app.goo.gl/xyz987",
        )

    def test_maps_validation_pickup_optional(self):
        """Verifies pickup orders allow empty or omitted Maps links."""
        self.assertEqual(validate_and_normalize_maps_url(None, "pickup"), "")
        self.assertEqual(validate_and_normalize_maps_url("", "pickup"), "")
        self.assertEqual(validate_and_normalize_maps_url("   ", "pickup"), "")

        # If provided, it must still be a valid Google Maps link
        valid_app = "https://maps.app.goo.gl/pickup123"
        self.assertEqual(validate_and_normalize_maps_url(valid_app, "pickup"), valid_app)

        with self.assertRaises(HTTPException) as ctx:
            validate_and_normalize_maps_url("https://not-google.com/map", "pickup")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_building_photo_url_validation(self):
        """Verifies building_photo_url validation rules."""
        # Empty or None returns None
        self.assertIsNone(validate_building_photo_url(None))
        self.assertIsNone(validate_building_photo_url(""))
        self.assertIsNone(validate_building_photo_url("   "))

        # Valid internal API file path
        valid_internal = "/api/files/sogil/building-photos/1234567890abcdef.webp"
        self.assertEqual(validate_building_photo_url(valid_internal), valid_internal)

        # Valid HTTPS external URL
        valid_external = "https://r2.sogilfurniture.com/photos/building1.jpg"
        self.assertEqual(validate_building_photo_url(valid_external), valid_external)

        # Reject invalid scheme or injection
        with self.assertRaises(HTTPException) as ctx:
            validate_building_photo_url("javascript:alert(1)")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("URL foto gedung tidak valid", ctx.exception.detail)

        with self.assertRaises(HTTPException) as ctx:
            validate_building_photo_url("data:image/png;base64,iVBORw0KGgoAAAANSUhEUg...")
        self.assertEqual(ctx.exception.status_code, 400)

        # Reject excessively long URL
        oversized = "https://example.com/" + ("a" * 1005)
        with self.assertRaises(HTTPException) as ctx:
            validate_building_photo_url(oversized)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("terlalu panjang", ctx.exception.detail)

    async def test_upload_building_photo_endpoint_validation(self):
        """Verifies upload_building_photo endpoint security and integrity checks."""
        mock_req = MagicMock(spec=Request)
        mock_req.headers = {}
        mock_req.client = None

        mock_rate_coll = MagicMock()
        mock_rate_coll.count_documents = AsyncMock(return_value=0)
        mock_rate_coll.insert_one = AsyncMock()

        # 1. Reject invalid extensions (PDF, EXE, SVG, etc.)
        mock_file_pdf = MagicMock(spec=UploadFile)
        mock_file_pdf.filename = "document.pdf"
        mock_file_pdf.read = AsyncMock(return_value=b"%PDF-1.4...")
        with patch.object(server.db, "__getitem__", return_value=mock_rate_coll), \
             patch.object(server.db, "upload_rate_limits", mock_rate_coll, create=True):
            with self.assertRaises(HTTPException) as ctx:
                await upload_building_photo(mock_req, mock_file_pdf)
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("Format gambar tidak didukung", ctx.exception.detail)

            # 2. Reject files larger than 10MB
            mock_file_large = MagicMock(spec=UploadFile)
            mock_file_large.filename = "big_photo.jpg"
            mock_file_large.read = AsyncMock(return_value=b"A" * (10 * 1024 * 1024 + 1))
            with self.assertRaises(HTTPException) as ctx:
                await upload_building_photo(mock_req, mock_file_large)
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("Ukuran gambar maksimal 10MB", ctx.exception.detail)

            # 3. Reject corrupt image data (fake jpg extension but invalid image bytes)
            mock_file_corrupt = MagicMock(spec=UploadFile)
            mock_file_corrupt.filename = "fake_image.jpg"
            mock_file_corrupt.read = AsyncMock(return_value=b"This is not a real image stream.")
            with self.assertRaises(HTTPException) as ctx:
                await upload_building_photo(mock_req, mock_file_corrupt)
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("File gambar tidak valid atau rusak", ctx.exception.detail)

            # 4. Accept genuine image bytes, optimize, upload to R2, and insert metadata
            genuine_img = Image.new("RGB", (100, 100), color="blue")
            img_byte_arr = io.BytesIO()
            genuine_img.save(img_byte_arr, format="JPEG")
            valid_jpeg_bytes = img_byte_arr.getvalue()

            mock_file_valid = MagicMock(spec=UploadFile)
            mock_file_valid.filename = "building_entrance.jpg"
            mock_file_valid.read = AsyncMock(return_value=valid_jpeg_bytes)

            mock_files_coll = MagicMock()
            mock_files_coll.insert_one = AsyncMock()
            mock_files_coll.count_documents = AsyncMock(return_value=0)

            with patch("server.put_object") as mock_put, \
                 patch.object(server.db, "files", mock_files_coll, create=True):
                mock_put.return_value = {
                    "storage_path": "sogil/building-photos/uuid123.webp",
                    "size": len(valid_jpeg_bytes),
                }

                resp = await upload_building_photo(mock_req, mock_file_valid)

                self.assertIn("path", resp)
                self.assertIn("url", resp)
                self.assertEqual(resp["path"], "sogil/building-photos/uuid123.webp")
                self.assertEqual(resp["url"], "/api/files/sogil/building-photos/uuid123.webp")

                # Verify R2 put_object was called
                self.assertTrue(mock_put.called)
                r2_path_arg = mock_put.call_args[0][0]
                self.assertTrue(r2_path_arg.startswith(f"{server.APP_NAME}/building-photos/"))

                # Verify metadata record inserted
                self.assertTrue(mock_files_coll.insert_one.called)
                inserted_record = mock_files_coll.insert_one.call_args[0][0]
                self.assertEqual(inserted_record["original_filename"], "building_entrance.jpg")
                self.assertEqual(inserted_record["category"], "building_photo")
                self.assertEqual(inserted_record["is_deleted"], False)
                self.assertEqual(inserted_record["ip"], "127.0.0.1")

    def test_order_input_schema_accepts_building_photo(self):
        """Verifies OrderInput pydantic model accepts and validates building_photo_url."""
        order_dict = {
            "customer_name": "Test Customer",
            "customer_phone": "+201012345678",
            "customer_address": "Cairo, Abbasia St.",
            "customer_maps_url": "https://maps.app.goo.gl/test1234",
            "delivery_method": "delivery",
            "payment_method": "cash",
            "building_photo_url": "/api/files/sogil/building-photos/abc123.webp",
        }
        order_input = OrderInput(**order_dict)
        self.assertEqual(order_input.building_photo_url, "/api/files/sogil/building-photos/abc123.webp")

        # Optional field default is None
        order_dict_no_photo = {
            "customer_name": "Test Customer 2",
            "customer_phone": "+201012345679",
            "customer_address": "Cairo",
            "delivery_method": "pickup",
            "payment_method": "cash",
        }
        order_input_no_photo = OrderInput(**order_dict_no_photo)
        self.assertIsNone(order_input_no_photo.building_photo_url)

    async def test_create_order_delivery_without_maps_rejected(self):
        """Verifies create_order rejects delivery requests without valid Maps link."""
        from server import create_order, OrderItemInput
        mock_req = MagicMock()
        order_data = OrderInput(
            customer_name="Ahmad",
            customer_phone="+201012345678",
            customer_address="Cairo, Street 9",
            customer_maps_url="",  # missing maps
            delivery_method="delivery",
            delivery_zone_id="zone_123",
            payment_method="cash",
            items=[OrderItemInput(product_id="prod_1", quantity=1, config={})],
        )

        with self.assertRaises(HTTPException) as ctx:
            await create_order(mock_req, order_data)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Link Google Maps lokasi pengiriman wajib diisi", ctx.exception.detail)

    async def test_create_order_persists_photo_url_without_binary(self):
        """Verifies create_order persists building_photo_url cleanly without binary or base64 data."""
        from server import create_order, OrderItemInput
        from bson import ObjectId

        mock_req = MagicMock()
        mock_req.state = MagicMock()
        mock_req.state.customer = None

        photo_url = "/api/files/sogil/building-photos/valid1234.webp"
        order_data = OrderInput(
            customer_name="Siti Fatimah",
            customer_phone="+201012345678",
            customer_address="Imarah 20, Kairo, Lantai 2",
            customer_maps_url="",
            delivery_method="pickup",
            payment_method="cash",
            building_photo_url=photo_url,
            items=[OrderItemInput(product_id="prod_1", quantity=1, config={})],
        )

        mock_product = {
            "_id": ObjectId("507f1f77bcf86cd799439011"),
            "name": "Meja Belajar",
            "category": "meja",
            "active": True,
            "base_price_le": 200.0,
            "height_options": [],
            "finishing_options": [],
            "size_variants": [],
        }

        mock_orders_coll = MagicMock()
        mock_orders_coll.insert_one = AsyncMock(return_value=MagicMock(inserted_id="ord_test_photo"))
        mock_orders_coll.find_one = AsyncMock(return_value={
            "_id": "ord_test_photo",
            "order_number": "SGF-20261101-PHOTO",
            "customer_name": "Siti Fatimah",
            "customer_phone": "+201012345678",
            "customer_address": "Imarah 20, Kairo, Lantai 2",
            "building_photo_url": photo_url,
            "delivery_method": "pickup",
            "payment_method": "cash",
            "items": [],
            "total_le": 200.0,
            "estimated_total_idr": 70000,
        })

        mock_products_coll = MagicMock()
        mock_products_coll.find_one = AsyncMock(return_value=mock_product)

        def mock_getitem(name):
            if name == "orders":
                return mock_orders_coll
            if name == "products":
                return mock_products_coll
            return MagicMock()

        with patch.object(server.db, "__getitem__", side_effect=mock_getitem), \
             patch.object(server.db, "orders", mock_orders_coll, create=True), \
             patch.object(server.db, "products", mock_products_coll, create=True), \
             patch("server.generate_order_number", return_value="SGF-20261101-PHOTO"), \
             patch("server.get_setting", new_callable=AsyncMock, return_value=357.0):

            result = await create_order(mock_req, order_data)

            self.assertIsNotNone(result)
            self.assertEqual(result.get("building_photo_url"), photo_url)

            # Inspect what was passed to insert_one
            self.assertTrue(mock_orders_coll.insert_one.called)
            inserted_doc = mock_orders_coll.insert_one.call_args[0][0]

            self.assertEqual(inserted_doc["building_photo_url"], photo_url)
            # Ensure no binary bytes or huge base64 strings
            for k, v in inserted_doc.items():
                self.assertNotIsInstance(v, bytes, f"Field {k} contains binary bytes!")
                if isinstance(v, str):
                    self.assertFalse(v.startswith("data:image"), f"Field {k} contains embedded base64 image data!")

    def test_get_client_ip_extraction(self):
        """Verifies reliable extraction of client IP through Cloudflare and reverse proxies."""
        # 1. Cloudflare connecting IP
        req_cf = MagicMock()
        req_cf.headers = {"cf-connecting-ip": "197.38.12.34"}
        self.assertEqual(get_client_ip(req_cf), "197.38.12.34")

        # 2. X-Forwarded-For (multi-hop, takes first IP)
        req_xff = MagicMock()
        req_xff.headers = {"x-forwarded-for": "156.204.88.99, 10.0.0.1, 127.0.0.1"}
        self.assertEqual(get_client_ip(req_xff), "156.204.88.99")

        # 3. Direct socket host
        req_direct = MagicMock()
        req_direct.headers = {}
        req_direct.client = MagicMock()
        req_direct.client.host = "192.168.1.50"
        self.assertEqual(get_client_ip(req_direct), "192.168.1.50")

        # 4. Fallback when request is None
        self.assertEqual(get_client_ip(None), "127.0.0.1")

    async def test_building_photo_rate_limit_blocking(self):
        """Verifies rate limiting blocks when 5 uploads occur within the 5-minute window."""
        mock_rate_coll = MagicMock()
        # Simulate 5 uploads already logged in last 5 minutes
        mock_rate_coll.count_documents = AsyncMock(return_value=5)

        with patch.object(server.db, "__getitem__", return_value=mock_rate_coll), \
             patch.object(server.db, "upload_rate_limits", mock_rate_coll, create=True):
            with self.assertRaises(HTTPException) as ctx:
                await check_building_photo_rate_limit("197.38.12.34")
            self.assertEqual(ctx.exception.status_code, 429)
            self.assertIn("Batas unggah foto tercapai", ctx.exception.detail)
            self.assertIn("maksimal 5 unggah per 5 menit", ctx.exception.detail)

    async def test_upload_building_photo_storage_failure(self):
        """Verifies storage/R2 failure returns clean 502 without leaking credentials."""
        mock_file = MagicMock(spec=UploadFile)
        mock_file.filename = "building.jpg"

        genuine_img = Image.new("RGB", (50, 50), color="green")
        buf = io.BytesIO()
        genuine_img.save(buf, format="JPEG")
        mock_file.read = AsyncMock(return_value=buf.getvalue())

        mock_req = MagicMock(spec=Request)
        mock_req.headers = {}
        mock_req.client = None

        mock_rate_coll = MagicMock()
        mock_rate_coll.count_documents = AsyncMock(return_value=0)

        with patch.object(server.db, "__getitem__", return_value=mock_rate_coll), \
             patch.object(server.db, "upload_rate_limits", mock_rate_coll, create=True), \
             patch("server.put_object", side_effect=Exception("S3 Connection Timeout to Cloudflare")):

            with self.assertRaises(HTTPException) as ctx:
                await upload_building_photo(mock_req, mock_file)
            self.assertEqual(ctx.exception.status_code, 502)
            self.assertIn("Layanan penyimpanan foto sedang tidak tersedia", ctx.exception.detail)
            self.assertNotIn("S3 Connection Timeout", ctx.exception.detail)

    async def test_download_file_cache_control_privacy(self):
        """Verifies building_photo category gets private cache control while others get public."""
        building_record = {
            "storage_path": "sogil/building-photos/uuid1.webp",
            "content_type": "image/webp",
            "category": "building_photo",
        }
        product_record = {
            "storage_path": "sogil/uploads/uuid2.webp",
            "content_type": "image/webp",
            "category": "product",
        }

        mock_files_coll = MagicMock()

        with patch.object(server.db, "__getitem__", return_value=mock_files_coll), \
             patch.object(server.db, "files", mock_files_coll, create=True), \
             patch("server.get_object", return_value=(b"image_bytes", "image/webp")):

            # 1. Building photo download -> private cache
            mock_files_coll.find_one = AsyncMock(return_value=building_record)
            resp_building = await download_file("sogil/building-photos/uuid1.webp")
            self.assertEqual(resp_building.headers.get("cache-control"), "private, max-age=3600")

            # 2. Product image download -> public cache
            mock_files_coll.find_one = AsyncMock(return_value=product_record)
            resp_prod = await download_file("sogil/uploads/uuid2.webp")
            self.assertEqual(resp_prod.headers.get("cache-control"), "public, max-age=86400")

    async def test_reserve_upload_quota_atomic_concurrency(self):
        """Verifies atomic upload quota reservation under concurrent burst.
        10 simultaneous requests from same IP -> exactly 5 allowed, 5 rejected.
        Separate IP gets independent quota of 5.
        """
        client = AsyncMongoMockClient()
        mock_db = client["test_phase2_db"]
        with patch.object(server, "db", mock_db):
            # Run 10 concurrent requests from IP 1
            ip1 = "197.38.12.34"
            tasks1 = [reserve_upload_quota(ip1) for _ in range(10)]
            results1 = await asyncio.gather(*tasks1)
            allowed1 = [res[0] for res in results1]
            self.assertEqual(allowed1.count(True), 5)
            self.assertEqual(allowed1.count(False), 5)

            # Different IP gets its own independent 5 slots
            ip2 = "41.233.10.20"
            tasks2 = [reserve_upload_quota(ip2) for _ in range(5)]
            results2 = await asyncio.gather(*tasks2)
            allowed2 = [res[0] for res in results2]
            self.assertEqual(allowed2.count(True), 5)
            self.assertEqual(allowed2.count(False), 0)

    async def test_reserve_upload_quota_rollback(self):
        """Verifies server-side failure triggers rollback, freeing the quota slot for subsequent requests."""
        client = AsyncMongoMockClient()
        mock_db = client["test_phase2_db"]
        with patch.object(server, "db", mock_db):
            ip = "197.38.12.34"
            # Reserve 5 slots
            reserved_timestamps = []
            for _ in range(5):
                allowed, ts = await reserve_upload_quota(ip)
                self.assertTrue(allowed)
                reserved_timestamps.append(ts)

            # 6th request is blocked
            blocked, _ = await reserve_upload_quota(ip)
            self.assertFalse(blocked)

            # Roll back one reserved slot
            await rollback_upload_quota(ip, reserved_timestamps[0])

            # Now a new request is allowed
            allowed_again, _ = await reserve_upload_quota(ip)
            self.assertTrue(allowed_again)

    async def test_upload_building_photo_compensating_cleanup_on_db_insert_failure(self):
        """Verifies that if MongoDB db.files.insert_one fails after R2 put_object succeeds,
        compensatory delete_object(path) is executed and quota is rolled back.
        """
        mock_file = MagicMock(spec=UploadFile)
        mock_file.filename = "building.jpg"
        genuine_img = Image.new("RGB", (50, 50), color="blue")
        buf = io.BytesIO()
        genuine_img.save(buf, format="JPEG")
        mock_file.read = AsyncMock(return_value=buf.getvalue())

        mock_req = MagicMock(spec=Request)
        mock_req.headers = {}
        mock_req.client = None

        client = AsyncMongoMockClient()
        mock_db = client["test_phase2_db"]
        mock_files = MagicMock()
        mock_files.insert_one = AsyncMock(side_effect=Exception("MongoDB connection dropped"))
        mock_db.files = mock_files

        with patch.object(server, "db", mock_db), \
             patch("server.put_object", return_value={"storage_path": "sogil/building-photos/test_uuid.webp", "size": 1200}) as mock_put, \
             patch("server.delete_object") as mock_delete:

            with self.assertRaises(HTTPException) as ctx:
                await upload_building_photo(mock_req, mock_file)

            self.assertEqual(ctx.exception.status_code, 502)
            self.assertIn("Layanan penyimpanan foto sedang tidak tersedia", ctx.exception.detail)
            mock_delete.assert_called_once()
            del_arg = mock_delete.call_args[0][0]
            self.assertTrue(del_arg.startswith(f"{server.APP_NAME}/building-photos/"))
            self.assertTrue(del_arg.endswith(".webp"))

            # Verify rate limit quota was rolled back
            rate_doc = await mock_db.upload_rate_limits.find_one({"_id": "bphoto_rate:127.0.0.1"})
            reservations = rate_doc.get("reservations", [])
            self.assertEqual(len(reservations), 0)

    async def test_upload_building_photo_compensation_failure_critical_log(self):
        """Verifies critical log is emitted if compensatory delete_object fails, without masking HTTP 502."""
        mock_file = MagicMock(spec=UploadFile)
        mock_file.filename = "building.jpg"
        genuine_img = Image.new("RGB", (50, 50), color="blue")
        buf = io.BytesIO()
        genuine_img.save(buf, format="JPEG")
        mock_file.read = AsyncMock(return_value=buf.getvalue())

        mock_req = MagicMock(spec=Request)
        mock_req.headers = {}
        mock_req.client = None

        client = AsyncMongoMockClient()
        mock_db = client["test_phase2_db"]
        mock_files = MagicMock()
        mock_files.insert_one = AsyncMock(side_effect=Exception("DB write conflict"))
        mock_db.files = mock_files

        with patch.object(server, "db", mock_db), \
             patch("server.put_object", return_value={"storage_path": "sogil/building-photos/orphan_uuid.webp", "size": 1200}), \
             patch("server.delete_object", side_effect=Exception("R2 S3 Error 503")) as mock_delete, \
             patch("server.logger.critical") as mock_log_critical:

            with self.assertRaises(HTTPException) as ctx:
                await upload_building_photo(mock_req, mock_file)

            self.assertEqual(ctx.exception.status_code, 502)
            mock_delete.assert_called_once()
            mock_log_critical.assert_called_once()
            self.assertIn("RECONCILIATION NEEDED: Orphan R2 object detected", mock_log_critical.call_args[0][0])
            self.assertIn(f"{server.APP_NAME}/building-photos/", mock_log_critical.call_args[0][0])

    async def test_client_validation_error_retains_quota(self):
        """Verifies client errors (invalid format, corrupt image) retain quota to mitigate CPU/memory DoS."""
        mock_file = MagicMock(spec=UploadFile)
        mock_file.filename = "invalid.exe"
        mock_file.read = AsyncMock(return_value=b"not an image")

        mock_req = MagicMock(spec=Request)
        mock_req.headers = {}
        mock_req.client = None

        client = AsyncMongoMockClient()
        mock_db = client["test_phase2_db"]

        with patch.object(server, "db", mock_db):
            with self.assertRaises(HTTPException) as ctx:
                await upload_building_photo(mock_req, mock_file)
            self.assertEqual(ctx.exception.status_code, 400)

            # Quota reservation is RETAINED (1 reservation recorded)
            rate_doc = await mock_db.upload_rate_limits.find_one({"_id": "bphoto_rate:127.0.0.1"})
            reservations = rate_doc.get("reservations", [])
            self.assertEqual(len(reservations), 1)

    def test_get_client_ip_with_trusted_origin_token(self):
        """Verifies proxy header trust boundary when TRUSTED_ORIGIN_VERIFY_SECRET is set."""
        # When secret is configured
        with patch.dict(os.environ, {"TRUSTED_ORIGIN_VERIFY_SECRET": "secret123"}):
            # Valid token present -> trusts CF-Connecting-IP
            req_valid = MagicMock()
            req_valid.headers = {
                "x-origin-verify": "secret123",
                "cf-connecting-ip": "197.38.12.34",
            }
            self.assertEqual(get_client_ip(req_valid), "197.38.12.34")

            # Missing or invalid token -> rejects spoofed header, falls back to direct client IP
            req_spoofed = MagicMock()
            req_spoofed.headers = {
                "cf-connecting-ip": "1.2.3.4",
            }
            req_spoofed.client.host = "10.0.0.5"
            self.assertEqual(get_client_ip(req_spoofed), "10.0.0.5")

        # When secret is NOT configured -> standard behavior
        with patch.dict(os.environ, {}, clear=True):
            req_standard = MagicMock()
            req_standard.headers = {"cf-connecting-ip": "197.38.12.34"}
            self.assertEqual(get_client_ip(req_standard), "197.38.12.34")

    async def test_upload_rate_limits_indexes_in_seed(self):
        """Verifies seed() provisions the TTL index and does not create redundant compound index."""
        client = AsyncMongoMockClient()
        test_seed_db = client["test_seed_db"]
        await server.seed(test_seed_db)
        info = await test_seed_db.upload_rate_limits.index_information()
        self.assertIn("updated_at_1", info)
        self.assertEqual(info["updated_at_1"].get("expireAfterSeconds"), 600)
        self.assertNotIn("ip_1_updated_at_-1", info)

    async def test_reserve_upload_quota_identical_timestamp_isolated_rollback(self):
        """Verifies two reservations with the exact same millisecond timestamp have unique IDs,
        and rolling back the first reservation does NOT delete the second reservation.
        """
        from datetime import datetime, timezone
        client = AsyncMongoMockClient()
        mock_db = client["test_phase2_db"]
        with patch.object(server, "db", mock_db):
            ip = "197.38.12.34"
            same_time = datetime(2026, 11, 2, 10, 0, 0, 123000, tzinfo=timezone.utc)

            # Two reservations at identical timestamp
            allowed1, id1 = await reserve_upload_quota(ip, now=same_time)
            allowed2, id2 = await reserve_upload_quota(ip, now=same_time)

            self.assertTrue(allowed1)
            self.assertTrue(allowed2)
            self.assertNotEqual(id1, id2)

            # Verify document has both reservations
            doc = await mock_db.upload_rate_limits.find_one({"_id": f"bphoto_rate:{ip}"})
            self.assertEqual(len(doc["reservations"]), 2)

            # Roll back only the first reservation
            await rollback_upload_quota(ip, id1)

            # Verify that only id1 was removed, and id2 remains intact
            doc_after = await mock_db.upload_rate_limits.find_one({"_id": f"bphoto_rate:{ip}"})
            self.assertEqual(len(doc_after["reservations"]), 1)
            self.assertEqual(doc_after["reservations"][0]["id"], id2)
            saved_ts = doc_after["reservations"][0]["ts"]
            if saved_ts.tzinfo is None:
                saved_ts = saved_ts.replace(tzinfo=timezone.utc)
            self.assertEqual(saved_ts, same_time)

    async def test_reserve_upload_quota_legacy_document_backward_compatibility(self):
        """Verifies backward compatibility with legacy documents that store timestamps as bare dates."""
        from datetime import datetime, timezone, timedelta
        client = AsyncMongoMockClient()
        mock_db = client["test_phase2_db"]
        with patch.object(server, "db", mock_db):
            ip = "156.204.88.99"
            now = datetime.now(timezone.utc)

            # Legacy document with 1 expired timestamp and 2 active timestamps
            await mock_db.upload_rate_limits.insert_one({
                "_id": f"bphoto_rate:{ip}",
                "ip": ip,
                "category": "building_photo",
                "timestamps": [
                    now - timedelta(seconds=400),  # expired (>300s)
                    now - timedelta(seconds=120),  # active
                    now - timedelta(seconds=60),   # active
                ],
                "allowed": True,
            })

            # New reservation using new schema
            allowed, new_id = await reserve_upload_quota(ip, now=now)
            self.assertTrue(allowed)

            doc = await mock_db.upload_rate_limits.find_one({"_id": f"bphoto_rate:{ip}"})
            # Expired timestamp pruned, 2 active legacy migrated, 1 new added -> total 3
            self.assertEqual(len(doc["reservations"]), 3)
            ids = [r["id"] for r in doc["reservations"]]
            self.assertIn("legacy", ids)
            self.assertIn(new_id, ids)

            # Rolling back the new reservation leaves the 2 legacy ones
            await rollback_upload_quota(ip, new_id)
            doc_after = await mock_db.upload_rate_limits.find_one({"_id": f"bphoto_rate:{ip}"})
            self.assertEqual(len(doc_after["reservations"]), 2)

    async def test_reserve_upload_quota_rolling_window_pruning(self):
        """Verifies that reservations older than 300 seconds do not count towards the 5-upload quota."""
        from datetime import datetime, timezone, timedelta
        client = AsyncMongoMockClient()
        mock_db = client["test_phase2_db"]
        with patch.object(server, "db", mock_db):
            ip = "41.233.10.55"
            now = datetime.now(timezone.utc)
            old_time = now - timedelta(seconds=350)

            # Pre-insert 5 reservations that are all expired (>300s old)
            await mock_db.upload_rate_limits.insert_one({
                "_id": f"bphoto_rate:{ip}",
                "ip": ip,
                "reservations": [
                    {"id": f"old_{i}", "ts": old_time} for i in range(5)
                ],
                "allowed": True,
            })

            # Since all 5 are expired, a new request at 'now' MUST be allowed
            allowed, new_id = await reserve_upload_quota(ip, now=now)
            self.assertTrue(allowed)

            doc = await mock_db.upload_rate_limits.find_one({"_id": f"bphoto_rate:{ip}"})
            # Only the new reservation should remain in the active array
            self.assertEqual(len(doc["reservations"]), 1)
            self.assertEqual(doc["reservations"][0]["id"], new_id)



if __name__ == "__main__":
    unittest.main()
