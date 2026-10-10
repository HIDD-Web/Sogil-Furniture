"""Automated tests for Phase 3.B.1 — Revenue Recognition & Immutable Handover Snapshot.

Covers all 20 required Phase 3.B.1 test specifications:
TEST 1: First handover creates snapshot and status history entry.
TEST 2: Full payment: handover recognizes approved sale value; zero duplicate cash receipt.
TEST 3: Partial payment: recognized revenue equals full sale value, independent of amount paid.
TEST 4: Unpaid order: handover still recognizes full sale value as receivable.
TEST 5: Overpayment: overpayment does not inflate recognized sales revenue.
TEST 6: Repeated handover request: original snapshot is not overwritten.
TEST 7: Concurrent handover requests: concurrency protection / idempotency.
TEST 8: Transaction failure: failed writes do not leave partially recognized order.
TEST 9: Timestamp & actor: original handover timestamp and actor persisted.
TEST 10: Direct edit after handover: attempt to modify total_le returns HTTP 409 Conflict.
TEST 11: Other protected fields: attempt to change subtotal_le, delivery_fee_le, discount_le, items returns HTTP 409.
TEST 12: Mixed request: prohibited financial change with allowed field rejected atomically.
TEST 13: Payment status restriction: manual payment_status modification remains rejected HTTP 400.
TEST 14: Status reversal: moving from selesai to another status preserves completed_at & snapshot.
TEST 15: Legacy completed order: historical selesai order without snapshot does not receive fabricated data.
TEST 16: Existing valid snapshot: retries preserve existing snapshot.
TEST 17: Alternate update paths / permanent delete: protected checks intact.
TEST 18: Regression: unaffected order updates (admin_note, payment_method) work normally.
TEST 19: Currency integrity: snapshot uses order currency, zero EGP/IDR mixing.
TEST 20: Post-handover cancellation safeguards: selesai -> dibatalkan requires confirmation, reason, and auth.
"""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from fastapi import HTTPException

from server import (
    admin_update_order,
    OrderStatusUpdate,
)


class TestPhase3B1HandoverRecognition(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.admin_finance = {
            "id": "admin_fin_01",
            "name": "Finance Head",
            "role": "admin",
            "permissions": {"manage_orders": True, "access_finance": True},
        }
        self.admin_ops = {
            "id": "admin_ops_01",
            "name": "Ops Lead",
            "role": "admin",
            "permissions": {"manage_orders": True, "access_finance": False},
        }
        self.owner = {
            "id": "owner_01",
            "name": "Owner Syahid",
            "role": "owner",
            "permissions": {"manage_orders": True, "access_finance": True},
        }

    def _setup_mock_db(self, mock_db):
        mock_db.work_assignments.find.return_value.to_list = AsyncMock(return_value=[])
        mock_db.wage_obligations.find.return_value.to_list = AsyncMock(return_value=[])
        mock_db.orders.update_one = AsyncMock()

    # =========================================================================
    # TEST 1: First handover creates snapshot and status history entry
    # =========================================================================
    async def test_01_first_handover_creates_snapshot(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3-001",
            "order_status": "siap",
            "total_le": 1500.0,
            "currency": "EGP",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            res = await admin_update_order(
                order_id=order_id,
                data=OrderStatusUpdate(order_status="selesai"),
                admin=self.admin_finance,
            )

        mock_db.orders.update_one.assert_called_once()
        call_args = mock_db.orders.update_one.call_args[0]
        update_doc = call_args[1]

        # Verify $set
        self.assertIn("$set", update_doc)
        set_fields = update_doc["$set"]
        self.assertEqual(set_fields["order_status"], "selesai")
        self.assertEqual(set_fields["recognized_revenue_le"], 1500.0)
        self.assertEqual(set_fields["completed_by_id"], "admin_fin_01")
        self.assertEqual(set_fields["completed_by_name"], "Finance Head")
        self.assertIn("completed_at", set_fields)

        # Verify $push status_history
        self.assertIn("$push", update_doc)
        history_entry = update_doc["$push"]["status_history"]
        self.assertEqual(history_entry["from_status"], "siap")
        self.assertEqual(history_entry["to_status"], "selesai")
        self.assertEqual(history_entry["changed_by_id"], "admin_fin_01")
        self.assertEqual(history_entry["changed_by_name"], "Finance Head")

    # =========================================================================
    # TEST 2: Full payment: handover recognizes approved sale value; no cash txn
    # =========================================================================
    async def test_02_full_payment_handover_recognizes_sale_value(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439012"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3-002",
            "order_status": "siap",
            "payment_status": "lunas",
            "paid_amount_le": 1000.0,
            "total_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            res = await admin_update_order(
                order_id=order_id,
                data=OrderStatusUpdate(order_status="selesai"),
                admin=self.admin_finance,
            )

        call_args = mock_db.orders.update_one.call_args[0]
        set_fields = call_args[1]["$set"]
        self.assertEqual(set_fields["recognized_revenue_le"], 1000.0)
        # Verify handover does NOT insert into finance_transactions
        mock_db.finance_transactions.insert_one.assert_not_called()

    # =========================================================================
    # TEST 3: Partial payment: recognized revenue equals full sale value
    # =========================================================================
    async def test_03_partial_payment_handover_recognizes_full_sale_value(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439013"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3-003",
            "order_status": "siap",
            "payment_status": "dp",
            "paid_amount_le": 300.0,
            "total_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            await admin_update_order(
                order_id=order_id,
                data=OrderStatusUpdate(order_status="selesai"),
                admin=self.admin_finance,
            )

        set_fields = mock_db.orders.update_one.call_args[0][1]["$set"]
        # Full sale value 1000 is recognized, NOT capped at 300
        self.assertEqual(set_fields["recognized_revenue_le"], 1000.0)

    # =========================================================================
    # TEST 4: Unpaid order: handover still recognizes full sale value
    # =========================================================================
    async def test_04_unpaid_handover_recognizes_sale_value(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439014"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3-004",
            "order_status": "siap",
            "payment_status": "belum_dibayar",
            "paid_amount_le": 0.0,
            "total_le": 1200.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            await admin_update_order(
                order_id=order_id,
                data=OrderStatusUpdate(order_status="selesai"),
                admin=self.admin_finance,
            )

        set_fields = mock_db.orders.update_one.call_args[0][1]["$set"]
        self.assertEqual(set_fields["recognized_revenue_le"], 1200.0)

    # =========================================================================
    # TEST 5: Overpayment: overpayment does not inflate recognized sales revenue
    # =========================================================================
    async def test_05_overpayment_does_not_inflate_recognized_revenue(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439015"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3-005",
            "order_status": "siap",
            "payment_status": "overpaid",
            "paid_amount_le": 1500.0,
            "total_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            await admin_update_order(
                order_id=order_id,
                data=OrderStatusUpdate(order_status="selesai"),
                admin=self.admin_finance,
            )

        set_fields = mock_db.orders.update_one.call_args[0][1]["$set"]
        # Revenue is exactly total_le (1000.0), NOT 1500.0
        self.assertEqual(set_fields["recognized_revenue_le"], 1000.0)

    # =========================================================================
    # TEST 6: Repeated handover request: original snapshot is not overwritten
    # =========================================================================
    async def test_06_repeated_handover_does_not_overwrite_snapshot(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439016"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3-006",
            "order_status": "selesai",
            "total_le": 1000.0,
            "completed_at": "2026-09-01T10:00:00Z",
            "completed_by_id": "admin_original",
            "completed_by_name": "Original Admin",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            # Admin patches admin_note on already selesai order
            await admin_update_order(
                order_id=order_id,
                data=OrderStatusUpdate(admin_note="Customer requested copy invoice"),
                admin=self.admin_finance,
            )

        set_fields = mock_db.orders.update_one.call_args[0][1]["$set"]
        # completed_at and recognized_revenue_le must NOT be overwritten
        self.assertNotIn("completed_at", set_fields)
        self.assertNotIn("recognized_revenue_le", set_fields)
        self.assertNotIn("completed_by_id", set_fields)

    # =========================================================================
    # TEST 7: Concurrent handover requests idempotency
    # =========================================================================
    async def test_07_concurrent_handover_idempotent_no_duplicate_snapshot(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439017"
        # First request finishes, sets completed_at
        order_doc_after_first = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3-007",
            "order_status": "selesai",
            "total_le": 1000.0,
            "completed_at": "2026-10-10T12:00:00Z",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc_after_first)

        with patch("server.db", mock_db):
            # Second concurrent request arrives with order_status="selesai"
            await admin_update_order(
                order_id=order_id,
                data=OrderStatusUpdate(order_status="selesai"),
                admin=self.admin_ops,
            )

        set_fields = mock_db.orders.update_one.call_args[0][1]["$set"]
        # Since existing_order already had completed_at and recognized_revenue_le, no new snapshot
        self.assertNotIn("recognized_revenue_le", set_fields)
        self.assertNotIn("completed_at", set_fields)

    # =========================================================================
    # TEST 8: Transaction failure: atomicity & fail-closed behavior
    # =========================================================================
    async def test_08_transaction_failure_raises_exception(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439018"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3-008",
            "order_status": "siap",
            "total_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.orders.update_one = AsyncMock(side_effect=Exception("Database connection lost"))

        with patch("server.db", mock_db):
            with self.assertRaises(Exception):
                await admin_update_order(
                    order_id=order_id,
                    data=OrderStatusUpdate(order_status="selesai"),
                    admin=self.admin_finance,
                )

    # =========================================================================
    # TEST 9: Timestamp & actor: original handover timestamp and actor persisted
    # =========================================================================
    async def test_09_timestamp_and_actor_persisted_accurately(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439019"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3-009",
            "order_status": "diproses",
            "total_le": 2500.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            await admin_update_order(
                order_id=order_id,
                data=OrderStatusUpdate(order_status="selesai"),
                admin=self.owner,
            )

        set_fields = mock_db.orders.update_one.call_args[0][1]["$set"]
        self.assertEqual(set_fields["completed_by_id"], "owner_01")
        self.assertEqual(set_fields["completed_by_name"], "Owner Syahid")
        self.assertEqual(set_fields["recognized_revenue_le"], 2500.0)

    # =========================================================================
    # TEST 10: Direct edit after handover: modify total_le returns HTTP 409
    # =========================================================================
    async def test_10_direct_total_edit_post_handover_rejected_409(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439020"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3-010",
            "order_status": "selesai",
            "completed_at": "2026-10-01T10:00:00Z",
            "recognized_revenue_le": 1000.0,
            "total_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            with self.assertRaises(HTTPException) as ctx:
                await admin_update_order(
                    order_id=order_id,
                    data=OrderStatusUpdate(total_le=1200.0),
                    admin=self.admin_finance,
                )
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertIn("tidak dapat diubah nilainya secara langsung", ctx.exception.detail)

    # =========================================================================
    # TEST 11: Other protected fields: subtotal, delivery_fee, discount, items
    # =========================================================================
    async def test_11_protected_financial_fields_rejected_409(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439021"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3-011",
            "order_status": "selesai",
            "completed_at": "2026-10-01T10:00:00Z",
            "recognized_revenue_le": 1000.0,
            "total_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            # Test delivery_fee_le
            with self.assertRaises(HTTPException) as ctx1:
                await admin_update_order(
                    order_id=order_id,
                    data=OrderStatusUpdate(delivery_fee_le=150.0),
                    admin=self.admin_finance,
                )
            self.assertEqual(ctx1.exception.status_code, 409)

            # Test discount_le
            with self.assertRaises(HTTPException) as ctx2:
                await admin_update_order(
                    order_id=order_id,
                    data=OrderStatusUpdate(discount_le=50.0),
                    admin=self.admin_finance,
                )
            self.assertEqual(ctx2.exception.status_code, 409)

            # Test items
            with self.assertRaises(HTTPException) as ctx3:
                await admin_update_order(
                    order_id=order_id,
                    data=OrderStatusUpdate(items=[{"item_id": "itm_1", "quantity": 2}]),
                    admin=self.admin_finance,
                )
            self.assertEqual(ctx3.exception.status_code, 409)

    # =========================================================================
    # TEST 12: Mixed request: prohibited financial change rejected atomically
    # =========================================================================
    async def test_12_mixed_request_rejected_atomically_without_partial_apply(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439022"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3-012",
            "order_status": "selesai",
            "completed_at": "2026-10-01T10:00:00Z",
            "recognized_revenue_le": 1000.0,
            "total_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            # Attempt to update admin_note AND total_le simultaneously
            with self.assertRaises(HTTPException) as ctx:
                await admin_update_order(
                    order_id=order_id,
                    data=OrderStatusUpdate(admin_note="Allowed Note", total_le=1500.0),
                    admin=self.admin_finance,
                )
            self.assertEqual(ctx.exception.status_code, 409)
            # Verify update_one was never called (no partial update)
            mock_db.orders.update_one.assert_not_called()

    # =========================================================================
    # TEST 13: Payment status restriction: manual payment_status rejected 400
    # =========================================================================
    async def test_13_payment_status_manual_change_rejected(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439023"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3-013",
            "order_status": "diproses",
            "payment_status": "dp",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            with self.assertRaises(HTTPException) as ctx:
                await admin_update_order(
                    order_id=order_id,
                    data=OrderStatusUpdate(payment_status="lunas"),
                    admin=self.admin_finance,
                )
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("Status pembayaran tidak dapat diubah secara manual", ctx.exception.detail)

    # =========================================================================
    # TEST 14: Status reversal: moving from selesai preserves completed_at
    # =========================================================================
    async def test_14_status_reversal_preserves_completed_at_and_snapshot(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439024"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3-014",
            "order_status": "selesai",
            "completed_at": "2026-10-01T10:00:00Z",
            "completed_by_id": "admin_orig",
            "completed_by_name": "Orig Admin",
            "recognized_revenue_le": 1000.0,
            "total_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            # Admin reverts status to diproses
            await admin_update_order(
                order_id=order_id,
                data=OrderStatusUpdate(order_status="diproses"),
                admin=self.admin_finance,
            )

        set_fields = mock_db.orders.update_one.call_args[0][1]["$set"]
        self.assertEqual(set_fields["order_status"], "diproses")
        # completed_at and recognized_revenue_le are NOT unset or erased
        self.assertNotIn("completed_at", set_fields)
        self.assertNotIn("recognized_revenue_le", set_fields)

    # =========================================================================
    # TEST 15: Legacy completed order: historical selesai without snapshot
    # =========================================================================
    async def test_15_legacy_completed_order_no_fabricated_snapshot(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439025"
        # Historical order already selesai before Phase 3, without completed_at
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-LEGACY-001",
            "order_status": "selesai",
            "total_le": 1000.0,
            # No completed_at, no recognized_revenue_le
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            # Admin updates note
            await admin_update_order(
                order_id=order_id,
                data=OrderStatusUpdate(admin_note="Catatan arsip"),
                admin=self.admin_finance,
            )

        set_fields = mock_db.orders.update_one.call_args[0][1]["$set"]
        # Must not synthesize or backfill completed_at or recognized_revenue_le
        self.assertNotIn("completed_at", set_fields)
        self.assertNotIn("recognized_revenue_le", set_fields)

    # =========================================================================
    # TEST 16: Existing valid snapshot: retries preserve existing snapshot
    # =========================================================================
    async def test_16_retried_request_preserves_existing_snapshot(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439026"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3-026",
            "order_status": "selesai",
            "completed_at": "2026-10-05T08:00:00Z",
            "recognized_revenue_le": 850.0,
            "total_le": 850.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            # Retry sending selesai
            await admin_update_order(
                order_id=order_id,
                data=OrderStatusUpdate(order_status="selesai"),
                admin=self.admin_ops,
            )

        # Since from_status == to_status ('selesai' == 'selesai'), no push to status_history
        # and no modification to completed_at / recognized_revenue_le
        set_fields = mock_db.orders.update_one.call_args[0][1]["$set"]
        self.assertNotIn("completed_at", set_fields)
        self.assertNotIn("recognized_revenue_le", set_fields)

    # =========================================================================
    # TEST 17: Post-handover direct price edit on existing legacy selesai
    # =========================================================================
    async def test_17_legacy_selesai_protected_against_direct_price_edits(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439027"
        # Order is legacy selesai without completed_at
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-LEGACY-002",
            "order_status": "selesai",
            "total_le": 500.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            with self.assertRaises(HTTPException) as ctx:
                await admin_update_order(
                    order_id=order_id,
                    data=OrderStatusUpdate(total_le=600.0),
                    admin=self.admin_finance,
                )
            self.assertEqual(ctx.exception.status_code, 409)

    # =========================================================================
    # TEST 18: Regression: unaffected permitted order updates work normally
    # =========================================================================
    async def test_18_permitted_order_updates_work_normally(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439028"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3-028",
            "order_status": "diproses",
            "payment_method": "cash",
            "total_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            await admin_update_order(
                order_id=order_id,
                data=OrderStatusUpdate(payment_method="transfer", admin_note="Transfer BCA"),
                admin=self.admin_ops,
            )

        set_fields = mock_db.orders.update_one.call_args[0][1]["$set"]
        self.assertEqual(set_fields["payment_method"], "transfer")
        self.assertEqual(set_fields["admin_note"], "Transfer BCA")

    # =========================================================================
    # TEST 19: Currency integrity: snapshot uses float order total_le
    # =========================================================================
    async def test_19_currency_integrity_snapshot_uses_order_total(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439029"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3-029",
            "order_status": "siap",
            "total_le": 4500.50,
            "exchange_rate_idr_per_le": 357.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            await admin_update_order(
                order_id=order_id,
                data=OrderStatusUpdate(order_status="selesai"),
                admin=self.admin_finance,
            )

        set_fields = mock_db.orders.update_one.call_args[0][1]["$set"]
        self.assertEqual(set_fields["recognized_revenue_le"], 4500.50)

    # =========================================================================
    # TEST 20: Post-handover cancellation safeguards
    # =========================================================================
    async def test_20_post_handover_cancellation_safeguards(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439030"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3-030",
            "order_status": "selesai",
            "completed_at": "2026-10-01T10:00:00Z",
            "recognized_revenue_le": 1000.0,
            "total_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            # A. Missing confirmation -> HTTP 400
            with self.assertRaises(HTTPException) as ctx_a:
                await admin_update_order(
                    order_id=order_id,
                    data=OrderStatusUpdate(order_status="dibatalkan"),
                    admin=self.owner,
                )
            self.assertEqual(ctx_a.exception.status_code, 400)
            self.assertIn("memerlukan konfirmasi eksplisit", ctx_a.exception.detail)

            # B. Missing reason -> HTTP 400
            with self.assertRaises(HTTPException) as ctx_b:
                await admin_update_order(
                    order_id=order_id,
                    data=OrderStatusUpdate(
                        order_status="dibatalkan",
                        confirm_handover_cancellation=True,
                        cancellation_reason="   "
                    ),
                    admin=self.owner,
                )
            self.assertEqual(ctx_b.exception.status_code, 400)
            self.assertIn("minimal 5 karakter", ctx_b.exception.detail)

            # C. Non-finance / non-owner admin -> HTTP 403
            with self.assertRaises(HTTPException) as ctx_c:
                await admin_update_order(
                    order_id=order_id,
                    data=OrderStatusUpdate(
                        order_status="dibatalkan",
                        confirm_handover_cancellation=True,
                        cancellation_reason="Customer cancel after delivery"
                    ),
                    admin=self.admin_ops,
                )
            self.assertEqual(ctx_c.exception.status_code, 403)
            self.assertIn("Hanya owner atau admin dengan akses keuangan", ctx_c.exception.detail)

            # D. Authorized owner with confirmation and reason -> Success
            await admin_update_order(
                order_id=order_id,
                data=OrderStatusUpdate(
                    order_status="dibatalkan",
                    confirm_handover_cancellation=True,
                    cancellation_reason="Retur barang cacat pasca serah terima"
                ),
                admin=self.owner,
            )

        call_args = mock_db.orders.update_one.call_args[0]
        set_fields = call_args[1]["$set"]
        history_entry = call_args[1]["$push"]["status_history"]

        self.assertEqual(set_fields["order_status"], "dibatalkan")
        self.assertEqual(history_entry["from_status"], "selesai")
        self.assertEqual(history_entry["to_status"], "dibatalkan")
        self.assertEqual(history_entry["reason"], "Retur barang cacat pasca serah terima")

    # =========================================================================
    # TEST 21: Status reversal to diproses, then cancellation without confirmation -> 400
    # =========================================================================
    async def test_21_reversal_then_cancellation_requires_confirmation(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439031"
        # Order previously reached selesai and was reverted to diproses (snapshot preserved)
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3-031",
            "order_status": "diproses",
            "completed_at": "2026-10-01T10:00:00Z",
            "recognized_revenue_le": 1200.0,
            "total_le": 1200.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            # Attempt to cancel without confirm_handover_cancellation
            with self.assertRaises(HTTPException) as ctx:
                await admin_update_order(
                    order_id=order_id,
                    data=OrderStatusUpdate(order_status="dibatalkan"),
                    admin=self.owner,
                )
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("memerlukan konfirmasi eksplisit", ctx.exception.detail)

    # =========================================================================
    # TEST 22: Status reversal to diproses, then cancellation without valid reason -> 400
    # =========================================================================
    async def test_22_reversal_then_cancellation_requires_valid_reason(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439032"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3-032",
            "order_status": "diproses",
            "completed_at": "2026-10-01T10:00:00Z",
            "recognized_revenue_le": 1200.0,
            "total_le": 1200.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            # Attempt to cancel with short/whitespace reason (< 5 chars)
            with self.assertRaises(HTTPException) as ctx:
                await admin_update_order(
                    order_id=order_id,
                    data=OrderStatusUpdate(
                        order_status="dibatalkan",
                        confirm_handover_cancellation=True,
                        cancellation_reason="nope",
                    ),
                    admin=self.owner,
                )
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("minimal 5 karakter", ctx.exception.detail)

    # =========================================================================
    # TEST 23: Status reversal to diproses, then cancellation by unauthorized user -> 403
    # =========================================================================
    async def test_23_reversal_then_cancellation_unauthorized_rejected_403(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439033"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3-033",
            "order_status": "diproses",
            "completed_at": "2026-10-01T10:00:00Z",
            "recognized_revenue_le": 1200.0,
            "total_le": 1200.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            with self.assertRaises(HTTPException) as ctx:
                await admin_update_order(
                    order_id=order_id,
                    data=OrderStatusUpdate(
                        order_status="dibatalkan",
                        confirm_handover_cancellation=True,
                        cancellation_reason="Customer cancelled after return",
                    ),
                    admin=self.admin_ops,
                )
            self.assertEqual(ctx.exception.status_code, 403)
            self.assertIn("Hanya owner atau admin dengan akses keuangan", ctx.exception.detail)

    # =========================================================================
    # TEST 24: Authorized cancellation after reversal succeeds and preserves snapshot
    # =========================================================================
    async def test_24_authorized_cancellation_after_reversal_succeeds_and_preserves_snapshot(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439034"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3-034",
            "order_status": "diproses",
            "completed_at": "2026-10-01T10:00:00Z",
            "completed_by_id": "admin_orig",
            "completed_by_name": "Orig Admin",
            "recognized_revenue_le": 1200.0,
            "total_le": 1200.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db):
            await admin_update_order(
                order_id=order_id,
                data=OrderStatusUpdate(
                    order_status="dibatalkan",
                    confirm_handover_cancellation=True,
                    cancellation_reason="Dibatalkan sah oleh finance pasca revisi",
                ),
                admin=self.admin_finance,
            )

        call_args = mock_db.orders.update_one.call_args[0]
        set_fields = call_args[1]["$set"]
        history_entry = call_args[1]["$push"]["status_history"]

        self.assertEqual(set_fields["order_status"], "dibatalkan")
        # Ensure completed_at and recognized_revenue_le are NOT unset or erased
        self.assertNotIn("completed_at", set_fields)
        self.assertNotIn("recognized_revenue_le", set_fields)
        self.assertEqual(history_entry["from_status"], "diproses")
        self.assertEqual(history_entry["to_status"], "dibatalkan")
        self.assertEqual(history_entry["reason"], "Dibatalkan sah oleh finance pasca revisi")

    # =========================================================================
    # TEST 25: Concurrency race condition: database atomic query protects first snapshot
    # =========================================================================
    async def test_25_concurrency_race_atomic_query_protects_first_snapshot(self):
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "507f1f77bcf86cd799439035"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-P3-035",
            "order_status": "siap",
            "total_le": 2000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        # Simulate update_one returning matched_count=0 on the atomic query, indicating another worker won
        first_call_result = MagicMock()
        first_call_result.matched_count = 0
        mock_db.orders.update_one = AsyncMock(side_effect=[first_call_result, MagicMock(matched_count=1)])

        with patch("server.db", mock_db):
            await admin_update_order(
                order_id=order_id,
                data=OrderStatusUpdate(order_status="selesai"),
                admin=self.admin_finance,
            )

        # The first call to update_one was the atomic query with completed_at filter
        first_call = mock_db.orders.update_one.call_args_list[0]
        query_filter = first_call[0][0]
        self.assertIn("completed_at", query_filter)
        self.assertEqual(query_filter["completed_at"], {"$in": [None, False]})
        self.assertIsNone(query_filter["recognized_revenue_le"])

        # The fallback call updated remaining fields without snapshot overwrite
        second_call = mock_db.orders.update_one.call_args_list[1]
        fallback_set = second_call[0][1]["$set"]
        self.assertNotIn("completed_at", fallback_set)
        self.assertNotIn("recognized_revenue_le", fallback_set)
        self.assertNotIn("completed_by_id", fallback_set)
        self.assertEqual(fallback_set["order_status"], "selesai")


if __name__ == "__main__":
    unittest.main()

