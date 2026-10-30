"""
Phase 08.5B — Read-Only Admin Wage Reconciliation Engine Test Suite.
Sogil Furniture | Financial Integrity First

Comprehensive verification of:
1. All 10 Candidate Classification Categories:
   - Category 1: ELIGIBLE_MISSING_OBLIGATION
   - Category 2: BLOCKED_CAP_CONFLICT (active marker & direct exceedance)
   - Category 3: BLOCKED_CONFIGURATION_CORRECTED (audit log verified)
   - Category 4: EXISTING_OBLIGATION (accrued)
   - Category 5: ORDER_NOT_FULLY_PAID (unpaid, dp, outstanding)
   - Category 6: VOIDED_OR_CANCELLED (order void, cancelled, batal)
   - Category 7: LEGACY_MANUAL_PAYMENT (isolated historical orders)
   - Category 8: OBLIGATION_ALREADY_SETTLED_OR_PARTIALLY_SETTLED (paid / partial)
   - Category 9: INVALID_OR_MISSING_CONFIGURATION (disabled policy, missing rate, invalid recipient)
   - Category 10: AMBIGUOUS_REQUIRES_OWNER_REVIEW (payment mismatch, unverifiable block, voided obligation)
2. Zero Database Mutation Guarantee (Strict Read-Only).
3. CLI Apply-Mode Rejection & Security Halt.
4. Determinism of repeated executions.
5. JSON Manifest and Markdown Report Generation.
"""

import asyncio
import copy
import json
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from datetime import datetime, timezone
import pytest
import unittest

from scripts.reconcile_admin_wages import (
    CandidateCategory,
    CATEGORY_DESCRIPTIONS,
    build_admin_wage_accrual_event_key,
    classify_order as _orig_classify_order,
    run_reconciliation_dry_run,
    format_markdown_report,
    format_json_report,
    parse_args,
    main_async,
)


def classify_order(*args, **kwargs):
    """
    Test suite compatibility wrapper: Phase 08.5B test fixtures were written prior to
    cutoff-date introduction. For modern orders in this test suite that omit order_date/created_at,
    provide a modern order_date ('2026-10-26T10:00:00Z') so they are evaluated as modern.
    """
    if "order" in kwargs and isinstance(kwargs["order"], dict):
        ord_doc = kwargs["order"]
        if not ord_doc.get("order_date") and not ord_doc.get("created_at") and not ord_doc.get("is_historical") and not ord_doc.get("historical"):
            ord_doc["order_date"] = "2026-10-26T10:00:00Z"
    elif len(args) > 0 and isinstance(args[0], dict):
        ord_doc = args[0]
        if not ord_doc.get("order_date") and not ord_doc.get("created_at") and not ord_doc.get("is_historical") and not ord_doc.get("historical"):
            ord_doc["order_date"] = "2026-10-26T10:00:00Z"
    return _orig_classify_order(*args, **kwargs)


class TestPhase08_5BReconciliationDryRun(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.active_admin_id = "600000000000000000000001"
        self.staff_admin_id = "600000000000000000000002"
        self.admins_by_id = {
            self.active_admin_id: {
                "_id": ObjectId(self.active_admin_id),
                "name": "Owner Admin",
                "role": "owner",
                "is_active": True,
            },
            self.staff_admin_id: {
                "_id": ObjectId(self.staff_admin_id),
                "name": "Staff Admin",
                "role": "staff",
                "is_active": True,
            },
        }

        self.valid_policy = {
            "default_wage_per_order_le": 100.0,
            "default_recipient_id": self.staff_admin_id,
            "default_recipient_name": "Staff Admin",
            "unusual_amount_threshold_le": 300.0,
            "max_wage_per_order_le": 500.0,
            "enabled": True,
            "currency": "EGP",
            "is_configured": True,
        }

    # ==========================================================================
    # 1. TAXONOMY TESTS (10 CATEGORIES)
    # ==========================================================================

    def test_01_eligible_missing_obligation_classification(self):
        """Order is lunas, valid payments, no obligation, valid policy -> ELIGIBLE_MISSING_OBLIGATION"""
        order = {
            "_id": ObjectId("671fc0000000000000000001"),
            "order_number": "SGF-2026-0001",
            "order_date": "2026-10-25T10:00:00Z",
            "payment_status": "lunas",
            "total_amount_le": 1500.0,
            "paid_amount_le": 1500.0,
            "outstanding_amount_le": 0.0,
        }
        payments = [{"amount_le": 1500.0, "status": "paid"}]

        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=[],
            payments=payments,
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )

        self.assertEqual(res["candidate_category"], CandidateCategory.ELIGIBLE_MISSING_OBLIGATION.value)
        self.assertEqual(res["reason_code"], "FULLY_PAID_MISSING_ACCRUAL")
        self.assertTrue(res["cap_validation_passed"])
        self.assertEqual(res["proposed_amount_le"], 100.0)
        self.assertEqual(res["proposed_recipient_id"], self.staff_admin_id)
        self.assertEqual(res["proposed_recipient_name"], "Staff Admin")
        self.assertFalse(res["owner_review_required"])
        self.assertEqual(res["recommended_action"], "ACCRUE_IN_APPLY_PHASE")
        self.assertEqual(res["canonical_event_key"], "admin_wage:671fc0000000000000000001")

    def test_02_blocked_cap_conflict_active_marker(self):
        """Order has active admin_wage_blocked marker -> BLOCKED_CAP_CONFLICT"""
        order = {
            "_id": ObjectId("671fc0000000000000000002"),
            "order_number": "SGF-2026-0002",
            "payment_status": "lunas",
            "total_amount_le": 2000.0,
            "paid_amount_le": 2000.0,
            "outstanding_amount_le": 0.0,
            "admin_wage_blocked": {
                "status": "blocked_hard_cap_conflict",
                "reason": "Nominal upah override (600.0 LE) melebihi batas maksimum aktif (500.0 LE)",
                "attempted_amount_le": 600.0,
                "max_wage_per_order_le": 500.0,
                "recipient_id": self.staff_admin_id,
                "recipient_name": "Staff Admin",
            },
        }

        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=[],
            payments=[],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )

        self.assertEqual(res["candidate_category"], CandidateCategory.BLOCKED_CAP_CONFLICT.value)
        self.assertEqual(res["reason_code"], "CURRENTLY_BLOCKED_CAP_CONFLICT")
        self.assertFalse(res["cap_validation_passed"])
        self.assertEqual(res["proposed_amount_le"], 600.0)
        self.assertTrue(res["owner_review_required"])
        self.assertEqual(res["recommended_action"], "REQUIRES_OWNER_OVERRIDE_ADJUSTMENT")

    def test_03_blocked_cap_conflict_override_exceeds_cap_without_marker(self):
        """Order override amount > hard cap even if blocked marker was not persisted -> BLOCKED_CAP_CONFLICT"""
        order = {
            "_id": ObjectId("671fc0000000000000000003"),
            "order_number": "SGF-2026-0003",
            "payment_status": "lunas",
            "total_amount_le": 2000.0,
            "paid_amount_le": 2000.0,
            "outstanding_amount_le": 0.0,
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 750.0,
                "recipient_id": self.staff_admin_id,
                "recipient_name": "Staff Admin",
            },
        }

        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=[],
            payments=[],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )

        self.assertEqual(res["candidate_category"], CandidateCategory.BLOCKED_CAP_CONFLICT.value)
        self.assertEqual(res["reason_code"], "OVERRIDE_EXCEEDS_HARD_CAP")
        self.assertFalse(res["cap_validation_passed"])
        self.assertEqual(res["proposed_amount_le"], 750.0)
        self.assertTrue(res["owner_review_required"])
        self.assertEqual(res["recommended_action"], "REQUIRES_OWNER_OVERRIDE_ADJUSTMENT")

    def test_04_blocked_configuration_corrected_with_valid_audit(self):
        """Order was previously blocked, cleared with valid audit log -> BLOCKED_CONFIGURATION_CORRECTED"""
        order_id = "671fc0000000000000000004"
        order = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-2026-0004",
            "payment_status": "lunas",
            "total_amount_le": 3000.0,
            "paid_amount_le": 3000.0,
            "outstanding_amount_le": 0.0,
            "admin_wage_blocked": None,
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 250.0,  # Corrected from 600 to 250 (<= 500 hard cap)
                "recipient_id": self.staff_admin_id,
                "recipient_name": "Staff Admin",
                "override_reason": "Koreksi manual disetujui Owner",
            },
        }
        audit_logs = [
            {
                "action": "order_admin_wage_override_updated",
                "entity_type": "order",
                "entity_id": order_id,
                "entity_identifier": "SGF-2026-0004",
                "timestamp": "2026-10-28T12:00:00Z",
                "metadata": {
                    "previous_override": {"is_override": True, "amount_le": 600.0},
                    "new_override": {"is_override": True, "amount_le": 250.0},
                    "resolved_blocked_state": {
                        "status": "blocked_hard_cap_conflict",
                        "attempted_amount_le": 600.0,
                        "max_wage_per_order_le": 500.0,
                    },
                },
            }
        ]

        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=audit_logs,
            payments=[{"amount_le": 3000.0, "status": "paid"}],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )

        self.assertEqual(res["candidate_category"], CandidateCategory.BLOCKED_CONFIGURATION_CORRECTED.value)
        self.assertEqual(res["reason_code"], "POST_BLOCKED_RESOLVED_PENDING_ACCRUAL")
        self.assertTrue(res["cap_validation_passed"])
        self.assertEqual(res["proposed_amount_le"], 250.0)
        self.assertFalse(res["owner_review_required"])
        self.assertEqual(res["recommended_action"], "ACCRUE_IN_APPLY_PHASE")

    def test_05_unverifiable_blocked_history_classified_as_ambiguous(self):
        """Order marked as previously blocked without trustworthy audit trail -> AMBIGUOUS_REQUIRES_OWNER_REVIEW"""
        order_id = "671fc0000000000000000005"
        order = {
            "_id": ObjectId(order_id),
            "order_number": "SGF-2026-0005",
            "payment_status": "lunas",
            "total_amount_le": 2000.0,
            "paid_amount_le": 2000.0,
            "outstanding_amount_le": 0.0,
            "admin_wage_blocked_unverifiable": True,  # Unverified past block marker
            "admin_wage_blocked": None,
        }

        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=[],  # No audit logs to verify
            payments=[],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )

        self.assertEqual(res["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res["reason_code"], "UNVERIFIABLE_BLOCKED_HISTORY")
        self.assertTrue(res["owner_review_required"])
        self.assertEqual(res["recommended_action"], "REQUIRES_OWNER_DATA_AUDIT")

    def test_06_existing_obligation_accrued(self):
        """Order already has active accrued obligation -> EXISTING_OBLIGATION"""
        order = {
            "_id": ObjectId("671fc0000000000000000006"),
            "order_number": "SGF-2026-0006",
            "payment_status": "lunas",
            "total_amount_le": 1200.0,
            "paid_amount_le": 1200.0,
        }
        obligation = {
            "obligation_number": "WOB-2026-0101",
            "task_category": "admin",
            "accrual_event_key": f"admin_wage:{order['_id']}",
            "status": "accrued",
            "paid_amount_le": 0.0,
            "total_amount_le": 100.0,
        }

        res = classify_order(
            order=order,
            obligation=obligation,
            audit_logs=[],
            payments=[],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )

        self.assertEqual(res["candidate_category"], CandidateCategory.EXISTING_OBLIGATION.value)
        self.assertEqual(res["reason_code"], "OBLIGATION_ALREADY_ACCRUED")
        self.assertEqual(res["existing_obligation_number"], "WOB-2026-0101")
        self.assertEqual(res["existing_obligation_status"], "accrued")
        self.assertFalse(res["owner_review_required"])
        self.assertEqual(res["recommended_action"], "NO_ACTION_REQUIRED")

    def test_07_existing_obligation_already_settled_or_partially_settled(self):
        """Order has obligation that is already settled/paid -> OBLIGATION_ALREADY_SETTLED_OR_PARTIALLY_SETTLED"""
        order = {
            "_id": ObjectId("671fc0000000000000000007"),
            "order_number": "SGF-2026-0007",
            "payment_status": "lunas",
            "total_amount_le": 1500.0,
            "paid_amount_le": 1500.0,
        }
        obligation = {
            "obligation_number": "WOB-2026-0102",
            "task_category": "admin",
            "accrual_event_key": f"admin_wage:{order['_id']}",
            "status": "paid",
            "paid_amount_le": 100.0,
            "total_amount_le": 100.0,
            "settlement_id": "SETTLE-001",
        }

        res = classify_order(
            order=order,
            obligation=obligation,
            audit_logs=[],
            payments=[],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )

        self.assertEqual(res["candidate_category"], CandidateCategory.OBLIGATION_ALREADY_SETTLED_OR_PARTIALLY_SETTLED.value)
        self.assertEqual(res["reason_code"], "OBLIGATION_SETTLED_OR_PARTIAL")
        self.assertEqual(res["existing_obligation_status"], "paid")
        self.assertFalse(res["owner_review_required"])
        self.assertEqual(res["recommended_action"], "NO_ACTION_REQUIRED")

    def test_08_order_not_fully_paid(self):
        """Order is dp or unpaid or outstanding > 0 -> ORDER_NOT_FULLY_PAID"""
        order = {
            "_id": ObjectId("671fc0000000000000000008"),
            "order_number": "SGF-2026-0008",
            "payment_status": "dp",
            "total_amount_le": 2500.0,
            "paid_amount_le": 1000.0,
            "outstanding_amount_le": 1500.0,
        }

        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=[],
            payments=[],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )

        self.assertEqual(res["candidate_category"], CandidateCategory.ORDER_NOT_FULLY_PAID.value)
        self.assertEqual(res["reason_code"], "ORDER_PAYMENT_INCOMPLETE")
        self.assertFalse(res["owner_review_required"])
        self.assertEqual(res["recommended_action"], "NO_ACTION_REQUIRED")

    def test_09_voided_or_cancelled_order(self):
        """Order is cancelled/void -> VOIDED_OR_CANCELLED"""
        order = {
            "_id": ObjectId("671fc0000000000000000009"),
            "order_number": "SGF-2026-0009",
            "order_status": "cancelled",
            "payment_status": "void",
            "total_amount_le": 1000.0,
            "paid_amount_le": 0.0,
        }

        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=[],
            payments=[],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )

        self.assertEqual(res["candidate_category"], CandidateCategory.VOIDED_OR_CANCELLED.value)
        self.assertEqual(res["reason_code"], "ORDER_CANCELLED_OR_VOIDED")
        self.assertFalse(res["owner_review_required"])
        self.assertEqual(res["recommended_action"], "NO_ACTION_REQUIRED")

    def test_10_legacy_manual_payment_isolated(self):
        """Order has legacy manual flags -> LEGACY_MANUAL_PAYMENT with owner review required"""
        order = {
            "_id": ObjectId("671fc0000000000000000010"),
            "order_number": "SGF-LEGACY-001",
            "payment_status": "lunas",
            "admin_wage_legacy_reconciled": True,
            "total_amount_le": 5000.0,
            "paid_amount_le": 5000.0,
        }

        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=[],
            payments=[],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )

        self.assertEqual(res["candidate_category"], CandidateCategory.LEGACY_MANUAL_PAYMENT.value)
        self.assertEqual(res["reason_code"], "HISTORICAL_LEGACY_MANUAL_ORDER")
        self.assertTrue(res["owner_review_required"])
        self.assertEqual(res["recommended_action"], "ISOLATE_FOR_OWNER_REVIEW")

    def test_11_invalid_or_missing_configuration_unregistered_recipient(self):
        """Order has override with unregistered recipient -> INVALID_OR_MISSING_CONFIGURATION"""
        order = {
            "_id": ObjectId("671fc0000000000000000011"),
            "order_number": "SGF-2026-0011",
            "payment_status": "lunas",
            "total_amount_le": 1000.0,
            "paid_amount_le": 1000.0,
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 120.0,
                "recipient_id": "999999999999999999999999",  # Non-existent admin
                "recipient_name": "Ghost Admin",
            },
        }

        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=[],
            payments=[],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )

        self.assertEqual(res["candidate_category"], CandidateCategory.INVALID_OR_MISSING_CONFIGURATION.value)
        self.assertEqual(res["reason_code"], "RECIPIENT_NOT_FOUND")
        self.assertTrue(res["owner_review_required"])
        self.assertEqual(res["recommended_action"], "CONFIGURE_POLICY_OR_OVERRIDE")

    def test_12_invalid_or_missing_configuration_policy_disabled(self):
        """Order has no override, global policy is disabled -> INVALID_OR_MISSING_CONFIGURATION"""
        order = {
            "_id": ObjectId("671fc0000000000000000012"),
            "order_number": "SGF-2026-0012",
            "payment_status": "lunas",
            "total_amount_le": 1000.0,
            "paid_amount_le": 1000.0,
        }
        disabled_policy = copy.deepcopy(self.valid_policy)
        disabled_policy["enabled"] = False

        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=[],
            payments=[],
            policy=disabled_policy,
            admins_by_id=self.admins_by_id,
        )

        self.assertEqual(res["candidate_category"], CandidateCategory.INVALID_OR_MISSING_CONFIGURATION.value)
        self.assertEqual(res["reason_code"], "POLICY_DISABLED_OR_UNCONFIGURED")
        self.assertTrue(res["owner_review_required"])

    def test_13_ambiguous_payment_discrepancy(self):
        """Order claims lunas but payments sum < total amount -> AMBIGUOUS_REQUIRES_OWNER_REVIEW"""
        order = {
            "_id": ObjectId("671fc0000000000000000013"),
            "order_number": "SGF-2026-0013",
            "payment_status": "lunas",
            "total_amount_le": 2000.0,
            "paid_amount_le": 2000.0,
        }
        # Only 1000 LE recorded in payments collection
        payments = [{"amount_le": 1000.0, "status": "paid"}]

        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=[],
            payments=payments,
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )

        self.assertEqual(res["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res["reason_code"], "PAYMENT_SUM_MISMATCH")
        self.assertTrue(res["owner_review_required"])
        self.assertEqual(res["recommended_action"], "REQUIRES_OWNER_DATA_AUDIT")

    def test_14_ambiguous_voided_obligation_on_lunas_order(self):
        """Order is lunas but existing obligation status is void -> AMBIGUOUS_REQUIRES_OWNER_REVIEW"""
        order = {
            "_id": ObjectId("671fc0000000000000000014"),
            "order_number": "SGF-2026-0014",
            "payment_status": "lunas",
            "total_amount_le": 1000.0,
            "paid_amount_le": 1000.0,
        }
        obligation = {
            "obligation_number": "WOB-2026-0099",
            "task_category": "admin",
            "accrual_event_key": f"admin_wage:{order['_id']}",
            "status": "void",
            "paid_amount_le": 0.0,
        }

        res = classify_order(
            order=order,
            obligation=obligation,
            audit_logs=[],
            payments=[],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )

        self.assertEqual(res["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res["reason_code"], "VOIDED_OBLIGATION_ON_LUNAS_ORDER")
        self.assertTrue(res["owner_review_required"])

    # ==========================================================================
    # 2. RUNNER, ZERO-WRITE GUARANTEE & DETERMINISM
    # ==========================================================================

    async def test_15_dry_run_zero_database_writes_guarantee(self):
        """Verifies that run_reconciliation_dry_run executes ZERO mutation methods."""
        mock_db = MagicMock()

        # Mock settings collection
        mock_settings = MagicMock()
        mock_settings.find_one = AsyncMock(return_value={
            "key": "admin_wage_policy",
            "value": {
                "default_wage_per_order_le": 100.0,
                "default_recipient_id": self.staff_admin_id,
                "default_recipient_name": "Staff Admin",
                "max_wage_per_order_le": 500.0,
                "unusual_amount_threshold_le": 300.0,
                "enabled": True,
            }
        })
        mock_db.settings = mock_settings

        # Mock admins collection
        mock_admins = MagicMock()
        mock_admin_cursor = MagicMock()
        mock_admin_cursor.to_list = AsyncMock(return_value=[
            {"_id": ObjectId(self.staff_admin_id), "name": "Staff Admin", "is_active": True}
        ])
        mock_admins.find.return_value = mock_admin_cursor
        mock_db.admins = mock_admins

        # Mock orders collection with 2 orders
        mock_orders = MagicMock()
        mock_order_cursor = MagicMock()
        mock_order_cursor.sort.return_value = mock_order_cursor
        mock_order_cursor.to_list = AsyncMock(return_value=[
            {
                "_id": ObjectId("671fc0000000000000000021"),
                "order_number": "SGF-2026-0021",
                "order_date": "2026-10-26T10:00:00Z",
                "payment_status": "lunas",
                "total_amount_le": 1000.0,
                "paid_amount_le": 1000.0,
                "outstanding_amount_le": 0.0,
            },
            {
                "_id": ObjectId("671fc0000000000000000022"),
                "order_number": "SGF-2026-0022",
                "order_date": "2026-10-26T10:00:00Z",
                "payment_status": "dp",
                "total_amount_le": 2000.0,
                "paid_amount_le": 500.0,
                "outstanding_amount_le": 1500.0,
            }
        ])
        mock_orders.find.return_value = mock_order_cursor
        mock_db.orders = mock_orders

        # Mock wage_obligations collection
        mock_wob = MagicMock()
        mock_wob_cursor = MagicMock()
        mock_wob_cursor.to_list = AsyncMock(return_value=[])
        mock_wob.find.return_value = mock_wob_cursor
        mock_db.wage_obligations = mock_wob

        # Mock audit_logs collection
        mock_audit = MagicMock()
        mock_audit_cursor = MagicMock()
        mock_audit_cursor.to_list = AsyncMock(return_value=[])
        mock_audit.find.return_value = mock_audit_cursor
        mock_db.audit_logs = mock_audit

        # Mock payments collection
        mock_payments = MagicMock()
        mock_pmt_cursor = MagicMock()
        mock_pmt_cursor.to_list = AsyncMock(return_value=[
            {
                "_id": ObjectId("671fc0000000000000000099"),
                "order_id": "671fc0000000000000000021",
                "amount_le": 1000.0,
                "status": "paid",
            }
        ])
        mock_payments.find.return_value = mock_pmt_cursor
        mock_db.payments = mock_payments

        # Run dry run
        manifest = await run_reconciliation_dry_run(mock_db)

        # Assertions on manifest
        self.assertEqual(manifest["mode"], "DRY_RUN")
        self.assertEqual(manifest["database_mutations_executed"], 0)
        self.assertEqual(manifest["summary"]["total_orders_inspected"], 2)
        self.assertEqual(manifest["summary"]["total_eligible_orders"], 1)
        self.assertEqual(manifest["summary"]["total_eligible_wage_amount_le"], 100.0)

        # STRICT SAFETY ASSERTION: Zero write operations called
        for col_name in ["orders", "wage_obligations", "settings", "audit_logs", "payments", "admins"]:
            col = getattr(mock_db, col_name)
            self.assertFalse(col.insert_one.called, f"Write forbidden: {col_name}.insert_one called!")
            self.assertFalse(col.insert_many.called, f"Write forbidden: {col_name}.insert_many called!")
            self.assertFalse(col.update_one.called, f"Write forbidden: {col_name}.update_one called!")
            self.assertFalse(col.update_many.called, f"Write forbidden: {col_name}.update_many called!")
            self.assertFalse(col.delete_one.called, f"Write forbidden: {col_name}.delete_one called!")
            self.assertFalse(col.delete_many.called, f"Write forbidden: {col_name}.delete_many called!")
            self.assertFalse(col.replace_one.called, f"Write forbidden: {col_name}.replace_one called!")

    def test_16_repeated_dry_run_determinism(self):
        """Repeated classification on same inputs produces identical deterministic output."""
        order = {
            "_id": ObjectId("671fc0000000000000000030"),
            "order_number": "SGF-2026-0030",
            "payment_status": "lunas",
            "total_amount_le": 1800.0,
            "paid_amount_le": 1800.0,
        }

        res1 = classify_order(order, None, [], [], self.valid_policy, self.admins_by_id)
        res2 = classify_order(order, None, [], [], self.valid_policy, self.admins_by_id)

        self.assertEqual(res1, res2)

    # ==========================================================================
    # 3. CLI APPLY REJECTION & SAFETY HALT
    # ==========================================================================

    def test_17_cli_apply_mode_strictly_rejected(self):
        """CLI must reject --apply with SystemExit code 2 and security halt message."""
        with self.assertRaises(SystemExit) as ctx:
            asyncio.run(main_async(["--apply"]))
        self.assertEqual(ctx.exception.code, 2)

    # ==========================================================================
    # 4. REPORT FORMATTING TESTS
    # ==========================================================================

    def test_18_report_formatting_json_and_markdown(self):
        """Validates that Markdown and JSON formatters include all essential sections."""
        manifest = {
            "report_id": "rec_test_123",
            "generated_at": "2026-10-29T07:00:00Z",
            "phase": "08.5B",
            "mode": "DRY_RUN",
            "database_mutations_executed": 0,
            "policy_snapshot": self.valid_policy,
            "summary": {
                "total_orders_inspected": 3,
                "category_counts": {
                    CandidateCategory.ELIGIBLE_MISSING_OBLIGATION.value: 1,
                    CandidateCategory.BLOCKED_CAP_CONFLICT.value: 1,
                    CandidateCategory.LEGACY_MANUAL_PAYMENT.value: 1,
                },
                "category_proposed_amounts_le": {
                    CandidateCategory.ELIGIBLE_MISSING_OBLIGATION.value: 100.0,
                    CandidateCategory.BLOCKED_CAP_CONFLICT.value: 600.0,
                },
                "total_eligible_orders": 1,
                "total_eligible_wage_amount_le": 100.0,
                "total_owner_review_required": 2,
            },
            "candidates": [
                {
                    "order_id": "671fc0000000000000000041",
                    "order_number": "SGF-2026-0041",
                    "order_date": "2026-10-25T10:00:00Z",
                    "payment_status": "lunas",
                    "total_order_le": 1500.0,
                    "paid_amount_le": 1500.0,
                    "candidate_category": CandidateCategory.ELIGIBLE_MISSING_OBLIGATION.value,
                    "reason_code": "FULLY_PAID_MISSING_ACCRUAL",
                    "reason_description": "Pesanan lunas tanpa kewajiban upah",
                    "proposed_recipient_id": self.staff_admin_id,
                    "proposed_recipient_name": "Staff Admin",
                    "proposed_amount_le": 100.0,
                    "active_hard_cap_le": 500.0,
                    "cap_validation_passed": True,
                    "canonical_event_key": "admin_wage:671fc0000000000000000041",
                    "existing_obligation_number": None,
                    "existing_obligation_status": None,
                    "owner_review_required": False,
                    "recommended_action": "ACCRUE_IN_APPLY_PHASE",
                },
                {
                    "order_id": "671fc0000000000000000042",
                    "order_number": "SGF-2026-0042",
                    "order_date": "2026-10-26T10:00:00Z",
                    "payment_status": "lunas",
                    "total_order_le": 2000.0,
                    "paid_amount_le": 2000.0,
                    "candidate_category": CandidateCategory.BLOCKED_CAP_CONFLICT.value,
                    "reason_code": "CURRENTLY_BLOCKED_CAP_CONFLICT",
                    "reason_description": "Konflik batas maksimum",
                    "proposed_recipient_id": self.staff_admin_id,
                    "proposed_recipient_name": "Staff Admin",
                    "proposed_amount_le": 600.0,
                    "active_hard_cap_le": 500.0,
                    "cap_validation_passed": False,
                    "canonical_event_key": "admin_wage:671fc0000000000000000042",
                    "existing_obligation_number": None,
                    "existing_obligation_status": None,
                    "owner_review_required": True,
                    "recommended_action": "REQUIRES_OWNER_OVERRIDE_ADJUSTMENT",
                },
                {
                    "order_id": "671fc0000000000000000043",
                    "order_number": "SGF-LEGACY-002",
                    "order_date": "2026-10-20T10:00:00Z",
                    "payment_status": "lunas",
                    "total_order_le": 3000.0,
                    "paid_amount_le": 3000.0,
                    "candidate_category": CandidateCategory.LEGACY_MANUAL_PAYMENT.value,
                    "reason_code": "HISTORICAL_LEGACY_MANUAL_ORDER",
                    "reason_description": "Pesanan manual historis",
                    "proposed_recipient_id": None,
                    "proposed_recipient_name": None,
                    "proposed_amount_le": None,
                    "active_hard_cap_le": 500.0,
                    "cap_validation_passed": False,
                    "canonical_event_key": "admin_wage:671fc0000000000000000043",
                    "existing_obligation_number": None,
                    "existing_obligation_status": None,
                    "owner_review_required": True,
                    "recommended_action": "ISOLATE_FOR_OWNER_REVIEW",
                }
            ]
        }

        # JSON Formatting
        json_output = format_json_report(manifest)
        parsed = json.loads(json_output)
        self.assertEqual(parsed["report_id"], "rec_test_123")
        self.assertEqual(len(parsed["candidates"]), 3)

        # Markdown Formatting
        md_output = format_markdown_report(manifest)
        self.assertIn("LAPORAN DRY-RUN REKONSILIASI UPAH ADMIN (PHASE 08.5B)", md_output)
        self.assertIn("Tabel Ringkasan Klasifikasi 10 Kategori", md_output)
        self.assertIn("Rincian Kandidat Siap Terbit (Eligible & Corrected)", md_output)
        self.assertIn("Rincian Pesanan Terblokir (Blocked Cap Conflict)", md_output)
        self.assertIn("Rincian Pesanan Historis / Pembayaran Manual (Legacy Orders)", md_output)
        self.assertIn("Pernyataan Kepatuhan Integritas Finansial", md_output)

    # ==========================================================================
    # 5. FINDING P1 REGRESSION TESTS: PAYMENT DATA CONSISTENCY & FAIL-CLOSED
    # ==========================================================================

    def test_p1_01_paid_order_with_zero_payment_records_fails_closed_to_ambiguous(self):
        """P1: Order marked lunas with total > 0 but zero payment records fails closed to AMBIGUOUS."""
        order = {
            "_id": ObjectId("671fc0000000000000000101"),
            "order_number": "SGF-P1-001",
            "payment_status": "lunas",
            "total_amount_le": 2500.0,
            "paid_amount_le": 2500.0,
        }
        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=[],
            payments=[],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res["reason_code"], "MISSING_PAYMENT_RECORDS")
        self.assertTrue(res["owner_review_required"])
        self.assertEqual(res["recommended_action"], "REQUIRES_OWNER_DATA_AUDIT")

    def test_p1_02_paid_order_with_valid_matching_payments_eligible(self):
        """P1: Order marked lunas with matching payments is successfully ELIGIBLE."""
        order = {
            "_id": ObjectId("671fc0000000000000000102"),
            "order_number": "SGF-P1-002",
            "payment_status": "lunas",
            "total_amount_le": 1500.0,
            "paid_amount_le": 1500.0,
        }
        payments = [{"amount_le": 1500.0, "status": "paid"}]
        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=[],
            payments=payments,
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.ELIGIBLE_MISSING_OBLIGATION.value)
        self.assertEqual(res["reason_code"], "FULLY_PAID_MISSING_ACCRUAL")
        self.assertFalse(res["owner_review_required"])

    def test_p1_03_paid_order_with_insufficient_payment_records_ambiguous(self):
        """P1: Order marked lunas where sum of payments < total fails closed with PAYMENT_SUM_MISMATCH."""
        order = {
            "_id": ObjectId("671fc0000000000000000103"),
            "order_number": "SGF-P1-003",
            "payment_status": "lunas",
            "total_amount_le": 2000.0,
            "paid_amount_le": 2000.0,
        }
        payments = [{"amount_le": 1200.0, "status": "paid"}]
        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=[],
            payments=payments,
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res["reason_code"], "PAYMENT_SUM_MISMATCH")
        self.assertTrue(res["owner_review_required"])

    def test_p1_04_paid_order_with_all_voided_payments_fails_closed(self):
        """P1: Order marked lunas where all payments are void fails closed with MISSING_PAYMENT_RECORDS."""
        order = {
            "_id": ObjectId("671fc0000000000000000104"),
            "order_number": "SGF-P1-004",
            "payment_status": "lunas",
            "total_amount_le": 1800.0,
            "paid_amount_le": 1800.0,
        }
        payments = [
            {"amount_le": 1000.0, "status": "void"},
            {"amount_le": 800.0, "status": "cancelled"},
        ]
        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=[],
            payments=payments,
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res["reason_code"], "MISSING_PAYMENT_RECORDS")
        self.assertTrue(res["owner_review_required"])

    def test_p1_05_confirmed_legacy_order_with_zero_payments_isolated_as_legacy(self):
        """P1: Confirmed legacy order without payments is properly isolated as LEGACY_MANUAL_PAYMENT."""
        order = {
            "_id": ObjectId("671fc0000000000000000105"),
            "order_number": "SGF-LEGACY-005",
            "payment_status": "lunas",
            "total_amount_le": 5000.0,
            "paid_amount_le": 5000.0,
            "admin_wage_legacy_reconciled": True,
        }
        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=[],
            payments=[],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.LEGACY_MANUAL_PAYMENT.value)
        self.assertEqual(res["reason_code"], "HISTORICAL_LEGACY_MANUAL_ORDER")
        self.assertTrue(res["owner_review_required"])

    def test_p1_06_unconfirmed_historical_looking_order_without_payments_fails_closed(self):
        """P1: Unconfirmed historical order (no legacy flag, zero payments) fails closed to AMBIGUOUS."""
        order = {
            "_id": ObjectId("671fc0000000000000000106"),
            "order_number": "SGF-HIST-006",
            "created_at": "2024-03-15T08:00:00Z",
            "payment_status": "lunas",
            "total_amount_le": 3500.0,
            "paid_amount_le": 3500.0,
        }
        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=[],
            payments=[],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res["reason_code"], "MISSING_PAYMENT_RECORDS")
        self.assertTrue(res["owner_review_required"])

    def test_p1_07_zero_total_order_with_zero_payments(self):
        """P1: Order with 0.0 total amount does not require payment documents."""
        order = {
            "_id": ObjectId("671fc0000000000000000107"),
            "order_number": "SGF-ZERO-007",
            "payment_status": "lunas",
            "total_amount_le": 0.0,
            "paid_amount_le": 0.0,
        }
        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=[],
            payments=[],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.ELIGIBLE_MISSING_OBLIGATION.value)
        self.assertEqual(res["reason_code"], "FULLY_PAID_MISSING_ACCRUAL")

    def test_p1_08_multiple_partial_payments_summing_to_total_eligible(self):
        """P1: Multiple partial payments summing up to total amount correctly pass validation."""
        order = {
            "_id": ObjectId("671fc0000000000000000108"),
            "order_number": "SGF-MULTI-008",
            "payment_status": "lunas",
            "total_amount_le": 2500.0,
            "paid_amount_le": 2500.0,
        }
        payments = [
            {"amount_le": 1000.0, "status": "paid"},
            {"amount_le": 500.0, "status": "paid"},
            {"amount_le": 1000.0, "status": "paid"},
        ]
        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=[],
            payments=payments,
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.ELIGIBLE_MISSING_OBLIGATION.value)
        self.assertEqual(res["reason_code"], "FULLY_PAID_MISSING_ACCRUAL")

    # ==========================================================================
    # 6. FINDING P2 REGRESSION TESTS: AUDIT TRAIL & CLEARED BLOCK MARKER
    # ==========================================================================

    def test_p2_audit_01_valid_blocked_state_correction_audit_event_eligible_corrected(self):
        """P2-Audit: Cleared block marker with valid correlated audit log classifies as BLOCKED_CONFIGURATION_CORRECTED."""
        oid = "671fc0000000000000000201"
        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-AUD-001",
            "payment_status": "lunas",
            "total_amount_le": 2000.0,
            "paid_amount_le": 2000.0,
            "admin_wage_blocked": None,
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 200.0,
                "recipient_id": self.staff_admin_id,
                "recipient_name": "Staff Admin",
            },
        }
        audit_logs = [
            {
                "action": "order_admin_wage_override_updated",
                "entity_id": oid,
                "entity_identifier": "SGF-AUD-001",
                "metadata": {
                    "resolved_blocked_state": {
                        "status": "blocked_hard_cap_conflict",
                        "attempted_amount_le": 600.0,
                    }
                },
            }
        ]
        payments = [{"amount_le": 2000.0, "status": "paid"}]
        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=audit_logs,
            payments=payments,
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.BLOCKED_CONFIGURATION_CORRECTED.value)
        self.assertEqual(res["reason_code"], "POST_BLOCKED_RESOLVED_PENDING_ACCRUAL")
        self.assertFalse(res["owner_review_required"])

    def test_p2_audit_02_cleared_block_marker_without_audit_log_fails_closed(self):
        """P2-Audit: Cleared block marker ('admin_wage_blocked': None) without audit log fails closed."""
        oid = "671fc0000000000000000202"
        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-AUD-002",
            "payment_status": "lunas",
            "total_amount_le": 2000.0,
            "paid_amount_le": 2000.0,
            "admin_wage_blocked": None,
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 200.0,
                "recipient_id": self.staff_admin_id,
                "recipient_name": "Staff Admin",
            },
        }
        payments = [{"amount_le": 2000.0, "status": "paid"}]
        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=[],
            payments=payments,
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res["reason_code"], "UNVERIFIABLE_BLOCKED_HISTORY")
        self.assertTrue(res["owner_review_required"])

    def test_p2_audit_03_cleared_block_marker_with_malformed_metadata_fails_closed(self):
        """P2-Audit: Cleared block marker with corrupt audit log metadata fails closed."""
        oid = "671fc0000000000000000203"
        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-AUD-003",
            "payment_status": "lunas",
            "total_amount_le": 2000.0,
            "paid_amount_le": 2000.0,
            "admin_wage_blocked": None,
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 200.0,
                "recipient_id": self.staff_admin_id,
                "recipient_name": "Staff Admin",
            },
        }
        audit_logs = [
            {
                "action": "order_admin_wage_override_updated",
                "entity_id": oid,
                "metadata": "CORRUPTED_STRING_NOT_A_DICT",
            }
        ]
        payments = [{"amount_le": 2000.0, "status": "paid"}]
        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=audit_logs,
            payments=payments,
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res["reason_code"], "UNVERIFIABLE_BLOCKED_HISTORY")
        self.assertTrue(res["owner_review_required"])

    def test_p2_audit_04_cleared_block_marker_with_unrelated_order_audit_log_fails_closed(self):
        """P2-Audit: Audit log for a different order does not satisfy cleared block verification."""
        oid = "671fc0000000000000000204"
        other_oid = "671fc0000000000000000999"
        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-AUD-004",
            "payment_status": "lunas",
            "total_amount_le": 2000.0,
            "paid_amount_le": 2000.0,
            "admin_wage_blocked": None,
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 200.0,
                "recipient_id": self.staff_admin_id,
                "recipient_name": "Staff Admin",
            },
        }
        audit_logs = [
            {
                "action": "order_admin_wage_override_updated",
                "entity_id": other_oid,
                "entity_identifier": "SGF-AUD-OTHER",
                "metadata": {
                    "resolved_blocked_state": {
                        "status": "blocked_hard_cap_conflict",
                    }
                },
            }
        ]
        payments = [{"amount_le": 2000.0, "status": "paid"}]
        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=audit_logs,
            payments=payments,
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res["reason_code"], "UNVERIFIABLE_BLOCKED_HISTORY")
        self.assertTrue(res["owner_review_required"])

    def test_p2_audit_05_bson_objectid_vs_string_entity_id_correlation(self):
        """P2-Audit: Correlates audit log whether entity_id is string or BSON ObjectId."""
        oid_str = "671fc0000000000000000205"
        order = {
            "_id": ObjectId(oid_str),
            "order_number": "SGF-AUD-005",
            "payment_status": "lunas",
            "total_amount_le": 2000.0,
            "paid_amount_le": 2000.0,
            "admin_wage_blocked": None,
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 200.0,
                "recipient_id": self.staff_admin_id,
                "recipient_name": "Staff Admin",
            },
        }
        audit_logs = [
            {
                "action": "order_admin_wage_override_updated",
                "entity_id": ObjectId(oid_str),  # BSON ObjectId in audit log
                "metadata": {
                    "resolved_blocked_state": {
                        "status": "blocked_hard_cap_conflict",
                    }
                },
            }
        ]
        payments = [{"amount_le": 2000.0, "status": "paid"}]
        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=audit_logs,
            payments=payments,
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.BLOCKED_CONFIGURATION_CORRECTED.value)

    def test_p2_audit_06_entity_identifier_order_number_correlation(self):
        """P2-Audit: Correlates audit log when matching via entity_identifier / order_number."""
        oid_str = "671fc0000000000000000206"
        order = {
            "_id": ObjectId(oid_str),
            "order_number": "SGF-AUD-006",
            "payment_status": "lunas",
            "total_amount_le": 2000.0,
            "paid_amount_le": 2000.0,
            "admin_wage_blocked": None,
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 200.0,
                "recipient_id": self.staff_admin_id,
                "recipient_name": "Staff Admin",
            },
        }
        audit_logs = [
            {
                "action": "order_admin_wage_override_updated",
                "entity_id": None,
                "entity_identifier": "SGF-AUD-006",
                "metadata": {
                    "resolved_blocked_state": {
                        "status": "blocked_hard_cap_conflict",
                    }
                },
            }
        ]
        payments = [{"amount_le": 2000.0, "status": "paid"}]
        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=audit_logs,
            payments=payments,
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.BLOCKED_CONFIGURATION_CORRECTED.value)

    def test_p2_audit_07_contradictory_correction_events_fails_closed(self):
        """P2-Audit: Contradictory/corrupt audit logs alongside valid ones fails closed."""
        oid = "671fc0000000000000000207"
        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-AUD-007",
            "payment_status": "lunas",
            "total_amount_le": 2000.0,
            "paid_amount_le": 2000.0,
            "admin_wage_blocked": None,
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 200.0,
                "recipient_id": self.staff_admin_id,
                "recipient_name": "Staff Admin",
            },
        }
        audit_logs = [
            {
                "action": "order_admin_wage_override_updated",
                "entity_id": oid,
                "metadata": {
                    "resolved_blocked_state": {"status": "blocked_hard_cap_conflict"}
                },
            },
            {
                "action": "order_admin_wage_override_cleared",
                "entity_id": oid,
                "metadata": None,  # Contradictory / corrupted
            },
        ]
        payments = [{"amount_le": 2000.0, "status": "paid"}]
        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=audit_logs,
            payments=payments,
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res["reason_code"], "UNVERIFIABLE_BLOCKED_HISTORY")
        self.assertTrue(res["owner_review_required"])

    def test_p2_audit_08_corrected_override_still_exceeding_hard_cap_fails_closed(self):
        """P2-Audit: Corrected override that still exceeds hard cap fails closed to BLOCKED_CAP_CONFLICT."""
        oid = "671fc0000000000000000208"
        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-AUD-008",
            "payment_status": "lunas",
            "total_amount_le": 2000.0,
            "paid_amount_le": 2000.0,
            "admin_wage_blocked": None,
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 700.0,  # 700.0 > 500.0 hard cap
                "recipient_id": self.staff_admin_id,
                "recipient_name": "Staff Admin",
            },
        }
        audit_logs = [
            {
                "action": "order_admin_wage_override_updated",
                "entity_id": oid,
                "metadata": {
                    "resolved_blocked_state": {"status": "blocked_hard_cap_conflict"}
                },
            }
        ]
        payments = [{"amount_le": 2000.0, "status": "paid"}]
        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=audit_logs,
            payments=payments,
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.BLOCKED_CAP_CONFLICT.value)
        self.assertEqual(res["reason_code"], "OVERRIDE_EXCEEDS_HARD_CAP")
        self.assertTrue(res["owner_review_required"])

    def test_p2_audit_09_normal_order_without_block_marker_no_unverifiable_flag(self):
        """P2-Audit: Normal order without block marker never flags UNVERIFIABLE_BLOCKED_HISTORY."""
        oid = "671fc0000000000000000209"
        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-AUD-009",
            "payment_status": "lunas",
            "total_amount_le": 1500.0,
            "paid_amount_le": 1500.0,
        }
        # Notice "admin_wage_blocked" key is completely absent
        payments = [{"amount_le": 1500.0, "status": "paid"}]
        res = classify_order(
            order=order,
            obligation=None,
            audit_logs=[],
            payments=payments,
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.ELIGIBLE_MISSING_OBLIGATION.value)
        self.assertEqual(res["reason_code"], "FULLY_PAID_MISSING_ACCRUAL")

    # ==========================================================================
    # 7. FINDING P2 REGRESSION TESTS: DUPLICATE WAGE OBLIGATIONS DETECTION
    # ==========================================================================

    def test_p2_dup_01_no_existing_obligations(self):
        """P2-Dup: Empty obligations list classifies as ELIGIBLE when other criteria pass."""
        order = {
            "_id": ObjectId("671fc0000000000000000301"),
            "order_number": "SGF-DUP-001",
            "payment_status": "lunas",
            "total_amount_le": 1000.0,
            "paid_amount_le": 1000.0,
        }
        payments = [{"amount_le": 1000.0, "status": "paid"}]
        res = classify_order(
            order=order,
            obligations=[],
            audit_logs=[],
            payments=payments,
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.ELIGIBLE_MISSING_OBLIGATION.value)

    def test_p2_dup_02_single_existing_accrued_obligation(self):
        """P2-Dup: Exactly 1 existing obligation classifies as EXISTING_OBLIGATION."""
        order = {
            "_id": ObjectId("671fc0000000000000000302"),
            "order_number": "SGF-DUP-002",
            "payment_status": "lunas",
            "total_amount_le": 1000.0,
            "paid_amount_le": 1000.0,
        }
        ob = {
            "_id": ObjectId("671fc0000000000000000399"),
            "obligation_number": "WOB-DUP-001",
            "task_category": "admin",
            "accrual_event_key": f"admin_wage:{order['_id']}",
            "status": "accrued",
            "paid_amount_le": 0.0,
        }
        res = classify_order(
            order=order,
            obligations=[ob],
            audit_logs=[],
            payments=[],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.EXISTING_OBLIGATION.value)
        self.assertEqual(res["existing_obligation_number"], "WOB-DUP-001")

    def test_p2_dup_03_two_distinct_obligations_same_canonical_key_ambiguous(self):
        """P2-Dup: Two distinct obligation documents with same canonical key trigger duplicate detection."""
        oid = "671fc0000000000000000303"
        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-DUP-003",
            "payment_status": "lunas",
            "total_amount_le": 1500.0,
            "paid_amount_le": 1500.0,
        }
        ob1 = {
            "_id": ObjectId("671fc0000000000000000311"),
            "obligation_number": "WOB-DUP-011",
            "accrual_event_key": f"admin_wage:{oid}",
            "status": "accrued",
        }
        ob2 = {
            "_id": ObjectId("671fc0000000000000000312"),
            "obligation_number": "WOB-DUP-012",
            "accrual_event_key": f"admin_wage:{oid}",
            "status": "accrued",
        }
        res = classify_order(
            order=order,
            obligations=[ob1, ob2],
            audit_logs=[],
            payments=[{"amount_le": 1500.0, "status": "paid"}],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res["reason_code"], "DUPLICATE_OBLIGATION_DOCUMENTS_DETECTED")
        self.assertTrue(res["owner_review_required"])
        self.assertIn("WOB-DUP-011", res["existing_obligation_number"])
        self.assertIn("WOB-DUP-012", res["existing_obligation_number"])

    def test_p2_dup_04_two_distinct_obligations_same_order_id_different_keys_ambiguous(self):
        """P2-Dup: Two distinct obligations with same order_id but different event keys trigger duplicate detection."""
        oid = "671fc0000000000000000304"
        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-DUP-004",
            "payment_status": "lunas",
            "total_amount_le": 1500.0,
            "paid_amount_le": 1500.0,
        }
        ob1 = {
            "_id": ObjectId("671fc0000000000000000313"),
            "obligation_number": "WOB-DUP-013",
            "order_id": oid,
            "task_category": "admin",
            "accrual_event_key": f"admin_wage:{oid}",
            "status": "accrued",
        }
        ob2 = {
            "_id": ObjectId("671fc0000000000000000314"),
            "obligation_number": "WOB-DUP-014",
            "order_id": oid,
            "task_category": "admin",
            "accrual_event_key": f"admin_wage:{oid}",
            "status": "accrued",
        }
        res = classify_order(
            order=order,
            obligations=[ob1, ob2],
            audit_logs=[],
            payments=[{"amount_le": 1500.0, "status": "paid"}],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res["reason_code"], "DUPLICATE_OBLIGATION_DOCUMENTS_DETECTED")
        self.assertTrue(res["owner_review_required"])

    def test_p2_dup_05_single_obligation_matched_by_both_order_id_and_key_deduplicated(self):
        """P2-Dup: The same obligation document matched by both order_id and key is deduplicated to 1."""
        oid = "671fc0000000000000000305"
        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-DUP-005",
            "payment_status": "lunas",
            "total_amount_le": 1500.0,
            "paid_amount_le": 1500.0,
        }
        same_ob = {
            "_id": ObjectId("671fc0000000000000000315"),
            "obligation_number": "WOB-DUP-015",
            "order_id": oid,
            "accrual_event_key": f"admin_wage:{oid}",
            "status": "accrued",
        }
        # Passing same document twice (e.g. from order_id match and accrual_event_key match)
        res = classify_order(
            order=order,
            obligations=[same_ob, same_ob],
            audit_logs=[],
            payments=[],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.EXISTING_OBLIGATION.value)
        self.assertEqual(res["existing_obligation_number"], "WOB-DUP-015")
        self.assertFalse(res["owner_review_required"])

    def test_p2_dup_06_duplicate_obligations_where_one_is_paid_ambiguous(self):
        """P2-Dup: Duplicate obligations where one is already paid still triggers duplicate detection."""
        oid = "671fc0000000000000000306"
        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-DUP-006",
            "payment_status": "lunas",
            "total_amount_le": 1500.0,
            "paid_amount_le": 1500.0,
        }
        ob1 = {
            "_id": ObjectId("671fc0000000000000000316"),
            "obligation_number": "WOB-DUP-016",
            "task_category": "admin",
            "accrual_event_key": f"admin_wage:{oid}",
            "status": "accrued",
        }
        ob2 = {
            "_id": ObjectId("671fc0000000000000000317"),
            "obligation_number": "WOB-DUP-017",
            "task_category": "admin",
            "accrual_event_key": f"admin_wage:{oid}",
            "status": "paid",
            "paid_amount_le": 100.0,
        }
        res = classify_order(
            order=order,
            obligations=[ob1, ob2],
            audit_logs=[],
            payments=[],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res["reason_code"], "DUPLICATE_OBLIGATION_DOCUMENTS_DETECTED")
        self.assertTrue(res["owner_review_required"])

    async def test_p2_dup_07_runner_preloads_and_detects_duplicate_obligations(self):
        """P2-Dup: Full dry-run runner correctly preloads and isolates orders with duplicate obligations."""
        mock_db = MagicMock()

        # Settings
        mock_settings = MagicMock()
        mock_settings.find_one = AsyncMock(return_value={
            "key": "admin_wage_policy",
            "value": self.valid_policy,
        })
        mock_db.settings = mock_settings

        # Admins
        mock_admins = MagicMock()
        mock_admin_cursor = MagicMock()
        mock_admin_cursor.to_list = AsyncMock(return_value=[
            {"_id": ObjectId(self.staff_admin_id), "name": "Staff Admin", "is_active": True}
        ])
        mock_admins.find.return_value = mock_admin_cursor
        mock_db.admins = mock_admins

        # Order
        target_oid = "671fc0000000000000000307"
        mock_orders = MagicMock()
        mock_order_cursor = MagicMock()
        mock_order_cursor.sort.return_value = mock_order_cursor
        mock_order_cursor.to_list = AsyncMock(return_value=[
            {
                "_id": ObjectId(target_oid),
                "order_number": "SGF-DUP-007",
                "payment_status": "lunas",
                "total_amount_le": 1200.0,
                "paid_amount_le": 1200.0,
                "outstanding_amount_le": 0.0,
            }
        ])
        mock_orders.find.return_value = mock_order_cursor
        mock_db.orders = mock_orders

        # Wage obligations returning 2 distinct records for target_oid
        mock_wob = MagicMock()
        mock_wob_cursor = MagicMock()
        mock_wob_cursor.to_list = AsyncMock(return_value=[
            {
                "_id": ObjectId("671fc0000000000000000318"),
                "order_id": target_oid,
                "obligation_number": "WOB-DUP-018",
                "accrual_event_key": f"admin_wage:{target_oid}",
                "status": "accrued",
            },
            {
                "_id": ObjectId("671fc0000000000000000319"),
                "order_id": target_oid,
                "obligation_number": "WOB-DUP-019",
                "accrual_event_key": f"admin_wage:{target_oid}",
                "status": "accrued",
            },
        ])
        mock_wob.find.return_value = mock_wob_cursor
        mock_db.wage_obligations = mock_wob

        # Audit logs and payments
        mock_audit = MagicMock()
        mock_audit_cursor = MagicMock()
        mock_audit_cursor.to_list = AsyncMock(return_value=[])
        mock_audit.find.return_value = mock_audit_cursor
        mock_db.audit_logs = mock_audit

        mock_payments = MagicMock()
        mock_pmt_cursor = MagicMock()
        mock_pmt_cursor.to_list = AsyncMock(return_value=[
            {"_id": ObjectId(), "order_id": target_oid, "amount_le": 1200.0, "status": "paid"}
        ])
        mock_payments.find.return_value = mock_pmt_cursor
        mock_db.payments = mock_payments

        manifest = await run_reconciliation_dry_run(mock_db)
        self.assertEqual(manifest["summary"]["total_orders_inspected"], 1)
        self.assertEqual(manifest["summary"]["total_eligible_orders"], 0)
        self.assertEqual(manifest["summary"]["total_owner_review_required"], 1)
        
        candidate = manifest["candidates"][0]
        self.assertEqual(candidate["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(candidate["reason_code"], "DUPLICATE_OBLIGATION_DOCUMENTS_DETECTED")
        self.assertTrue(candidate["owner_review_required"])
