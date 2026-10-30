"""
Phase 08.5C.1 — Reconciliation Query and Historical Classification Remediation Test Suite.
Sogil Furniture | Financial Integrity First

Comprehensive verification of:
1. Carpenter obligation shares an order ID with a missing admin obligation.
2. Multiple carpenter obligations must not cause an admin duplicate classification.
3. One genuine admin obligation is recognized through the canonical accrual event key.
4. Multiple genuine admin obligations for one order remain ambiguous.
5. The same obligation document matching multiple query paths is counted once.
6. ObjectId and string representations do not cause false duplicates.
7. A paid order with no admin obligation and disabled policy is not automatically treated as historically reconciled.
8. Known historical manual-payment evidence produces LEGACY_MANUAL_PAYMENT.
9. Missing or incomplete historical evidence produces AMBIGUOUS_REQUIRES_OWNER_REVIEW (LEGACY_PAYMENT_STATUS_UNVERIFIABLE).
10. Existing paid/partially paid admin obligations remain immutable.
11. No test depends on production database access (100% in-memory mocks and fixtures).
12. Existing --apply rejection and read-only invariants remain intact.
13. Reproduction of Phase 08.5C 15-order production dry-run scenarios without accessing production.
"""

import asyncio
import copy
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from datetime import datetime, timezone
import pytest

from scripts.reconcile_admin_wages import (
    CandidateCategory,
    DEFAULT_ADMIN_WAGE_SYSTEM_CUTOFF,
    KNOWN_WORKER_TASK_CATEGORIES,
    build_admin_wage_accrual_event_key,
    classify_order,
    evaluate_obligation_type,
    run_reconciliation_dry_run,
    format_markdown_report,
    format_json_report,
    parse_args,
    main_async,
)


class TestPhase08_5C1Remediation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.owner_id = "6a903257e895ef02b51d9636"
        self.azka_id = "6a9031b86f261cb1ed5479ad"
        self.worker_id = "6aad900ed142966177ee787a"

        self.admins_by_id = {
            self.owner_id: {
                "_id": ObjectId(self.owner_id),
                "name": "Owner Sogil",
                "role": "owner",
                "is_active": True,
            },
            self.azka_id: {
                "_id": ObjectId(self.azka_id),
                "name": "Azka",
                "role": "staff",
                "is_active": True,
            },
            self.worker_id: {
                "_id": ObjectId(self.worker_id),
                "name": "Ayyas",
                "role": "worker",
                "is_active": True,
            },
        }

        self.active_policy = {
            "default_wage_per_order_le": 50.0,
            "default_recipient_id": self.azka_id,
            "default_recipient_name": "Azka",
            "unusual_amount_threshold_le": 75.0,
            "max_wage_per_order_le": 100.0,
            "enabled": True,
            "currency": "EGP",
            "is_configured": True,
            "admin_wage_system_cutoff": "2026-10-25T00:00:00Z",
        }

        self.disabled_policy = copy.deepcopy(self.active_policy)
        self.disabled_policy["enabled"] = False

    # ==========================================================================
    # TEST 1: Carpenter obligation shares order ID with missing admin obligation
    # ==========================================================================
    def test_01_carpenter_obligation_shares_order_id_with_missing_admin_obligation(self):
        """Carpenter obligation (task_category: whole_item) must not be counted as admin obligation."""
        oid = "671fc0000000000000000001"
        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-2026-MODERN-001",
            "order_date": "2026-10-26T10:00:00Z",  # Modern order post-cutoff
            "payment_status": "lunas",
            "total_amount_le": 2000.0,
            "paid_amount_le": 2000.0,
        }
        # Carpenter wage obligation
        carpenter_ob = {
            "_id": ObjectId("671fc0000000000000000011"),
            "obligation_number": "WOB-CARPENTER-001",
            "order_id": oid,
            "work_assignment_id": "wa_671fc0000000000000000011",
            "task_category": "whole_item",
            "worker_id": self.worker_id,
            "worker_name": "Ayyas",
            "total_amount_le": 200.0,
            "status": "paid",
            "paid_amount_le": 200.0,
        }
        payments = [{"amount_le": 2000.0, "status": "paid"}]

        res = classify_order(
            order=order,
            obligations=[carpenter_ob],
            audit_logs=[],
            payments=payments,
            policy=self.active_policy,
            admins_by_id=self.admins_by_id,
        )

        # Carpenter obligation is filtered out; modern order missing admin obligation is eligible
        self.assertEqual(res["candidate_category"], CandidateCategory.ELIGIBLE_MISSING_OBLIGATION.value)
        self.assertEqual(res["reason_code"], "FULLY_PAID_MISSING_ACCRUAL")
        self.assertEqual(res["proposed_amount_le"], 50.0)
        self.assertEqual(res["proposed_recipient_id"], self.azka_id)
        self.assertFalse(res["owner_review_required"])

    # ==========================================================================
    # TEST 2: Multiple carpenter obligations do not cause duplicate admin classification
    # ==========================================================================
    def test_02_multiple_carpenter_obligations_do_not_cause_admin_duplicate_classification(self):
        """Phase 08.5C Finding: Orders with multiple carpenter obligations must NOT trigger DUPLICATE_OBLIGATION_DOCUMENTS_DETECTED."""
        oid = "6acb6b6a9b8a6826afde4d29"
        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-2026-MODERN-002",
            "order_date": "2026-10-26T12:00:00Z",
            "payment_status": "lunas",
            "total_amount_le": 3000.0,
            "paid_amount_le": 3000.0,
        }
        # Two distinct carpenter obligations (like in SGF-20261011-001)
        carpenter_ob1 = {
            "_id": ObjectId("6ad22e106b124acb2e581c04"),
            "obligation_number": "WOB-20261016-0001",
            "order_id": oid,
            "work_assignment_id": "6ad22e106b124acb2e581c04",
            "task_category": "whole_item",
            "worker_name": "Ayyas",
            "status": "paid",
        }
        carpenter_ob2 = {
            "_id": ObjectId("6ad23c286b124acb2e581c11"),
            "obligation_number": "WOB-20261016-0002",
            "order_id": oid,
            "work_assignment_id": "6ad23c286b124acb2e581c11",
            "task_category": "whole_item",
            "worker_name": "Zikra",
            "status": "paid",
        }
        payments = [{"amount_le": 3000.0, "status": "paid"}]

        res = classify_order(
            order=order,
            obligations=[carpenter_ob1, carpenter_ob2],
            audit_logs=[],
            payments=payments,
            policy=self.active_policy,
            admins_by_id=self.admins_by_id,
        )

        self.assertNotEqual(res["reason_code"], "DUPLICATE_OBLIGATION_DOCUMENTS_DETECTED")
        self.assertEqual(res["candidate_category"], CandidateCategory.ELIGIBLE_MISSING_OBLIGATION.value)
        self.assertFalse(res["owner_review_required"])

    # ==========================================================================
    # TEST 3: One genuine admin obligation recognized through canonical key
    # ==========================================================================
    def test_03_genuine_admin_obligation_recognized_through_canonical_accrual_key(self):
        """Genuine admin wage obligation with accrual_event_key admin_wage:{order_id} is recognized."""
        oid = "671fc0000000000000000003"
        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-2026-0003",
            "order_date": "2026-10-26T10:00:00Z",
            "payment_status": "lunas",
            "total_amount_le": 1500.0,
            "paid_amount_le": 1500.0,
        }
        admin_ob = {
            "_id": ObjectId("671fc0000000000000000033"),
            "obligation_number": "WOB-ADMIN-0001",
            "order_id": oid,
            "accrual_event_key": f"admin_wage:{oid}",
            "task_category": "admin",
            "pricing_basis": "per_order_admin",
            "status": "accrued",
            "total_amount_le": 50.0,
            "paid_amount_le": 0.0,
        }

        res = classify_order(
            order=order,
            obligations=[admin_ob],
            audit_logs=[],
            payments=[{"amount_le": 1500.0, "status": "paid"}],
            policy=self.active_policy,
            admins_by_id=self.admins_by_id,
        )

        self.assertEqual(res["candidate_category"], CandidateCategory.EXISTING_OBLIGATION.value)
        self.assertEqual(res["reason_code"], "OBLIGATION_ALREADY_ACCRUED")
        self.assertEqual(res["existing_obligation_number"], "WOB-ADMIN-0001")
        self.assertFalse(res["owner_review_required"])

    # ==========================================================================
    # TEST 4: Multiple genuine admin obligations for one order remain ambiguous
    # ==========================================================================
    def test_04_multiple_genuine_admin_obligations_remain_ambiguous(self):
        """Multiple distinct admin wage obligations for same order trigger DUPLICATE_OBLIGATION_DOCUMENTS_DETECTED."""
        oid = "671fc0000000000000000004"
        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-2026-0004",
            "order_date": "2026-10-26T10:00:00Z",
            "payment_status": "lunas",
            "total_amount_le": 2500.0,
            "paid_amount_le": 2500.0,
        }
        admin_ob1 = {
            "_id": ObjectId("671fc0000000000000000041"),
            "obligation_number": "WOB-ADMIN-0041",
            "order_id": oid,
            "accrual_event_key": f"admin_wage:{oid}",
            "task_category": "admin",
            "status": "accrued",
        }
        admin_ob2 = {
            "_id": ObjectId("671fc0000000000000000042"),
            "obligation_number": "WOB-ADMIN-0042",
            "order_id": oid,
            "task_category": "admin",
            "pricing_basis": "per_order_admin",
            "status": "accrued",
        }

        res = classify_order(
            order=order,
            obligations=[admin_ob1, admin_ob2],
            audit_logs=[],
            payments=[{"amount_le": 2500.0, "status": "paid"}],
            policy=self.active_policy,
            admins_by_id=self.admins_by_id,
        )

        self.assertEqual(res["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res["reason_code"], "DUPLICATE_OBLIGATION_DOCUMENTS_DETECTED")
        self.assertTrue(res["owner_review_required"])

    # ==========================================================================
    # TEST 5: Same obligation document matching multiple query paths is counted once
    # ==========================================================================
    def test_05_same_obligation_document_matching_multiple_paths_is_deduplicated(self):
        """Document matched via both accrual_event_key and order_id is deduplicated and not counted twice."""
        oid = "671fc0000000000000000005"
        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-2026-0005",
            "order_date": "2026-10-26T10:00:00Z",
            "payment_status": "lunas",
            "total_amount_le": 1000.0,
            "paid_amount_le": 1000.0,
        }
        # Same doc passed twice in list (representing cursor matching via two $or clauses)
        ob_doc = {
            "_id": ObjectId("671fc0000000000000000055"),
            "obligation_number": "WOB-ADMIN-0055",
            "order_id": oid,
            "accrual_event_key": f"admin_wage:{oid}",
            "task_category": "admin",
            "status": "accrued",
        }
        ob_doc_clone = copy.deepcopy(ob_doc)

        res = classify_order(
            order=order,
            obligations=[ob_doc, ob_doc_clone],
            audit_logs=[],
            payments=[{"amount_le": 1000.0, "status": "paid"}],
            policy=self.active_policy,
            admins_by_id=self.admins_by_id,
        )

        # Deduplication succeeds -> single obligation -> EXISTING_OBLIGATION (NOT ambiguous duplicate)
        self.assertEqual(res["candidate_category"], CandidateCategory.EXISTING_OBLIGATION.value)
        self.assertEqual(res["reason_code"], "OBLIGATION_ALREADY_ACCRUED")
        self.assertEqual(res["existing_obligation_number"], "WOB-ADMIN-0055")
        self.assertFalse(res["owner_review_required"])

    # ==========================================================================
    # TEST 6: ObjectId and string representations do not cause false duplicates
    # ==========================================================================
    def test_06_objectid_and_string_normalization_does_not_cause_false_duplicates(self):
        """ObjectId vs string _id representations must be normalized and not create false duplicate flags."""
        oid = "671fc0000000000000000006"
        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-2026-0006",
            "order_date": "2026-10-26T10:00:00Z",
            "payment_status": "lunas",
            "total_amount_le": 1000.0,
            "paid_amount_le": 1000.0,
        }
        ob_obj_id = {
            "_id": ObjectId("671fc0000000000000000066"),
            "obligation_number": "WOB-ADMIN-0066",
            "order_id": ObjectId(oid),
            "accrual_event_key": f"admin_wage:{oid}",
            "task_category": "admin",
            "status": "accrued",
        }
        ob_str_id = {
            "_id": "671fc0000000000000000066",
            "obligation_number": "WOB-ADMIN-0066",
            "order_id": str(oid),
            "accrual_event_key": f"admin_wage:{oid}",
            "task_category": "admin",
            "status": "accrued",
        }

        res = classify_order(
            order=order,
            obligations=[ob_obj_id, ob_str_id],
            audit_logs=[],
            payments=[{"amount_le": 1000.0, "status": "paid"}],
            policy=self.active_policy,
            admins_by_id=self.admins_by_id,
        )

        self.assertEqual(res["candidate_category"], CandidateCategory.EXISTING_OBLIGATION.value)
        self.assertEqual(res["existing_obligation_number"], "WOB-ADMIN-0066")

    # ==========================================================================
    # TEST 7: Paid historical order with disabled policy is NOT historically reconciled
    # ==========================================================================
    def test_07_historical_paid_order_with_disabled_policy_not_auto_reconciled(self):
        """A historical paid order with disabled policy must NOT be treated as reconciled, nor falsely marked INVALID_CONFIG."""
        oid = "6abd2fa9ba628977745838e7"  # SGF-20260930-001 from Phase 08.5C
        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-20260930-001",
            "order_date": "2026-09-30T15:50:01Z",
            "payment_status": "lunas",
            "total_amount_le": 2475.25,
            "paid_amount_le": 2475.25,
            "admin_wage_legacy_reconciled": None,
        }
        payments = [{"amount_le": 2475.25, "status": "paid"}]

        res = classify_order(
            order=order,
            obligations=[],
            audit_logs=[],
            payments=payments,
            policy=self.disabled_policy,  # Policy disabled!
            admins_by_id=self.admins_by_id,
        )

        # Must NOT be LEGACY_MANUAL_PAYMENT (not reconciled)
        self.assertNotEqual(res["candidate_category"], CandidateCategory.LEGACY_MANUAL_PAYMENT.value)
        # Must NOT be silently dismissed as INVALID_OR_MISSING_CONFIGURATION
        self.assertNotEqual(res["candidate_category"], CandidateCategory.INVALID_OR_MISSING_CONFIGURATION.value)
        # Must be flagged as AMBIGUOUS_REQUIRES_OWNER_REVIEW with LEGACY_PAYMENT_STATUS_UNVERIFIABLE
        self.assertEqual(res["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res["reason_code"], "LEGACY_PAYMENT_STATUS_UNVERIFIABLE")
        self.assertTrue(res["owner_review_required"])

    # ==========================================================================
    # TEST 8: Known historical manual-payment evidence produces LEGACY_MANUAL_PAYMENT
    # ==========================================================================
    def test_08_known_historical_manual_payment_evidence_produces_legacy_manual_payment(self):
        """Order with admin_wage_legacy_reconciled: True produces LEGACY_MANUAL_PAYMENT."""
        oid = "671fc0000000000000000008"
        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-CONFIRMED-LEGACY-008",
            "order_date": "2026-10-01T10:00:00Z",
            "payment_status": "lunas",
            "total_amount_le": 4500.0,
            "paid_amount_le": 4500.0,
            "admin_wage_legacy_reconciled": True,
            "admin_wage_recipient_name": "Azka",
            "legacy_finance_transaction_id": "txn_manual_azka_123",
        }

        res = classify_order(
            order=order,
            obligations=[],
            audit_logs=[],
            payments=[],
            policy=self.active_policy,
            admins_by_id=self.admins_by_id,
        )

        self.assertEqual(res["candidate_category"], CandidateCategory.LEGACY_MANUAL_PAYMENT.value)
        self.assertEqual(res["reason_code"], "HISTORICAL_LEGACY_MANUAL_ORDER")
        self.assertTrue(res["owner_review_required"])
        self.assertEqual(res["recommended_action"], "ISOLATE_FOR_OWNER_REVIEW")

    # ==========================================================================
    # TEST 9: Missing or incomplete historical evidence produces AMBIGUOUS_REQUIRES_OWNER_REVIEW
    # ==========================================================================
    def test_09_missing_or_incomplete_historical_evidence_produces_ambiguous_owner_review(self):
        """Historical order (created pre-cutoff) without reliable legacy evidence produces AMBIGUOUS with LEGACY_PAYMENT_STATUS_UNVERIFIABLE."""
        oid = "6acb6f789b8a6826afde4d2a"  # SGF-20261011-002
        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-20261011-002",
            "order_date": "2026-10-11T11:14:00Z",
            "payment_status": "lunas",
            "total_amount_le": 4000.0,
            "paid_amount_le": 4000.0,
        }
        payments = [{"amount_le": 4000.0, "status": "paid"}]

        res = classify_order(
            order=order,
            obligations=[],
            audit_logs=[],
            payments=payments,
            policy=self.active_policy,  # Even with active policy!
            admins_by_id=self.admins_by_id,
        )

        self.assertEqual(res["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res["reason_code"], "LEGACY_PAYMENT_STATUS_UNVERIFIABLE")
        self.assertTrue(res["owner_review_required"])

    # ==========================================================================
    # TEST 10: Existing paid/partially paid admin obligations remain immutable
    # ==========================================================================
    def test_10_existing_paid_or_partially_paid_admin_obligations_remain_immutable(self):
        """Admin wage obligation with status paid is classified as OBLIGATION_ALREADY_SETTLED_OR_PARTIALLY_SETTLED and locked."""
        oid = "671fc0000000000000000010"
        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-2026-0010",
            "order_date": "2026-10-26T10:00:00Z",
            "payment_status": "lunas",
            "total_amount_le": 1000.0,
            "paid_amount_le": 1000.0,
        }
        paid_admin_ob = {
            "_id": ObjectId("671fc0000000000000000101"),
            "obligation_number": "WOB-ADMIN-PAID-01",
            "order_id": oid,
            "accrual_event_key": f"admin_wage:{oid}",
            "task_category": "admin",
            "pricing_basis": "per_order_admin",
            "status": "paid",
            "paid_amount_le": 50.0,
            "settlement_id": "WST-20261026-0001",
        }

        res = classify_order(
            order=order,
            obligations=[paid_admin_ob],
            audit_logs=[],
            payments=[{"amount_le": 1000.0, "status": "paid"}],
            policy=self.active_policy,
            admins_by_id=self.admins_by_id,
        )

        self.assertEqual(res["candidate_category"], CandidateCategory.OBLIGATION_ALREADY_SETTLED_OR_PARTIALLY_SETTLED.value)
        self.assertEqual(res["reason_code"], "OBLIGATION_SETTLED_OR_PARTIAL")
        self.assertEqual(res["recommended_action"], "NO_ACTION_REQUIRED")
        self.assertFalse(res["owner_review_required"])

    # ==========================================================================
    # TEST 11: Unknown legacy obligation types handled conservatively
    # ==========================================================================
    def test_11_unknown_legacy_obligation_types_handled_conservatively(self):
        """Obligation with unrecognized task_category triggers UNKNOWN_OBLIGATION_TYPE_DETECTED."""
        oid = "671fc0000000000000000011"
        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-2026-0011",
            "order_date": "2026-10-26T10:00:00Z",
            "payment_status": "lunas",
            "total_amount_le": 1000.0,
            "paid_amount_le": 1000.0,
        }
        unknown_ob = {
            "_id": ObjectId("671fc0000000000000000111"),
            "obligation_number": "WOB-UNKNOWN-001",
            "order_id": oid,
            "task_category": "special_unsupported_category",
            "status": "accrued",
        }

        res = classify_order(
            order=order,
            obligations=[unknown_ob],
            audit_logs=[],
            payments=[{"amount_le": 1000.0, "status": "paid"}],
            policy=self.active_policy,
            admins_by_id=self.admins_by_id,
        )

        self.assertEqual(res["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res["reason_code"], "UNKNOWN_OBLIGATION_TYPE_DETECTED")
        self.assertTrue(res["owner_review_required"])

    # ==========================================================================
    # TEST 12: Invariants and Apply-Mode Rejection
    # ==========================================================================
    def test_12_apply_mode_rejection_and_read_only_invariant(self):
        """CLI parser accepts --dry-run and main_async strictly rejects --apply."""
        args_dry = parse_args(["--dry-run"])
        self.assertTrue(args_dry.dry_run)
        self.assertFalse(args_dry.apply)

        args_apply = parse_args(["--apply"])
        self.assertTrue(args_apply.apply)

        with self.assertRaises(SystemExit) as ctx:
            asyncio.run(main_async(["--apply"]))
        self.assertNotEqual(ctx.exception.code, 0)

    # ==========================================================================
    # TEST 13: Full Reproduction of Phase 08.5C Production Orders (15 Orders)
    # ==========================================================================
    async def test_13_reproduce_phase_08_5c_15_production_orders_dry_run(self):
        """
        Simulates the entire 15-order production dataset from Phase 08.5C in-memory.
        Verifies:
        - 13 historical orders become AMBIGUOUS_REQUIRES_OWNER_REVIEW (LEGACY_PAYMENT_STATUS_UNVERIFIABLE).
        - 2 unpaid orders become ORDER_NOT_FULLY_PAID.
        - 0 eligible candidates (0.00 LE).
        - historical_liability_status is UNRESOLVED_REQUIRES_OWNER_REVIEW.
        - Zero production access, zero database mutation.
        """
        # Mock database with 15 orders, 11 carpenter obligations, 13 payments
        mock_db = MagicMock()

        # Policy document in settings (enabled: False as in production)
        policy_doc = {
            "key": "admin_wage_policy",
            "value": {
                "default_wage_per_order_le": 50.0,
                "default_recipient_id": self.azka_id,
                "default_recipient_name": "Azka",
                "unusual_amount_threshold_le": 75.0,
                "max_wage_per_order_le": 100.0,
                "enabled": False,
                "currency": "EGP",
                "admin_wage_system_cutoff": "2026-10-25T00:00:00Z",
            }
        }
        mock_db.settings.find_one = AsyncMock(return_value=policy_doc)

        # Mock Admins
        mock_db.admins.find.return_value.to_list = AsyncMock(return_value=list(self.admins_by_id.values()))

        # 15 Orders from Phase 08.5C
        orders_data = [
            {"_id": ObjectId("6abd2fa9ba628977745838e7"), "order_number": "SGF-20260930-001", "created_at": "2026-09-30T15:50:01Z", "payment_status": "lunas", "total_amount_le": 2475.25, "paid_amount_le": 2475.25},
            {"_id": ObjectId("6abf4ee626a940e388c7e258"), "order_number": "SGF-20261002-001", "created_at": "2026-10-02T06:27:50Z", "payment_status": "lunas", "total_amount_le": 1000.0, "paid_amount_le": 1000.0},
            {"_id": ObjectId("6ac0bab18d54d51a83fdf23d"), "order_number": "SGF-20261003-001", "created_at": "2026-10-03T08:20:01Z", "payment_status": "lunas", "total_amount_le": 2495.0, "paid_amount_le": 2495.0},
            {"_id": ObjectId("6ac3f0e1d059c322df25dc55"), "order_number": "SGF-20261005-001", "created_at": "2026-10-05T18:48:00Z", "payment_status": "lunas", "total_amount_le": 1197.25, "paid_amount_le": 1197.25},
            {"_id": ObjectId("6ac544b2015d50fe8676c37a"), "order_number": "SGF-20261006-002", "created_at": "2026-10-06T18:57:54Z", "payment_status": "lunas", "total_amount_le": 3249.5, "paid_amount_le": 3249.5},
            {"_id": ObjectId("6acb6b6a9b8a6826afde4d29"), "order_number": "SGF-20261011-001", "created_at": "2026-10-11T10:56:41Z", "payment_status": "lunas", "total_amount_le": 2600.0, "paid_amount_le": 2600.0},
            {"_id": ObjectId("6acb6f789b8a6826afde4d2a"), "order_number": "SGF-20261011-002", "created_at": "2026-10-11T11:14:00Z", "payment_status": "lunas", "total_amount_le": 4000.0, "paid_amount_le": 4000.0},
            {"_id": ObjectId("6acb7c939b8a6826afde4d2b"), "order_number": "SGF-20261011-003", "created_at": "2026-10-11T12:09:55Z", "payment_status": "lunas", "total_amount_le": 2650.0, "paid_amount_le": 2650.0},
            {"_id": ObjectId("6ad266bbf538c800cb2ca2b3"), "order_number": "SGF-20261016-001", "created_at": "2026-10-16T18:02:34Z", "payment_status": "lunas", "total_amount_le": 1450.0, "paid_amount_le": 1450.0},
            {"_id": ObjectId("6ad36846d9f2684525145843"), "order_number": "SGF-20261017-001", "created_at": "2026-10-17T12:21:26Z", "payment_status": "lunas", "total_amount_le": 2400.0, "paid_amount_le": 2400.0},
            {"_id": ObjectId("6ad3766ed9f2684525145847"), "order_number": "SGF-20261017-002", "created_at": "2026-10-17T13:21:49Z", "payment_status": "lunas", "total_amount_le": 5535.0, "paid_amount_le": 5535.0},
            {"_id": ObjectId("6ad4e8aa2d3a597898f07221"), "order_number": "SGF-20261018-001", "created_at": "2026-10-18T15:41:30Z", "payment_status": "lunas", "total_amount_le": 1853.75, "paid_amount_le": 1853.75},
            {"_id": ObjectId("6ad666e12d3a597898f0722e"), "order_number": "SGF-20261019-001", "created_at": "2026-10-19T18:52:17Z", "payment_status": "lunas", "total_amount_le": 1000.0, "paid_amount_le": 1000.0},
            {"_id": ObjectId("6adf591c72e47fb702a82edc"), "order_number": "SGF-20261026-001", "created_at": "2026-10-26T13:43:55Z", "payment_status": "belum_dibayar", "total_amount_le": 1500.0, "paid_amount_le": 0.0},
            {"_id": ObjectId("6ae1fd4b78207d8e64c2a092"), "order_number": "SGF-20261028-001", "created_at": "2026-10-28T13:48:59Z", "payment_status": "belum_dibayar", "total_amount_le": 2000.0, "paid_amount_le": 0.0},
        ]

        # 11 Carpenter wage obligations
        carpenter_wobs = [
            {"obligation_number": "WOB-20261016-0001", "accrual_event_key": "acc_6ad22e106b124acb2e581c04", "work_assignment_id": "6ad22e106b124acb2e581c04", "order_id": "6acb6b6a9b8a6826afde4d29", "task_category": "whole_item", "status": "paid"},
            {"obligation_number": "WOB-20261016-0002", "accrual_event_key": "acc_6ad23c286b124acb2e581c11", "work_assignment_id": "6ad23c286b124acb2e581c11", "order_id": "6acb6b6a9b8a6826afde4d29", "task_category": "whole_item", "status": "paid"},
            {"obligation_number": "WOB-20261017-0001", "accrual_event_key": "acc_6ad3f1e6d9f268452514584e", "work_assignment_id": "6ad3f1e6d9f268452514584e", "order_id": "6ad266bbf538c800cb2ca2b3", "task_category": "whole_item", "status": "paid"},
            {"obligation_number": "WOB-20261017-0002", "accrual_event_key": "acc_6ad37d3cd9f2684525145848", "work_assignment_id": "6ad37d3cd9f2684525145848", "order_id": "6ad36846d9f2684525145843", "task_category": "whole_item", "status": "paid"},
            {"obligation_number": "WOB-20261017-0003", "accrual_event_key": "acc_6ad37d53d9f2684525145849", "work_assignment_id": "6ad37d53d9f2684525145849", "order_id": "6ad36846d9f2684525145843", "task_category": "whole_item", "status": "paid"},
            {"obligation_number": "WOB-20261019-0001", "accrual_event_key": "acc_6ad694022d3a597898f0722f", "work_assignment_id": "6ad694022d3a597898f0722f", "order_id": "6ad4e8aa2d3a597898f07221", "task_category": "whole_item", "status": "paid"},
            {"obligation_number": "WOB-20261019-0002", "accrual_event_key": "acc_6ad6949c2d3a597898f07234", "work_assignment_id": "6ad6949c2d3a597898f07234", "order_id": "6ad666e12d3a597898f0722e", "task_category": "whole_item", "status": "paid"},
            {"obligation_number": "WOB-20261020-0001", "accrual_event_key": "acc_6ad3f571d9f268452514585e", "work_assignment_id": "6ad3f571d9f268452514585e", "order_id": "6acb7c939b8a6826afde4d2b", "task_category": "whole_item", "status": "paid"},
            {"obligation_number": "WOB-20261020-0002", "accrual_event_key": "acc_6ad6947a2d3a597898f07233", "work_assignment_id": "6ad6947a2d3a597898f07233", "order_id": "6ad3766ed9f2684525145847", "task_category": "whole_item", "status": "paid"},
            {"obligation_number": "WOB-20261020-0003", "accrual_event_key": "acc_6ad3f55fd9f268452514585d", "work_assignment_id": "6ad3f55fd9f268452514585d", "order_id": "6acb7c939b8a6826afde4d2b", "task_category": "whole_item", "status": "paid"},
            {"obligation_number": "WOB-20261020-0004", "accrual_event_key": "acc_6ad6945b2d3a597898f07232", "work_assignment_id": "6ad6945b2d3a597898f07232", "order_id": "6ad3766ed9f2684525145847", "task_category": "whole_item", "status": "paid"},
        ]

        # 13 Payments
        payments_data = [
            {"order_id": str(o["_id"]), "amount_le": o["total_amount_le"], "status": "paid"}
            for o in orders_data if o["payment_status"] == "lunas"
        ]

        mock_db.orders.find.return_value.sort.return_value.to_list = AsyncMock(return_value=orders_data)
        mock_db.wage_obligations.find.return_value.to_list = AsyncMock(return_value=carpenter_wobs)
        mock_db.audit_logs.find.return_value.to_list = AsyncMock(return_value=[])
        mock_db.payments.find.return_value.to_list = AsyncMock(return_value=payments_data)

        # Run Dry-Run Engine
        report = await run_reconciliation_dry_run(db=mock_db)
        summary = report["summary"]

        self.assertEqual(summary["total_orders_inspected"], 15)
        self.assertEqual(summary["total_eligible_orders"], 0)
        self.assertEqual(summary["total_eligible_wage_amount_le"], 0.0)
        self.assertEqual(summary["category_counts"][CandidateCategory.ORDER_NOT_FULLY_PAID.value], 2)
        # All 13 historical orders must now be properly classified as AMBIGUOUS_REQUIRES_OWNER_REVIEW
        self.assertEqual(summary["category_counts"][CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value], 13)
        self.assertEqual(summary["total_historical_unresolved"], 13)
        self.assertEqual(summary["historical_liability_status"], "UNRESOLVED_REQUIRES_OWNER_REVIEW")
        self.assertEqual(summary["total_owner_review_required"], 13)

        # Markdown report generation verification
        md_text = format_markdown_report(report)
        self.assertIn("BELUM TERRESOLUSI", md_text)
        self.assertIn("13 pesanan historis", md_text)
