# backend/tests/test_phase3_finance_adjustments.py
"""
Phase 3.B.6 — Explicit Finance Adjustments Automated Test Suite
Master Test Matrix (TC-B6-01 through TC-B6-39)

Guarantees:
- B6-OD-01: Zero writes to payments, customer_credit_events, finance_transactions.
- B6-OD-02 & B6-OD-05: Positive/negative price_correction without artificial caps/secondary approvals.
- B6-OD-03: Cumulative downward adjustments capped at net recognized revenue; repeated full reversals rejected.
- B6-OD-04: Daily sequential ID format ADJ-YYYYMMDD-XXXX.
- Fail-closed multi-document transaction behavior, idempotency replay, and order serialization guard.
"""

import asyncio
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from fastapi import HTTPException, Response
from pydantic import ValidationError

from server import (
    admin_create_finance_adjustment,
    generate_adjustment_number,
    FinanceAdjustmentInput,
    clean,
)


class TestPhase3B6FinanceAdjustments(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.admin_owner = {
            "id": "admin_owner_01",
            "name": "Owner Sogil",
            "role": "owner",
            "permissions": {"manage_orders": True, "access_finance": True},
        }
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

        # Mock PyMongo client for transactions
        self.mock_session = AsyncMock()
        self.mock_session.start_transaction = MagicMock()
        self.mock_session.__aenter__ = AsyncMock(return_value=self.mock_session)
        self.mock_session.__aexit__ = AsyncMock(return_value=None)

        self.mock_client = MagicMock()
        self.mock_client.start_session = AsyncMock(return_value=self.mock_session)

    def _setup_mock_db(self, mock_db):
        mock_db.orders = MagicMock()
        mock_db.payments = MagicMock()
        mock_db.customer_credit_events = MagicMock()
        mock_db.finance_transactions = MagicMock()
        mock_db.finance_adjustments = MagicMock()
        mock_db.counters = MagicMock()

        # Default async behaviors
        mock_db.orders.find_one = AsyncMock(return_value=None)
        mock_db.orders.update_one = AsyncMock(return_value=MagicMock(matched_count=1, modified_count=1))
        mock_db.finance_adjustments.find_one = AsyncMock(return_value=None)
        mock_db.finance_adjustments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))

        # Default adjustments list is empty
        mock_adj_cursor = MagicMock()
        mock_adj_cursor.to_list = AsyncMock(return_value=[])
        mock_db.finance_adjustments.find.return_value = mock_adj_cursor

        # Default payments list is empty
        mock_pmt_cursor = MagicMock()
        mock_pmt_cursor.to_list = AsyncMock(return_value=[])
        mock_db.payments.find.return_value = mock_pmt_cursor

        # Default counter
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 1})

    # =========================================================================
    # Group A: Authorization & Role Checks (TC-01 to TC-03)
    # =========================================================================

    async def test_tc01_owner_allowed(self):
        """TC-01: Owner role is permitted to create adjustments."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-001",
            "order_status": "selesai",
            "currency": "EGP",
            "completed_at": "2026-10-10T12:00:00Z",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            res = await admin_create_finance_adjustment(
                FinanceAdjustmentInput(
                    order_id=order_id,
                    type="price_correction",
                    currency="EGP",
                    amount=-100.0,
                    reason="Diskon susulan",
                    idempotency_key="tc01_owner_key_123",
                ),
                Response(),
                self.admin_owner
            )
        self.assertEqual(res["type"], "price_correction")
        self.assertEqual(res["amount"], -100.0)

    async def test_tc02_finance_permission_allowed(self):
        """TC-02: Admin with access_finance permission is permitted."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-002",
            "order_status": "selesai",
            "currency": "EGP",
            "completed_at": "2026-10-10T12:00:00Z",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            res = await admin_create_finance_adjustment(
                FinanceAdjustmentInput(
                    order_id=order_id,
                    type="price_correction",
                    currency="EGP",
                    amount=-50.0,
                    reason="Koreksi harga",
                    idempotency_key="tc02_fin_key_123",
                ),
                Response(),
                self.admin_finance
            )
        self.assertEqual(res["amount"], -50.0)

    async def test_tc03_unauthorized_user_rejected_403(self):
        """TC-03: Staff without access_finance rejected with HTTP 403."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id="670868f123456789abcdef01",
                        type="price_correction",
                        currency="EGP",
                        amount=-50.0,
                        reason="Koreksi harga",
                        idempotency_key="tc03_unauth_key_123",
                    ),
                    Response(),
                    self.admin_ops
                )
        self.assertEqual(cm.exception.status_code, 403)
        mock_db.finance_adjustments.insert_one.assert_not_called()

    # =========================================================================
    # Group B: Input Validation (TC-04 to TC-13)
    # =========================================================================

    async def test_tc04_missing_or_blank_required_fields_rejected(self):
        """TC-04: Missing required fields fail validation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id="",
                        type="price_correction",
                        currency="EGP",
                        amount=-50.0,
                        reason="Valid reason",
                        idempotency_key="tc04_key_123",
                    ),
                    Response(),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 422)

    async def test_tc05_invalid_type_rejected(self):
        """TC-05: Invalid adjustment type rejected with 422."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id="670868f123456789abcdef01",
                        type="invalid_type",
                        currency="EGP",
                        amount=-50.0,
                        reason="Valid reason",
                        idempotency_key="tc05_key_123",
                    ),
                    Response(),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 422)

    async def test_tc06_unsupported_currency_rejected(self):
        """TC-06: Unsupported currency rejected with 422."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id="670868f123456789abcdef01",
                        type="price_correction",
                        currency="USD",
                        amount=-50.0,
                        reason="Valid reason",
                        idempotency_key="tc06_key_123",
                    ),
                    Response(),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 422)

    async def test_tc07_currency_mismatch_rejected(self):
        """TC-07: Currency mismatch between order (EGP) and payload (IDR) rejected with 422."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-007",
            "order_status": "selesai",
            "currency": "EGP",
            "completed_at": "2026-10-10T12:00:00Z",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id=order_id,
                        type="price_correction",
                        currency="IDR",
                        amount=-50.0,
                        reason="Valid reason",
                        idempotency_key="tc07_key_123",
                    ),
                    Response(),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 422)
            self.assertIn("harus sesuai dengan mata uang pesanan", cm.exception.detail)

    async def test_tc08_zero_amount_rejected(self):
        """TC-08: Zero monetary amount rejected with 422."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id="670868f123456789abcdef01",
                        type="price_correction",
                        currency="EGP",
                        amount=0.0,
                        reason="Valid reason",
                        idempotency_key="tc08_key_123",
                    ),
                    Response(),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 422)
            self.assertIn("tidak boleh nol", cm.exception.detail)

    async def test_tc09_more_than_two_decimal_places_rejected(self):
        """TC-09: Amounts with more than 2 decimal places rejected with 422."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id="670868f123456789abcdef01",
                        type="price_correction",
                        currency="EGP",
                        amount=-50.125,
                        reason="Valid reason",
                        idempotency_key="tc09_key_123",
                    ),
                    Response(),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 422)
            self.assertIn("lebih dari 2 tempat desimal", cm.exception.detail)

    async def test_tc10_invalid_reason_length_rejected(self):
        """TC-10: Reason shorter than 5 chars rejected with 422."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id="670868f123456789abcdef01",
                        type="price_correction",
                        currency="EGP",
                        amount=-50.0,
                        reason="abc",  # 3 chars
                        idempotency_key="tc10_key_123",
                    ),
                    Response(),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 422)
            self.assertIn("minimal 5 karakter", cm.exception.detail)

    async def test_tc11_invalid_idempotency_key_length_rejected(self):
        """TC-11: Idempotency key shorter than 8 chars rejected with 422."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id="670868f123456789abcdef01",
                        type="price_correction",
                        currency="EGP",
                        amount=-50.0,
                        reason="Valid reason",
                        idempotency_key="short",  # 5 chars
                    ),
                    Response(),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 422)
            self.assertIn("minimal 8 karakter", cm.exception.detail)

    async def test_tc12_wrong_sign_revenue_reversal_rejected(self):
        """TC-12: Positive amount for revenue_reversal rejected with 422."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id="670868f123456789abcdef01",
                        type="revenue_reversal",
                        currency="EGP",
                        amount=100.0,  # positive is invalid
                        reason="Valid reason",
                        idempotency_key="tc12_key_123",
                    ),
                    Response(),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 422)
            self.assertIn("harus bernilai negatif", cm.exception.detail)

    async def test_tc13_wrong_sign_return_allowance_rejected(self):
        """TC-13: Positive amount for return_allowance rejected with 422."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id="670868f123456789abcdef01",
                        type="return_allowance",
                        currency="EGP",
                        amount=200.0,  # positive is invalid
                        reason="Valid reason",
                        idempotency_key="tc13_key_123",
                    ),
                    Response(),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 422)
            self.assertIn("harus bernilai negatif", cm.exception.detail)

    # =========================================================================
    # Group C: Eligibility & Immutability (TC-14 to TC-20)
    # =========================================================================

    async def test_tc14_valid_completed_order_accepted(self):
        """TC-14: Completed order with snapshot accepted."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-014",
            "order_status": "selesai",
            "currency": "EGP",
            "completed_at": "2026-10-10T12:00:00Z",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            res = await admin_create_finance_adjustment(
                FinanceAdjustmentInput(
                    order_id=order_id,
                    type="return_allowance",
                    currency="EGP",
                    amount=-150.0,
                    reason="Cacat minor finishing",
                    idempotency_key="tc14_key_123",
                ),
                Response(),
                self.admin_finance
            )
        self.assertEqual(res["type"], "return_allowance")
        self.assertEqual(res["amount"], -150.0)

    async def test_tc15_valid_post_handover_cancelled_order_accepted(self):
        """TC-15: Post-handover cancelled order (dibatalkan with valid snapshot) accepted."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-015",
            "order_status": "dibatalkan",
            "currency": "EGP",
            "completed_at": "2026-10-10T12:00:00Z",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            res = await admin_create_finance_adjustment(
                FinanceAdjustmentInput(
                    order_id=order_id,
                    type="revenue_reversal",
                    currency="EGP",
                    amount=-1000.0,
                    reason="Pembatalan resmi setelah serah terima",
                    idempotency_key="tc15_key_123",
                ),
                Response(),
                self.admin_finance
            )
        self.assertEqual(res["type"], "revenue_reversal")
        self.assertEqual(res["amount"], -1000.0)

    async def test_tc16_in_flight_order_rejected_even_with_snapshots(self):
        """TC-16: Active in-flight order (diproses) rejected with 409 even if snapshot populated."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-016",
            "order_status": "diproses",  # in-flight
            "currency": "EGP",
            "completed_at": "2026-10-10T12:00:00Z",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id=order_id,
                        type="price_correction",
                        currency="EGP",
                        amount=-50.0,
                        reason="Koreksi harga",
                        idempotency_key="tc16_key_123",
                    ),
                    Response(),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 409)
            self.assertIn("hanya berlaku untuk pesanan yang telah serah terima", cm.exception.detail)

    async def test_tc17_missing_completed_at_rejected(self):
        """TC-17: Order with status selesai but missing completed_at rejected with 409."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-017",
            "order_status": "selesai",
            "currency": "EGP",
            "completed_at": None,
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id=order_id,
                        type="price_correction",
                        currency="EGP",
                        amount=-50.0,
                        reason="Koreksi harga",
                        idempotency_key="tc17_key_123",
                    ),
                    Response(),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 409)
            self.assertIn("tidak lengkap atau tidak valid", cm.exception.detail)

    async def test_tc18_invalid_completed_at_rejected(self):
        """TC-18: Order with empty string completed_at rejected with 409."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-018",
            "order_status": "selesai",
            "currency": "EGP",
            "completed_at": "   ",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id=order_id,
                        type="price_correction",
                        currency="EGP",
                        amount=-50.0,
                        reason="Koreksi harga",
                        idempotency_key="tc18_key_123",
                    ),
                    Response(),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 409)

    async def test_tc19_missing_or_invalid_recognized_revenue_rejected(self):
        """TC-19: Order with status selesai but missing recognized_revenue_le rejected with 409."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-019",
            "order_status": "selesai",
            "currency": "EGP",
            "completed_at": "2026-10-10T12:00:00Z",
            "recognized_revenue_le": None,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id=order_id,
                        type="price_correction",
                        currency="EGP",
                        amount=-50.0,
                        reason="Koreksi harga",
                        idempotency_key="tc19_key_123",
                    ),
                    Response(),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 409)

    async def test_tc20_original_snapshot_fields_remain_unchanged(self):
        """TC-20: Adjustment execution never overwrites completed_at or recognized_revenue_le."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-020",
            "order_status": "selesai",
            "currency": "EGP",
            "completed_at": "2026-10-10T12:00:00Z",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            await admin_create_finance_adjustment(
                FinanceAdjustmentInput(
                    order_id=order_id,
                    type="price_correction",
                    currency="EGP",
                    amount=-100.0,
                    reason="Koreksi harga",
                    idempotency_key="tc20_key_123",
                ),
                Response(),
                self.admin_finance
            )

        # Inspect update_one call on orders
        mock_db.orders.update_one.assert_called_once()
        update_args = mock_db.orders.update_one.call_args[0][1]
        self.assertIn("$set", update_args)
        set_fields = update_args["$set"]
        self.assertNotIn("completed_at", set_fields)
        self.assertNotIn("recognized_revenue_le", set_fields)
        self.assertIn("last_finance_adjustment_at", set_fields)

    # =========================================================================
    # Group D: Accounting & Adjustment Behavior (TC-21 to TC-27)
    # =========================================================================

    async def test_tc21_positive_price_correction_accepted_without_cap(self):
        """TC-21: Positive price correction (+1500 LE on 1000 LE order) accepted per B6-OD-05."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-021",
            "order_status": "selesai",
            "currency": "EGP",
            "completed_at": "2026-10-10T12:00:00Z",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            res = await admin_create_finance_adjustment(
                FinanceAdjustmentInput(
                    order_id=order_id,
                    type="price_correction",
                    currency="EGP",
                    amount=1500.0,  # 150% increase, no cap
                    reason="Permintaan custom ukiran tambahan besar",
                    idempotency_key="tc21_key_123",
                ),
                Response(),
                self.admin_finance
            )
        self.assertEqual(res["amount"], 1500.0)
        self.assertEqual(res["order_impact"]["net_adjusted_revenue_le"], 2500.0)

    async def test_tc22_negative_price_correction_within_recognized_revenue(self):
        """TC-22: Negative price correction (-300 LE on 1000 LE order) accepted."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-022",
            "order_status": "selesai",
            "currency": "EGP",
            "completed_at": "2026-10-10T12:00:00Z",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            res = await admin_create_finance_adjustment(
                FinanceAdjustmentInput(
                    order_id=order_id,
                    type="price_correction",
                    currency="EGP",
                    amount=-300.0,
                    reason="Diskon susulan",
                    idempotency_key="tc22_key_123",
                ),
                Response(),
                self.admin_finance
            )
        self.assertEqual(res["order_impact"]["net_adjusted_revenue_le"], 700.0)

    async def test_tc23_cumulative_negative_cannot_drive_revenue_below_zero(self):
        """TC-23: Negative adjustment exceeding remaining net revenue rejected with 422."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-023",
            "order_status": "selesai",
            "currency": "EGP",
            "completed_at": "2026-10-10T12:00:00Z",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        # Prior adjustment already reduced by 800 LE, remaining is 200 LE
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[{"amount": -800.0, "is_void": False}])
        mock_db.finance_adjustments.find.return_value = mock_cursor

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id=order_id,
                        type="return_allowance",
                        currency="EGP",
                        amount=-300.0,  # exceeds remaining 200 LE
                        reason="Koreksi retur",
                        idempotency_key="tc23_key_123",
                    ),
                    Response(),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 422)
            self.assertIn("melebihi sisa pendapatan", cm.exception.detail)

    async def test_tc24_downward_adjustment_at_zero_net_revenue_returns_409(self):
        """TC-24: Further downward adjustment when net revenue is already zero returns 409."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-024",
            "order_status": "dibatalkan",
            "currency": "EGP",
            "completed_at": "2026-10-10T12:00:00Z",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        # Prior adjustment already fully reversed (net revenue == 0)
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[{"amount": -1000.0, "is_void": False}])
        mock_db.finance_adjustments.find.return_value = mock_cursor

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id=order_id,
                        type="revenue_reversal",
                        currency="EGP",
                        amount=-50.0,
                        reason="Pembalikan kedua",
                        idempotency_key="tc24_key_123",
                    ),
                    Response(),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 409)
            self.assertIn("telah sepenuhnya dibalikkan", cm.exception.detail)

    async def test_tc25_multiple_valid_adjustments_supported(self):
        """TC-25: Multiple valid adjustments correctly accumulate."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-025",
            "order_status": "selesai",
            "currency": "EGP",
            "completed_at": "2026-10-10T12:00:00Z",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        # Prior adjustment: -200 LE
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[{"amount": -200.0, "is_void": False}])
        mock_db.finance_adjustments.find.return_value = mock_cursor

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            res = await admin_create_finance_adjustment(
                FinanceAdjustmentInput(
                    order_id=order_id,
                    type="price_correction",
                    currency="EGP",
                    amount=-100.0,
                    reason="Penyesuaian kedua",
                    idempotency_key="tc25_key_123",
                ),
                Response(),
                self.admin_finance
            )
        self.assertEqual(res["order_impact"]["cumulative_net_adjustments_le"], -300.0)
        self.assertEqual(res["order_impact"]["net_adjusted_revenue_le"], 700.0)

    async def test_tc26_compensating_adjustment_preserves_original(self):
        """TC-26: Compensating adjustment opposite-signed price_correction works cleanly."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-026",
            "order_status": "selesai",
            "currency": "EGP",
            "completed_at": "2026-10-10T12:00:00Z",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        # Erroneous prior adjustment of -300 LE
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[{"amount": -300.0, "adjustment_id": "ADJ-20261012-0001", "is_void": False}])
        mock_db.finance_adjustments.find.return_value = mock_cursor

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            res = await admin_create_finance_adjustment(
                FinanceAdjustmentInput(
                    order_id=order_id,
                    type="price_correction",
                    currency="EGP",
                    amount=300.0,  # Offset the erroneous -300
                    reason="Koreksi pembatalan atas ADJ-20261012-0001 (salah input)",
                    idempotency_key="tc26_comp_key_123",
                ),
                Response(),
                self.admin_finance
            )
        # Both are preserved; net cumulative adjustment returns to 0.0
        self.assertEqual(res["order_impact"]["cumulative_net_adjustments_le"], 0.0)
        self.assertEqual(res["order_impact"]["net_adjusted_revenue_le"], 1000.0)

    async def test_tc27_zero_writes_to_payments_credit_or_finance_transactions(self):
        """TC-27: Strict B6-OD-01 enforcement: zero writes to payments, customer_credit_events, finance_transactions."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-027",
            "order_status": "selesai",
            "currency": "EGP",
            "completed_at": "2026-10-10T12:00:00Z",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            await admin_create_finance_adjustment(
                FinanceAdjustmentInput(
                    order_id=order_id,
                    type="price_correction",
                    currency="EGP",
                    amount=-200.0,
                    reason="Diskon susulan",
                    idempotency_key="tc27_key_123",
                ),
                Response(),
                self.admin_finance
            )

        # Assert zero writes to prohibited collections
        mock_db.payments.insert_one.assert_not_called()
        mock_db.customer_credit_events.insert_one.assert_not_called()
        mock_db.finance_transactions.insert_one.assert_not_called()
        # Assert written only to finance_adjustments
        mock_db.finance_adjustments.insert_one.assert_called_once()

    # =========================================================================
    # Group E: Idempotency & Concurrency (TC-28 to TC-33)
    # =========================================================================

    async def test_tc28_identical_replay_returns_original_without_duplication(self):
        """TC-28: Identical replay with matching key returns HTTP 200 with existing adjustment."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-028",
            "order_status": "selesai",
            "currency": "EGP",
            "completed_at": "2026-10-10T12:00:00Z",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        existing_record = {
            "_id": ObjectId("670868f123456789abcdef99"),
            "adjustment_id": "ADJ-20261012-0042",
            "order_id": order_id,
            "type": "price_correction",
            "currency": "EGP",
            "amount": -100.0,
            "reason": "Diskon susulan",
            "evidence_reference": "https://example.com/doc.pdf",
            "notes": "Catatan admin",
            "idempotency_key": "tc28_replay_key_123",
        }
        mock_db.finance_adjustments.find_one = AsyncMock(return_value=existing_record)

        resp = Response()
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            res = await admin_create_finance_adjustment(
                FinanceAdjustmentInput(
                    order_id=order_id,
                    type="price_correction",
                    currency="EGP",
                    amount=-100.0,
                    reason="Diskon susulan",
                    evidence_reference="https://example.com/doc.pdf",
                    notes="Catatan admin",
                    idempotency_key="tc28_replay_key_123",
                ),
                resp,
                self.admin_finance
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(res["adjustment_id"], "ADJ-20261012-0042")
        mock_db.finance_adjustments.insert_one.assert_not_called()

    async def test_tc29_reused_key_with_different_amount_returns_409(self):
        """TC-29: Reused key with mismatched amount returns HTTP 409."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"

        existing_record = {
            "_id": ObjectId("670868f123456789abcdef99"),
            "adjustment_id": "ADJ-20261012-0042",
            "order_id": order_id,
            "type": "price_correction",
            "currency": "EGP",
            "amount": -100.0,
            "reason": "Diskon susulan",
            "idempotency_key": "tc29_diff_key_123",
        }
        mock_db.finance_adjustments.find_one = AsyncMock(return_value=existing_record)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id=order_id,
                        type="price_correction",
                        currency="EGP",
                        amount=-200.0,  # different amount
                        reason="Diskon susulan",
                        idempotency_key="tc29_diff_key_123",
                    ),
                    Response(),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 409)
            self.assertIn("parameter yang berbeda", cm.exception.detail)

    async def test_tc29b_reused_key_with_different_reason_returns_409(self):
        """TC-29b: Reused key with mismatched reason returns HTTP 409."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"

        existing_record = {
            "_id": ObjectId("670868f123456789abcdef99"),
            "adjustment_id": "ADJ-20261012-0042",
            "order_id": order_id,
            "type": "price_correction",
            "currency": "EGP",
            "amount": -100.0,
            "reason": "Alasan awal serah terima",
            "idempotency_key": "tc29b_diff_reason_key",
        }
        mock_db.finance_adjustments.find_one = AsyncMock(return_value=existing_record)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id=order_id,
                        type="price_correction",
                        currency="EGP",
                        amount=-100.0,
                        reason="Alasan berbeda yang dicoba kirim",
                        idempotency_key="tc29b_diff_reason_key",
                    ),
                    Response(),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 409)
            self.assertIn("parameter yang berbeda", cm.exception.detail)

    async def test_tc29c_reused_key_with_different_notes_returns_409(self):
        """TC-29c: Reused key with mismatched notes returns HTTP 409."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"

        existing_record = {
            "_id": ObjectId("670868f123456789abcdef99"),
            "adjustment_id": "ADJ-20261012-0042",
            "order_id": order_id,
            "type": "price_correction",
            "currency": "EGP",
            "amount": -100.0,
            "reason": "Alasan valid",
            "notes": "Catatan versi 1",
            "idempotency_key": "tc29c_diff_notes_key",
        }
        mock_db.finance_adjustments.find_one = AsyncMock(return_value=existing_record)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id=order_id,
                        type="price_correction",
                        currency="EGP",
                        amount=-100.0,
                        reason="Alasan valid",
                        notes="Catatan versi 2 berbeda",
                        idempotency_key="tc29c_diff_notes_key",
                    ),
                    Response(),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 409)
            self.assertIn("parameter yang berbeda", cm.exception.detail)

    async def test_tc29d_reused_key_with_different_evidence_reference_returns_409(self):
        """TC-29d: Reused key with mismatched evidence_reference returns HTTP 409."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"

        existing_record = {
            "_id": ObjectId("670868f123456789abcdef99"),
            "adjustment_id": "ADJ-20261012-0042",
            "order_id": order_id,
            "type": "price_correction",
            "currency": "EGP",
            "amount": -100.0,
            "reason": "Alasan valid",
            "evidence_reference": "https://example.com/doc1.pdf",
            "idempotency_key": "tc29d_diff_evid_key",
        }
        mock_db.finance_adjustments.find_one = AsyncMock(return_value=existing_record)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id=order_id,
                        type="price_correction",
                        currency="EGP",
                        amount=-100.0,
                        reason="Alasan valid",
                        evidence_reference="https://example.com/doc2.pdf",
                        idempotency_key="tc29d_diff_evid_key",
                    ),
                    Response(),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 409)
            self.assertIn("parameter yang berbeda", cm.exception.detail)

    async def test_tc30_concurrent_same_key_duplicate_key_error_handled(self):
        """TC-30: Concurrent duplicate key error resolved by revalidating winning record."""
        import pymongo.errors
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-030",
            "order_status": "selesai",
            "currency": "EGP",
            "completed_at": "2026-10-10T12:00:00Z",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        winning_record = {
            "_id": ObjectId("670868f123456789abcdef99"),
            "adjustment_id": "ADJ-20261012-0042",
            "order_id": order_id,
            "type": "price_correction",
            "currency": "EGP",
            "amount": -100.0,
            "reason": "Diskon susulan",
            "evidence_reference": None,
            "notes": None,
            "idempotency_key": "tc30_race_key_123",
        }
        # First check returns None (race), insert raises DuplicateKeyError, then lookup finds winning record
        mock_db.finance_adjustments.find_one = AsyncMock(side_effect=[None, winning_record])
        mock_db.finance_adjustments.insert_one = AsyncMock(
            side_effect=pymongo.errors.DuplicateKeyError("E11000 duplicate key error collection: finance_adjustments index: uniq_adjustments_idempotency")
        )

        resp = Response()
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            res = await admin_create_finance_adjustment(
                FinanceAdjustmentInput(
                    order_id=order_id,
                    type="price_correction",
                    currency="EGP",
                    amount=-100.0,
                    reason="Diskon susulan",
                    idempotency_key="tc30_race_key_123",
                ),
                resp,
                self.admin_finance
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(res["adjustment_id"], "ADJ-20261012-0042")

    async def test_tc30b_concurrent_duplicate_key_error_with_mismatched_payload_returns_409(self):
        """TC-30b: Concurrent race where winning record has mismatched payload returns HTTP 409."""
        import pymongo.errors
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-030b",
            "order_status": "selesai",
            "currency": "EGP",
            "completed_at": "2026-10-10T12:00:00Z",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        winning_record = {
            "_id": ObjectId("670868f123456789abcdef99"),
            "adjustment_id": "ADJ-20261012-0042",
            "order_id": order_id,
            "type": "price_correction",
            "currency": "EGP",
            "amount": -100.0,
            "reason": "Alasan dari request pertama",
            "idempotency_key": "tc30b_race_diff_key",
        }
        # First check returns None (race), insert raises DuplicateKeyError, then lookup finds winning record with different reason
        mock_db.finance_adjustments.find_one = AsyncMock(side_effect=[None, winning_record])
        mock_db.finance_adjustments.insert_one = AsyncMock(
            side_effect=pymongo.errors.DuplicateKeyError("E11000 duplicate key error collection: finance_adjustments index: uniq_adjustments_idempotency")
        )

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id=order_id,
                        type="price_correction",
                        currency="EGP",
                        amount=-100.0,
                        reason="Alasan berbeda pada request kedua yang kalah race",
                        idempotency_key="tc30b_race_diff_key",
                    ),
                    Response(),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 409)
            self.assertIn("parameter yang berbeda", cm.exception.detail)

    async def test_tc31_concurrent_downward_adjustments_serialize_on_order(self):
        """TC-31: Order serialization guard touched inside transaction."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-031",
            "order_status": "selesai",
            "currency": "EGP",
            "completed_at": "2026-10-10T12:00:00Z",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            await admin_create_finance_adjustment(
                FinanceAdjustmentInput(
                    order_id=order_id,
                    type="price_correction",
                    currency="EGP",
                    amount=-100.0,
                    reason="Diskon susulan",
                    idempotency_key="tc31_guard_key_123",
                ),
                Response(),
                self.admin_finance
            )
        # Serialization touch on order
        mock_db.orders.update_one.assert_called_once()
        self.assertIn("last_finance_adjustment_at", mock_db.orders.update_one.call_args[0][1]["$set"])

    async def test_tc32_daily_id_allocation_increments_counter(self):
        """TC-32: Daily adjustment ID increments atomic counter."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 42})

        with patch("server.db", mock_db):
            adj_id = await generate_adjustment_number()
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        self.assertEqual(adj_id, f"ADJ-{today}-0042")

    async def test_tc33_transient_transaction_error_retries_and_exhaustion(self):
        """TC-33: Transient transaction conflict retries up to max_retries and raises 409 on exhaustion."""
        import pymongo.errors
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-033",
            "order_status": "selesai",
            "currency": "EGP",
            "completed_at": "2026-10-10T12:00:00Z",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        # TransientTransactionError simulation
        transient_err = pymongo.errors.PyMongoError("TransientTransactionError simulated")
        setattr(transient_err, "has_error_label", lambda label: label == "TransientTransactionError")
        mock_db.finance_adjustments.insert_one = AsyncMock(side_effect=transient_err)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id=order_id,
                        type="price_correction",
                        currency="EGP",
                        amount=-100.0,
                        reason="Diskon susulan",
                        idempotency_key="tc33_retry_key_123",
                    ),
                    Response(),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 409)
            self.assertIn("Terjadi konflik transaksi bersamaan", cm.exception.detail)

    # =========================================================================
    # Group F: Transaction Capability & Fail-Closed (TC-34 to TC-35)
    # =========================================================================

    async def test_tc34_production_environment_without_transaction_fails_closed_503(self):
        """TC-34: Production mode without transaction capability raises HTTP 503."""
        import pymongo.errors
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        # Client raises ConfigurationError on start_session
        failing_client = MagicMock()
        failing_client.start_session = AsyncMock(side_effect=pymongo.errors.ConfigurationError("Replica set required"))

        with patch("server.db", mock_db), patch("server.client", failing_client), patch("server.is_standalone_fallback_permitted", return_value=False):
            with self.assertRaises(HTTPException) as cm:
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id="670868f123456789abcdef01",
                        type="price_correction",
                        currency="EGP",
                        amount=-100.0,
                        reason="Diskon susulan",
                        idempotency_key="tc34_fail_closed_key",
                    ),
                    Response(),
                    self.admin_finance
                )
            self.assertEqual(cm.exception.status_code, 503)
            self.assertIn("Fail-Closed", cm.exception.detail)

    async def test_tc35_no_standalone_write_replay_on_transaction_failure(self):
        """TC-35: Transaction failure does not attempt non-transactional writes."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        # Transaction aborts inside context manager
        failing_session = AsyncMock()
        failing_session.start_transaction = MagicMock(side_effect=RuntimeError("Fatal transaction abort"))
        failing_session.__aenter__ = AsyncMock(return_value=failing_session)
        failing_session.__aexit__ = AsyncMock(return_value=None)
        client_mock = MagicMock()
        client_mock.start_session = AsyncMock(return_value=failing_session)

        with patch("server.db", mock_db), patch("server.client", client_mock), patch("server.is_standalone_fallback_permitted", return_value=False):
            with self.assertRaises(RuntimeError):
                await admin_create_finance_adjustment(
                    FinanceAdjustmentInput(
                        order_id="670868f123456789abcdef01",
                        type="price_correction",
                        currency="EGP",
                        amount=-100.0,
                        reason="Diskon susulan",
                        idempotency_key="tc35_fatal_key",
                    ),
                    Response(),
                    self.admin_finance
                )
        mock_db.finance_adjustments.insert_one.assert_not_called()

    # =========================================================================
    # Group G: Persistence & Audit Schema (TC-36 to TC-39)
    # =========================================================================

    async def test_tc36_successful_request_returns_201_with_order_impact(self):
        """TC-36: Successful adjustment returns 201 with clean record and order_impact."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-036",
            "order_status": "selesai",
            "currency": "EGP",
            "completed_at": "2026-10-10T12:00:00Z",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        # Mock payment of 700 LE recorded
        mock_pmt_cursor = MagicMock()
        mock_pmt_cursor.to_list = AsyncMock(return_value=[{"amount_le": 700.0, "status": "recorded"}])
        mock_db.payments.find.return_value = mock_pmt_cursor

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            res = await admin_create_finance_adjustment(
                FinanceAdjustmentInput(
                    order_id=order_id,
                    type="price_correction",
                    currency="EGP",
                    amount=-100.0,
                    reason="Diskon susulan",
                    idempotency_key="tc36_success_key",
                ),
                Response(),
                self.admin_finance
            )
        self.assertIn("order_impact", res)
        impact = res["order_impact"]
        self.assertEqual(impact["original_recognized_revenue_le"], 1000.0)
        self.assertEqual(impact["cumulative_net_adjustments_le"], -100.0)
        self.assertEqual(impact["net_adjusted_revenue_le"], 900.0)
        self.assertEqual(impact["canonical_paid_le"], 700.0)
        self.assertEqual(impact["piutang_usaha_le"], 200.0)
        self.assertEqual(impact["unallocated_excess_le"], 0.0)

    async def test_tc37_public_id_format_matches_specification(self):
        """TC-37: Adjustment ID matches ADJ-YYYYMMDD-XXXX."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-037",
            "order_status": "selesai",
            "currency": "EGP",
            "completed_at": "2026-10-10T12:00:00Z",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 7})

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            res = await admin_create_finance_adjustment(
                FinanceAdjustmentInput(
                    order_id=order_id,
                    type="price_correction",
                    currency="EGP",
                    amount=-100.0,
                    reason="Diskon susulan",
                    idempotency_key="tc37_format_key",
                ),
                Response(),
                self.admin_finance
            )
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        self.assertEqual(res["adjustment_id"], f"ADJ-{today}-0007")

    async def test_tc38_audit_metadata_persisted_correctly(self):
        """TC-38: Actor ID, name, and ISO timestamps persisted."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        order_id = "670868f123456789abcdef01"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SO-038",
            "order_status": "selesai",
            "currency": "EGP",
            "completed_at": "2026-10-10T12:00:00Z",
            "recognized_revenue_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            await admin_create_finance_adjustment(
                FinanceAdjustmentInput(
                    order_id=order_id,
                    type="price_correction",
                    currency="EGP",
                    amount=-100.0,
                    reason="Diskon susulan",
                    idempotency_key="tc38_audit_key",
                ),
                Response(),
                self.admin_finance
            )
        saved_doc = mock_db.finance_adjustments.insert_one.call_args[0][0]
        self.assertEqual(saved_doc["created_by_id"], "admin_fin_01")
        self.assertEqual(saved_doc["created_by_name"], "Finance Head")
        self.assertIn("created_at", saved_doc)
        self.assertEqual(saved_doc["order_completed_at"], "2026-10-10T12:00:00Z")

    async def test_tc39_index_bootstrap_creates_required_indexes(self):
        """TC-39: startup seed provisions the 4 indexes for finance_adjustments."""
        from server import seed
        mock_db = MagicMock()
        mock_db.admins = MagicMock()
        mock_db.admins.find_one = AsyncMock(return_value={"_id": ObjectId(), "role": "owner"})
        mock_db.admins.create_index = AsyncMock()
        mock_db.products = MagicMock()
        mock_db.products.create_index = AsyncMock()
        mock_db.products.count_documents = AsyncMock(return_value=1)
        mock_db.products.find_one = AsyncMock(return_value=None)
        mock_db.products.update_one = AsyncMock()
        mock_db.products.update_many = AsyncMock()
        mock_db.orders = MagicMock()
        mock_db.orders.create_index = AsyncMock()
        mock_db.customers = MagicMock()
        mock_db.customers.create_index = AsyncMock()
        mock_db.point_transactions = MagicMock()
        mock_db.point_transactions.create_index = AsyncMock()
        mock_db.finance_transactions = MagicMock()
        mock_db.finance_transactions.create_index = AsyncMock()
        mock_db.referrals = MagicMock()
        mock_db.referrals.create_index = AsyncMock()
        mock_db.invoices = MagicMock()
        mock_db.invoices.create_index = AsyncMock()
        mock_db.claim_attempts = MagicMock()
        mock_db.claim_attempts.create_index = AsyncMock()
        mock_db.audit_logs = MagicMock()
        mock_db.audit_logs.create_index = AsyncMock()
        mock_db.settings = MagicMock()
        mock_db.settings.find_one = AsyncMock(return_value={"val": 1})
        mock_db.delivery_zones = MagicMock()
        mock_db.delivery_zones.count_documents = AsyncMock(return_value=1)
        mock_db.materials = MagicMock()
        mock_db.materials.create_index = AsyncMock()
        mock_db.material_purchases = MagicMock()
        mock_db.material_purchases.create_index = AsyncMock()
        mock_db.material_purchases.index_information = AsyncMock(return_value={})
        mock_db.material_stocks = MagicMock()
        mock_db.material_stocks.create_index = AsyncMock()
        mock_db.stock_forms = MagicMock()
        mock_db.stock_forms.create_index = AsyncMock()
        mock_db.stock_transformations = MagicMock()
        mock_db.stock_transformations.create_index = AsyncMock()
        mock_db.payments = MagicMock()
        mock_db.payments.create_index = AsyncMock()
        mock_db.wage_rules = MagicMock()
        mock_db.wage_rules.create_index = AsyncMock()
        mock_db.work_assignments = MagicMock()
        mock_db.work_assignments.create_index = AsyncMock()
        mock_db.wage_obligations = MagicMock()
        mock_db.wage_obligations.create_index = AsyncMock()
        mock_db.customer_credit_events = MagicMock()
        mock_db.customer_credit_events.create_index = AsyncMock()
        mock_db.categories = MagicMock()
        mock_db.categories.count_documents = AsyncMock(return_value=1)
        mock_db.finance_adjustments = MagicMock()
        mock_db.finance_adjustments.create_index = AsyncMock()

        # Call seed with patched db
        with patch("server.db", mock_db), patch("server.ensure_probe_infrastructure", AsyncMock()):
            await seed()

        # Check that finance_adjustments.create_index was called for each required index
        call_names = [call[1].get("name") for call in mock_db.finance_adjustments.create_index.call_args_list]
        self.assertIn("uniq_adjustment_id", call_names)
        self.assertIn("uniq_adjustments_idempotency", call_names)
        self.assertIn("idx_adjustments_order_lookup", call_names)
        self.assertIn("idx_adjustments_period_reporting", call_names)


if __name__ == "__main__":
    unittest.main()
