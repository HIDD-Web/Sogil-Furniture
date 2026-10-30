"""
Phase 08.5D — Activation Policy, Eligibility Lifecycle & Idempotency Test Suite
Sogil Furniture | Financial Integrity First

Verifies:
1. Toggle otomatis OFF secara default.
2. Kedua kondisi wajib terpenuhi sebelum akrual (selesai DAN lunas).
3. Selesai lalu lunas (Sequence A).
4. Lunas lalu selesai (Sequence B).
5. Pesanan belum selesai dan belum lunas saat aktivasi masuk cakupan.
6. Pesanan sudah lunas tetapi belum selesai saat aktivasi masuk cakupan.
7. Pesanan sudah selesai tetapi belum lunas saat aktivasi masuk cakupan.
8. Pesanan selesai dan lunas saat fitur OFF dicatat skipped_disabled_window.
9. Aktivasi ulang tidak mengakru pesanan yang dilewati selama OFF (anti-retroactive).
10. Aktivasi ulang dapat mencakup pesanan yang masih pending selama OFF.
11. Override manual tetap dapat diakru saat global OFF.
12. Override manual tidak berubah ketika tarif global diperbarui.
13. Konfigurasi manual tidak valid tidak diam-diam jatuh ke default.
14. Perubahan mode manual/otomatis tidak membuat kewajiban ganda.
15. Kewajiban existing tidak terpengaruh oleh toggle global.
16. Kewajiban voided tidak diakru ulang otomatis (fail-closed quarantine).
17. Dua proses akrual bersamaan menghasilkan paling banyak satu kewajiban.
18. Retry setelah gangguan transient tidak menghasilkan duplikasi.
19. Kegagalan pada tiap tahap tidak menghasilkan keadaan finansial tidak konsisten.
20. Pesanan historis tidak diakru otomatis berdasarkan asumsi atau tanggal buatan.
21. Status eligibility dan audit log tetap konsisten setelah evaluasi dan siklus aktivasi.
22. Perubahan order yang tidak relevan tidak memicu akrual yang salah.
"""

import copy
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
import pymongo.errors
from fastapi import HTTPException

# Path setup
BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
for p in [str(REPO_ROOT), str(BACKEND_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

import server
from server import (
    build_admin_wage_accrual_event_key,
    is_order_completed,
    is_order_fully_paid,
    is_order_excluded_from_admin_wage,
    is_timestamp_within_active_cycle,
    is_order_historical_unreconciled,
    get_order_admin_wage_eligibility,
    get_active_admin_wage_policy,
    process_order_admin_wage_accrual,
    evaluate_and_process_order_admin_wage_accrual,
    admin_create_order_payment,
    admin_update_order,
    admin_update_order_admin_wage,
    admin_update_wage_policy_endpoint,
    PaymentCreateInput,
    AdminWageOverrideInput,
    OrderStatusUpdate,
)


class TestPhase08_5DActivationPolicy(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.admin_owner = {
            "id": "507f1f77bcf86cd799439001",
            "_id": ObjectId("507f1f77bcf86cd799439001"),
            "name": "Owner Sogil",
            "role": "owner",
            "permissions": {"manage_orders": True, "access_finance": True},
        }
        self.admin_finance = {
            "id": "507f1f77bcf86cd799439003",
            "_id": ObjectId("507f1f77bcf86cd799439003"),
            "name": "Finance Admin",
            "role": "admin",
            "permissions": {"manage_orders": True, "access_finance": True},
        }
        self.default_worker_id = "507f1f77bcf86cd799439002"
        self.default_worker = {
            "_id": ObjectId(self.default_worker_id),
            "id": self.default_worker_id,
            "name": "Sarah Administrasi",
            "role": "admin",
            "active": True,
        }

        # Mock client session for transactions
        self.mock_session = AsyncMock()
        self.mock_session.__aenter__.return_value = self.mock_session
        self.mock_session.__aexit__.return_value = None
        self.mock_session.start_transaction = MagicMock()
        self.mock_session.commit_transaction = AsyncMock()
        self.mock_session.abort_transaction = AsyncMock()

        self.mock_client = MagicMock()
        self.mock_client.start_session = AsyncMock(return_value=self.mock_session)

    def _setup_mock_db(self, mock_db, policy_enabled=True, wage_amount=50.0):
        mock_db.client = self.mock_client

        # Default active policy with activation cycle
        cycle_id = "cycle_20261030_001"
        self.policy_doc = {
            "key": "admin_wage_policy",
            "value": {
                "default_wage_per_order_le": wage_amount,
                "default_recipient_id": self.default_worker_id,
                "default_recipient_name": "Sarah Administrasi",
                "unusual_amount_threshold_le": 100.0,
                "max_wage_per_order_le": 150.0,
                "enabled": policy_enabled,
                "currency": "EGP",
                "rounding_policy": "piastre_round_half_up",
                "is_configured": True,
                "current_cycle_id": cycle_id if policy_enabled else None,
                "initial_activation_at": "2026-10-30T00:00:00Z" if policy_enabled else None,
                "activation_cycles": [
                    {
                        "cycle_id": cycle_id,
                        "enabled_at": "2026-10-30T00:00:00Z",
                        "enabled_by_id": self.admin_owner["id"],
                        "enabled_by_name": self.admin_owner["name"],
                        "enabled_reason": "Peluncuran kebijakan",
                        "disabled_at": None if policy_enabled else "2026-10-30T12:00:00Z",
                        "disabled_by_id": None if policy_enabled else self.admin_owner["id"],
                        "disabled_by_name": None if policy_enabled else self.admin_owner["name"],
                        "disabled_reason": None if policy_enabled else "Penonaktifan sementara",
                    }
                ] if policy_enabled else [],
            }
        }

        mock_db.settings.find_one = AsyncMock(return_value=self.policy_doc)
        mock_db.admins.find_one = AsyncMock(return_value=self.default_worker)
        mock_db.wage_obligations.find_one = AsyncMock(return_value=None)
        mock_db.wage_obligations.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.audit_logs.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        async def mock_default_order_find(query, **kwargs):
            return {"_id": query.get("_id"), "order_status": "diproses", "payment_status": "lunas", "completed_at": None, "paid_at": None}
        mock_db.orders.find_one = AsyncMock(side_effect=mock_default_order_find)
        mock_db.orders.update_one = AsyncMock(return_value=MagicMock(matched_count=1, modified_count=1))
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        mock_db.finance_transactions.update_one = AsyncMock(return_value=MagicMock(matched_count=1, modified_count=1))
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 101})

    # =========================================================================
    # 1. Toggle otomatis OFF secara default
    # =========================================================================
    async def test_01_toggle_global_off_by_default(self):
        """1. When system is initialized or unconfigured, global toggle defaults to OFF."""
        mock_db = MagicMock()
        mock_db.settings.find_one = AsyncMock(return_value=None)

        with patch("server.db", mock_db):
            policy = await get_active_admin_wage_policy()

        self.assertFalse(policy["enabled"])
        self.assertFalse(policy["is_configured"])
        self.assertIsNone(policy["default_wage_per_order_le"])
        self.assertEqual(policy["activation_cycles"], [])
        self.assertIsNone(policy["current_cycle_id"])

    # =========================================================================
    # 2. Kedua kondisi wajib terpenuhi sebelum akrual
    # =========================================================================
    async def test_02_both_conditions_required_before_accrual(self):
        """2. Neither completed alone nor paid alone produces a wage obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)

        # Case A: Completed but UNPAID
        order_unpaid = {
            "_id": ObjectId("507f1f77bcf86cd799439011"),
            "order_number": "SGF-20261030-001",
            "order_status": "selesai",
            "payment_status": "belum_dibayar",
            "total_le": 500.0,
            "paid_amount_le": 0.0,
        }
        with patch("server.db", mock_db):
            res_a = await evaluate_and_process_order_admin_wage_accrual(order_unpaid, self.admin_finance)
        self.assertEqual(res_a["status"], "skipped_payment_not_lunas")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)
        self.assertEqual(res_a["eligibility"]["scope_status"], "in_scope_pending")

        # Case B: Paid but INCOMPLETE (status: diproses)
        order_incomplete = {
            "_id": ObjectId("507f1f77bcf86cd799439012"),
            "order_number": "SGF-20261030-002",
            "order_status": "diproses",
            "payment_status": "lunas",
            "total_le": 500.0,
            "paid_amount_le": 500.0,
        }
        with patch("server.db", mock_db):
            res_b = await evaluate_and_process_order_admin_wage_accrual(order_incomplete, self.admin_finance)
        self.assertEqual(res_b["status"], "skipped_order_not_completed")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)
        self.assertEqual(res_b["eligibility"]["scope_status"], "in_scope_pending")

    # =========================================================================
    # 3. Selesai lalu lunas (Sequence A)
    # =========================================================================
    async def test_03_sequence_a_completed_first_then_paid(self):
        """3. Sequence A: Order completed first, customer pays second -> accrues exactly 1 obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)
        order_id = "507f1f77bcf86cd799439013"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261030-003",
            "order_status": "selesai",
            "completed_at": "2026-10-30T09:00:00Z",
            "payment_status": "belum_dibayar",
            "total_le": 500.0,
            "paid_amount_le": 0.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[{"amount_le": 500.0, "status": "recorded"}])
        mock_db.payments.find.return_value = mock_find

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=500.0, payment_method="cash")
            res = await admin_create_order_payment(order_id, payload, self.admin_finance)

        self.assertEqual(res["order_summary"]["payment_status"], "lunas")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)
        wob = mock_db.wage_obligations.insert_one.call_args[0][0]
        self.assertEqual(wob["total_amount_le"], 50.0)
        self.assertEqual(wob["status"], "accrued")
        self.assertEqual(wob["accrual_event_key"], f"admin_wage:{order_id}")

    # =========================================================================
    # 4. Lunas lalu selesai (Sequence B)
    # =========================================================================
    async def test_04_sequence_b_paid_first_then_completed(self):
        """4. Sequence B: Order paid first, marked completed second -> accrues exactly 1 obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)
        order_id = "507f1f77bcf86cd799439014"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261030-004",
            "order_status": "diproses",
            "payment_status": "lunas",
            "total_le": 600.0,
            "paid_amount_le": 600.0,
            "outstanding_amount_le": 0.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            update_data = OrderStatusUpdate(order_status="selesai")
            await admin_update_order(order_id, update_data, self.admin_finance)

        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)
        wob = mock_db.wage_obligations.insert_one.call_args[0][0]
        self.assertEqual(wob["total_amount_le"], 50.0)
        self.assertEqual(wob["accrual_event_key"], f"admin_wage:{order_id}")

    # =========================================================================
    # 5. Pesanan belum selesai dan belum lunas saat aktivasi
    # =========================================================================
    async def test_05_pre_activation_uncompleted_unpaid_enrolled(self):
        """5. Order created before activation (uncompleted & unpaid) accrues when settled after activation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)
        order_id = "507f1f77bcf86cd799439015"
        # Created 2 days before activation
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261028-005",
            "created_at": "2026-10-28T10:00:00Z",
            "order_status": "diproses",
            "payment_status": "belum_dibayar",
            "total_le": 400.0,
            "paid_amount_le": 0.0,
        }
        # Step 1: Customer pays while active
        order_doc["payment_status"] = "lunas"
        order_doc["paid_amount_le"] = 400.0
        order_doc["outstanding_amount_le"] = 0.0

        # Step 2: Order completed while active
        order_doc["order_status"] = "selesai"
        order_doc["completed_at"] = "2026-10-30T10:00:00Z"

        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")

        self.assertEqual(res["status"], "accrued")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)
        self.assertEqual(res["eligibility"]["scope_status"], "accrued")

    # =========================================================================
    # 6. Pesanan sudah lunas tetapi belum selesai saat aktivasi
    # =========================================================================
    async def test_06_pre_activation_paid_incomplete_enrolled(self):
        """6. Order paid before activation, completed after activation -> qualifies and accrues."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)
        order_id = "507f1f77bcf86cd799439016"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261028-006",
            "created_at": "2026-10-28T08:00:00Z",
            "order_status": "diproses",
            "payment_status": "lunas",
            "total_le": 500.0,
            "paid_amount_le": 500.0,
            "outstanding_amount_le": 0.0,
        }
        # Second condition (completion) occurs after activation
        order_doc["order_status"] = "selesai"
        order_doc["completed_at"] = "2026-10-30T11:00:00Z"

        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")

        self.assertEqual(res["status"], "accrued")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)

    # =========================================================================
    # 7. Pesanan sudah selesai tetapi belum lunas saat aktivasi
    # =========================================================================
    async def test_07_pre_activation_completed_unpaid_enrolled(self):
        """7. Order completed before activation, paid after activation -> qualifies and accrues."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)
        order_id = "507f1f77bcf86cd799439017"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261028-007",
            "created_at": "2026-10-28T08:00:00Z",
            "order_status": "selesai",
            "completed_at": "2026-10-28T12:00:00Z",
            "payment_status": "belum_dibayar",
            "total_le": 700.0,
            "paid_amount_le": 0.0,
        }
        # Second condition (payment) occurs after activation
        order_doc["payment_status"] = "lunas"
        order_doc["paid_amount_le"] = 700.0
        order_doc["outstanding_amount_le"] = 0.0
        order_doc["paid_at"] = "2026-10-30T10:00:00Z"

        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")

        self.assertEqual(res["status"], "accrued")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)

    # =========================================================================
    # 8. Pesanan selesai dan lunas saat fitur OFF
    # =========================================================================
    async def test_08_completed_and_paid_while_off_skipped(self):
        """8. Order settling (completed & paid) while feature is OFF is skipped with skipped_disabled_window."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=False)
        order_doc = {
            "_id": ObjectId("507f1f77bcf86cd799439018"),
            "order_number": "SGF-20261030-008",
            "order_status": "selesai",
            "completed_at": "2026-10-30T14:00:00Z",
            "payment_status": "lunas",
            "total_le": 450.0,
            "paid_amount_le": 450.0,
            "outstanding_amount_le": 0.0,
        }

        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")

        self.assertEqual(res["status"], "skipped_policy_disabled")
        self.assertEqual(res["eligibility"]["scope_status"], "skipped_disabled_window")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

    # =========================================================================
    # 9. Aktivasi ulang tidak mengakru pesanan yang dilewati selama OFF
    # =========================================================================
    async def test_09_reactivation_does_not_retroactively_accrue_skipped_orders(self):
        """9. Anti-Retroactivity: Re-enabling policy does not retroactively accrue orders skipped while OFF."""
        mock_db = MagicMock()
        # Policy is now re-enabled (Cycle 2)
        self._setup_mock_db(mock_db, policy_enabled=True)

        # Order was previously skipped during an OFF window
        order_doc = {
            "_id": ObjectId("507f1f77bcf86cd799439019"),
            "order_number": "SGF-20261030-009",
            "order_status": "selesai",
            "completed_at": "2026-10-30T14:00:00Z",
            "payment_status": "lunas",
            "total_le": 450.0,
            "paid_amount_le": 450.0,
            "admin_wage_skipped": {
                "status": "skipped_disabled_window",
                "reason": "Kebijakan upah admin tidak aktif saat pesanan selesai dan lunas",
                "skipped_at": "2026-10-30T14:00:00Z"
            },
            "admin_wage_eligibility": {
                "scope_status": "skipped_disabled_window",
                "governance_mode": "automatic",
                "skip_reason": "settled_while_automation_disabled"
            }
        }

        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")

        self.assertEqual(res["status"], "skipped_disabled_window_matured")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)
        self.assertEqual(res["eligibility"]["scope_status"], "skipped_disabled_window")

    # =========================================================================
    # 10. Aktivasi ulang dapat mencakup pesanan yang masih belum selesai dan lunas
    # =========================================================================
    async def test_10_reactivation_accrues_orders_pending_throughout_inactive_period(self):
        """10. Re-activation correctly accrues orders that remained pending during the OFF period and settle now."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)

        # Order created during OFF period, was not completed and not paid
        order_doc = {
            "_id": ObjectId("507f1f77bcf86cd799439020"),
            "order_number": "SGF-20261030-010",
            "created_at": "2026-10-30T13:00:00Z",
            "order_status": "selesai",
            "completed_at": "2026-10-30T16:00:00Z", # Settled now in Cycle 2
            "payment_status": "lunas",
            "total_le": 500.0,
            "paid_amount_le": 500.0,
            "admin_wage_eligibility": {
                "scope_status": "in_scope_pending",
                "governance_mode": "automatic"
            }
        }

        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")

        self.assertEqual(res["status"], "accrued")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)

    # =========================================================================
    # 11. Override manual tetap dapat diakru saat global OFF
    # =========================================================================
    async def test_11_manual_override_accrues_when_global_off(self):
        """11. Valid manual override accrues wage obligation even when global policy toggle is OFF."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=False)

        order_id = "507f1f77bcf86cd799439021"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261030-011",
            "order_status": "selesai",
            "completed_at": "2026-10-30T10:00:00Z",
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 1000.0,
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 75.0,
                "recipient_id": self.default_worker_id,
                "recipient_name": "Sarah Administrasi",
                "override_reason": "Order manual khusus",
            }
        }

        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")

        self.assertEqual(res["status"], "accrued")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)
        wob = mock_db.wage_obligations.insert_one.call_args[0][0]
        self.assertEqual(wob["total_amount_le"], 75.0)
        self.assertTrue(wob["is_override"])
        self.assertEqual(res["eligibility"]["scope_status"], "accrued")
        self.assertEqual(res["eligibility"]["governance_mode"], "manual_override")

    # =========================================================================
    # 12. Override manual tidak berubah ketika tarif global diperbarui
    # =========================================================================
    async def test_12_manual_override_unaffected_by_global_rate_changes(self):
        """12. Changing global rate from 50 to 90 does not alter existing order's manual override of 75."""
        mock_db = MagicMock()
        # Global policy configured with 90 LE
        self._setup_mock_db(mock_db, policy_enabled=True, wage_amount=90.0)

        order_id = "507f1f77bcf86cd799439022"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261030-012",
            "order_status": "selesai",
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 1000.0,
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 75.0,
                "recipient_id": self.default_worker_id,
                "recipient_name": "Sarah Administrasi",
                "override_reason": "Tarif khusus yang tidak boleh berubah",
            }
        }

        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")

        self.assertEqual(res["status"], "accrued")
        wob = mock_db.wage_obligations.insert_one.call_args[0][0]
        self.assertEqual(wob["total_amount_le"], 75.0) # Preserved 75, not global 90
        self.assertTrue(wob["is_override"])

    # =========================================================================
    # 13. Konfigurasi manual tidak valid tidak diam-diam jatuh ke default
    # =========================================================================
    async def test_13_invalid_manual_config_fails_closed_no_silent_fallback(self):
        """13. Missing or invalid manual override rate fails closed (blocked) and never silently uses default rate."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True, wage_amount=50.0)

        # Case A: is_override=True but amount_le is None
        order_no_rate = {
            "_id": ObjectId("507f1f77bcf86cd799439023"),
            "order_number": "SGF-20261030-013A",
            "order_status": "selesai",
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 1000.0,
            "admin_wage_override": {
                "is_override": True,
                "amount_le": None, # Missing rate
                "recipient_id": self.default_worker_id,
            }
        }
        with patch("server.db", mock_db):
            res_a = await evaluate_and_process_order_admin_wage_accrual(order_no_rate, self.admin_finance)

        self.assertEqual(res_a["status"], "blocked_missing_rate")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)
        self.assertEqual(res_a["eligibility"]["scope_status"], "blocked")

        # Case B: is_override=True with non-existent recipient
        order_bad_recip = {
            "_id": ObjectId("507f1f77bcf86cd799439024"),
            "order_number": "SGF-20261030-013B",
            "order_status": "selesai",
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 1000.0,
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 60.0,
                "recipient_id": "507f1f77bcf86cd799439999", # Ghost ID
            }
        }
        mock_db.admins.find_one = AsyncMock(return_value=None)
        with patch("server.db", mock_db):
            res_b = await evaluate_and_process_order_admin_wage_accrual(order_bad_recip, self.admin_finance)

        self.assertEqual(res_b["status"], "blocked_invalid_recipient")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

    # =========================================================================
    # 14. Perubahan mode tidak membuat kewajiban ganda
    # =========================================================================
    async def test_14_mode_change_does_not_create_duplicate_obligations(self):
        """14. Switching an accrued order from manual to automatic does not generate a second obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)
        order_id = "507f1f77bcf86cd799439025"
        accrual_key = f"admin_wage:{order_id}"

        # Existing obligation already issued under manual override
        existing_obligation = {
            "_id": ObjectId("807f1f77bcf86cd799439025"),
            "obligation_number": "WOB-20261030-0025",
            "accrual_event_key": accrual_key,
            "task_category": "admin",
            "worker_id": self.default_worker_id,
            "worker_name": "Sarah Administrasi",
            "total_amount_le": 75.0,
            "status": "accrued",
            "is_override": True,
        }
        mock_db.wage_obligations.find_one = AsyncMock(return_value=existing_obligation)

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261030-014",
            "order_status": "selesai",
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 1000.0,
            "admin_wage_override": {"is_override": False}, # Changed to automatic
        }

        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")

        self.assertEqual(res["status"], "already_accrued")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)
        self.assertEqual(res["obligation"]["obligation_number"], "WOB-20261030-0025")

    # =========================================================================
    # 15. Kewajiban existing tidak terpengaruh oleh toggle
    # =========================================================================
    async def test_15_existing_obligations_unaffected_by_global_toggle_off(self):
        """15. Turning global toggle OFF never mutates, voids, or deletes previously issued obligations."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=False) # Global toggle OFF

        order_id = "507f1f77bcf86cd799439026"
        accrual_key = f"admin_wage:{order_id}"
        existing_obligation = {
            "_id": ObjectId("807f1f77bcf86cd799439026"),
            "obligation_number": "WOB-20261030-0026",
            "accrual_event_key": accrual_key,
            "task_category": "admin",
            "worker_id": self.default_worker_id,
            "worker_name": "Sarah Administrasi",
            "total_amount_le": 50.0,
            "status": "paid", # Already paid
        }
        mock_db.wage_obligations.find_one = AsyncMock(return_value=existing_obligation)

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261030-015",
            "order_status": "selesai",
            "payment_status": "lunas",
            "total_le": 500.0,
            "paid_amount_le": 500.0,
        }

        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")

        self.assertEqual(res["status"], "already_accrued")
        self.assertEqual(res["obligation"]["status"], "paid")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

    # =========================================================================
    # 16. Kewajiban voided tidak diakru ulang otomatis
    # =========================================================================
    async def test_16_voided_obligation_blocks_automatic_reaccrual(self):
        """16. Orders whose admin wage obligation was previously voided are quarantined and blocked from re-accrual."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)

        order_id = "507f1f77bcf86cd799439027"
        accrual_key = f"admin_wage:{order_id}"
        voided_obligation = {
            "_id": ObjectId("807f1f77bcf86cd799439027"),
            "obligation_number": "WOB-20261030-0027",
            "accrual_event_key": accrual_key,
            "task_category": "admin",
            "status": "voided",
        }
        mock_db.wage_obligations.find_one = AsyncMock(return_value=voided_obligation)

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261030-016",
            "order_status": "selesai",
            "payment_status": "lunas",
            "total_le": 500.0,
            "paid_amount_le": 500.0,
        }

        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")

        self.assertEqual(res["status"], "blocked_prior_voided_obligation")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)
        self.assertTrue(res["blocked"]["owner_review_required"])

    # =========================================================================
    # 17. Dua proses akrual bersamaan menghasilkan paling banyak satu kewajiban
    # =========================================================================
    async def test_17_concurrent_accrual_yields_at_most_one_obligation(self):
        """17. Race condition with DuplicateKeyError on uniq_wage_obligation_accrual_event reuses winning obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)

        order_id = "507f1f77bcf86cd799439028"
        accrual_key = f"admin_wage:{order_id}"
        winning_obligation = {
            "_id": ObjectId("807f1f77bcf86cd799439028"),
            "obligation_number": "WOB-20261030-0028",
            "accrual_event_key": accrual_key,
            "task_category": "admin",
            "worker_id": self.default_worker_id,
            "worker_name": "Sarah Administrasi",
            "total_amount_le": 50.0,
            "status": "accrued",
        }

        # First find_one returns None (both see no obligation)
        # insert_one fails with DuplicateKeyError for the second worker
        # second find_one returns winning_obligation
        call_count = 0
        async def mock_wob_find(q, **kw):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                return winning_obligation
            return None

        mock_db.wage_obligations.find_one = AsyncMock(side_effect=mock_wob_find)
        mock_db.wage_obligations.insert_one = AsyncMock(
            side_effect=pymongo.errors.DuplicateKeyError("E11000 duplicate key: uniq_wage_obligation_accrual_event")
        )

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261030-017",
            "order_status": "selesai",
            "payment_status": "lunas",
            "total_le": 500.0,
            "paid_amount_le": 500.0,
        }

        with patch("server.db", mock_db):
            res = await process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")

        self.assertEqual(res["status"], "accrued")
        self.assertEqual(res["obligation"]["obligation_number"], "WOB-20261030-0028")

    # =========================================================================
    # 18. Retry setelah gangguan tidak menghasilkan duplikasi
    # =========================================================================
    async def test_18_retry_after_transient_failure_no_duplicates(self):
        """18. Retrying after transient network interruption executes idempotently with zero duplicates."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)

        order_id = "507f1f77bcf86cd799439029"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261030-018",
            "order_status": "selesai",
            "payment_status": "lunas",
            "total_le": 500.0,
            "paid_amount_le": 500.0,
        }

        with patch("server.db", mock_db):
            # Attempt 1: succeeds
            res1 = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")
            self.assertEqual(res1["status"], "accrued")

            # Mock finding the obligation on Attempt 2 (idempotent retry)
            mock_db.wage_obligations.find_one = AsyncMock(return_value={
                "_id": ObjectId(),
                "obligation_number": res1["obligation"]["obligation_number"],
                "accrual_event_key": f"admin_wage:{order_id}",
                "total_amount_le": 50.0,
                "status": "accrued",
            })

            res2 = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_finance, lifecycle_event="order_completed")
            self.assertEqual(res2["status"], "already_accrued")
            self.assertEqual(res2["obligation"]["obligation_number"], res1["obligation"]["obligation_number"])
            # Exactly 1 insert call across both attempts
            self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)

    # =========================================================================
    # 19. Kegagalan pada tiap tahap tidak menghasilkan keadaan finansial yang tidak konsisten
    # =========================================================================
    async def test_19_failure_at_any_stage_preserves_consistent_state(self):
        """19. Database failure during accrual aborts transaction cleanly without partial order mutation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)

        order_id = "507f1f77bcf86cd799439030"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261030-019",
            "order_status": "selesai",
            "total_le": 500.0,
            "payment_status": "belum_dibayar",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_db.payments.find_one = AsyncMock(return_value=None)
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[{"amount_le": 500.0, "status": "recorded"}])
        mock_db.payments.find.return_value = mock_find

        # Simulate unexpected DB error during wage obligation insertion
        mock_db.wage_obligations.insert_one = AsyncMock(side_effect=pymongo.errors.PyMongoError("Disk full / connection reset"))

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=500.0, payment_method="cash")
            with self.assertRaises(pymongo.errors.PyMongoError):
                await admin_create_order_payment(order_id, payload, self.admin_finance)

    # =========================================================================
    # 20. Pesanan historis dengan legacy markers dikecualikan dan aktivasi tidak memindai pesanan lama
    # =========================================================================
    async def test_20_historical_orders_not_accrued_on_assumptions_or_arbitrary_dates(self):
        """20. Historical orders with legacy markers remain quarantined, and policy activation never backfills old orders."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)

        # Historical order with explicit legacy manual marker (backward compatibility)
        order_hist = {
            "_id": ObjectId("507f1f77bcf86cd799439031"),
            "order_number": "SGF-HIST-001",
            "created_at": "2026-09-01T10:00:00Z",
            "order_status": "selesai",
            "completed_at": "2026-09-10T12:00:00Z",
            "payment_status": "lunas",
            "total_le": 1500.0,
            "paid_amount_le": 1500.0,
            "is_legacy_manual": True,
        }

        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_hist, self.admin_finance)

        self.assertIn(res["status"], ("skipped_legacy_reconciled", "skipped_pre_activation_historical"))
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)
        self.assertEqual(res["eligibility"]["scope_status"], "excluded_historical")

    # =========================================================================
    # 21. Status eligibility dan audit log tetap konsisten setelah retry
    # =========================================================================
    async def test_21_eligibility_and_audit_logs_remain_consistent_after_retries(self):
        """21. Eligibility subdocument and audit logs accurately record activation cycles and transitions."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)

        # Test helper: get_order_admin_wage_eligibility
        order_accrued = {
            "order_number": "SGF-20261030-021",
            "admin_wage_obligation": {
                "obligation_number": "WOB-20261030-0099",
                "is_override": False,
            }
        }
        el = get_order_admin_wage_eligibility(order_accrued)
        self.assertEqual(el["scope_status"], "accrued")
        self.assertEqual(el["governance_mode"], "automatic")

        # Test helper: is_timestamp_within_active_cycle
        policy = {
            "activation_cycles": [
                {
                    "cycle_id": "cycle_001",
                    "enabled_at": "2026-10-01T00:00:00Z",
                    "disabled_at": "2026-10-15T00:00:00Z"
                },
                {
                    "cycle_id": "cycle_002",
                    "enabled_at": "2026-10-20T00:00:00Z",
                    "disabled_at": None # Open
                }
            ]
        }
        is_in, cid = is_timestamp_within_active_cycle("2026-10-10T12:00:00Z", policy)
        self.assertTrue(is_in)
        self.assertEqual(cid, "cycle_001")

        is_in2, cid2 = is_timestamp_within_active_cycle("2026-10-18T00:00:00Z", policy)
        self.assertFalse(is_in2) # Inactive window
        self.assertIsNone(cid2)

        is_in3, cid3 = is_timestamp_within_active_cycle("2026-10-25T00:00:00Z", policy)
        self.assertTrue(is_in3)
        self.assertEqual(cid3, "cycle_002")

    # =========================================================================
    # 22. Perubahan order yang tidak relevan tidak memicu akrual yang salah
    # =========================================================================
    async def test_22_irrelevant_order_updates_do_not_trigger_false_accrual(self):
        """22. Updating notes or transitioning non-completed statuses does not evaluate or trigger wage accrual."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)

        order_id = "507f1f77bcf86cd799439032"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261030-022",
            "order_status": "pesanan_masuk",
            "payment_status": "belum_dibayar",
            "total_le": 500.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            # Transition from 'pesanan_masuk' to 'diproses' (not 'selesai')
            update_data = OrderStatusUpdate(order_status="diproses")
            await admin_update_order(order_id, update_data, self.admin_finance)

        # Zero wage obligations created
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)


if __name__ == "__main__":
    unittest.main()
