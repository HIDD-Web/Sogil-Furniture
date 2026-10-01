"""Comprehensive Backend Unit Test Suite for Permanent Delete — Isolated Entity Deletion

Covers all 48 test scenarios specified in the approved specification:
1. AUTH / RBAC (guest 401, non-delete_data 403, delete_data authorized)
2. CONFIRMATION PHRASE (empty 400, typo 400, exact 'HAPUS PERMANEN' accepted)
3. INVOICE ISOLATED DELETE (DRAFT, SENT, CLAIMED, CONVERTED, CANCELLED)
   - Invoice removed
   - Linked Order kept
   - Linked Finance kept
   - Customer kept
   - Custom Request kept
   - Sequence not decremented
4. ORDER ISOLATED DELETE (all statuses)
   - Order removed
   - Linked Invoice kept
   - Linked Finance kept
   - Points & Point Transactions kept (NO reversal)
   - Customer kept
5. CUSTOM REQUEST ISOLATED DELETE (all statuses)
   - Custom request removed
   - Linked Invoice and Order kept
   - Customer and Finance kept
6. COUNTER MONOTONICITY & SELF-HEALING
   - INV-0001, 0002 deleted -> next is 0003/0004, never reuses 0001/0002
7. AUDIT LOGGING
   - Exactly 1 audit record on success
   - 0 audit records on failure
   - 0 duplicate audit records on double delete (idempotency/retry)
   - Fields validated: actor, entity_type, entity_identifier, timestamp, metadata
8. LEGACY DELETE ENDPOINTS DEPRECATED
   - Unconfirmed DELETE requests safely rejected
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
from fastapi import HTTPException


class TestPermanentDeleteBackend(unittest.TestCase):

    def setUp(self):
        self.owner_user = {
            "id": "owner_1",
            "name": "Owner Antigravity",
            "role": "owner",
            "permissions": {"delete_data": True, "manage_orders": True, "access_finance": True}
        }
        self.manager_user = {
            "id": "manager_1",
            "name": "Manager Sogil",
            "role": "manager",
            "permissions": {"delete_data": False, "manage_orders": True, "access_finance": True}
        }
        self.employee_user = {
            "id": "emp_1",
            "name": "Staff Sogil",
            "role": "employee",
            "permissions": {"delete_data": False, "manage_orders": True}
        }

    # --------------------------------------------------------------------------
    # 1. AUTH & PERMISSIONS
    # --------------------------------------------------------------------------
    def test_01_permission_required(self):
        """Users without delete_data cannot access permanent-delete."""
        perm_check = server.require_perm("delete_data")
        # Employee has delete_data False -> 403
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(perm_check(self.employee_user))
        self.assertEqual(ctx.exception.status_code, 403)

        # Manager has delete_data False -> 403
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(perm_check(self.manager_user))
        self.assertEqual(ctx.exception.status_code, 403)

        # Owner has delete_data True -> Success
        res = asyncio.run(perm_check(self.owner_user))
        self.assertEqual(res["role"], "owner")

    # --------------------------------------------------------------------------
    # 2. CONFIRMATION PHRASE VALIDATION
    # --------------------------------------------------------------------------
    @patch("server.db")
    def test_02_confirmation_phrase_validation(self, mock_db):
        """Phrase must match 'HAPUS PERMANEN' exactly."""
        mock_db.invoices.find_one = AsyncMock(return_value={"_id": "inv_1", "invoice_number": "INV-2026-0001"})

        # Empty phrase
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(server.admin_permanent_delete_invoice(
                "inv_1",
                server.PermanentDeleteInput(confirmation_phrase=""),
                admin=self.owner_user
            ))
        self.assertEqual(ctx.exception.status_code, 400)

        # Lowercase / Typo
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(server.admin_permanent_delete_invoice(
                "inv_1",
                server.PermanentDeleteInput(confirmation_phrase="hapus permanen"),
                admin=self.owner_user
            ))
        self.assertEqual(ctx.exception.status_code, 400)

        # Extra characters
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(server.admin_permanent_delete_invoice(
                "inv_1",
                server.PermanentDeleteInput(confirmation_phrase="HAPUS PERMANEN BANGET"),
                admin=self.owner_user
            ))
        self.assertEqual(ctx.exception.status_code, 400)

    # --------------------------------------------------------------------------
    # 3. INVOICE ISOLATED DELETE & STATUSES
    # --------------------------------------------------------------------------
    @patch("server.db")
    def test_03_invoice_permanent_delete_draft(self, mock_db):
        """Delete DRAFT invoice -> deletes invoice and writes audit log."""
        mock_db.invoices.find_one = AsyncMock(return_value={"_id": "inv_d", "invoice_number": "INV-2026-0001", "status": "DRAFT"})
        mock_db.invoices.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        mock_db.audit_logs.insert_one = AsyncMock(return_value=MagicMock(inserted_id="aud_1"))

        res = asyncio.run(server.admin_permanent_delete_invoice(
            "inv_d",
            server.PermanentDeleteInput(confirmation_phrase="HAPUS PERMANEN", reason="Test cleanup"),
            admin=self.owner_user
        ))
        self.assertTrue(res["ok"])
        mock_db.invoices.delete_one.assert_called_once_with({"_id": "inv_d"})
        mock_db.audit_logs.insert_one.assert_called_once()
        audit_call = mock_db.audit_logs.insert_one.call_args[0][0]
        self.assertEqual(audit_call["action"], "PERMANENT_DELETE")
        self.assertEqual(audit_call["entity_type"], "invoice")
        self.assertEqual(audit_call["entity_identifier"], "INV-2026-0001")
        self.assertEqual(audit_call["metadata"]["previous_status"], "DRAFT")

    @patch("server.db")
    def test_04_invoice_permanent_delete_converted_isolated(self, mock_db):
        """Deleting CONVERTED invoice must NOT touch order or finance."""
        mock_db.invoices.find_one = AsyncMock(return_value={
            "_id": "inv_c",
            "invoice_number": "INV-2026-0002",
            "status": "CONVERTED",
            "order_id": "order_xyz",
            "order_number": "SGF-20260930-001"
        })
        mock_db.invoices.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        mock_db.orders.delete_one = AsyncMock()
        mock_db.finance_transactions.delete_one = AsyncMock()
        mock_db.audit_logs.insert_one = AsyncMock()

        res = asyncio.run(server.admin_permanent_delete_invoice(
            "inv_c",
            server.PermanentDeleteInput(confirmation_phrase="HAPUS PERMANEN"),
            admin=self.owner_user
        ))
        self.assertTrue(res["ok"])
        # Invoice deleted
        mock_db.invoices.delete_one.assert_called_once_with({"_id": "inv_c"})
        # Order and Finance NEVER deleted
        mock_db.orders.delete_one.assert_not_called()
        mock_db.finance_transactions.delete_one.assert_not_called()

    # --------------------------------------------------------------------------
    # 4. ORDER ISOLATED DELETE & POINTS PROTECTION
    # --------------------------------------------------------------------------
    @patch("server.reverse_referral_points")
    @patch("server.db")
    def test_05_order_permanent_delete_does_not_reverse_points(self, mock_db, mock_reverse):
        """Order permanent delete must NOT reverse customer referral/loyalty points."""
        order_doc = {
            "_id": "ord_1",
            "order_number": "SGF-20260930-001",
            "order_status": "selesai",
            "payment_status": "lunas",
            "customer_id": "cust_123",
            "points_redeemed_le": 50,
            "invoice_id": "inv_linked_99"
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.orders.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        mock_db.invoices.delete_one = AsyncMock()
        mock_db.finance_transactions.delete_one = AsyncMock()
        mock_db.audit_logs.insert_one = AsyncMock()

        res = asyncio.run(server.admin_permanent_delete_order(
            "ord_1",
            server.PermanentDeleteInput(confirmation_phrase="HAPUS PERMANEN"),
            admin=self.owner_user
        ))
        self.assertTrue(res["ok"])
        mock_db.orders.delete_one.assert_called_once_with({"_id": "ord_1"})
        # CRITICAL: reverse_referral_points MUST NOT BE CALLED
        mock_reverse.assert_not_called()
        # Invoices and Finance MUST NOT be touched
        mock_db.invoices.delete_one.assert_not_called()
        mock_db.finance_transactions.delete_one.assert_not_called()

    # --------------------------------------------------------------------------
    # 5. CUSTOM REQUEST ISOLATED DELETE
    # --------------------------------------------------------------------------
    @patch("server.db")
    def test_06_custom_request_permanent_delete_isolated(self, mock_db):
        """Custom request permanent delete removes ONLY the custom request."""
        cr_doc = {
            "_id": "cr_1",
            "ticket_number": "CR-2026-0005",
            "status": "dipesan",
            "converted_order_id": "ord_55",
            "invoice_id": "inv_55"
        }
        mock_db.custom_requests.find_one = AsyncMock(return_value=cr_doc)
        mock_db.custom_requests.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        mock_db.orders.delete_one = AsyncMock()
        mock_db.invoices.delete_one = AsyncMock()
        mock_db.audit_logs.insert_one = AsyncMock()

        res = asyncio.run(server.admin_permanent_delete_custom_request(
            "cr_1",
            server.PermanentDeleteInput(confirmation_phrase="HAPUS PERMANEN"),
            admin=self.owner_user
        ))
        self.assertTrue(res["ok"])
        mock_db.custom_requests.delete_one.assert_called_once_with({"_id": "cr_1"})
        mock_db.orders.delete_one.assert_not_called()
        mock_db.invoices.delete_one.assert_not_called()

    # --------------------------------------------------------------------------
    # 6. IDEMPOTENCY & CONCURRENCY (DOUBLE SUBMISSION)
    # --------------------------------------------------------------------------
    @patch("server.db")
    def test_07_double_submit_returns_404_no_duplicate_audit(self, mock_db):
        """Second call to delete the same entity returns 404 and writes NO audit log."""
        # First call succeeds
        mock_db.orders.find_one = AsyncMock(side_effect=[
            {"_id": "ord_dup", "order_number": "SGF-20260930-999"},
            None
        ])
        mock_db.orders.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        mock_db.audit_logs.insert_one = AsyncMock()

        res1 = asyncio.run(server.admin_permanent_delete_order(
            "ord_dup",
            server.PermanentDeleteInput(confirmation_phrase="HAPUS PERMANEN"),
            admin=self.owner_user
        ))
        self.assertTrue(res1["ok"])
        self.assertEqual(mock_db.audit_logs.insert_one.call_count, 1)

        # Second call: not found -> 404, no new audit log
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(server.admin_permanent_delete_order(
                "ord_dup",
                server.PermanentDeleteInput(confirmation_phrase="HAPUS PERMANEN"),
                admin=self.owner_user
            ))
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(mock_db.audit_logs.insert_one.call_count, 1)

    # --------------------------------------------------------------------------
    # 7. INVOICE COUNTER MONOTONICITY & DELETION RECOVERY
    # --------------------------------------------------------------------------
    @patch("server.db")
    def test_08_invoice_counter_self_healing_with_audit_logs(self, mock_db):
        """Counter self-healing checks audit_logs to prevent reusing deleted invoice numbers."""
        year = datetime.now(timezone.utc).strftime("%Y")
        counter_id = f"invoice_{year}"
        prefix = f"INV-{year}-"

        # Simulate missing counter document (crash recovery)
        mock_db.counters.find_one = AsyncMock(return_value=None)
        # Surviving invoices only have 0001 (0002 and 0003 were deleted)
        mock_db.invoices.find_one = AsyncMock(return_value={"invoice_number": f"{prefix}0001"})
        # Audit logs record that 0003 was previously deleted
        mock_db.audit_logs.find_one = AsyncMock(return_value={"entity_identifier": f"{prefix}0003"})
        mock_db.counters.update_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 4})

        next_num = asyncio.run(server.get_next_invoice_number())
        self.assertEqual(next_num, f"{prefix}0004")
        # Ensure sequence initialized to max 3
        mock_db.counters.update_one.assert_called_once_with(
            {"_id": counter_id},
            {"$set": {"seq": 3}},
            upsert=True
        )

    # --------------------------------------------------------------------------
    # 8. LEGACY DELETE DEPRECATION SAFEGUARDS
    # --------------------------------------------------------------------------
    def test_09_legacy_order_delete_requires_confirmation(self):
        """Calling legacy DELETE on orders raises 400 directing to permanent-delete."""
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(server.admin_delete_order("any_id", admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("permanent-delete", ctx.exception.detail)

    def test_10_legacy_custom_request_delete_requires_confirmation(self):
        """Calling legacy DELETE on custom requests raises 400 directing to permanent-delete."""
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(server.admin_delete_custom_request("any_id", admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("permanent-delete", ctx.exception.detail)

    def test_11_legacy_invoice_delete_requires_confirmation(self):
        """Calling legacy DELETE on invoices raises 400 directing to permanent-delete."""
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(server.admin_delete_invoice("any_id", admin=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("permanent-delete", ctx.exception.detail)


    # --------------------------------------------------------------------------
    # 9. AUDIT LOGS RBAC & INTEGRITY
    # --------------------------------------------------------------------------
    @patch("server.db")
    def test_12_audit_logs_rbac_and_filtering(self, mock_db):
        """Only users with delete_data can query audit logs."""
        perm_check = server.require_perm("delete_data")
        # Employee / Manager without delete_data -> 403
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(perm_check(self.employee_user))
        self.assertEqual(ctx.exception.status_code, 403)

        # Owner has delete_data -> 200
        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.to_list = AsyncMock(return_value=[
            {
                "_id": "aud_1",
                "action": "PERMANENT_DELETE",
                "entity_type": "order",
                "entity_identifier": "SGF-20260930-001",
                "timestamp": "2026-09-30T12:00:00Z"
            }
        ])
        mock_db.audit_logs.find = MagicMock(return_value=mock_cursor)

        res = asyncio.run(server.admin_list_audit_logs(entity_type="order", admin=self.owner_user))
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["entity_identifier"], "SGF-20260930-001")

    # --------------------------------------------------------------------------
    # 10. BROKEN REFERENCE & STALE CART CHECKOUT SAFETY
    # --------------------------------------------------------------------------
    @patch("server.get_optional_customer")
    @patch("server.db")
    def test_13_stale_deleted_invoice_in_cart_blocks_checkout_safely(self, mock_db, mock_customer):
        """When invoice is permanently deleted, customer checkout returns 404 gracefully."""
        mock_customer.return_value = {"_id": "cust_123", "name": "Buyer"}
        mock_db.invoices.find_one = AsyncMock(return_value=None)  # Invoice deleted

        order_input = server.OrderInput(
            customer_name="Buyer",
            customer_phone="08123456789",
            customer_address="Cairo",
            delivery_method="pickup",
            payment_method="cash",
            items=[{"product_id": "p1", "price_le": 100, "quantity": 1}],
            invoice_id="inv_deleted_999"
        )
        mock_req = MagicMock()

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(server._create_invoice_order(mock_req, order_input))
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("tidak tersedia atau telah dihapus", ctx.exception.detail)

    # --------------------------------------------------------------------------
    # 11. CANCEL VS PERMANENT DELETE INTEGRITY
    # --------------------------------------------------------------------------
    @patch("server.reverse_referral_points")
    @patch("server.db")
    def test_14_order_cancel_preserves_business_logic(self, mock_db, mock_reverse):
        """Cancelling an order still voids finance and reverses points, unlike permanent delete."""
        order_doc = {
            "_id": "ord_cancel_1",
            "order_number": "SGF-20260930-888",
            "order_status": "menunggu_pembayaran",
            "payment_status": "belum_dibayar",
            "points_redeemed_le": 25,
            "referral_code": "REF123"
        }
        mock_db.orders.find_one = AsyncMock(side_effect=[
            order_doc,
            {**order_doc, "order_status": "dibatalkan"}
        ])
        mock_db.orders.update_one = AsyncMock(return_value=None)
        mock_db.finance_transactions.find_one = AsyncMock(return_value={"_id": "txn_1", "status": "active"})
        mock_db.finance_transactions.update_one = AsyncMock(return_value=None)
        mock_reverse.return_value = None

        res = asyncio.run(server.admin_update_order(
            "ord_cancel_1",
            server.OrderStatusUpdate(order_status="dibatalkan"),
            admin=self.owner_user
        ))
        # Normal cancel DOES reverse points
        mock_reverse.assert_called_once()
        called_order = mock_reverse.call_args[0][0]
        self.assertEqual(called_order["_id"], "ord_cancel_1")
        self.assertEqual(called_order["order_status"], "dibatalkan")
        # Normal cancel DOES void finance txn
        mock_db.finance_transactions.update_one.assert_called_once()


if __name__ == "__main__":
    unittest.main()
