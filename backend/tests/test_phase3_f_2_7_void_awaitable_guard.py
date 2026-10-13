"""Targeted regression tests for Phase 3.F.2.7:
Async Awaitable Guard Fix & Finance Void Regression.

Covers:
- Test C1: Remaining credit blocks void (50 minted, 30 consumed -> 20 available -> void of 50 fails with HTTP 409)
- Test C2: Sufficient remaining credit permits void (50 minted, 0 consumed -> 50 available -> void succeeds with HTTP 200 and persists reversal)
- Test C3: Fully consumed credit blocks void (50 minted, 50 consumed -> 0 available -> void fails with HTTP 409)
- Test C4: Awaitable return-type regression (find_one returning an asyncio.Future is properly awaited and consumed by overdraft guard)
- Test C5: Database failure is fail-safe (lookup/lock failure halts void, payment remains recorded)
- Test C6: Repeat void attempt on already-voided payment is rejected without duplicate reversal
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from fastapi import HTTPException
import pymongo
import pymongo.errors

from server import (
    admin_void_order_payment,
    PaymentVoidInput,
)


class TestPhase3F27VoidAwaitableGuard(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.admin_owner = {
            "id": "admin_owner_01",
            "name": "Owner Sogil",
            "role": "owner",
            "permissions": {"manage_orders": True, "access_finance": True},
        }

        self.mock_session = AsyncMock()
        self.mock_session.__aenter__.return_value = self.mock_session
        self.mock_session.__aexit__.return_value = None
        self.mock_session.start_transaction = MagicMock()
        self.mock_session.start_transaction.return_value.__aenter__ = AsyncMock(return_value=self.mock_session)
        self.mock_session.start_transaction.return_value.__aexit__ = AsyncMock(return_value=None)

        self.mock_client = MagicMock()
        self.mock_client.start_session = AsyncMock(return_value=self.mock_session)

        self.order_id = str(ObjectId())
        self.payment_id = str(ObjectId())
        self.customer_id = str(ObjectId())
        self.finance_txn_id = str(ObjectId())

        self.base_order = {
            "_id": ObjectId(self.order_id),
            "order_number": "ORD-TEST-001",
            "customer_id": self.customer_id,
            "order_status": "diproses",
            "total_le": 100.0,
            "currency": "EGP",
        }

        self.base_payment = {
            "_id": ObjectId(self.payment_id),
            "payment_number": "PAY-TEST-001",
            "order_id": self.order_id,
            "order_number": "ORD-TEST-001",
            "amount_le": 150.0,
            "currency": "EGP",
            "status": "recorded",
            "finance_transaction_id": self.finance_txn_id,
        }

    # -------------------------------------------------------------------------
    # Test C1: Remaining credit blocks void (50 minted, 30 consumed -> 20 remain)
    # -------------------------------------------------------------------------
    @patch("server.client")
    @patch("server.db")
    async def test_c1_remaining_credit_blocks_void(self, mock_db, mock_client):
        mock_client.start_session = AsyncMock(return_value=self.mock_session)
        mock_db.orders.find_one = AsyncMock(return_value=self.base_order)
        mock_db.payments.find_one = AsyncMock(return_value=dict(self.base_payment))
        mock_db.customers.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
        mock_db.payments.update_one = AsyncMock()
        mock_db.finance_transactions.update_one = AsyncMock()

        # Simulated Motor Future returning credit_minted event (+50.0 EGP)
        cce_doc = {
            "_id": ObjectId(),
            "event_number": "CCE-MINT-001",
            "event_type": "credit_minted",
            "customer_id": self.customer_id,
            "source_payment_id": self.payment_id,
            "currency": "EGP",
            "signed_amount": 50.0,
        }
        fut_cce = asyncio.Future()
        fut_cce.set_result(cce_doc)
        mock_db.customer_credit_events.find_one = MagicMock(return_value=fut_cce)

        # Mock customer credit balance aggregation: remaining is 20.0 EGP
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[{"_id": None, "total": 20.0}])
        mock_db.customer_credit_events.aggregate.return_value = mock_cursor

        payload = PaymentVoidInput(reason="Customer requested cancellation")

        with self.assertRaises(HTTPException) as ctx:
            await admin_void_order_payment(
                self.order_id, self.payment_id, payload, self.admin_owner
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("Konflik saldo", ctx.exception.detail)
        # Payment must NOT be marked voided
        mock_db.payments.update_one.assert_not_called()
        mock_db.finance_transactions.update_one.assert_not_called()

    # -------------------------------------------------------------------------
    # Test C2: Sufficient remaining credit permits void (50 minted, 0 consumed)
    # -------------------------------------------------------------------------
    @patch("server.compute_order_payment_summary")
    @patch("server.generate_credit_event_number")
    @patch("server.client")
    @patch("server.db")
    async def test_c2_sufficient_remaining_credit_permits_void(
        self, mock_db, mock_client, mock_gen_num, mock_summary
    ):
        mock_client.start_session = AsyncMock(return_value=self.mock_session)
        mock_gen_num.return_value = "CCE-REV-001"
        mock_summary.return_value = {
            "payment_status": "belum_dibayar",
            "paid_amount_le": 0.0,
            "outstanding_amount_le": 100.0,
        }

        mock_db.orders.find_one = AsyncMock(return_value=self.base_order)
        mock_db.orders.update_one = AsyncMock()
        mock_db.payments.find_one = AsyncMock(side_effect=[
            dict(self.base_payment),  # Pre-void check
            dict(self.base_payment, status="voided")  # Final return
        ])
        mock_db.customers.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
        mock_db.payments.update_one = AsyncMock()
        mock_db.finance_transactions.update_one = AsyncMock()

        # Simulated Motor Future returning credit_minted event (+50.0 EGP)
        cce_doc = {
            "_id": ObjectId(),
            "event_number": "CCE-MINT-001",
            "event_type": "credit_minted",
            "customer_id": self.customer_id,
            "source_payment_id": self.payment_id,
            "currency": "EGP",
            "signed_amount": 50.0,
        }
        fut_cce = asyncio.Future()
        fut_cce.set_result(cce_doc)
        mock_db.customer_credit_events.find_one = MagicMock(return_value=fut_cce)

        # Insertion future for reversal event
        fut_insert = asyncio.Future()
        fut_insert.set_result(MagicMock(inserted_id=ObjectId()))
        mock_db.customer_credit_events.insert_one = MagicMock(return_value=fut_insert)

        # Customer holds full 50.0 EGP balance
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[{"_id": None, "total": 50.0}])
        mock_db.customer_credit_events.aggregate.return_value = mock_cursor

        payload = PaymentVoidInput(reason="Valid return within return window")
        res = await admin_void_order_payment(
            self.order_id, self.payment_id, payload, self.admin_owner
        )

        self.assertEqual(res["status"], "voided")
        mock_db.payments.update_one.assert_called_once()
        mock_db.finance_transactions.update_one.assert_called_once()
        # Ensure reversal event was inserted with signed_amount = -50.0
        mock_db.customer_credit_events.insert_one.assert_called_once()
        inserted_rev = mock_db.customer_credit_events.insert_one.call_args[0][0]
        self.assertEqual(inserted_rev["event_type"], "credit_reversed")
        self.assertEqual(inserted_rev["signed_amount"], -50.0)

    # -------------------------------------------------------------------------
    # Test C3: Fully consumed credit blocks void (50 minted, 50 consumed -> 0 left)
    # -------------------------------------------------------------------------
    @patch("server.client")
    @patch("server.db")
    async def test_c3_fully_consumed_credit_blocks_void(self, mock_db, mock_client):
        mock_client.start_session = AsyncMock(return_value=self.mock_session)
        mock_db.orders.find_one = AsyncMock(return_value=self.base_order)
        mock_db.payments.find_one = AsyncMock(return_value=dict(self.base_payment))
        mock_db.customers.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
        mock_db.payments.update_one = AsyncMock()

        cce_doc = {
            "_id": ObjectId(),
            "event_number": "CCE-MINT-001",
            "event_type": "credit_minted",
            "customer_id": self.customer_id,
            "source_payment_id": self.payment_id,
            "currency": "EGP",
            "signed_amount": 50.0,
        }
        fut_cce = asyncio.Future()
        fut_cce.set_result(cce_doc)
        mock_db.customer_credit_events.find_one = MagicMock(return_value=fut_cce)

        # Balance is 0.0 EGP
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[{"_id": None, "total": 0.0}])
        mock_db.customer_credit_events.aggregate.return_value = mock_cursor

        payload = PaymentVoidInput(reason="Void attempt after credit fully spent")

        with self.assertRaises(HTTPException) as ctx:
            await admin_void_order_payment(
                self.order_id, self.payment_id, payload, self.admin_owner
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("Konflik saldo", ctx.exception.detail)
        mock_db.payments.update_one.assert_not_called()

    # -------------------------------------------------------------------------
    # Test C4: Awaitable return-type regression (Future vs native Coroutine)
    # -------------------------------------------------------------------------
    @patch("server.client")
    @patch("server.db")
    async def test_c4_awaitable_return_type_regression(self, mock_db, mock_client):
        """Verifies that an asyncio.Future (which satisfies inspect.isawaitable but NOT
        asyncio.iscoroutine) is properly awaited by admin_void_order_payment."""
        mock_client.start_session = AsyncMock(return_value=self.mock_session)
        mock_db.orders.find_one = AsyncMock(return_value=self.base_order)
        mock_db.payments.find_one = AsyncMock(return_value=dict(self.base_payment))
        mock_db.customers.update_one = AsyncMock(return_value=MagicMock(matched_count=1))

        # Explicitly construct an _asyncio.Future to emulate Motor
        fut = asyncio.Future()
        fut.set_result({
            "_id": ObjectId(),
            "event_number": "CCE-MINT-FUT",
            "event_type": "credit_minted",
            "customer_id": self.customer_id,
            "source_payment_id": self.payment_id,
            "currency": "EGP",
            "signed_amount": 100.0,
        })

        self.assertFalse(asyncio.iscoroutine(fut))
        self.assertTrue(hasattr(fut, "__await__"))

        mock_db.customer_credit_events.find_one = MagicMock(return_value=fut)

        # Balance insufficient (50 < 100)
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[{"_id": None, "total": 50.0}])
        mock_db.customer_credit_events.aggregate.return_value = mock_cursor

        payload = PaymentVoidInput(reason="Testing Future awaitability")

        # Because inspect.isawaitable recognizes the Future, the overdraft guard runs and raises 409
        with self.assertRaises(HTTPException) as ctx:
            await admin_void_order_payment(
                self.order_id, self.payment_id, payload, self.admin_owner
            )

        self.assertEqual(ctx.exception.status_code, 409)

    # -------------------------------------------------------------------------
    # Test C5: Database failure is fail-safe
    # -------------------------------------------------------------------------
    @patch("server.client")
    @patch("server.db")
    async def test_c5_database_failure_is_failsafe(self, mock_db, mock_client):
        mock_client.start_session = AsyncMock(return_value=self.mock_session)
        mock_db.orders.find_one = AsyncMock(return_value=self.base_order)
        mock_db.payments.find_one = AsyncMock(return_value=dict(self.base_payment))

        # Database raises error during credit events lookup
        fut_err = asyncio.Future()
        fut_err.set_exception(pymongo.errors.ConnectionFailure("Simulated DB failure"))
        mock_db.customer_credit_events.find_one = MagicMock(return_value=fut_err)

        payload = PaymentVoidInput(reason="Void during DB failure")

        with self.assertRaises(pymongo.errors.ConnectionFailure):
            await admin_void_order_payment(
                self.order_id, self.payment_id, payload, self.admin_owner
            )

        # Zero payment mutations allowed
        mock_db.payments.update_one.assert_not_called()

    # -------------------------------------------------------------------------
    # Test C6: Idempotent retry on already-voided payment is rejected cleanly
    # -------------------------------------------------------------------------
    @patch("server.client")
    @patch("server.db")
    async def test_c6_repeat_void_attempt_rejected(self, mock_db, mock_client):
        mock_db.orders.find_one = AsyncMock(return_value=self.base_order)
        # Payment already voided
        already_voided = dict(self.base_payment, status="voided", void_reason="Initial void")
        mock_db.payments.find_one = AsyncMock(return_value=already_voided)

        payload = PaymentVoidInput(reason="Second void attempt")

        with self.assertRaises(HTTPException) as ctx:
            await admin_void_order_payment(
                self.order_id, self.payment_id, payload, self.admin_owner
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("sudah dibatalkan sebelumnya", ctx.exception.detail)
        # Session should not even start
        mock_client.start_session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
