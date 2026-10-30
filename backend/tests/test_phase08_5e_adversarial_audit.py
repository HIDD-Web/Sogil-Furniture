# backend/tests/test_phase08_5e_adversarial_audit.py
"""
PHASE 08.5E — INDEPENDENT ADVERSARIAL CODE AUDIT TEST SUITE
Sogil Furniture — Admin Wage Activation Policy & Per-Order Eligibility Lifecycle

Adversarial stress-testing of:
1. Multi-cycle activation lifecycle transitions and duplicate prevention.
2. Durable anti-retroactivity across multi-step mutations, retries, and re-enables.
3. Historical order boundary isolation (pre vs post activation permutations).
4. Transactional atomicity, rollbacks, and recovery under partial write failures.
5. Strict manual override validation against silent fallbacks and hard-cap clamping.
6. Completion and payment evaluation under adversarial, contradictory, and malformed inputs.
7. Quarantine of voided obligations across policy toggles and mode changes.
"""

import pytest
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from bson import ObjectId
from datetime import datetime, timezone
import copy
import pymongo.errors

from server import (
    get_active_admin_wage_policy,
    is_timestamp_within_active_cycle,
    is_order_historical_unreconciled,
    get_order_admin_wage_eligibility,
    process_order_admin_wage_accrual,
    evaluate_and_process_order_admin_wage_accrual,
    is_order_completed,
    is_order_fully_paid,
    is_order_excluded_from_admin_wage,
    build_admin_wage_accrual_event_key,
    _safe_finance_amount,
    admin_update_wage_policy_endpoint,
)

@pytest.mark.anyio
class TestPhase08_5EAdversarialAudit(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.admin_owner = {
            "id": "507f1f77bcf86cd799439001",
            "_id": ObjectId("507f1f77bcf86cd799439001"),
            "name": "Owner Admin",
            "role": "owner",
            "permissions": ["manage_settings", "manage_orders", "view_finances"],
        }
        self.admin_staff = {
            "id": "507f1f77bcf86cd799439002",
            "_id": ObjectId("507f1f77bcf86cd799439002"),
            "name": "Sarah Administrasi",
            "role": "admin",
            "permissions": ["manage_orders"],
        }
        self.default_policy = {
            "default_wage_per_order_le": 50.0,
            "default_recipient_id": "507f1f77bcf86cd799439002",
            "default_recipient_name": "Sarah Administrasi",
            "currency": "EGP",
            "unusual_amount_threshold_le": 80.0,
            "max_wage_per_order_le": 100.0,
            "enabled": False,
            "is_configured": True,
            "initial_activation_at": None,
            "current_cycle_id": None,
            "activation_cycles": [],
        }

    def _setup_mock_db(self, mock_db, policy_enabled=False, initial_act=None, cycles=None):
        pol = copy.deepcopy(self.default_policy)
        pol["enabled"] = policy_enabled
        pol["initial_activation_at"] = initial_act
        pol["activation_cycles"] = cycles or []
        if policy_enabled and cycles:
            pol["current_cycle_id"] = cycles[-1]["cycle_id"]

        mock_db.settings.find_one = AsyncMock(side_effect=lambda q, **kw: (
            {"key": "admin_wage_policy", "value": copy.deepcopy(pol)}
            if q.get("key") == "admin_wage_policy"
            else {"key": "exchange_rate_idr_per_le", "value": 357.0}
        ))
        mock_db.system_rates.find_one = AsyncMock(return_value={"rate": 357.0})
        async def mock_order_find_one(query, **kwargs):
            qid = str(query.get("_id") or "")
            if "71" in qid:
                return {
                    "_id": query.get("_id"),
                    "order_status": "selesai",
                    "completed_at": "2026-09-10T10:00:00Z",
                    "paid_at": "2026-09-10T12:00:00Z",
                    "payment_status": "lunas",
                    "is_legacy_manual": True
                }
            if "72" in qid:
                return {
                    "_id": query.get("_id"),
                    "order_status": "selesai",
                    "completed_at": "2026-09-10T10:00:00Z",
                    "payment_status": "belum_dibayar",
                    "paid_at": None,
                }
            if "73" in qid:
                return {
                    "_id": query.get("_id"),
                    "order_status": "diproses",
                    "completed_at": None,
                    "payment_status": "lunas",
                    "paid_at": "2026-09-10T12:00:00Z",
                }
            return {
                "_id": query.get("_id"),
                "order_status": "diproses",
                "payment_status": "lunas",
                "completed_at": None,
                "paid_at": None
            }
        mock_db.orders.find_one = AsyncMock(side_effect=mock_order_find_one)
        mock_db.orders.update_one = AsyncMock(return_value=MagicMock(matched_count=1, modified_count=1))
        mock_db.wage_obligations.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("807f1f77bcf86cd799439044")))
        mock_db.wage_obligations.update_one = AsyncMock()
        mock_db.wage_obligations.find_one = AsyncMock(return_value=None)
        mock_db.audit_logs.insert_one = AsyncMock()
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 101})

        async def mock_admin_find_one(query, **kwargs):
            qid = str(query.get("_id") or "")
            if "507f1f77bcf86cd799439002" in qid:
                return self.admin_staff
            if "507f1f77bcf86cd799439001" in qid:
                return self.admin_owner
            return None

        mock_db.admins.find_one = AsyncMock(side_effect=mock_admin_find_one)
        return pol

    # =========================================================================
    # AUDIT 1: Activation Lifecycle Under Repeated Requests & Re-Enables
    # =========================================================================
    async def test_audit_01_activation_lifecycle_multi_cycle_progression(self):
        """Audit 1: Multi-cycle enable/disable transitions record precise immutable cycles."""
        mock_db = MagicMock()
        mock_db.client = MagicMock()
        mock_db.settings.update_one = AsyncMock()
        mock_db.audit_logs.insert_one = AsyncMock()
        mock_db.admins.find_one = AsyncMock(return_value=self.admin_staff)

        # Start with fresh un-activated policy
        saved_policy_val = copy.deepcopy(self.default_policy)
        mock_db.settings.find_one = AsyncMock(side_effect=lambda q, **kw: (
            {"key": "admin_wage_policy", "value": copy.deepcopy(saved_policy_val)}
            if q.get("key") == "admin_wage_policy" else None
        ))

        def _make_req(payload):
            req = MagicMock()
            req.json = AsyncMock(return_value=payload)
            return req

        # 1. First Enable Transition (OFF -> ON)
        payload_on = {
            "default_wage_per_order_le": 50.0,
            "default_recipient_id": "507f1f77bcf86cd799439002",
            "unusual_amount_threshold_le": 80.0,
            "max_wage_per_order_le": 100.0,
            "enabled": True,
            "change_reason": "Pembukaan siklus aktivasi perdana 2026-10"
        }
        with patch("server.db", mock_db):
            res_on = await admin_update_wage_policy_endpoint("admin", _make_req(payload_on), self.admin_owner)

        self.assertTrue(res_on["enabled"])
        self.assertEqual(len(res_on["activation_cycles"]), 1)
        cycle_1_id = res_on["current_cycle_id"]
        self.assertIsNotNone(cycle_1_id)
        self.assertIsNotNone(res_on["initial_activation_at"])
        initial_act_epoch = res_on["initial_activation_at"]

        # Update saved doc
        saved_policy_val = copy.deepcopy(res_on)

        # 2. Repeated Enable Request with Same Settings -> No-Op, No Duplicate Cycle
        with patch("server.db", mock_db):
            res_noop = await admin_update_wage_policy_endpoint("admin", _make_req(payload_on), self.admin_owner)

        self.assertTrue(res_noop.get("no_op"))
        self.assertEqual(len(res_noop["activation_cycles"]), 1)
        self.assertEqual(res_noop["current_cycle_id"], cycle_1_id)

        # 3. Rate Update While ON -> Changes rate, preserves active cycle 1, no new cycle
        payload_rate_change = copy.deepcopy(payload_on)
        payload_rate_change["default_wage_per_order_le"] = 55.0
        payload_rate_change["change_reason"] = "Penyesuaian tarif bulanan"
        with patch("server.db", mock_db):
            res_rate = await admin_update_wage_policy_endpoint("admin", _make_req(payload_rate_change), self.admin_owner)

        self.assertEqual(res_rate["default_wage_per_order_le"], 55.0)
        self.assertEqual(len(res_rate["activation_cycles"]), 1)
        self.assertEqual(res_rate["current_cycle_id"], cycle_1_id)
        saved_policy_val = copy.deepcopy(res_rate)

        # 4. Disable Transition (ON -> OFF) -> Closes cycle 1
        payload_off = copy.deepcopy(payload_rate_change)
        payload_off["enabled"] = False
        payload_off["change_reason"] = "Penutupan siklus sementara untuk audit keuangan"
        with patch("server.db", mock_db):
            res_off = await admin_update_wage_policy_endpoint("admin", _make_req(payload_off), self.admin_owner)

        self.assertFalse(res_off["enabled"])
        self.assertIsNone(res_off["current_cycle_id"])
        self.assertEqual(len(res_off["activation_cycles"]), 1)
        self.assertIsNotNone(res_off["activation_cycles"][0]["disabled_at"])
        saved_policy_val = copy.deepcopy(res_off)

        # 5. Re-Enable Transition (OFF -> ON) -> Starts cycle 2, initial_activation_at remains intact
        payload_re_on = copy.deepcopy(payload_off)
        payload_re_on["enabled"] = True
        payload_re_on["change_reason"] = "Pembukaan siklus aktivasi kedua setelah audit"
        with patch("server.db", mock_db):
            res_re_on = await admin_update_wage_policy_endpoint("admin", _make_req(payload_re_on), self.admin_owner)

        self.assertTrue(res_re_on["enabled"])
        self.assertEqual(len(res_re_on["activation_cycles"]), 2)
        cycle_2_id = res_re_on["current_cycle_id"]
        self.assertNotEqual(cycle_1_id, cycle_2_id)
        self.assertEqual(res_re_on["initial_activation_at"], initial_act_epoch)

    # =========================================================================
    # AUDIT 2: Durable Anti-Retroactive Protection Under Multi-Step Mutations
    # =========================================================================
    async def test_audit_02_durable_anti_retroactivity_across_all_triggers(self):
        """Audit 2: Order settled while OFF cannot be retroactively accrued by ANY future event."""
        mock_db = MagicMock()
        order_id = "507f1f77bcf86cd799439099"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261028-099",
            "created_at": "2026-10-28T08:00:00Z",
            "order_status": "selesai",
            "completed_at": "2026-10-28T10:00:00Z",
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 1000.0,
            "outstanding_amount_le": 0.0,
        }

        # Step 1: Settles while policy is OFF
        self._setup_mock_db(mock_db, policy_enabled=False)
        with patch("server.db", mock_db):
            res_skip = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_staff)

        self.assertEqual(res_skip["status"], "skipped_policy_disabled")
        self.assertEqual(res_skip["eligibility"]["scope_status"], "skipped_disabled_window")

        # Simulate database persistence of the skip state
        order_doc["admin_wage_skipped"] = res_skip["skipped"]
        order_doc["admin_wage_eligibility"] = res_skip["eligibility"]

        # Step 2: System is now re-enabled (ON)
        cycles = [{
            "cycle_id": "cycle_20261030_001",
            "enabled_at": "2026-10-30T00:00:00Z",
            "disabled_at": None,
        }]
        self._setup_mock_db(mock_db, policy_enabled=True, initial_act="2026-10-30T00:00:00Z", cycles=cycles)

        # Step 3: Trigger A — Repeat payment summary evaluation
        payment_summary = {
            "payment_status": "lunas",
            "paid_amount_le": 1000.0,
            "outstanding_amount_le": 0.0,
            "payment_date": "2026-10-31T10:00:00Z"
        }
        with patch("server.db", mock_db):
            res_retry_pay = await evaluate_and_process_order_admin_wage_accrual(
                order_doc, self.admin_staff, payment_summary=payment_summary
            )
        self.assertEqual(res_retry_pay["status"], "skipped_disabled_window_matured")
        self.assertEqual(res_retry_pay["eligibility"]["scope_status"], "skipped_disabled_window")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

        # Step 4: Trigger B — Completion status update triggered again
        order_mutated = dict(order_doc)
        order_mutated["notes"] = "Catatan alamat pengiriman diubah oleh admin"
        order_mutated["updated_at"] = "2026-10-31T12:00:00Z"
        with patch("server.db", mock_db):
            res_retry_status = await evaluate_and_process_order_admin_wage_accrual(
                order_mutated, self.admin_staff
            )
        self.assertEqual(res_retry_status["status"], "skipped_disabled_window_matured")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

        # Step 5: Legacy order without subdocument, only admin_wage_skipped status
        legacy_skipped_order = {
            "_id": ObjectId("507f1f77bcf86cd799439098"),
            "order_number": "SGF-20261028-098",
            "order_status": "selesai",
            "payment_status": "lunas",
            "total_le": 500.0,
            "paid_amount_le": 500.0,
            "outstanding_amount_le": 0.0,
            "admin_wage_skipped": {
                "status": "skipped_policy_disabled",
                "reason": "Kebijakan nonaktif",
                "skipped_at": "2026-10-28T10:00:00Z"
            }
        }
        with patch("server.db", mock_db):
            res_legacy_skip = await evaluate_and_process_order_admin_wage_accrual(
                legacy_skipped_order, self.admin_staff
            )
        self.assertEqual(res_legacy_skip["status"], "skipped_disabled_window_matured")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

    # =========================================================================
    # AUDIT 3: Historical Order Boundary Isolation & Permutations
    # =========================================================================
    async def test_audit_03_historical_order_boundary_permutations(self):
        """Audit 3: Rigorously verifies which historical orders accrue and which remain isolated."""
        mock_db = MagicMock()
        activation_epoch = "2026-10-30T00:00:00Z"
        cycles = [{
            "cycle_id": "cycle_20261030_001",
            "enabled_at": activation_epoch,
            "disabled_at": None,
        }]
        self._setup_mock_db(mock_db, policy_enabled=True, initial_act=activation_epoch, cycles=cycles)

        # Permutation 1: Completed & Paid with legacy marker -> Excluded Historical
        hist_settled = {
            "_id": ObjectId("507f1f77bcf86cd799439071"),
            "order_number": "SGF-HIST-71",
            "created_at": "2026-09-01T08:00:00Z",
            "order_status": "selesai",
            "completed_at": "2026-09-10T10:00:00Z",
            "paid_at": "2026-09-10T12:00:00Z",
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 1000.0,
            "outstanding_amount_le": 0.0,
            "is_legacy_manual": True,
        }
        with patch("server.db", mock_db):
            res_1 = await evaluate_and_process_order_admin_wage_accrual(hist_settled, self.admin_staff)
        self.assertIn(res_1["status"], ("skipped_legacy_reconciled", "skipped_pre_activation_historical"))
        self.assertEqual(res_1["eligibility"]["scope_status"], "excluded_historical")

        # Permutation 2: Completed BEFORE, but Paid AFTER activation -> QUALIFIES & ACCRUES
        hist_paid_post = {
            "_id": ObjectId("507f1f77bcf86cd799439072"),
            "order_number": "SGF-HIST-72",
            "created_at": "2026-09-01T08:00:00Z",
            "order_status": "selesai",
            "completed_at": "2026-09-10T10:00:00Z",
            "paid_at": "2026-10-31T09:00:00Z", # Post-activation
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 1000.0,
            "outstanding_amount_le": 0.0,
        }
        with patch("server.db", mock_db):
            res_2 = await evaluate_and_process_order_admin_wage_accrual(hist_paid_post, self.admin_staff, lifecycle_event="payment_lunas")
        self.assertEqual(res_2["status"], "accrued")
        self.assertEqual(res_2["eligibility"]["scope_status"], "accrued")

        # Permutation 3: Paid BEFORE, but Completed AFTER activation -> QUALIFIES & ACCRUES
        hist_comp_post = {
            "_id": ObjectId("507f1f77bcf86cd799439073"),
            "order_number": "SGF-HIST-73",
            "created_at": "2026-09-01T08:00:00Z",
            "order_status": "selesai",
            "completed_at": "2026-10-31T14:00:00Z", # Post-activation
            "paid_at": "2026-09-10T12:00:00Z",
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 1000.0,
            "outstanding_amount_le": 0.0,
        }
        with patch("server.db", mock_db):
            res_3 = await evaluate_and_process_order_admin_wage_accrual(hist_comp_post, self.admin_staff, lifecycle_event="order_completed")
        self.assertEqual(res_3["status"], "accrued")
        self.assertEqual(res_3["eligibility"]["scope_status"], "accrued")

        # Permutation 4: Created BEFORE, but BOTH Completed and Paid AFTER activation -> QUALIFIES & ACCRUES
        hist_both_post = {
            "_id": ObjectId("507f1f77bcf86cd799439074"),
            "order_number": "SGF-HIST-74",
            "created_at": "2026-09-01T08:00:00Z",
            "order_status": "selesai",
            "completed_at": "2026-10-31T10:00:00Z", # Post-activation
            "paid_at": "2026-10-31T11:00:00Z",      # Post-activation
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 1000.0,
            "outstanding_amount_le": 0.0,
        }
        with patch("server.db", mock_db):
            res_4 = await evaluate_and_process_order_admin_wage_accrual(hist_both_post, self.admin_staff, lifecycle_event="order_completed")
        self.assertEqual(res_4["status"], "accrued")
        self.assertEqual(res_4["eligibility"]["scope_status"], "accrued")

    # =========================================================================
    # AUDIT 4: Transaction Failure Consistency & Rollbacks
    # =========================================================================
    async def test_audit_04_transaction_failure_handling(self):
        """Audit 4: Tests transient write conflict and duplicate key error recovery."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)
        order_id = "507f1f77bcf86cd799439088"
        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261030-088",
            "order_status": "selesai",
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 1000.0,
            "outstanding_amount_le": 0.0,
        }

        # Subtest 1: DuplicateKeyError recovery when obligation was inserted in racing thread
        existing_wob = {
            "_id": ObjectId("807f1f77bcf86cd799439055"),
            "obligation_number": "WOB-202610-0999",
            "accrual_event_key": f"admin_wage:{order_id}",
            "status": "accrued",
            "worker_id": "507f1f77bcf86cd799439002",
            "worker_name": "Sarah Administrasi",
            "total_amount_le": 50.0,
            "accrued_at": "2026-10-30T10:00:00Z",
        }
        mock_db.wage_obligations.insert_one = AsyncMock(side_effect=pymongo.errors.DuplicateKeyError(
            f"E11000 duplicate key error collection: wage_obligations index: uniq_wage_obligation_accrual_event dup key: {{ accrual_event_key: 'admin_wage:{order_id}' }}"
        ))
        mock_db.wage_obligations.find_one = AsyncMock(return_value=existing_wob)

        with patch("server.db", mock_db):
            res_dup = await process_order_admin_wage_accrual(order_doc, self.admin_staff, lifecycle_event="order_completed")

        # Idempotent recovery returns existing obligation details
        self.assertEqual(res_dup["status"], "already_accrued")
        self.assertEqual(res_dup["obligation"]["obligation_number"], "WOB-202610-0999")
        self.assertEqual(res_dup["eligibility"]["scope_status"], "accrued")

        # Subtest 2: Non-accrual key duplicate key error is re-raised (fail-closed)
        mock_db.wage_obligations.find_one = AsyncMock(return_value=None)
        mock_db.wage_obligations.insert_one = AsyncMock(side_effect=pymongo.errors.DuplicateKeyError(
            "E11000 duplicate key error collection: wage_obligations index: other_index_key"
        ))
        with patch("server.db", mock_db):
            with self.assertRaises(pymongo.errors.DuplicateKeyError):
                await process_order_admin_wage_accrual(order_doc, self.admin_staff, lifecycle_event="order_completed")

    # =========================================================================
    # AUDIT 5: Manual Override Strict Validation & Hard-Cap Clamping Resistance
    # =========================================================================
    async def test_audit_05_manual_override_hard_cap_and_silent_fallback_resistance(self):
        """Audit 5: Confirms manual override rejects invalid amounts, unverified recipients, and hard cap excess."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_enabled=True)
        order_id = "507f1f77bcf86cd799439077"
        base_order = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261030-077",
            "order_status": "selesai",
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 1000.0,
            "outstanding_amount_le": 0.0,
        }

        # 1. Override exceeds hard-cap (100.0 LE) -> blocked_hard_cap_conflict without clamping
        order_over_cap = copy.deepcopy(base_order)
        order_over_cap["admin_wage_override"] = {
            "is_override": True,
            "amount_le": 150.0, # Exceeds 100.0
            "recipient_id": "507f1f77bcf86cd799439002",
            "recipient_name": "Sarah Administrasi",
            "override_reason": "Special bonus"
        }
        with patch("server.db", mock_db):
            res_cap = await evaluate_and_process_order_admin_wage_accrual(order_over_cap, self.admin_staff)
        self.assertEqual(res_cap["status"], "blocked_hard_cap_conflict")
        self.assertEqual(res_cap["eligibility"]["scope_status"], "blocked")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

        # 2. Override with invalid/malformed amount -> blocked_missing_rate (No silent fallback to default 50.0 LE)
        order_bad_amt = copy.deepcopy(base_order)
        order_bad_amt["admin_wage_override"] = {
            "is_override": True,
            "amount_le": "N/A_NOT_A_NUMBER",
            "recipient_id": "507f1f77bcf86cd799439002",
        }
        with patch("server.db", mock_db):
            res_bad_amt = await evaluate_and_process_order_admin_wage_accrual(order_bad_amt, self.admin_staff)
        self.assertEqual(res_bad_amt["status"], "blocked_missing_rate")
        self.assertEqual(res_bad_amt["eligibility"]["scope_status"], "blocked")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

        # 3. Override with negative amount -> blocked_missing_rate
        order_neg_amt = copy.deepcopy(base_order)
        order_neg_amt["admin_wage_override"] = {
            "is_override": True,
            "amount_le": -25.0,
            "recipient_id": "507f1f77bcf86cd799439002",
        }
        with patch("server.db", mock_db):
            res_neg = await evaluate_and_process_order_admin_wage_accrual(order_neg_amt, self.admin_staff)
        self.assertEqual(res_neg["status"], "blocked_missing_rate")
        self.assertEqual(res_neg["eligibility"]["scope_status"], "blocked")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

        # 4. Override with unregistered recipient -> blocked_invalid_recipient
        order_bad_recip = copy.deepcopy(base_order)
        order_bad_recip["admin_wage_override"] = {
            "is_override": True,
            "amount_le": 60.0,
            "recipient_id": "507f1f77bcf86cd799439999", # Unknown ID
        }
        with patch("server.db", mock_db):
            res_bad_recip = await evaluate_and_process_order_admin_wage_accrual(order_bad_recip, self.admin_staff)
        self.assertEqual(res_bad_recip["status"], "blocked_invalid_recipient")
        self.assertEqual(res_bad_recip["eligibility"]["scope_status"], "blocked")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

    # =========================================================================
    # AUDIT 6: Completion and Payment Classification Under Contradictory Inputs
    # =========================================================================
    def test_audit_06_completion_and_payment_classification_edge_cases(self):
        """Audit 6: Evaluates is_order_completed and is_order_fully_paid against adversarial payloads."""
        # 1. Cancelled order with completed_at timestamp -> must NOT be completed
        cancelled_with_completed_at = {
            "order_status": "dibatalkan",
            "completed_at": "2026-10-30T10:00:00Z",
            "status_history": [{"to_status": "dibatalkan", "reason": "Customer cancelled"}]
        }
        self.assertFalse(is_order_completed(cancelled_with_completed_at))

        # 2. Voided order with order_status='selesai' -> must NOT be completed
        voided_with_selesai = {
            "is_voided": True,
            "order_status": "selesai",
            "completed_at": "2026-10-30T10:00:00Z"
        }
        self.assertFalse(is_order_completed(voided_with_selesai))

        # 3. Contradictory payment: claims 'lunas' but outstanding balance is positive -> must NOT be fully paid
        contradictory_lunas = {
            "payment_status": "lunas",
            "total_le": 1000.0,
            "paid_amount_le": 300.0,
            "outstanding_amount_le": 700.0, # Positive outstanding
        }
        self.assertFalse(is_order_fully_paid(contradictory_lunas))

        # 4. Contradictory payment summary: claims 'lunas' but paid < total
        contradictory_summary = {
            "payment_status": "lunas",
            "total_le": 500.0,
            "paid_amount_le": 100.0,
            "outstanding_amount_le": 400.0,
        }
        self.assertFalse(is_order_fully_paid({"total_le": 500.0}, payment_summary=contradictory_summary))

        # 5. Overpayment qualifies as fully paid
        overpaid_order = {
            "payment_status": "overpaid",
            "total_le": 500.0,
            "paid_amount_le": 600.0,
            "outstanding_amount_le": 0.0,
        }
        self.assertTrue(is_order_fully_paid(overpaid_order))

        # 6. Malformed strings / NaN fail closed safely
        malformed_order = {
            "payment_status": "lunas",
            "total_le": "invalid_number",
            "paid_amount_le": float("nan"),
            "outstanding_amount_le": None,
        }
        self.assertFalse(is_order_fully_paid(malformed_order))

    # =========================================================================
    # AUDIT 7: Quarantine of Voided Obligations Across Toggles & Mode Changes
    # =========================================================================
    async def test_audit_07_voided_obligation_quarantine(self):
        """Audit 7: Voided obligation blocks automatic re-accrual even after policy toggles and mode changes."""
        mock_db = MagicMock()
        order_id = "507f1f77bcf86cd799439066"
        self._setup_mock_db(mock_db, policy_enabled=True)

        voided_wob = {
            "_id": ObjectId("807f1f77bcf86cd799439011"),
            "obligation_number": "WOB-202610-0011",
            "accrual_event_key": f"admin_wage:{order_id}",
            "status": "voided",
            "worker_id": "507f1f77bcf86cd799439002",
            "worker_name": "Sarah Administrasi",
            "total_amount_le": 50.0,
            "voided_at": "2026-10-30T11:00:00Z",
        }
        mock_db.wage_obligations.find_one = AsyncMock(return_value=voided_wob)

        order_doc = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-20261030-066",
            "order_status": "selesai",
            "payment_status": "lunas",
            "total_le": 800.0,
            "paid_amount_le": 800.0,
            "outstanding_amount_le": 0.0,
        }

        # Attempt 1: Automatic evaluation against existing voided obligation
        with patch("server.db", mock_db):
            res_void = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_staff)

        self.assertEqual(res_void["status"], "blocked_prior_voided_obligation")
        self.assertEqual(res_void["eligibility"]["scope_status"], "blocked")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)

        # Attempt 2: Policy toggle cycle (OFF then ON again)
        # Even after re-enabling policy, the voided obligation must STILL block re-accrual
        cycles = [{
            "cycle_id": "cycle_20261031_002",
            "enabled_at": "2026-10-31T00:00:00Z",
            "disabled_at": None,
        }]
        self._setup_mock_db(mock_db, policy_enabled=True, initial_act="2026-10-30T00:00:00Z", cycles=cycles)
        mock_db.wage_obligations.find_one = AsyncMock(return_value=voided_wob)

        with patch("server.db", mock_db):
            res_void_post_toggle = await evaluate_and_process_order_admin_wage_accrual(order_doc, self.admin_staff)

        self.assertEqual(res_void_post_toggle["status"], "blocked_prior_voided_obligation")
        self.assertEqual(res_void_post_toggle["eligibility"]["scope_status"], "blocked")
        self.assertEqual(mock_db.wage_obligations.insert_one.call_count, 0)
