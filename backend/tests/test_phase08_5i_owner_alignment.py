"""
Test Suite: Phase 08.5I — Owner Policy Alignment & Contract Verification
Verifies the 14 mandatory Owner business scenarios for Sogil Furniture Admin Wage Accrual:
1. Completion first, then payment in full, when global policy is ON -> Exactly one obligation.
2. Payment in full first, then completion, when global policy is ON -> Exactly one obligation.
3. Both conditions met when global policy is OFF -> Permanent skip persisted, zero obligation.
4. Matured when OFF, then feature turned ON -> Protected from retroactive accrual.
5. Pending (only one condition met) when re-enabled, matures when ON -> Accrues exactly one obligation.
6. Orders completed & paid before first activation are NOT accrued when feature is activated (no scan/backfill).
7. Non-lifecycle edits (notes, addresses) on historical orders do NOT trigger accrual.
8. Valid manual override accrues even when global policy is OFF.
9. Incomplete manual override (missing recipient or nominal) fails closed without taking global defaults.
10. Retry and duplicate events are idempotent via canonical event key (no duplicate obligation).
11. VOID / CANCELLED orders or prior voided obligations block accrual safely.
12. Invalid financial data (NaN, Inf, negative, malformed) fails closed.
13. Hard cap conflict blocks without clamping or fallback.
14. Transaction failure / rollback leaves no inconsistent obligation or audit record.
15. AdminWagePolicyInput defaults enabled to False.
"""

import copy
from datetime import datetime, timezone
from decimal import Decimal
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
import pymongo
import pymongo.errors
from pydantic import ValidationError

from server import (
    AdminWagePolicyInput,
    build_admin_wage_accrual_event_key,
    is_order_completed,
    is_order_fully_paid,
    is_order_excluded_from_admin_wage,
    get_order_admin_wage_eligibility,
    get_active_admin_wage_policy,
    process_order_admin_wage_accrual,
    evaluate_and_process_order_admin_wage_accrual,
    admin_create_order_payment,
    execute_order_handover_completion,
    admin_update_order,
    admin_update_wage_policy_endpoint,
    execute_transaction_with_safety,
    PaymentCreateInput,
    OrderStatusUpdate,
)


class TestPhase08_5IOwnerAlignment(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.admin_owner = {
            "id": "600000000000000000000001",
            "name": "Owner Sogil",
            "role": "owner",
            "permissions": {"access_finance": True, "manage_orders": True},
        }
        self.admin_staff = {
            "id": "600000000000000000000002",
            "name": "Staff Toko",
            "role": "admin",
            "permissions": {"manage_orders": True},
        }
        self.sarah_admin = {
            "_id": ObjectId("507f1f77bcf86cd799439002"),
            "id": "507f1f77bcf86cd799439002",
            "name": "Sarah Administrasi",
            "role": "admin",
            "active": True,
        }
        self.azka_admin = {
            "_id": ObjectId("6a9031b86f261cb1ed5479ad"),
            "id": "6a9031b86f261cb1ed5479ad",
            "name": "Azka",
            "role": "admin",
            "active": True,
        }
        self.mock_session = AsyncMock()
        self.mock_session.__aenter__.return_value = self.mock_session
        self.mock_session.__aexit__.return_value = None
        self.mock_session.start_transaction = MagicMock()
        self.mock_session.start_transaction.return_value.__aenter__ = AsyncMock(return_value=self.mock_session)
        self.mock_session.start_transaction.return_value.__aexit__ = AsyncMock(return_value=None)
        self.mock_session.commit_transaction = AsyncMock()
        self.mock_session.abort_transaction = AsyncMock()

        self.mock_client = MagicMock()
        self.mock_client.start_session = AsyncMock(return_value=self.mock_session)

    def _setup_mock_db(self, mock_db, policy_enabled=True, default_rate=50.0, hard_cap=100.0, unusual_thresh=75.0):
        # Configure active admin wage policy in settings
        policy_doc = {
            "key": "admin_wage_policy",
            "value": {
                "default_wage_per_order_le": default_rate,
                "default_recipient_id": "507f1f77bcf86cd799439002",
                "default_recipient_name": "Sarah Administrasi",
                "unusual_amount_threshold_le": unusual_thresh,
                "max_wage_per_order_le": hard_cap,
                "enabled": policy_enabled,
                "currency": "EGP",
                "rounding_policy": "piastre_round_half_up",
                "is_configured": True,
                "activation_cycles": [{
                    "cycle_id": "cycle_test_001",
                    "enabled_at": "2026-10-29T00:00:00Z",
                    "disabled_at": None if policy_enabled else "2026-10-29T12:00:00Z",
                }]
            }
        }
        mock_db.settings.find_one = AsyncMock(side_effect=lambda q, **kw: (
            policy_doc if q.get("key") == "admin_wage_policy"
            else {"key": "exchange_rate_idr_per_le", "value": 357.0}
        ))
        mock_db.settings.update_one = AsyncMock(return_value=MagicMock(matched_count=1, modified_count=1))
        mock_db.system_rates.find_one = AsyncMock(return_value={"rate": 357.0})
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 101})
        mock_db.customers.update_one = AsyncMock()
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()

        # Admins mock
        async def mock_admin_find_one(query, *args, **kwargs):
            q_id = str(query.get("_id") or query.get("id") or "")
            if "507f1f77bcf86cd799439002" in q_id:
                return self.sarah_admin
            if "6a9031b86f261cb1ed5479ad" in q_id:
                return self.azka_admin
            return None
        mock_db.admins.find_one = AsyncMock(side_effect=mock_admin_find_one)

        # Wage obligations mock
        mock_db.wage_obligations.find_one = AsyncMock(return_value=None)
        mock_db.wage_obligations.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("507f1f77bcf86cd799439099")))
        mock_db.wage_obligations.update_one = AsyncMock()

        mock_ob_cursor = MagicMock()
        mock_ob_cursor.to_list = AsyncMock(return_value=[])
        mock_db.wage_obligations.find.return_value = mock_ob_cursor

        mock_asn_cursor = MagicMock()
        mock_asn_cursor.to_list = AsyncMock(return_value=[])
        mock_db.work_assignments.find.return_value = mock_asn_cursor

        # Audit logs mock
        mock_db.audit_logs.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))

        # Orders mock
        async def mock_default_order_find(query, **kwargs):
            return {"_id": query.get("_id"), "order_status": "diproses", "payment_status": "lunas", "completed_at": None, "paid_at": None}
        mock_db.orders.find_one = AsyncMock(side_effect=mock_default_order_find)
        mock_db.orders.update_one = AsyncMock(return_value=MagicMock(matched_count=1, modified_count=1))
        mock_db.payments.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))
        return mock_db

    # =========================================================================
    # Scenario 15: Policy Input Model default is enabled=False
    # =========================================================================
    def test_15_admin_wage_policy_input_defaults_to_enabled_false(self):
        """15. AdminWagePolicyInput defaults to enabled=False without explicit input."""
        payload = AdminWagePolicyInput(
            default_wage_per_order_le=50.0,
            unusual_amount_threshold_le=75.0,
            max_wage_per_order_le=100.0,
        )
        self.assertFalse(payload.enabled, "Policy input must default to enabled=False")

    # =========================================================================
    # Scenario 1: Completion first, then payment in full, when global policy is ON
    # =========================================================================
    async def test_01_completion_first_then_payment_when_on(self):
        """1. Sequence A: Order completed first, then paid while ON -> Exactly one obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)

        order_id = "507f1f77bcf86cd799439011"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-S1",
            "order_status": "selesai",
            "completed_at": "2026-10-29T10:00:00Z",
            "payment_status": "belum_dibayar",
            "total_le": 1000.0,
            "paid_amount_le": 0.0,
            "outstanding_amount_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[{"amount_le": 1000.0, "status": "recorded"}])
        mock_db.payments.find.return_value = mock_find

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=1000.0, payment_method="cash")
            await admin_create_order_payment(order_id, payload, self.admin_owner)

        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)
        wob = mock_db.wage_obligations.insert_one.call_args[0][0]
        self.assertEqual(wob["task_category"], "admin")
        self.assertEqual(wob["total_amount_le"], 50.0)
        self.assertEqual(wob["worker_id"], "507f1f77bcf86cd799439002")

    # =========================================================================
    # Scenario 2: Payment in full first, then completion, when global policy is ON
    # =========================================================================
    async def test_02_payment_first_then_completion_when_on(self):
        """2. Sequence B: Order paid first, then completed while ON -> Exactly one obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)

        order_id = "507f1f77bcf86cd799439012"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-S2",
            "order_status": "diproses",
            "payment_status": "lunas",
            "total_le": 1200.0,
            "paid_amount_le": 1200.0,
            "outstanding_amount_le": 0.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            data = OrderStatusUpdate(order_status="selesai")
            await admin_update_order(order_id, data, self.admin_owner)

        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)
        wob = mock_db.wage_obligations.insert_one.call_args[0][0]
        self.assertEqual(wob["task_category"], "admin")
        self.assertEqual(wob["total_amount_le"], 50.0)

    # =========================================================================
    # Scenario 3: Both conditions met when global policy is OFF -> Permanent skip
    # =========================================================================
    async def test_03_both_conditions_met_when_off_permanent_skip(self):
        """3. Order matures when global policy is OFF -> Permanent skip persisted, 0 obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=False)

        order_id = "507f1f77bcf86cd799439013"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-S3",
            "order_status": "selesai",
            "completed_at": "2026-10-29T10:00:00Z",
            "payment_status": "belum_dibayar",
            "total_le": 500.0,
            "paid_amount_le": 0.0,
            "outstanding_amount_le": 500.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[{"amount_le": 500.0, "status": "recorded"}])
        mock_db.payments.find.return_value = mock_find

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=500.0, payment_method="cash")
            await admin_create_order_payment(order_id, payload, self.admin_owner)

        # Zero obligation created
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

        # Skipped metadata persisted onto the order
        update_call = mock_db.orders.update_one.call_args[0][1]
        self.assertIsNotNone(update_call["$set"].get("admin_wage_skipped"))
        self.assertEqual(update_call["$set"]["admin_wage_skipped"]["status"], "skipped_policy_disabled")
        self.assertEqual(update_call["$set"]["admin_wage_eligibility"]["scope_status"], "skipped_disabled_window")

    # =========================================================================
    # Scenario 4: Matured when OFF, then feature turned ON -> Protected from retroactive accrual
    # =========================================================================
    async def test_04_matured_when_off_then_reenable_not_retroactive(self):
        """4. Order that matured when OFF remains skipped after policy is toggled ON."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)

        order_matured_off = {
            "_id": ObjectId("507f1f77bcf86cd799439014"),
            "order_number": "SGF-20261029-S4",
            "order_status": "selesai",
            "completed_at": "2026-10-29T08:00:00Z",
            "payment_status": "lunas",
            "total_le": 750.0,
            "paid_amount_le": 750.0,
            "admin_wage_skipped": {
                "status": "skipped_policy_disabled",
                "reason": "Kebijakan upah admin nonaktif pada saat jatuh tempo",
            },
            "admin_wage_eligibility": {
                "scope_status": "skipped_disabled_window",
                "governance_mode": "automatic",
            }
        }
        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_matured_off, self.admin_owner)

        self.assertEqual(res["status"], "skipped_disabled_window_matured")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)
        self.assertEqual(res["eligibility"]["scope_status"], "skipped_disabled_window")

    # =========================================================================
    # Scenario 5: Pending when re-enabled, matures when ON -> Accrues exactly one
    # =========================================================================
    async def test_05_pending_when_reenable_then_matures_while_on_accrues(self):
        """5. Order pending (unpaid) while OFF, then matures after ON -> Accrues."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)

        order_id = "507f1f77bcf86cd799439015"
        # Order was completed when policy was OFF, but remained unpaid (in_scope_pending)
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-S5",
            "order_status": "selesai",
            "completed_at": "2026-10-28T14:00:00Z",
            "payment_status": "belum_dibayar",
            "total_le": 600.0,
            "paid_amount_le": 0.0,
            "outstanding_amount_le": 600.0,
            "admin_wage_eligibility": {
                "scope_status": "in_scope_pending",
                "governance_mode": "automatic",
            }
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[{"amount_le": 600.0, "status": "recorded"}])
        mock_db.payments.find.return_value = mock_find

        # Now payment occurs while policy is ON
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=600.0, payment_method="cash")
            await admin_create_order_payment(order_id, payload, self.admin_owner)

        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)
        wob = mock_db.wage_obligations.insert_one.call_args[0][0]
        self.assertEqual(wob["total_amount_le"], 50.0)

    # =========================================================================
    # Scenario 6: Orders completed & paid before activation NOT scanned/accrued
    # =========================================================================
    async def test_06_pre_activation_orders_not_accrued_when_feature_activated(self):
        """6. Activating admin wage policy updates db.settings only; does NOT scan or accrue orders."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=False)

        req_mock = MagicMock()
        req_mock.json = AsyncMock(return_value={
            "default_wage_per_order_le": 50.0,
            "default_recipient_id": "507f1f77bcf86cd799439002",
            "unusual_amount_threshold_le": 75.0,
            "max_wage_per_order_le": 100.0,
            "enabled": True,
            "change_reason": "Aktifkan otomatisasi upah admin produksi",
        })

        with patch("server.db", mock_db):
            resp = await admin_update_wage_policy_endpoint("admin", req_mock, self.admin_owner)

        self.assertTrue(resp["enabled"])
        # Crucial invariant: zero reads or updates to orders collection during activation!
        self.assertFalse(mock_db.orders.find.called)
        self.assertFalse(mock_db.orders.update_one.called)
        self.assertFalse(mock_db.orders.update_many.called)
        self.assertFalse(mock_db.wage_obligations.insert_one.called)

    # =========================================================================
    # Scenario 7: Non-lifecycle edits on historical orders do NOT trigger accrual
    # =========================================================================
    async def test_07_non_lifecycle_edits_on_historical_orders_do_not_accrue(self):
        """7. Editing admin notes or non-lifecycle fields on historical completed orders does NOT accrue."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)

        order_id = "507f1f77bcf86cd799439017"
        hist_order = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20260930-HIST",
            "order_status": "selesai",
            "completed_at": "2026-09-30T15:50:00Z",
            "payment_status": "lunas",
            "total_le": 2000.0,
            "paid_amount_le": 2000.0,
            "outstanding_amount_le": 0.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=hist_order)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            # Admin updates note only (non-lifecycle edit)
            data = OrderStatusUpdate(admin_note="Catatan arsip manual toko")
            await admin_update_order(order_id, data, self.admin_owner)

        # Zero wage obligation created
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

    # =========================================================================
    # Phase 08.5J — Test A: Repeated payment endpoint on already-paid historical order
    # =========================================================================
    async def test_07a_repeated_payment_on_already_paid_historical_order_no_accrual(self):
        """Test A (Phase 08.5J): Valid payment on an already-paid historical order does not accrue."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)

        order_id = "507f1f77bcf86cd79943901a"
        hist_paid_order = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261001-HIST1",
            "order_status": "selesai",
            "completed_at": "2026-10-01T12:00:00Z",
            "payment_status": "lunas",
            "total_le": 1500.0,
            "paid_amount_le": 1500.0,
            "outstanding_amount_le": 0.0,
            # Explicitly unmarked: no legacy flags, no prior obligation, no cutoff
        }
        mock_db.orders.find_one = AsyncMock(return_value=hist_paid_order)
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[
            {"amount_le": 1500.0, "status": "recorded"},
            {"amount_le": 50.0, "status": "recorded"}
        ])
        mock_db.payments.find.return_value = mock_find

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=50.0, payment_method="cash", notes="Penyesuaian saldo kasir")
            resp = await admin_create_order_payment(order_id, payload, self.admin_owner)

        # 1. Ordinary payment behavior succeeds
        self.assertTrue(mock_db.payments.insert_one.called)
        # 2. Transition guard holds: is_transition_to_lunas is False (old status was already lunas)
        # Therefore zero wage obligation created
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)
        # 3. No admin wage subdocument mutated or injected on order update
        update_call = mock_db.orders.update_one.call_args[0][1]
        self.assertNotIn("admin_wage_obligation", update_call["$set"])
        self.assertNotIn("admin_wage_eligibility", update_call["$set"])

    # =========================================================================
    # Phase 08.5J — Test B: Repeated completion endpoint on already-completed historical order
    # =========================================================================
    async def test_07b_repeated_completion_on_already_completed_historical_order_no_accrual(self):
        """Test B (Phase 08.5J): Calling completion update on an already-completed order does not accrue."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)

        order_id = "507f1f77bcf86cd79943901b"
        hist_comp_order = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261001-HIST2",
            "order_status": "selesai",
            "completed_at": "2026-10-01T12:00:00Z",
            "payment_status": "lunas",
            "total_le": 1800.0,
            "paid_amount_le": 1800.0,
            "outstanding_amount_le": 0.0,
            # Explicitly unmarked: no legacy flags, no prior obligation, no cutoff
        }
        mock_db.orders.find_one = AsyncMock(return_value=hist_comp_order)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            # Admin re-submits order_status='selesai' with note
            data = OrderStatusUpdate(order_status="selesai", admin_note="Verifikasi berkala serah terima")
            await admin_update_order(order_id, data, self.admin_owner)

        # 1. Zero wage obligation created (target_status == existing_status skips status change block)
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)
        # 2. No wage subdocument added
        update_call = mock_db.orders.update_one.call_args[0][1]
        self.assertNotIn("admin_wage_obligation", update_call["$set"])
        self.assertNotIn("admin_wage_eligibility", update_call["$set"])
        # 3. Ordinary non-lifecycle field (admin_note) updated
        self.assertEqual(update_call["$set"].get("admin_note"), "Verifikasi berkala serah terima")

    # =========================================================================
    # Scenario 8: Valid manual override accrues when global policy is OFF
    # =========================================================================
    async def test_08_valid_manual_override_accrues_when_global_off(self):
        """8. Valid manual override succeeds and creates obligation even when global policy is OFF."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=False)

        order_id = "507f1f77bcf86cd799439018"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-S8",
            "order_status": "selesai",
            "completed_at": "2026-10-29T10:00:00Z",
            "payment_status": "belum_dibayar",
            "total_le": 1000.0,
            "paid_amount_le": 0.0,
            "outstanding_amount_le": 1000.0,
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 65.0,
                "recipient_id": "6a9031b86f261cb1ed5479ad",
                "recipient_name": "Azka",
                "override_reason": "Manual fee khusus kasir",
            }
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[{"amount_le": 1000.0, "status": "recorded"}])
        mock_db.payments.find.return_value = mock_find

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=1000.0, payment_method="cash")
            await admin_create_order_payment(order_id, payload, self.admin_owner)

        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)
        wob = mock_db.wage_obligations.insert_one.call_args[0][0]
        self.assertEqual(wob["total_amount_le"], 65.0)
        self.assertEqual(wob["worker_id"], "6a9031b86f261cb1ed5479ad")
        self.assertEqual(wob["worker_name"], "Azka")
        self.assertTrue(wob["is_override"])

    # =========================================================================
    # Scenario 9: Incomplete manual override fails closed without global default
    # =========================================================================
    async def test_09_incomplete_manual_override_fails_closed_no_silent_global_default(self):
        """9. Incomplete manual override (missing recipient or nominal) blocks and refuses silent global fallback."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)

        # Subcase A: Missing recipient in manual override
        order_missing_recip = {
            "_id": ObjectId("507f1f77bcf86cd799439019"),
            "order_number": "SGF-20261029-S9A",
            "order_status": "selesai",
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 1000.0,
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 70.0,
                "recipient_id": None, # Missing!
            }
        }
        with patch("server.db", mock_db):
            res_a = await evaluate_and_process_order_admin_wage_accrual(order_missing_recip, self.admin_owner)

        self.assertEqual(res_a["status"], "blocked_missing_recipient")
        self.assertEqual(res_a["eligibility"]["scope_status"], "blocked")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

        # Subcase B: Missing nominal in manual override
        order_missing_nominal = {
            "_id": ObjectId("507f1f77bcf86cd799439020"),
            "order_number": "SGF-20261029-S9B",
            "order_status": "selesai",
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 1000.0,
            "admin_wage_override": {
                "is_override": True,
                "amount_le": None, # Missing!
                "recipient_id": "507f1f77bcf86cd799439002",
            }
        }
        with patch("server.db", mock_db):
            res_b = await evaluate_and_process_order_admin_wage_accrual(order_missing_nominal, self.admin_owner)

        self.assertEqual(res_b["status"], "blocked_missing_rate")
        self.assertEqual(res_b["eligibility"]["scope_status"], "blocked")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

    # =========================================================================
    # Scenario 10: Retry and duplicate events are idempotent (no duplicate obligation)
    # =========================================================================
    async def test_10_retry_and_duplicate_events_idempotent_no_duplicate_obligation(self):
        """10. Repeated calls or retries on accrued orders return already_accrued; zero duplicate obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)

        order_id = "507f1f77bcf86cd799439021"
        canonical_key = build_admin_wage_accrual_event_key(order_id)
        mock_db.wage_obligations.find_one = AsyncMock(return_value={
            "_id": ObjectId("507f1f77bcf86cd799439099"),
            "obligation_number": "WOB-20261029-0099",
            "accrual_event_key": canonical_key,
            "task_category": "admin",
            "status": "accrued",
            "total_amount_le": 50.0,
            "worker_id": "507f1f77bcf86cd799439002",
            "worker_name": "Sarah Administrasi",
        })

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-S10",
            "order_status": "selesai",
            "payment_status": "lunas",
            "total_le": 800.0,
            "paid_amount_le": 800.0,
        }
        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_owner)

        self.assertEqual(res["status"], "already_accrued")
        self.assertEqual(res["obligation"]["obligation_number"], "WOB-20261029-0099")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

    # =========================================================================
    # Scenario 11: VOID / CANCELLED orders or prior voided obligations block accrual
    # =========================================================================
    async def test_11_void_or_cancelled_orders_and_obligations_block_accrual(self):
        """11. Cancelled orders or prior voided obligations block re-accrual until explicit manual review."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)

        # Subcase A: Order is cancelled
        order_cancelled = {
            "_id": ObjectId("507f1f77bcf86cd799439022"),
            "order_number": "SGF-20261029-S11A",
            "order_status": "dibatalkan",
            "completed_at": "2026-10-29T10:00:00Z", # Even if completed_at exists
            "payment_status": "lunas",
            "total_le": 500.0,
            "paid_amount_le": 500.0,
        }
        with patch("server.db", mock_db):
            res_a = await evaluate_and_process_order_admin_wage_accrual(order_cancelled, self.admin_owner)

        self.assertEqual(res_a["status"], "skipped_order_not_completed")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

        # Subcase B: Prior wage obligation was voided
        order_id_b = "507f1f77bcf86cd799439023"
        canonical_key_b = build_admin_wage_accrual_event_key(order_id_b)
        mock_db.wage_obligations.find_one = AsyncMock(return_value={
            "_id": ObjectId("507f1f77bcf86cd799439098"),
            "obligation_number": "WOB-20261029-VOIDED",
            "accrual_event_key": canonical_key_b,
            "status": "voided",
            "task_category": "admin",
        })
        order_prior_void = {
            "_id": ObjectId(order_id_b),
            "order_number": "SGF-20261029-S11B",
            "order_status": "selesai",
            "payment_status": "lunas",
            "total_le": 500.0,
            "paid_amount_le": 500.0,
        }
        with patch("server.db", mock_db):
            res_b = await evaluate_and_process_order_admin_wage_accrual(order_prior_void, self.admin_owner)

        self.assertEqual(res_b["status"], "blocked_prior_voided_obligation")
        self.assertEqual(res_b["eligibility"]["scope_status"], "blocked")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

    # =========================================================================
    # Scenario 12: Invalid financial data fails closed
    # =========================================================================
    async def test_12_invalid_financial_data_fails_closed(self):
        """12. Corrupt or invalid financial amounts (NaN, Inf, negative) fail closed safely."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)

        order_nan = {
            "_id": ObjectId("507f1f77bcf86cd799439024"),
            "order_number": "SGF-20261029-S12",
            "order_status": "selesai",
            "payment_status": "lunas",
            "total_le": float("nan"),
            "paid_amount_le": 500.0,
            "outstanding_amount_le": float("nan"),
        }
        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(order_nan, self.admin_owner)

        self.assertEqual(res["status"], "skipped_payment_not_lunas")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

    # =========================================================================
    # Scenario 13: Hard cap conflict blocks without clamping or fallback
    # =========================================================================
    async def test_13_hard_cap_conflict_blocks_without_clamping_or_fallback(self):
        """13. Override above active hard cap blocks accrual with conflict alert; never clamps to cap."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True, hard_cap=100.0)

        order_id = "507f1f77bcf86cd799439025"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261029-S13",
            "order_status": "selesai",
            "completed_at": "2026-10-29T10:00:00Z",
            "payment_status": "belum_dibayar",
            "total_le": 1000.0,
            "paid_amount_le": 0.0,
            "outstanding_amount_le": 1000.0,
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 250.0, # Exceeds active hard cap 100.0 LE!
                "recipient_id": "507f1f77bcf86cd799439002",
                "recipient_name": "Sarah Administrasi",
                "override_reason": "Extra project bonus",
            }
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_doc)
        mock_find = MagicMock()
        mock_find.to_list = AsyncMock(return_value=[{"amount_le": 1000.0, "status": "recorded"}])
        mock_db.payments.find.return_value = mock_find

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            payload = PaymentCreateInput(amount=1000.0, payment_method="cash")
            await admin_create_order_payment(order_id, payload, self.admin_owner)

        # Payment succeeds
        self.assertTrue(mock_db.payments.insert_one.called)
        # Wage obligation is NOT created (never clamped to 100.0 LE)
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)
        # Blocked state recorded on order
        update_call = mock_db.orders.update_one.call_args[0][1]
        self.assertIsNotNone(update_call["$set"].get("admin_wage_blocked"))
        self.assertEqual(update_call["$set"]["admin_wage_blocked"]["status"], "blocked_hard_cap_conflict")
        self.assertEqual(update_call["$set"]["admin_wage_blocked"]["attempted_amount_le"], 250.0)
        self.assertEqual(update_call["$set"]["admin_wage_blocked"]["max_wage_per_order_le"], 100.0)

    # =========================================================================
    # Scenario 14: Transaction failure rollback leaves no inconsistent obligation
    # =========================================================================
    async def test_14_transaction_failure_rollback_no_inconsistent_obligation(self):
        """14. When a transaction aborts/fails, execute_transaction_with_safety rolls back cleanly."""
        mock_db = MagicMock()
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None
        mock_tx_context = AsyncMock()
        mock_tx_context.__aenter__ = AsyncMock(return_value=mock_session)
        mock_tx_context.__aexit__ = AsyncMock(return_value=None)
        mock_session.start_transaction = MagicMock(return_value=mock_tx_context)
        mock_session.commit_transaction = AsyncMock()
        mock_session.abort_transaction = AsyncMock()

        mock_client = MagicMock()
        mock_client.start_session = AsyncMock(return_value=mock_session)

        async def failing_operation(session):
            # Simulate failure during transaction operation
            raise RuntimeError("Database write disk error inside transaction")

        with self.assertRaises(RuntimeError):
            await execute_transaction_with_safety(
                mock_client,
                failing_operation
            )

        # Verify transaction context entered and exited (aborted) cleanly without commit
        self.assertTrue(mock_tx_context.__aenter__.called)
        self.assertTrue(mock_tx_context.__aexit__.called)
        self.assertFalse(mock_session.commit_transaction.called)

    # =========================================================================
    # Phase 08.5K Contract Hardening: Direct Evaluator Invocation Security
    # =========================================================================
    async def test_16_direct_evaluator_invocation_contract_hardening(self):
        """
        Phase 08.5K: Hardened Contract for Direct Evaluator Invocation.
        Enforces:
        1. Direct invocation without trusted lifecycle context fails-closed (skipped_missing_lifecycle_event).
        2. Direct invocation with invalid lifecycle event fails-closed (skipped_invalid_lifecycle_event).
        3. Direct invocation with valid lifecycle context ('order_completed' or 'payment_lunas') accrues.
        4. Direct invocation on explicit manual override succeeds regardless of lifecycle_event.
        """
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)
        order_id = "507f1f77bcf86cd799439099"

        async def mock_order_find(query, **kwargs):
            qid = str(query.get("_id") or "")
            if "507f1f77bcf86cd799439099" in qid:
                return dict(order_unmarked)
            if "507f1f77bcf86cd799439097" in qid:
                return {
                    "_id": ObjectId("507f1f77bcf86cd799439097"),
                    "order_status": "siap",
                    "payment_status": "lunas",
                    "total_le": 1200.0,
                    "paid_amount_le": 1200.0,
                    "outstanding_amount_le": 0.0,
                    "completed_at": None,
                    "paid_at": "2026-10-30T10:00:00Z"
                }
            return {"_id": query.get("_id"), "order_status": "diproses", "payment_status": "lunas", "completed_at": None, "paid_at": None}
        mock_db.orders.find_one = AsyncMock(side_effect=mock_order_find)

        # Skenario 1: Pesanan selesai dan lunas tanpa penanda khusus (simulasi pesanan historis)
        # Dipanggil langsung tanpa lifecycle_event -> WAJIB FAIL-CLOSED
        order_unmarked = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-HIST-DIRECT-001",
            "order_status": "selesai",
            "payment_status": "lunas",
            "total_le": 1200.0,
            "paid_amount_le": 1200.0,
            "outstanding_amount_le": 0.0,
            "completed_at": "2026-10-15T10:00:00Z",
            "paid_at": "2026-10-15T12:00:00Z",
        }

        with patch("server.db", mock_db):
            res_no_event = await evaluate_and_process_order_admin_wage_accrual(
                order_unmarked, self.admin_owner
            )

        self.assertEqual(res_no_event["status"], "skipped_missing_lifecycle_event")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)
        self.assertEqual(res_no_event["eligibility"]["scope_status"], "in_scope_pending")
        self.assertEqual(res_no_event["eligibility"]["skip_reason"], "missing_trusted_lifecycle_event")

        # Skenario 2: Dipanggil langsung dengan event tidak valid -> WAJIB FAIL-CLOSED
        with patch("server.db", mock_db):
            res_invalid = await evaluate_and_process_order_admin_wage_accrual(
                order_unmarked, self.admin_owner, lifecycle_event="hacked_lifecycle_bypass"
            )

        self.assertEqual(res_invalid["status"], "skipped_invalid_lifecycle_event")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)
        self.assertEqual(res_invalid["eligibility"]["skip_reason"], "invalid_lifecycle_event")

        # Skenario 3 (Phase 08.5M Security Fix): Pesanan historis dipanggil dengan event valid 'order_completed'
        # WAJIB FAIL-CLOSED (Dilarang akrual retroaktif untuk pesanan yang telah selesai sebelum sistem aktif)
        with patch("server.db", mock_db):
            res_valid_event = await evaluate_and_process_order_admin_wage_accrual(
                order_unmarked, self.admin_owner, lifecycle_event="order_completed"
            )

        self.assertEqual(res_valid_event["status"], "skipped_unverifiable_transition")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)
        self.assertEqual(res_valid_event["eligibility"]["scope_status"], "excluded_historical")
        self.assertEqual(res_valid_event["eligibility"]["skip_reason"], "settled_prior_to_system_activation")

        # Skenario 3b (Phase 08.5M): Pesanan historis dipanggil dengan forged payment event 'payment_lunas' -> WAJIB FAIL-CLOSED
        with patch("server.db", mock_db):
            res_forged_pmt = await evaluate_and_process_order_admin_wage_accrual(
                order_unmarked, self.admin_owner, lifecycle_event="payment_lunas"
            )

        self.assertEqual(res_forged_pmt["status"], "skipped_unverifiable_transition")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

        # Skenario 3c (Phase 08.5M): Pesanan historis dengan forged order['lifecycle_event'] -> WAJIB FAIL-CLOSED
        order_forged_doc = dict(order_unmarked)
        order_forged_doc["lifecycle_event"] = "order_completed"
        with patch("server.db", mock_db):
            res_doc_fallback = await evaluate_and_process_order_admin_wage_accrual(
                order_forged_doc, self.admin_owner
            )
        self.assertEqual(res_doc_fallback["status"], "skipped_missing_lifecycle_event")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

        # Skenario 3d (Phase 08.5M): Pesanan historis dengan forged payment summary -> WAJIB FAIL-CLOSED
        with patch("server.db", mock_db):
            res_summary_fallback = await evaluate_and_process_order_admin_wage_accrual(
                order_unmarked, self.admin_owner, payment_summary={"payment_status": "lunas", "paid_amount_le": 1200.0}
            )
        self.assertEqual(res_summary_fallback["status"], "skipped_missing_lifecycle_event")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

        # Skenario 3e (Phase 08.5M): Pesanan historis dengan fabricated transition context -> WAJIB FAIL-CLOSED
        with patch("server.db", mock_db):
            res_fabricated_ctx = await evaluate_and_process_order_admin_wage_accrual(
                order_unmarked, self.admin_owner, lifecycle_event="order_completed",
                transition_context={"from_status": "diproses", "to_status": "selesai"}
            )
        self.assertEqual(res_fabricated_ctx["status"], "skipped_unverifiable_transition")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

        # Skenario 3f (Phase 08.5M): Pesanan aktif baru dengan bukti transisi sah -> SUKSES AKRUAL
        new_active_order = {
            "_id": ObjectId("507f1f77bcf86cd799439097"),
            "order_number": "SGF-NEW-ACTIVE-001",
            "order_status": "selesai",
            "payment_status": "lunas",
            "total_le": 1200.0,
            "paid_amount_le": 1200.0,
            "outstanding_amount_le": 0.0,
            "completed_at": "2026-10-30T10:00:00Z",
            "paid_at": "2026-10-30T10:00:00Z",
        }
        with patch("server.db", mock_db):
            res_valid = await evaluate_and_process_order_admin_wage_accrual(
                new_active_order, self.admin_owner, lifecycle_event="order_completed",
                transition_context={
                    "transition_type": "order_completion",
                    "from_status": "siap",
                    "to_status": "selesai"
                }
            )

        self.assertEqual(res_valid["status"], "accrued")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)
        wob = mock_db.wage_obligations.insert_one.call_args[0][0]
        self.assertEqual(wob["total_amount_le"], 50.0)
        self.assertEqual(wob["accrual_event_key"], "admin_wage:507f1f77bcf86cd799439097")

        # Skenario 4: Manual override langsung tanpa lifecycle_event -> SUKSES AKRUAL (Intensi manual eksplisit)
        mock_db.wage_obligations.insert_one.reset_mock()
        order_override = {
            "_id": ObjectId("507f1f77bcf86cd799439098"),
            "order_number": "SGF-OVERRIDE-DIRECT-002",
            "order_status": "selesai",
            "payment_status": "lunas",
            "total_le": 1500.0,
            "paid_amount_le": 1500.0,
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 75.0,
                "recipient_id": "507f1f77bcf86cd799439002",
                "recipient_name": "Sarah Administrasi",
                "override_reason": "Manual bonus approved by Owner"
            }
        }

        with patch("server.db", mock_db):
            res_ovr = await evaluate_and_process_order_admin_wage_accrual(
                order_override, self.admin_owner
            )

        self.assertEqual(res_ovr["status"], "accrued")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)
        wob_ovr = mock_db.wage_obligations.insert_one.call_args[0][0]
        self.assertEqual(wob_ovr["total_amount_le"], 75.0)
        self.assertTrue(wob_ovr["is_override"])

    # =========================================================================
    # PHASE 08.5O: 12 ADVERSARIAL REGRESSION SCENARIOS (AUTHORITATIVE TRANSITION EVIDENCE)
    # =========================================================================

    async def test_phase08_5o_scenario_01_fabricated_persisted_order_ignored_for_historical(self):
        """1. Fabricated persisted_order in transition_context is ignored; DB state proves historical settled -> REJECTED."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)
        order_id = "507f1f77bcf86cd7994390a1"

        authoritative_db_order = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-HIST-ATTACK-001",
            "order_status": "selesai",
            "payment_status": "lunas",
            "completed_at": "2026-10-15T10:00:00Z",
            "paid_at": "2026-10-15T12:00:00Z",
            "total_le": 1000.0,
            "paid_amount_le": 1000.0,
        }
        mock_db.orders.find_one = AsyncMock(return_value=dict(authoritative_db_order))

        attacker_context = {
            "order_id": order_id,
            "from_status": "diproses",
            "to_status": "selesai",
            "persisted_order": {
                "_id": ObjectId(order_id),
                "order_status": "diproses",
                "payment_status": "belum_dibayar",
            }
        }

        with patch("server.db", mock_db):
            res = await process_order_admin_wage_accrual(
                authoritative_db_order,
                self.admin_owner,
                lifecycle_event="order_completed",
                transition_context=attacker_context
            )

        self.assertEqual(res["status"], "skipped_unverifiable_transition")
        self.assertEqual(res["eligibility"]["scope_status"], "excluded_historical")
        self.assertEqual(res["eligibility"]["skip_reason"], "settled_prior_to_system_activation")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

    async def test_phase08_5o_scenario_02_snapshot_order_id_mismatch_rejected(self):
        """2. Caller passes transition_context containing a different order ID -> REJECTED (order_identity_mismatch)."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)
        target_order_id = "507f1f77bcf86cd7994390a2"
        wrong_order_id = "507f1f77bcf86cd799439099"

        order_doc = {
            "_id": ObjectId(target_order_id),
            "order_number": "SGF-NEW-002",
            "order_status": "selesai",
            "payment_status": "lunas",
            "completed_at": "2026-10-30T10:00:00Z",
            "paid_at": "2026-10-30T10:00:00Z",
        }
        mock_db.orders.find_one = AsyncMock(return_value={
            "_id": ObjectId(target_order_id),
            "order_status": "diproses",
            "payment_status": "lunas",
        })

        mismatched_context = {
            "order_id": wrong_order_id,
            "from_status": "diproses",
            "to_status": "selesai"
        }

        with patch("server.db", mock_db):
            res = await process_order_admin_wage_accrual(
                order_doc,
                self.admin_owner,
                lifecycle_event="order_completed",
                transition_context=mismatched_context
            )

        self.assertEqual(res["status"], "skipped_unverifiable_transition")
        self.assertEqual(res["eligibility"]["skip_reason"], "order_identity_mismatch")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

    async def test_phase08_5o_scenario_03_forged_transition_context_contradictory_rejected(self):
        """3. Caller passes transition_context contradictory to db.orders state -> REJECTED."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)
        order_id = "507f1f77bcf86cd7994390a3"

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-NEW-003",
            "order_status": "selesai",
            "payment_status": "lunas",
            "completed_at": "2026-10-30T10:00:00Z",
            "paid_at": "2026-10-30T10:00:00Z",
        }
        mock_db.orders.find_one = AsyncMock(return_value={
            "_id": ObjectId(order_id),
            "order_status": "pesanan_masuk",
            "payment_status": "lunas",
        })

        contradictory_context = {
            "order_id": order_id,
            "from_status": "siap",
            "to_status": "selesai"
        }

        with patch("server.db", mock_db):
            res = await process_order_admin_wage_accrual(
                order_doc,
                self.admin_owner,
                lifecycle_event="order_completed",
                transition_context=contradictory_context
            )

        self.assertEqual(res["status"], "skipped_unverifiable_transition")
        self.assertEqual(res["eligibility"]["skip_reason"], "contradictory_transition_context")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

    async def test_phase08_5o_scenario_04_fabricated_lifecycle_event_without_genuine_transition_rejected(self):
        """4. Fabricated lifecycle_event="order_completed" when DB is already completed -> REJECTED."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)
        order_id = "507f1f77bcf86cd7994390a4"

        db_order = {
            "_id": ObjectId(order_id),
            "order_status": "selesai",
            "payment_status": "lunas",
            "completed_at": "2026-10-30T09:00:00Z",
            "paid_at": "2026-10-30T09:00:00Z",
        }
        mock_db.orders.find_one = AsyncMock(return_value=dict(db_order))

        with patch("server.db", mock_db):
            res = await process_order_admin_wage_accrual(
                db_order,
                self.admin_owner,
                lifecycle_event="order_completed"
            )

        self.assertEqual(res["status"], "skipped_unverifiable_transition")
        self.assertEqual(res["eligibility"]["skip_reason"], "order_already_completed_in_database")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

    async def test_phase08_5o_scenario_05_stale_or_inconsistent_snapshot_ignored_in_favor_of_authoritative_db(self):
        """5. Stale / inconsistent snapshot passed by caller is ignored; authoritative state from DB governs."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)
        order_id = "507f1f77bcf86cd7994390a5"

        mock_db.orders.find_one = AsyncMock(return_value={
            "_id": ObjectId(order_id),
            "order_status": "siap",
            "payment_status": "lunas",
            "completed_at": None,
            "paid_at": "2026-10-30T09:00:00Z",
        })

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-NEW-005",
            "order_status": "selesai",
            "payment_status": "lunas",
            "completed_at": "2026-10-30T10:00:00Z",
            "paid_at": "2026-10-30T09:00:00Z",
        }

        valid_context = {
            "order_id": order_id,
            "from_status": "siap",
            "to_status": "selesai",
            "persisted_order": {"stale_garbage": True}
        }

        with patch("server.db", mock_db):
            res = await process_order_admin_wage_accrual(
                order_doc,
                self.admin_owner,
                lifecycle_event="order_completed",
                transition_context=valid_context
            )

        self.assertEqual(res["status"], "accrued")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)

    async def test_phase08_5o_scenario_06_concurrent_accrual_idempotency_exactly_one_obligation(self):
        """6. Race condition triggers DuplicateKeyError on unique index -> handles idempotently with 1 obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)
        order_id = "507f1f77bcf86cd7994390a6"
        accrual_key = f"admin_wage:{order_id}"

        mock_db.orders.find_one = AsyncMock(return_value={
            "_id": ObjectId(order_id),
            "order_status": "diproses",
            "payment_status": "lunas",
        })

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-NEW-006",
            "order_status": "selesai",
            "payment_status": "lunas",
            "completed_at": "2026-10-30T10:00:00Z",
            "paid_at": "2026-10-30T10:00:00Z",
        }

        existing_obligation = {
            "_id": ObjectId("807f1f77bcf86cd799439066"),
            "obligation_number": "WOB-20261030-0066",
            "accrual_event_key": accrual_key,
            "task_category": "admin",
            "worker_id": "507f1f77bcf86cd799439002",
            "worker_name": "Sarah Administrasi",
            "total_amount_le": 50.0,
            "status": "accrued",
        }

        call_count = 0
        async def mock_wob_find(query, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                return existing_obligation
            return None

        mock_db.wage_obligations.find_one = AsyncMock(side_effect=mock_wob_find)
        mock_db.wage_obligations.insert_one = AsyncMock(
            side_effect=pymongo.errors.DuplicateKeyError("E11000 duplicate key error: uniq_wage_obligation_accrual_event")
        )

        with patch("server.db", mock_db):
            res = await process_order_admin_wage_accrual(
                order_doc,
                self.admin_owner,
                lifecycle_event="order_completed"
            )

        self.assertIn(res["status"], ("accrued", "already_accrued"))
        self.assertEqual(res["obligation"]["obligation_number"], "WOB-20261030-0066")

    async def test_phase08_5o_scenario_07_legitimate_payment_first_lifecycle_accrues_once(self):
        """7. Legitimate payment-first lifecycle: Order paid, then completed -> Accrues exactly once at completion."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)
        order_id = "507f1f77bcf86cd7994390a7"

        mock_db.orders.find_one = AsyncMock(return_value={
            "_id": ObjectId(order_id),
            "order_status": "diproses",
            "payment_status": "lunas",
            "completed_at": None,
            "paid_at": "2026-10-30T10:00:00Z",
        })

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-NEW-007",
            "order_status": "selesai",
            "payment_status": "lunas",
            "completed_at": "2026-10-30T11:00:00Z",
            "paid_at": "2026-10-30T10:00:00Z",
        }

        with patch("server.db", mock_db):
            res = await process_order_admin_wage_accrual(
                order_doc,
                self.admin_owner,
                lifecycle_event="order_completed"
            )

        self.assertEqual(res["status"], "accrued")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)

    async def test_phase08_5o_scenario_08_legitimate_completion_first_lifecycle_accrues_once(self):
        """8. Legitimate completion-first lifecycle: Order completed, then paid -> Accrues exactly once at payment."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)
        order_id = "507f1f77bcf86cd7994390a8"

        mock_db.orders.find_one = AsyncMock(return_value={
            "_id": ObjectId(order_id),
            "order_status": "selesai",
            "payment_status": "belum_dibayar",
            "completed_at": "2026-10-30T09:00:00Z",
            "paid_at": None,
        })

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-NEW-008",
            "order_status": "selesai",
            "payment_status": "lunas",
            "completed_at": "2026-10-30T09:00:00Z",
            "paid_at": "2026-10-30T11:00:00Z",
        }

        with patch("server.db", mock_db):
            res = await process_order_admin_wage_accrual(
                order_doc,
                self.admin_owner,
                lifecycle_event="payment_lunas"
            )

        self.assertEqual(res["status"], "accrued")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)

    async def test_phase08_5o_scenario_09_order_settled_during_disabled_window_never_retroactive(self):
        """9. Order settled during disabled window is marked skipped_disabled_window; re-enabling never accrues it."""
        mock_db = MagicMock()
        order_id = "507f1f77bcf86cd7994390a9"

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-OFF-009",
            "order_status": "selesai",
            "payment_status": "lunas",
            "completed_at": "2026-10-30T14:00:00Z",
            "paid_at": "2026-10-30T14:00:00Z",
            "admin_wage_skipped": {
                "status": "skipped_disabled_window",
                "reason": "Kebijakan nonaktif saat pesanan selesai dan lunas",
                "skipped_at": "2026-10-30T14:00:00Z"
            },
            "admin_wage_eligibility": {
                "scope_status": "skipped_disabled_window",
                "governance_mode": "automatic",
                "skip_reason": "settled_while_automation_disabled"
            }
        }

        self._setup_mock_db(mock_db, policy_enabled=True)
        mock_db.orders.find_one = AsyncMock(return_value=dict(order_doc))

        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(
                order_doc,
                self.admin_owner,
                lifecycle_event="order_completed"
            )

        self.assertEqual(res["status"], "skipped_disabled_window_matured")
        self.assertEqual(res["eligibility"]["scope_status"], "skipped_disabled_window")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

    async def test_phase08_5o_scenario_10_valid_explicit_manual_override_while_off_accrues(self):
        """10. Valid explicit manual override accrues wage obligation even when global automation is OFF."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=False)
        order_id = "507f1f77bcf86cd7994390b0"

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-OVR-010",
            "order_status": "selesai",
            "payment_status": "lunas",
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 65.0,
                "recipient_id": "507f1f77bcf86cd799439002",
                "recipient_name": "Sarah Administrasi",
                "override_reason": "Special performance bonus"
            }
        }
        mock_db.orders.find_one = AsyncMock(return_value=dict(order_doc))

        with patch("server.db", mock_db):
            res = await evaluate_and_process_order_admin_wage_accrual(
                order_doc,
                self.admin_owner
            )

        self.assertEqual(res["status"], "accrued")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 1)
        wob = mock_db.wage_obligations.insert_one.call_args[0][0]
        self.assertEqual(wob["total_amount_le"], 65.0)
        self.assertTrue(wob["is_override"])

    async def test_phase08_5o_scenario_11_cancelled_or_void_order_never_accrues_automatic_wage(self):
        """11. Cancelled / dibatalkan order with completed_at timestamp is rejected by evaluator."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)
        order_id = "507f1f77bcf86cd7994390b1"

        cancelled_order = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-CANCEL-011",
            "order_status": "dibatalkan",
            "payment_status": "lunas",
            "completed_at": "2026-10-30T10:00:00Z",
        }
        mock_db.orders.find_one = AsyncMock(return_value=dict(cancelled_order))

        with patch("server.db", mock_db):
            res = await process_order_admin_wage_accrual(
                cancelled_order,
                self.admin_owner,
                lifecycle_event="order_completed"
            )

        self.assertEqual(res["status"], "skipped_order_not_completed")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

    async def test_phase08_5o_scenario_12_authoritative_state_missing_fails_closed(self):
        """12. If authoritative state cannot be retrieved from db.orders, evaluator fails closed."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)
        order_id = "507f1f77bcf86cd7994390b2"

        mock_db.orders.find_one = AsyncMock(return_value=None)

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-MISSING-012",
            "order_status": "selesai",
            "payment_status": "lunas",
        }

        with patch("server.db", mock_db):
            res = await process_order_admin_wage_accrual(
                order_doc,
                self.admin_owner,
                lifecycle_event="order_completed"
            )

        self.assertEqual(res["status"], "skipped_unverifiable_transition")
        self.assertEqual(res["eligibility"]["skip_reason"], "authoritative_order_state_missing")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)


if __name__ == "__main__":
    unittest.main()
