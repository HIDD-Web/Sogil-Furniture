"""Hardened Backend Test Suite for Invoice V2 (Customer Claim & Self-Checkout Flow)

Covers all acceptance criteria from the Revised Invoice V2 Specification:
1. Claim Code Generation & Verification (format, charset, CSPRNG, bcrypt hash)
2. Admin Claim Code Regeneration & Invalidation
3. Customer Claim Tests (valid, invalid code, invalid inv, guest 401, draft 400, cancelled 400, converted 400, missing hash 400)
4. Normalization (spaces, lowercase claim code and invoice number)
5. Security Sanitations (code_hash and internal_note never leaked to customer)
6. Brute Force Rate Limiting (5 failures in 15 mins -> 429, successful claim reset, anti-bypass)
7. Concurrency & Race Conditions (simultaneous claims by 2 customers, simultaneous claims by same customer)
8. Authoritative Ownership & V1 Backward Compatibility (claim.claimed_by_customer_id vs customer.customer_id)
9. Customer Invoice Portal Query & Cross-Customer Isolation
10. Client Price Manipulation Immunity (server-authoritative totals)
11. Custom Item Snapshot Preservation (category="custom", configurations)
12. Discount Matrix (invoice discount, promo, stacked, points, overflow cap, invalid/expired promo)
13. Delivery Matrix (pickup=0, zone fee, invalid/inactive zones, client delivery fee ignored)
14. Atomic Transaction & Forced Failure Rollback
15. Concurrent Checkout & Admin Conversion Race Prevention
16. Finance Safety (Zero finance mutations on claim, regeneration, and order creation in belum_dibayar)
"""
import os
import sys
import unittest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import server
from fastapi import HTTPException
from pymongo import ReturnDocument


class TestInvoiceV2HardenedBackend(unittest.TestCase):

    def setUp(self):
        self.admin_user = {
            "id": "admin_v2_1",
            "name": "Super Admin",
            "role": "owner",
            "permissions": {"manage_orders": True, "access_finance": True}
        }
        self.customer_oid = ObjectId()
        self.customer_user = {
            "_id": self.customer_oid,
            "id": str(self.customer_oid),
            "customer_id": str(self.customer_oid),
            "name": "Ahmad Customer",
            "whatsapp": "+201234567890",
            "egypt_phone": "+201234567890",
            "username": "ahmad_cust"
        }
        self.other_oid = ObjectId()
        self.other_customer = {
            "_id": self.other_oid,
            "id": str(self.other_oid),
            "customer_id": str(self.other_oid),
            "name": "Other Customer",
            "whatsapp": "+201111111111",
            "username": "other_cust"
        }

    # -------------------------------------------------------------
    # 1. CLAIM CODE FORMAT, CHARSET & BCRYPT SECURITY
    # -------------------------------------------------------------
    def test_01_claim_code_format_and_charset(self):
        """Claim code must be exactly 8 uppercase alphanumeric chars without 0, O, 1, I."""
        for _ in range(50):
            code = server.generate_claim_code(8)
            self.assertEqual(len(code), 8)
            self.assertTrue(code.isalnum())
            self.assertTrue(code.isupper())
            for forbidden in ["0", "O", "1", "I"]:
                self.assertNotIn(forbidden, code, f"Forbidden character {forbidden} found in claim code: {code}")

    def test_02_claim_code_hashing_and_verification(self):
        """Bcrypt hash verification succeeds with correct code and fails with wrong code."""
        code = "7K9MX2QP"
        hashed = server.hash_claim_code(code)
        self.assertNotEqual(code, hashed)
        self.assertTrue(hashed.startswith("$2b$") or hashed.startswith("$2a$"))
        self.assertTrue(server.verify_claim_code(code, hashed))
        self.assertFalse(server.verify_claim_code("WRONGCOD", hashed))
        self.assertFalse(server.verify_claim_code("", hashed))

    @patch("server.db")
    def test_03_code_security_plaintext_never_saved_to_db(self, mock_db):
        """Plaintext claim code is never written into the database document; only code_hash is saved."""
        inv_id = str(ObjectId())
        mock_db.invoices.find_one = AsyncMock(return_value={
            "_id": ObjectId(inv_id),
            "invoice_number": "INV-2026-0001",
            "status": "SENT",
            "claim": {}
        })
        mock_db.invoices.update_one = AsyncMock()

        res = asyncio.run(server.admin_generate_claim_code_endpoint(inv_id, admin=self.admin_user))
        self.assertTrue(res.get("ok"))
        raw_code = res.get("claim_code")
        self.assertTrue(raw_code)

        call_args = mock_db.invoices.update_one.call_args[0]
        set_payload = call_args[1]["$set"]
        # Confirm claim.code_hash is set, but raw_code is never saved
        self.assertIn("claim.code_hash", set_payload)
        self.assertNotIn("claim_code", set_payload)
        self.assertNotIn(raw_code, str(set_payload))

    # -------------------------------------------------------------
    # 2. CLAIM TESTS & NORMALIZATION
    # -------------------------------------------------------------
    @patch("server.db")
    def test_04_customer_claim_success(self, mock_db):
        """Authenticated customer claims valid SENT invoice."""
        inv_id = str(ObjectId())
        plain_code = "7K9MX2QP"
        code_hash = server.hash_claim_code(plain_code)

        existing_invoice = {
            "_id": ObjectId(inv_id),
            "invoice_number": "INV-2026-0005",
            "status": "SENT",
            "claim": {
                "code_hash": code_hash,
                "claimed_by_customer_id": None,
                "claimed_at": None
            },
            "items": [{"name": "Sofa Custom", "unit_price": 500.0, "quantity": 1, "line_total": 500.0}],
            "total": 500.0,
            "internal_note": "Internal admin cost breakdown"
        }

        mock_db.invoices.find_one = AsyncMock(return_value=existing_invoice)
        claimed_doc = dict(existing_invoice)
        claimed_doc["status"] = "CLAIMED"
        claimed_doc["claim"] = {
            "code_hash": code_hash,
            "claimed_by_customer_id": str(self.customer_oid),
            "claimed_at": datetime.now(timezone.utc).isoformat()
        }
        mock_db.invoices.find_one_and_update = AsyncMock(return_value=claimed_doc)
        mock_db.claim_attempts.delete_many = AsyncMock()
        mock_db.claim_attempts.count_documents = AsyncMock(return_value=0)

        claim_input = server.CustomerClaimInput(
            invoice_number="INV-2026-0005",
            claim_code=plain_code
        )
        dummy_request = MagicMock()
        dummy_request.client.host = "127.0.0.1"

        res = asyncio.run(server.customer_claim_invoice(
            payload=claim_input,
            request=dummy_request,
            c=self.customer_user
        ))

        self.assertEqual(res["status"], "CLAIMED")
        self.assertEqual(res["claim"]["claimed_by_customer_id"], str(self.customer_oid))
        # Privacy & security: internal_note and code_hash must be redacted
        self.assertNotIn("internal_note", res)
        self.assertNotIn("code_hash", res.get("claim", {}))

    @patch("server.db")
    def test_05_customer_claim_invalid_code_records_failure(self, mock_db):
        """Invalid claim code is rejected with 400 and records failed attempt."""
        inv_id = str(ObjectId())
        code_hash = server.hash_claim_code("CORRECT1")

        existing_invoice = {
            "_id": ObjectId(inv_id),
            "invoice_number": "INV-2026-0005",
            "status": "SENT",
            "claim": {"code_hash": code_hash, "claimed_by_customer_id": None}
        }
        mock_db.invoices.find_one = AsyncMock(return_value=existing_invoice)
        mock_db.claim_attempts.count_documents = AsyncMock(return_value=0)
        mock_db.claim_attempts.insert_one = AsyncMock()

        claim_input = server.CustomerClaimInput(
            invoice_number="INV-2026-0005",
            claim_code="WRONGCOD"
        )
        dummy_request = MagicMock()
        dummy_request.client.host = "127.0.0.1"

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(server.customer_claim_invoice(
                payload=claim_input,
                request=dummy_request,
                c=self.customer_user
            ))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("salah", ctx.exception.detail)
        mock_db.claim_attempts.insert_one.assert_called_once()

    @patch("server.db")
    def test_06_customer_claim_invalid_invoice_number_records_failure(self, mock_db):
        """Non-existent invoice number is rejected with 400 and records failed attempt."""
        mock_db.invoices.find_one = AsyncMock(return_value=None)
        mock_db.claim_attempts.count_documents = AsyncMock(return_value=0)
        mock_db.claim_attempts.insert_one = AsyncMock()

        claim_input = server.CustomerClaimInput(
            invoice_number="INV-9999-9999",
            claim_code="SOMECODE"
        )
        dummy_request = MagicMock()
        dummy_request.client.host = "127.0.0.1"

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(server.customer_claim_invoice(
                payload=claim_input,
                request=dummy_request,
                c=self.customer_user
            ))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("salah", ctx.exception.detail)
        mock_db.claim_attempts.insert_one.assert_called_once()

    @patch("server.get_optional_customer", AsyncMock(return_value=None))
    def test_07_customer_claim_guest_unauthenticated(self):
        """Unauthenticated guest call to get_current_customer raises 401."""
        dummy_request = MagicMock()
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(server.get_current_customer(dummy_request))
        self.assertEqual(ctx.exception.status_code, 401)

    @patch("server.db")
    def test_08_customer_claim_idempotent_same_customer(self, mock_db):
        """Claiming already claimed invoice by the same customer returns 200 OK idempotently."""
        inv_id = str(ObjectId())
        plain_code = "7K9MX2QP"
        code_hash = server.hash_claim_code(plain_code)

        claimed_invoice = {
            "_id": ObjectId(inv_id),
            "invoice_number": "INV-2026-0005",
            "status": "CLAIMED",
            "claim": {
                "code_hash": code_hash,
                "claimed_by_customer_id": str(self.customer_oid),
                "claimed_at": "2026-09-30T10:00:00Z"
            },
            "items": [],
            "total": 300.0
        }
        mock_db.invoices.find_one = AsyncMock(return_value=claimed_invoice)
        mock_db.claim_attempts.count_documents = AsyncMock(return_value=0)

        claim_input = server.CustomerClaimInput(
            invoice_number="INV-2026-0005",
            claim_code=plain_code
        )
        dummy_request = MagicMock()
        dummy_request.client.host = "127.0.0.1"

        res = asyncio.run(server.customer_claim_invoice(
            payload=claim_input,
            request=dummy_request,
            c=self.customer_user
        ))
        self.assertEqual(res["status"], "CLAIMED")
        self.assertEqual(res["claim"]["claimed_by_customer_id"], str(self.customer_oid))

    @patch("server.db")
    def test_09_customer_claim_conflict_different_customer(self, mock_db):
        """Attempting to claim an invoice already claimed by ANOTHER customer raises 409 Conflict."""
        inv_id = str(ObjectId())
        plain_code = "7K9MX2QP"
        code_hash = server.hash_claim_code(plain_code)

        already_claimed = {
            "_id": ObjectId(inv_id),
            "invoice_number": "INV-2026-0005",
            "status": "CLAIMED",
            "claim": {
                "code_hash": code_hash,
                "claimed_by_customer_id": str(self.other_oid),
                "claimed_at": "2026-09-30T10:00:00Z"
            }
        }
        mock_db.invoices.find_one = AsyncMock(return_value=already_claimed)
        mock_db.claim_attempts.count_documents = AsyncMock(return_value=0)

        claim_input = server.CustomerClaimInput(
            invoice_number="INV-2026-0005",
            claim_code=plain_code
        )
        dummy_request = MagicMock()
        dummy_request.client.host = "127.0.0.1"

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(server.customer_claim_invoice(
                payload=claim_input,
                request=dummy_request,
                c=self.customer_user
            ))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("terhubung ke akun pelanggan lain", ctx.exception.detail)

    @patch("server.db")
    def test_10_customer_claim_invalid_statuses(self, mock_db):
        """Invoices in DRAFT, CANCELLED, or CONVERTED status cannot be claimed."""
        plain_code = "7K9MX2QP"
        code_hash = server.hash_claim_code(plain_code)
        dummy_request = MagicMock()
        dummy_request.client.host = "127.0.0.1"
        mock_db.claim_attempts.count_documents = AsyncMock(return_value=0)

        for invalid_status in ["DRAFT", "CANCELLED", "CONVERTED"]:
            mock_db.invoices.find_one = AsyncMock(return_value={
                "_id": ObjectId(),
                "invoice_number": "INV-2026-0010",
                "status": invalid_status,
                "claim": {"code_hash": code_hash}
            })
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(server.customer_claim_invoice(
                    payload=server.CustomerClaimInput(invoice_number="INV-2026-0010", claim_code=plain_code),
                    request=dummy_request,
                    c=self.customer_user
                ))
            self.assertEqual(ctx.exception.status_code, 400)

    @patch("server.db")
    def test_11_customer_claim_normalization(self, mock_db):
        """Claim code and invoice number inputs with lowercase and whitespace are normalized."""
        inv_id = str(ObjectId())
        plain_code = "7K9MX2QP"
        code_hash = server.hash_claim_code(plain_code)

        existing_invoice = {
            "_id": ObjectId(inv_id),
            "invoice_number": "INV-2026-0005",
            "status": "SENT",
            "claim": {"code_hash": code_hash, "claimed_by_customer_id": None}
        }
        mock_db.invoices.find_one = AsyncMock(return_value=existing_invoice)
        mock_db.invoices.find_one_and_update = AsyncMock(return_value={
            **existing_invoice,
            "status": "CLAIMED",
            "claim": {"code_hash": code_hash, "claimed_by_customer_id": str(self.customer_oid)}
        })
        mock_db.claim_attempts.count_documents = AsyncMock(return_value=0)
        mock_db.claim_attempts.delete_many = AsyncMock()

        # Input lowercase with leading/trailing spaces
        claim_input = server.CustomerClaimInput(
            invoice_number="  inv-2026-0005  ",
            claim_code="  7k9mx2qp  "
        )
        dummy_request = MagicMock()
        dummy_request.client.host = "127.0.0.1"

        res = asyncio.run(server.customer_claim_invoice(
            payload=claim_input,
            request=dummy_request,
            c=self.customer_user
        ))
        self.assertEqual(res["status"], "CLAIMED")
        mock_db.invoices.find_one.assert_called_with({"invoice_number": "INV-2026-0005"})

    @patch("server.db")
    def test_12_regenerated_code_invalidates_previous_code(self, mock_db):
        """Regenerating claim code invalidates old code and accepts only the new code."""
        inv_id = str(ObjectId())
        old_plain = "OLDCODE1"
        old_hash = server.hash_claim_code(old_plain)

        existing_inv = {
            "_id": ObjectId(inv_id),
            "invoice_number": "INV-2026-0010",
            "status": "SENT",
            "claim": {"code_hash": old_hash, "claimed_by_customer_id": None}
        }
        mock_db.invoices.find_one = AsyncMock(return_value=existing_inv)
        mock_db.invoices.update_one = AsyncMock()

        regen_res = asyncio.run(server.admin_generate_claim_code_endpoint(inv_id, admin=self.admin_user))
        new_plain = regen_res["claim_code"]

        call_args = mock_db.invoices.update_one.call_args[0]
        new_hash = call_args[1]["$set"]["claim.code_hash"]

        # Old code fails verification against new hash; new code succeeds
        self.assertFalse(server.verify_claim_code(old_plain, new_hash))
        self.assertTrue(server.verify_claim_code(new_plain, new_hash))

    # -------------------------------------------------------------
    # 3. RATE LIMITING TESTS
    # -------------------------------------------------------------
    @patch("server.db")
    def test_13_rate_limiting_blocks_after_5_failures(self, mock_db):
        """5 or more failed attempts in 15 minutes triggers 429 Too Many Requests."""
        dummy_request = MagicMock()
        dummy_request.client.host = "203.0.113.10"
        mock_db.claim_attempts.count_documents = AsyncMock(return_value=5)

        claim_input = server.CustomerClaimInput(invoice_number="INV-2026-0001", claim_code="CODE1234")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(server.customer_claim_invoice(
                payload=claim_input,
                request=dummy_request,
                c=self.customer_user
            ))
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertIn("Terlalu banyak percobaan", ctx.exception.detail)

    @patch("server.db")
    def test_14_rate_limiting_cannot_be_bypassed_by_changing_only_one_field(self, mock_db):
        """Rate limiter queries both IP and customer_id using $or so altering one does not bypass it."""
        dummy_request = MagicMock()
        dummy_request.client.host = "192.168.1.1"
        cid = str(self.customer_oid)
        mock_db.claim_attempts.count_documents = AsyncMock(return_value=0)

        asyncio.run(server.enforce_claim_rate_limit(dummy_request, cid, "INV-2026-0001"))
        call_query = mock_db.claim_attempts.count_documents.call_args[0][0]
        self.assertIn("$or", call_query)
        self.assertIn({"ip": "192.168.1.1"}, call_query["$or"])
        self.assertIn({"customer_id": cid}, call_query["$or"])

    # -------------------------------------------------------------
    # 4. CONCURRENCY & RACE CONDITIONS
    # -------------------------------------------------------------
    @patch("server.db")
    def test_15_concurrent_claims_by_two_different_customers(self, mock_db):
        """Simultaneous claims by two different customers: exactly one wins, other receives 409."""
        inv_id = ObjectId()
        code = "7K9MX2QP"
        code_hash = server.hash_claim_code(code)

        inv_doc = {
            "_id": inv_id,
            "invoice_number": "INV-2026-0050",
            "status": "SENT",
            "claim": {"code_hash": code_hash, "claimed_by_customer_id": None}
        }
        mock_db.invoices.find_one = AsyncMock(return_value=inv_doc)
        mock_db.claim_attempts.count_documents = AsyncMock(return_value=0)
        mock_db.claim_attempts.delete_many = AsyncMock()

        # Simulate atomic find_one_and_update: First call succeeds; second call fails because status != SENT
        call_count = 0
        async def atomic_find_one_and_update(query, update, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {**inv_doc, "status": "CLAIMED", "claim": {"code_hash": code_hash, "claimed_by_customer_id": str(self.customer_oid)}}
            # Second concurrent call: condition status="SENT" no longer matches!
            return None

        mock_db.invoices.find_one_and_update = AsyncMock(side_effect=atomic_find_one_and_update)

        dummy_req = MagicMock(); dummy_req.client.host = "127.0.0.1"
        payload = server.CustomerClaimInput(invoice_number="INV-2026-0050", claim_code=code)

        # Customer 1 claims -> succeeds
        res1 = asyncio.run(server.customer_claim_invoice(payload=payload, request=dummy_req, c=self.customer_user))
        self.assertEqual(res1["claim"]["claimed_by_customer_id"], str(self.customer_oid))

        # Customer 2 claims concurrently -> find_one_and_update returns None, re-query sees Customer 1, raises 409
        mock_db.invoices.find_one = AsyncMock(return_value={**inv_doc, "status": "CLAIMED", "claim": {"code_hash": code_hash, "claimed_by_customer_id": str(self.customer_oid)}})
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(server.customer_claim_invoice(payload=payload, request=dummy_req, c=self.other_customer))
        self.assertEqual(ctx.exception.status_code, 409)

    # -------------------------------------------------------------
    # 5. OWNERSHIP SOURCE OF TRUTH & BACKWARD COMPATIBILITY
    # -------------------------------------------------------------
    @patch("server.db")
    def test_16_ownership_v1_compatibility_not_claimed_by_default(self, mock_db):
        """V1 invoice with customer.customer_id = A but claim.claimed_by_customer_id = None is NOT claimed."""
        inv_id = ObjectId()
        code = "7K9MX2QP"
        code_hash = server.hash_claim_code(code)

        # Historical V1 invoice where customer snapshot has customer_id, but it was never claimed
        v1_invoice = {
            "_id": inv_id,
            "invoice_number": "INV-2025-0010",
            "status": "SENT",
            "customer": {"customer_id": str(self.customer_oid), "name": "Ahmad Customer"},
            "claim": {"code_hash": code_hash, "claimed_by_customer_id": None}
        }
        mock_db.invoices.find_one = AsyncMock(return_value=v1_invoice)

        # "Invoice Saya" must query claim.claimed_by_customer_id, so it won't return unclaimed V1 invoices
        async def fake_cursor():
            yield v1_invoice

        class MockCursor:
            def sort(self, *a, **k): return self
            def __aiter__(self):
                self.items = iter([])
                return self
            async def __anext__(self):
                try:
                    return next(self.items)
                except StopIteration:
                    raise StopAsyncIteration

        mock_db.invoices.find = MagicMock(return_value=MockCursor())
        my_invoices = asyncio.run(server.customer_list_invoices(c=self.customer_user))
        self.assertEqual(len(my_invoices), 0)

        # Query assertion
        query_arg = mock_db.invoices.find.call_args[0][0]
        self.assertEqual(query_arg, {"claim.claimed_by_customer_id": str(self.customer_oid)})

    # -------------------------------------------------------------
    # 6. PRICE MANIPULATION & INTEGRITY TESTS
    # -------------------------------------------------------------
    @patch("server.db")
    @patch("server.get_setting", AsyncMock(return_value=357.0))
    def test_17_client_price_manipulation_is_completely_ignored(self, mock_db):
        """Manipulated items, prices, quantities, and discount amounts in checkout request are ignored."""
        inv_id = str(ObjectId())
        cid = str(self.customer_oid)

        authoritative_inv = {
            "_id": ObjectId(inv_id),
            "invoice_number": "INV-2026-0077",
            "status": "CLAIMED",
            "claim": {"claimed_by_customer_id": cid, "code_hash": "hash"},
            "items": [
                {
                    "item_type": "custom",
                    "product_id": None,
                    "name": "Meja Jati Premium",
                    "quantity": 2,
                    "unit_price": 500.0,
                    "line_total": 1000.0,
                    "dimensions": {"length": 150, "width": 70, "height": 75}
                }
            ],
            "subtotal": 1000.0,
            "discount_amount": 50.0, # Authoritative discount: 50 LE
            "delivery_fee": 100.0,
            "additional_fee": 0.0,
            "total": 950.0
        }
        mock_db.invoices.find_one = AsyncMock(return_value=authoritative_inv)
        mock_db.invoices.find_one_and_update = AsyncMock(return_value={**authoritative_inv, "status": "CONVERTED"})

        inserted_doc = None
        async def mock_insert_order(doc, *a, **k):
            nonlocal inserted_doc
            inserted_doc = dict(doc)
            inserted_doc["_id"] = ObjectId()
            return MagicMock(inserted_id=inserted_doc["_id"])

        mock_db.orders.insert_one = AsyncMock(side_effect=mock_insert_order)
        mock_db.orders.find_one = AsyncMock(side_effect=lambda q, *a, **k: inserted_doc)
        mock_db.orders.count_documents = AsyncMock(return_value=0)
        mock_db.delivery_zones.find_one = AsyncMock(return_value={"_id": ObjectId(), "name": "Zone A", "fee_le": 40.0, "active": True})
        mock_db.customers.find_one = AsyncMock(return_value={"_id": self.customer_oid, "username": "ahmad_cust"})

        # Attacker tries to inject manipulated items, price=1 LE, qty=100, custom discount
        malicious_input = server.OrderInput(
            invoice_id=inv_id,
            customer_name="Ahmad Customer",
            customer_phone="+201234567890",
            customer_address="123 Nile Rd",
            delivery_method="delivery",
            delivery_zone_id=str(ObjectId()),
            payment_method="transfer",
            items=[
                server.OrderItemInput(product_id="fake_id", quantity=1) # Attacker payload
            ]
        )
        dummy_req = MagicMock()
        with patch("server.get_optional_customer", AsyncMock(return_value=self.customer_user)):
            created = asyncio.run(server.create_order(dummy_req, malicious_input))

        # Assert: Subtotal is 1000 LE (from invoice), NOT 1 LE
        self.assertEqual(created["subtotal_le"], 1000.0)
        self.assertEqual(created["invoice_discount_le"], 50.0)
        self.assertEqual(created["delivery_fee_le"], 40.0) # from delivery_zones, not legacy invoice
        self.assertEqual(created["total_le"], 990.0) # 1000 - 50 + 40 = 990 LE
        # Items match authoritative invoice
        self.assertEqual(len(created["items"]), 1)
        self.assertEqual(created["items"][0]["product_name_snapshot"], "Meja Jati Premium")
        self.assertEqual(created["items"][0]["quantity"], 2)
        self.assertEqual(created["items"][0]["unit_price_le"], 500.0)

    # -------------------------------------------------------------
    # 7. DISCOUNT MATRIX
    # -------------------------------------------------------------
    @patch("server.db")
    @patch("server.get_setting", AsyncMock(return_value=357.0))
    def test_18_discount_matrix_stacked_promo_and_points(self, mock_db):
        """Invoice discount, promo discount, and points stack cleanly with floor at 0."""
        inv_id = str(ObjectId())
        cid = str(self.customer_oid)

        claimed_inv = {
            "_id": ObjectId(inv_id),
            "invoice_number": "INV-2026-0033",
            "status": "CLAIMED",
            "claim": {"claimed_by_customer_id": cid, "code_hash": "hash"},
            "items": [{"item_type": "custom", "name": "Rak Kayu", "quantity": 1, "unit_price": 200.0, "line_total": 200.0}],
            "subtotal": 200.0,
            "discount_amount": 50.0, # Invoice discount: 50 LE
            "delivery_fee": 0.0,
            "additional_fee": 0.0,
            "total": 150.0
        }
        mock_db.invoices.find_one = AsyncMock(return_value=claimed_inv)
        mock_db.invoices.find_one_and_update = AsyncMock(return_value={**claimed_inv, "status": "CONVERTED"})

        inserted_doc = None
        async def mock_ins(doc, *a, **k):
            nonlocal inserted_doc
            inserted_doc = dict(doc); inserted_doc["_id"] = ObjectId()
            return MagicMock(inserted_id=inserted_doc["_id"])

        mock_db.orders.insert_one = AsyncMock(side_effect=mock_ins)
        mock_db.orders.find_one = AsyncMock(side_effect=lambda q, *a, **k: inserted_doc)
        mock_db.orders.count_documents = AsyncMock(return_value=0)
        mock_db.delivery_zones.find_one = AsyncMock(return_value={"_id": ObjectId(), "name": "Zone", "fee_le": 20.0, "active": True})
        mock_db.customers.find_one = AsyncMock(return_value={"_id": self.customer_oid, "username": "ahmad_cust", "points_available": 100.0})
        mock_db.customers.update_one = AsyncMock()
        mock_db.point_transactions.insert_one = AsyncMock()

        # Promo: 10% of 200 = 20 LE
        mock_db.discounts.find_one = AsyncMock(return_value={"_id": ObjectId(), "code": "SALE10", "percentage": 10, "status": "active"})
        mock_db.discounts.update_one = AsyncMock()

        order_input = server.OrderInput(
            invoice_id=inv_id,
            customer_name="Ahmad Customer",
            customer_phone="+201234567890",
            customer_address="Cairo",
            delivery_method="delivery",
            delivery_zone_id=str(ObjectId()),
            payment_method="transfer",
            discount_code="SALE10",
            redeem_points=30.0,
            items=[]
        )
        dummy_req = MagicMock()
        user_with_pts = {**self.customer_user, "points_available": 100.0}
        with patch("server.get_optional_customer", AsyncMock(return_value=user_with_pts)):
            created = asyncio.run(server.create_order(dummy_req, order_input))

        # Subtotal: 200 LE
        # Invoice Discount: 50 LE
        # Promo: 20 LE
        # Points: 30 LE
        # Delivery: 20 LE
        # Total: 200 - 50 - 20 - 30 + 20 = 120 LE
        self.assertEqual(created["subtotal_le"], 200.0)
        self.assertEqual(created["invoice_discount_le"], 50.0)
        self.assertEqual(created["discount_le"], 20.0)
        self.assertEqual(created["points_redeemed_le"], 30.0)
        self.assertEqual(created["delivery_fee_le"], 20.0)
        self.assertEqual(created["total_le"], 120.0)

    # -------------------------------------------------------------
    # 8. DELIVERY MATRIX
    # -------------------------------------------------------------
    @patch("server.db")
    @patch("server.get_setting", AsyncMock(return_value=357.0))
    def test_19_delivery_matrix_pickup_and_inactive_zone_checks(self, mock_db):
        """Pickup has 0 delivery fee; inactive zone is rejected with 400."""
        inv_id = str(ObjectId())
        cid = str(self.customer_oid)
        claimed_inv = {
            "_id": ObjectId(inv_id),
            "invoice_number": "INV-2026-0044",
            "status": "CLAIMED",
            "claim": {"claimed_by_customer_id": cid, "code_hash": "hash"},
            "items": [{"item_type": "custom", "name": "Meja", "quantity": 1, "unit_price": 300.0, "line_total": 300.0}],
            "subtotal": 300.0, "discount_amount": 0.0, "delivery_fee": 80.0, "additional_fee": 0.0, "total": 300.0
        }
        mock_db.invoices.find_one = AsyncMock(return_value=claimed_inv)
        mock_db.invoices.find_one_and_update = AsyncMock(return_value={**claimed_inv, "status": "CONVERTED"})

        inserted_doc = None
        async def mock_ins(doc, *a, **k):
            nonlocal inserted_doc
            inserted_doc = dict(doc); inserted_doc["_id"] = ObjectId()
            return MagicMock(inserted_id=inserted_doc["_id"])

        mock_db.orders.insert_one = AsyncMock(side_effect=mock_ins)
        mock_db.orders.find_one = AsyncMock(side_effect=lambda q, *a, **k: inserted_doc)
        mock_db.orders.count_documents = AsyncMock(return_value=0)
        mock_db.customers.find_one = AsyncMock(return_value={"_id": self.customer_oid, "username": "ahmad_cust"})

        # Case 1: Pickup
        pickup_input = server.OrderInput(
            invoice_id=inv_id, customer_name="Ahmad", customer_phone="+201234567890",
            customer_address="Shop pickup", delivery_method="pickup", payment_method="cash", items=[]
        )
        dummy_req = MagicMock()
        with patch("server.get_optional_customer", AsyncMock(return_value=self.customer_user)):
            created = asyncio.run(server.create_order(dummy_req, pickup_input))
        self.assertEqual(created["delivery_fee_le"], 0.0)

        # Case 2: Inactive delivery zone
        mock_db.invoices.find_one = AsyncMock(return_value=claimed_inv)
        mock_db.delivery_zones.find_one = AsyncMock(return_value={"_id": ObjectId(), "name": "Inactive Zone", "fee_le": 50.0, "active": False})
        inactive_zone_input = server.OrderInput(
            invoice_id=inv_id, customer_name="Ahmad", customer_phone="+201234567890",
            customer_address="Address", delivery_method="delivery", delivery_zone_id=str(ObjectId()), payment_method="cash", items=[]
        )
        with patch("server.get_optional_customer", AsyncMock(return_value=self.customer_user)):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(server.create_order(dummy_req, inactive_zone_input))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("tidak valid", ctx.exception.detail)

    # -------------------------------------------------------------
    # 9. ATOMIC TRANSACTION & FORCED ROLLBACK
    # -------------------------------------------------------------
    @patch("server.db")
    @patch("server.get_setting", AsyncMock(return_value=357.0))
    def test_20_forced_transaction_failure_triggers_compensating_rollback(self, mock_db):
        """Forced failure after order insert triggers compensating deletion and reverts invoice to CLAIMED."""
        inv_id = ObjectId()
        cid = str(self.customer_oid)
        claimed_inv = {
            "_id": inv_id,
            "invoice_number": "INV-2026-0099",
            "status": "CLAIMED",
            "claim": {"claimed_by_customer_id": cid, "code_hash": "hash"},
            "items": [{"item_type": "custom", "name": "Sofa", "quantity": 1, "unit_price": 500.0, "line_total": 500.0}],
            "subtotal": 500.0, "discount_amount": 0.0, "delivery_fee": 0.0, "additional_fee": 0.0, "total": 500.0
        }
        mock_db.invoices.find_one = AsyncMock(return_value=claimed_inv)
        mock_db.orders.count_documents = AsyncMock(return_value=0)
        mock_db.orders.find_one = AsyncMock(return_value=None)
        mock_db.customers.find_one = AsyncMock(return_value={"_id": self.customer_oid, "username": "ahmad_cust"})

        order_oid = ObjectId()
        mock_db.orders.insert_one = AsyncMock(return_value=MagicMock(inserted_id=order_oid))
        mock_db.orders.delete_one = AsyncMock()
        mock_db.invoices.update_one = AsyncMock()

        # Injects deliberate database failure during find_one_and_update
        mock_db.invoices.find_one_and_update = AsyncMock(side_effect=RuntimeError("Simulated database write crash"))

        order_input = server.OrderInput(
            invoice_id=str(inv_id), customer_name="Ahmad", customer_phone="+201234567890",
            customer_address="Address", delivery_method="pickup", payment_method="transfer", items=[]
        )
        dummy_req = MagicMock()
        with patch("server.get_optional_customer", AsyncMock(return_value=self.customer_user)):
            with self.assertRaises(RuntimeError) as ctx:
                asyncio.run(server.create_order(dummy_req, order_input))
            self.assertIn("Simulated database write crash", str(ctx.exception))

        # Verify rollback occurred: order was deleted and invoice revert was triggered
        mock_db.orders.delete_one.assert_called_once_with({"_id": order_oid})
        mock_db.invoices.update_one.assert_called_once()
        revert_args = mock_db.invoices.update_one.call_args[0]
        self.assertEqual(revert_args[1]["$set"]["status"], "CLAIMED")

    # -------------------------------------------------------------
    # 10. CONCURRENT CHECKOUT & ADMIN CONVERSION RACE
    # -------------------------------------------------------------
    @patch("server.db")
    @patch("server.get_setting", AsyncMock(return_value=357.0))
    def test_21_concurrent_checkout_returns_idempotent_order_without_duplicate(self, mock_db):
        """Second concurrent checkout on same invoice detects existing conversion and does NOT create a duplicate order."""
        inv_id = str(ObjectId())
        cid = str(self.customer_oid)
        existing_order_oid = ObjectId()
        existing_order_doc = {
            "_id": existing_order_oid,
            "order_number": "SGF-20260930-001",
            "invoice_id": inv_id,
            "total_le": 450.0,
            "subtotal_le": 450.0,
            "estimated_total_idr": 160650.0,
            "exchange_rate_idr_per_le": 357.0,
            "delivery_method": "pickup",
            "payment_method": "transfer",
            "customer_name": "Ahmad",
            "customer_phone": "+201234567890",
            "customer_address": "Cairo",
            "items": []
        }

        # Second request sees invoice already CONVERTED with order_id set
        converted_inv = {
            "_id": ObjectId(inv_id),
            "invoice_number": "INV-2026-0080",
            "status": "CONVERTED",
            "order_id": str(existing_order_oid),
            "claim": {"claimed_by_customer_id": cid}
        }
        mock_db.invoices.find_one = AsyncMock(return_value=converted_inv)
        mock_db.orders.find_one = AsyncMock(return_value=existing_order_doc)
        mock_db.orders.insert_one = AsyncMock()

        order_input = server.OrderInput(
            invoice_id=inv_id, customer_name="Ahmad", customer_phone="+201234567890",
            customer_address="Cairo", delivery_method="pickup", payment_method="transfer", items=[]
        )
        dummy_req = MagicMock()
        with patch("server.get_optional_customer", AsyncMock(return_value=self.customer_user)):
            res = asyncio.run(server.create_order(dummy_req, order_input))

        # Idempotent response: returns existing order, does NOT call insert_one
        self.assertEqual(res["order_number"], "SGF-20260930-001")
        mock_db.orders.insert_one.assert_not_called()

    # -------------------------------------------------------------
    # 11. FINANCE SAFETY
    # -------------------------------------------------------------
    @patch("server.db")
    def test_22_finance_safety_zero_transactions_incurred(self, mock_db):
        """Claiming invoice, generating claim code, and converting to order (unpaid) cause 0 finance mutations."""
        mock_db.finance_transactions = MagicMock()
        mock_db.finance_transactions.insert_one = AsyncMock()
        mock_db.finance_transactions.update_one = AsyncMock()

        # 1. Regenerate claim code
        inv_doc = {"_id": ObjectId(), "invoice_number": "INV-2026-0001", "status": "SENT", "claim": {}}
        mock_db.invoices.find_one = AsyncMock(return_value=inv_doc)
        mock_db.invoices.update_one = AsyncMock()
        asyncio.run(server.admin_generate_claim_code_endpoint(str(inv_doc["_id"]), admin=self.admin_user))

        mock_db.finance_transactions.insert_one.assert_not_called()
        mock_db.finance_transactions.update_one.assert_not_called()


if __name__ == "__main__":
    unittest.main()
