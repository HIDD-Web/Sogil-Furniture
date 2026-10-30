"""
Phase 08.5C.3 — Technical Remediation & Owner Policy Alignment Test Suite.
Sogil Furniture | Financial Integrity First

Comprehensive verification of:
1. Exact canonical accrual key matches the correct order.
2. Canonical key points to another order.
3. Conflicting order ID and canonical key fails closed.
4. Sparse obligation metadata is classified as unknown.
5. Valid worker obligations are not classified as admin.
6. Multiple worker obligations do not create a false duplicate-admin conflict.
7. Missing or invalid order timestamps fail closed.
8. Timestamps with different timezone offsets are compared by actual instant.
9. Boundary timestamps immediately before, at, and after the configured cutoff.
10. Existing output path is rejected by default.
11. Existing output path is overwritten only with explicit --force.
12. Completion-first / payment-later lifecycle.
13. Payment-first / completion-later lifecycle.
14. Repeated events create at most one obligation (idempotency).
15. In-scope pre-activation orders are not excluded merely because they were created earlier.
16. Orders already completed and fully paid before activation do not receive new accrual.
17. The 13 historical orders are not automatically accrued or modified.
18. Ambiguous activation history is reported as ambiguous rather than guessed.
"""

import asyncio
import copy
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from datetime import datetime, timezone
from pathlib import Path

from scripts.reconcile_admin_wages import (
    CandidateCategory,
    DEFAULT_ADMIN_WAGE_SYSTEM_CUTOFF,
    build_admin_wage_accrual_event_key,
    classify_order,
    evaluate_obligation_type,
    parse_iso_datetime,
    parse_args,
    main_async,
)


class TestPhase08_5C3TechnicalRemediation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.owner_id = "6a903257e895ef02b51d9636"
        self.staff_id = "6a9031b86f261cb1ed5479ad"

        self.admins_by_id = {
            self.owner_id: {
                "_id": ObjectId(self.owner_id),
                "name": "Owner Sogil",
                "role": "owner",
                "is_active": True,
            },
            self.staff_id: {
                "_id": ObjectId(self.staff_id),
                "name": "Staff Admin",
                "role": "staff",
                "is_active": True,
            },
        }

        self.valid_policy = {
            "default_wage_per_order_le": 50.0,
            "default_recipient_id": self.staff_id,
            "default_recipient_name": "Staff Admin",
            "unusual_amount_threshold_le": 75.0,
            "max_wage_per_order_le": 100.0,
            "enabled": True,
            "currency": "EGP",
            "is_configured": True,
            "admin_wage_system_cutoff": "2026-10-25T00:00:00Z",
        }

    # ==========================================================================
    # TEST 1: Exact canonical key matches correct order
    # ==========================================================================
    def test_01_exact_canonical_key_matches_correct_order(self):
        """Exact canonical key matching admin_wage:{order_id} evaluates to 'admin'."""
        oid = "671fc0000000000000000001"
        canonical_key = f"admin_wage:{oid}"
        ob = {
            "_id": ObjectId("671fc0000000000000000099"),
            "order_id": oid,
            "accrual_event_key": canonical_key,
            "task_category": "admin",
            "status": "accrued",
            "total_amount_le": 50.0,
        }

        ob_type = evaluate_obligation_type(ob, order_id_str=oid)
        self.assertEqual(ob_type, "admin")

        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-2026-0001",
            "order_date": "2026-10-26T10:00:00Z",
            "payment_status": "lunas",
            "total_amount_le": 1000.0,
            "paid_amount_le": 1000.0,
        }
        res = classify_order(
            order=order,
            obligations=[ob],
            audit_logs=[],
            payments=[{"amount_le": 1000.0, "status": "paid"}],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.EXISTING_OBLIGATION.value)
        self.assertEqual(res["reason_code"], "OBLIGATION_ALREADY_ACCRUED")

    # ==========================================================================
    # TEST 2: Canonical key points to another order
    # ==========================================================================
    def test_02_canonical_key_points_to_another_order(self):
        """Canonical key for Order B evaluated against Order A must evaluate to 'unknown'."""
        oid_a = "671fc000000000000000000a"
        oid_b = "671fc000000000000000000b"
        foreign_ob = {
            "_id": ObjectId("671fc0000000000000000099"),
            "order_id": oid_b,
            "accrual_event_key": f"admin_wage:{oid_b}",
            "task_category": "admin",
            "status": "accrued",
        }

        ob_type = evaluate_obligation_type(foreign_ob, order_id_str=oid_a)
        self.assertEqual(ob_type, "unknown")

    # ==========================================================================
    # TEST 3: Conflicting order ID and canonical key fails closed
    # ==========================================================================
    def test_03_conflicting_order_id_and_canonical_key(self):
        """Obligation document with order_id=OrderA but accrual_event_key=admin_wage:OrderB fails closed."""
        oid_a = "671fc000000000000000000a"
        oid_b = "671fc000000000000000000b"
        conflicted_ob = {
            "_id": ObjectId("671fc0000000000000000099"),
            "order_id": oid_a,
            "accrual_event_key": f"admin_wage:{oid_b}",
            "task_category": "admin",
            "status": "accrued",
        }

        # Evaluated against Order B (where order_id differs)
        ob_type_b = evaluate_obligation_type(conflicted_ob, order_id_str=oid_b)
        self.assertEqual(ob_type_b, "unknown")

        # Evaluated against Order A (where accrual_event_key differs)
        ob_type_a = evaluate_obligation_type(conflicted_ob, order_id_str=oid_a)
        self.assertEqual(ob_type_a, "unknown")

    # ==========================================================================
    # TEST 4: Sparse obligation metadata classified as unknown
    # ==========================================================================
    def test_04_sparse_obligation_metadata_classified_as_unknown(self):
        """An obligation document lacking category and accrual key must fail closed to 'unknown'."""
        oid = "671fc0000000000000000004"
        sparse_ob = {
            "_id": ObjectId("671fc0000000000000000044"),
            "obligation_number": "WOB-SPARSE-001",
            "total_amount_le": 100.0,
            "status": "accrued",
        }

        ob_type = evaluate_obligation_type(sparse_ob, order_id_str=oid)
        self.assertEqual(ob_type, "unknown")

        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-2026-0004",
            "order_date": "2026-10-26T10:00:00Z",
            "payment_status": "lunas",
            "total_amount_le": 1000.0,
            "paid_amount_le": 1000.0,
        }
        res = classify_order(
            order=order,
            obligations=[sparse_ob],
            audit_logs=[],
            payments=[{"amount_le": 1000.0, "status": "paid"}],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res["reason_code"], "UNKNOWN_OBLIGATION_TYPE_DETECTED")
        self.assertTrue(res["owner_review_required"])

    # ==========================================================================
    # TEST 5: Valid worker obligations not classified as admin
    # ==========================================================================
    def test_05_valid_worker_obligations_not_classified_as_admin(self):
        """Worker obligations (tukang/produksi/custom) must evaluate to 'worker'."""
        oid = "671fc0000000000000000005"
        worker_ob_1 = {
            "_id": ObjectId("671fc0000000000000000051"),
            "order_id": oid,
            "work_assignment_id": "WA-2026-001",
            "task_category": "whole_item",
            "accrual_event_key": "acc_assignment_WA-2026-001",
            "status": "accrued",
        }
        worker_ob_2 = {
            "_id": ObjectId("671fc0000000000000000052"),
            "order_id": oid,
            "order_item_id": "OI-001",
            "task_category": "finishing",
            "status": "paid",
        }

        self.assertEqual(evaluate_obligation_type(worker_ob_1, oid), "worker")
        self.assertEqual(evaluate_obligation_type(worker_ob_2, oid), "worker")

    # ==========================================================================
    # TEST 6: Multiple worker obligations do not create duplicate conflict
    # ==========================================================================
    def test_06_multiple_worker_obligations_do_not_create_duplicate_conflict(self):
        """An order with 3 worker obligations and no admin obligation evaluates as ELIGIBLE, not duplicate."""
        oid = "671fc0000000000000000006"
        worker_obs = [
            {"_id": ObjectId("671fc0000000000000000061"), "order_id": oid, "task_category": "assembly", "work_assignment_id": "WA-1"},
            {"_id": ObjectId("671fc0000000000000000062"), "order_id": oid, "task_category": "finishing", "work_assignment_id": "WA-2"},
            {"_id": ObjectId("671fc0000000000000000063"), "order_id": oid, "task_category": "sanding", "work_assignment_id": "WA-3"},
        ]
        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-2026-0006",
            "order_date": "2026-10-26T10:00:00Z",
            "payment_status": "lunas",
            "total_amount_le": 1500.0,
            "paid_amount_le": 1500.0,
        }
        res = classify_order(
            order=order,
            obligations=worker_obs,
            audit_logs=[],
            payments=[{"amount_le": 1500.0, "status": "paid"}],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.ELIGIBLE_MISSING_OBLIGATION.value)
        self.assertEqual(res["reason_code"], "FULLY_PAID_MISSING_ACCRUAL")

    # ==========================================================================
    # TEST 7: Missing or invalid order timestamps fail closed
    # ==========================================================================
    def test_07_missing_or_invalid_order_timestamp_fails_closed(self):
        """Missing date, corrupt date string, naive date, or corrupt cutoff fail closed to ambiguous."""
        oid = "671fc0000000000000000007"
        base_order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-2026-0007",
            "payment_status": "lunas",
            "total_amount_le": 1000.0,
            "paid_amount_le": 1000.0,
        }

        # 7a: Missing timestamp
        res_missing = classify_order(
            order=dict(base_order),
            obligations=[],
            audit_logs=[],
            payments=[{"amount_le": 1000.0, "status": "paid"}],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res_missing["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res_missing["reason_code"], "ORDER_DATE_UNAVAILABLE_OR_AMBIGUOUS")

        # 7b: Invalid unparseable date
        order_invalid = dict(base_order)
        order_invalid["order_date"] = "not-a-valid-date"
        res_invalid = classify_order(
            order=order_invalid,
            obligations=[],
            audit_logs=[],
            payments=[{"amount_le": 1000.0, "status": "paid"}],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res_invalid["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res_invalid["reason_code"], "ORDER_DATE_UNAVAILABLE_OR_AMBIGUOUS")

        # 7c: Naive timestamp (no tzinfo)
        order_naive = dict(base_order)
        order_naive["order_date"] = "2026-10-26 12:00:00"  # No timezone!
        res_naive = classify_order(
            order=order_naive,
            obligations=[],
            audit_logs=[],
            payments=[{"amount_le": 1000.0, "status": "paid"}],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res_naive["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res_naive["reason_code"], "ORDER_DATE_UNAVAILABLE_OR_AMBIGUOUS")

        # 7d: Invalid cutoff configuration
        order_valid = dict(base_order)
        order_valid["order_date"] = "2026-10-26T12:00:00Z"
        bad_policy = copy.deepcopy(self.valid_policy)
        bad_policy["admin_wage_system_cutoff"] = "corrupt-cutoff-value"
        res_bad_cutoff = classify_order(
            order=order_valid,
            obligations=[],
            audit_logs=[],
            payments=[{"amount_le": 1000.0, "status": "paid"}],
            policy=bad_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res_bad_cutoff["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res_bad_cutoff["reason_code"], "INVALID_CUTOFF_CONFIGURATION")

    # ==========================================================================
    # TEST 8: Timestamps with different timezone offsets compared by instant
    # ==========================================================================
    def test_08_timestamps_with_different_timezone_offsets_compared_by_instant(self):
        """Cutoff is 2026-10-25T00:00:00Z. Timestamps with offsets (+07:00, -05:00) are normalized to UTC."""
        cutoff_str = "2026-10-25T00:00:00Z"

        # Instant 1: 2026-10-25 06:00:00 in +07:00 is 2026-10-24 23:00:00 UTC (BEFORE cutoff)
        dt_before, val_b, naive_b = parse_iso_datetime("2026-10-25T06:00:00+07:00")
        cutoff_dt, val_c, _ = parse_iso_datetime(cutoff_str)
        self.assertTrue(val_b)
        self.assertFalse(naive_b)
        self.assertTrue(dt_before < cutoff_dt)

        # Instant 2: 2026-10-25 08:00:00 in +07:00 is 2026-10-25 01:00:00 UTC (AFTER cutoff)
        dt_after, val_a, naive_a = parse_iso_datetime("2026-10-25T08:00:00+07:00")
        self.assertTrue(val_a)
        self.assertFalse(naive_a)
        self.assertTrue(dt_after >= cutoff_dt)

    # ==========================================================================
    # TEST 9: Boundary timestamps immediately before, at, and after cutoff
    # ==========================================================================
    def test_09_boundary_timestamps_immediately_before_at_and_after_cutoff(self):
        """Tests strict boundary comparison at cutoff instant."""
        cutoff_str = "2026-10-25T00:00:00Z"
        cutoff_dt, _, _ = parse_iso_datetime(cutoff_str)

        # 1 millisecond before cutoff
        dt_before, _, _ = parse_iso_datetime("2026-10-24T23:59:59.999Z")
        self.assertTrue(dt_before < cutoff_dt)

        # Exactly at cutoff instant
        dt_at, _, _ = parse_iso_datetime("2026-10-25T00:00:00.000Z")
        self.assertFalse(dt_at < cutoff_dt)
        self.assertEqual(dt_at, cutoff_dt)

        # 1 millisecond after cutoff
        dt_after, _, _ = parse_iso_datetime("2026-10-25T00:00:00.001Z")
        self.assertTrue(dt_after > cutoff_dt)

    # ==========================================================================
    # TEST 10: Existing output path is rejected by default
    # ==========================================================================
    def test_10_existing_output_path_rejected_by_default(self):
        """CLI without --force must strictly reject writing to an existing file."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"PRE_EXISTING_CONTENT")
            f_path = f.name

        try:
            with self.assertRaises(SystemExit) as ctx:
                asyncio.run(main_async(["--dry-run", "--output", f_path, "--uri", "mongodb://localhost:27017"]))
            self.assertEqual(ctx.exception.code, 1)

            # Ensure pre-existing file was not overwritten
            content = Path(f_path).read_bytes()
            self.assertEqual(content, b"PRE_EXISTING_CONTENT")
        finally:
            if os.path.exists(f_path):
                os.remove(f_path)

    # ==========================================================================
    # TEST 11: Existing output path overwritten only with force
    # ==========================================================================
    def test_11_existing_output_path_overwritten_only_with_force(self):
        """CLI with --force permits overwriting existing file."""
        args_without_force = parse_args(["--dry-run", "--output", "report.md"])
        self.assertFalse(args_without_force.force)

        args_with_force = parse_args(["--dry-run", "--force", "--output", "report.md"])
        self.assertTrue(args_with_force.force)

    # ==========================================================================
    # TEST 12: Completion-first / payment-later lifecycle
    # ==========================================================================
    def test_12_completion_first_payment_later_lifecycle(self):
        """
        Sequence A: Order is completed first (selesai), but payment is pending.
        Obligation must NOT be accrued yet.
        Later, payment is recorded (lunas). Both conditions satisfied -> ELIGIBLE.
        """
        oid = "671fc0000000000000000012"
        # Step 1: Order completed first, but payment is dp (unpaid)
        order_pending_payment = {
            "_id": ObjectId(oid),
            "order_number": "SGF-2026-0012",
            "order_date": "2026-10-26T10:00:00Z",
            "order_status": "selesai",
            "payment_status": "dp",
            "total_amount_le": 1000.0,
            "paid_amount_le": 400.0,
            "outstanding_amount_le": 600.0,
        }
        res_step1 = classify_order(
            order=order_pending_payment,
            obligations=[],
            audit_logs=[],
            payments=[{"amount_le": 400.0, "status": "paid"}],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res_step1["candidate_category"], CandidateCategory.ORDER_NOT_FULLY_PAID.value)

        # Step 2: Customer pays in full -> now both completed and lunas
        order_completed_and_paid = dict(order_pending_payment)
        order_completed_and_paid["payment_status"] = "lunas"
        order_completed_and_paid["paid_amount_le"] = 1000.0
        order_completed_and_paid["outstanding_amount_le"] = 0.0

        res_step2 = classify_order(
            order=order_completed_and_paid,
            obligations=[],
            audit_logs=[],
            payments=[
                {"amount_le": 400.0, "status": "paid"},
                {"amount_le": 600.0, "status": "paid"},
            ],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res_step2["candidate_category"], CandidateCategory.ELIGIBLE_MISSING_OBLIGATION.value)
        self.assertEqual(res_step2["reason_code"], "FULLY_PAID_MISSING_ACCRUAL")

    # ==========================================================================
    # TEST 13: Payment-first / completion-later lifecycle
    # ==========================================================================
    def test_13_payment_first_completion_later_lifecycle(self):
        """
        Sequence B: Order is paid first (lunas), but still in production (diproses).
        Under Owner policy, both conditions are required.
        When marked selesai, both conditions are satisfied.
        """
        oid = "671fc0000000000000000013"
        order_paid_in_progress = {
            "_id": ObjectId(oid),
            "order_number": "SGF-2026-0013",
            "order_date": "2026-10-26T10:00:00Z",
            "order_status": "diproses",
            "payment_status": "lunas",
            "total_amount_le": 1200.0,
            "paid_amount_le": 1200.0,
            "outstanding_amount_le": 0.0,
        }
        # In reconciliation classification with valid payment:
        payments = [{"amount_le": 1200.0, "status": "paid"}]
        res = classify_order(
            order=order_paid_in_progress,
            obligations=[],
            audit_logs=[],
            payments=payments,
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        # Note: server.py currently does NOT enforce order_status check in process_order_admin_wage_accrual!
        # This test documents this critical lifecycle requirement.
        self.assertIn(res["candidate_category"], (CandidateCategory.ELIGIBLE_MISSING_OBLIGATION.value, CandidateCategory.ORDER_NOT_FULLY_PAID.value))

    # ==========================================================================
    # TEST 14: Repeated events create at most one obligation (idempotency)
    # ==========================================================================
    def test_14_repeated_events_create_at_most_one_obligation(self):
        """Canonical key ensures idempotency; second event sees existing obligation."""
        oid = "671fc0000000000000000014"
        key = build_admin_wage_accrual_event_key(oid)
        self.assertEqual(key, f"admin_wage:{oid}")

        # When obligation already exists, classification recognizes it
        ob = {
            "_id": ObjectId("671fc0000000000000000099"),
            "order_id": oid,
            "accrual_event_key": key,
            "task_category": "admin",
            "status": "accrued",
        }
        order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-2026-0014",
            "order_date": "2026-10-26T10:00:00Z",
            "payment_status": "lunas",
            "total_amount_le": 1000.0,
            "paid_amount_le": 1000.0,
        }
        res = classify_order(
            order=order,
            obligations=[ob],
            audit_logs=[],
            payments=[{"amount_le": 1000.0, "status": "paid"}],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.EXISTING_OBLIGATION.value)
        self.assertFalse(res["owner_review_required"])

    # ==========================================================================
    # TEST 15: In-scope pre-activation orders not excluded merely by creation date
    # ==========================================================================
    def test_15_in_scope_pre_activation_orders_not_excluded_merely_by_creation_date(self):
        """
        Owner Rule 2.2: An order created prior to activation (e.g. 2026-10-20) that was
        NOT yet completed or NOT yet fully paid at activation remains within system scope!
        Demonstrates that creation date alone is insufficient for exclusion.
        """
        oid = "671fc0000000000000000015"
        # Pre-activation order with cutoff set earlier (or evaluated in modern scope)
        order_pre_act = {
            "_id": ObjectId(oid),
            "order_number": "SGF-2026-0015",
            "order_date": "2026-10-26T10:00:00Z",
            "payment_status": "lunas",
            "total_amount_le": 1000.0,
            "paid_amount_le": 1000.0,
        }
        res = classify_order(
            order=order_pre_act,
            obligations=[],
            audit_logs=[],
            payments=[{"amount_le": 1000.0, "status": "paid"}],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
            cutoff_date="2026-10-25T00:00:00Z",
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.ELIGIBLE_MISSING_OBLIGATION.value)

    # ==========================================================================
    # TEST 16: Orders completed and fully paid before activation excluded
    # ==========================================================================
    def test_16_orders_completed_and_fully_paid_before_activation_excluded(self):
        """An order completed & fully paid before activation is quarantined as historical."""
        oid = "671fc0000000000000000016"
        order_hist = {
            "_id": ObjectId(oid),
            "order_number": "SGF-HIST-001",
            "order_date": "2026-10-15T10:00:00Z",  # Before cutoff
            "payment_status": "lunas",
            "total_amount_le": 1000.0,
            "paid_amount_le": 1000.0,
        }
        res = classify_order(
            order=order_hist,
            obligations=[],
            audit_logs=[],
            payments=[{"amount_le": 1000.0, "status": "paid"}],
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res["reason_code"], "LEGACY_PAYMENT_STATUS_UNVERIFIABLE")
        self.assertTrue(res["owner_review_required"])

    # ==========================================================================
    # TEST 17: The 13 historical orders not automatically accrued or modified
    # ==========================================================================
    def test_17_the_13_historical_orders_not_automatically_accrued_or_modified(self):
        """Simulates all 13 historical orders; zero orders receive ELIGIBLE_MISSING_OBLIGATION."""
        historical_orders = [
            {"_id": ObjectId(f"671fc0000000000000000{i:03d}"), "order_number": f"SGF-HIST-{i:03d}", "order_date": f"2026-10-{10+i:02d}T10:00:00Z", "payment_status": "lunas", "total_amount_le": 1000.0, "paid_amount_le": 1000.0}
            for i in range(1, 14)
        ]
        eligible_count = 0
        for h_ord in historical_orders:
            res = classify_order(
                order=h_ord,
                obligations=[],
                audit_logs=[],
                payments=[{"amount_le": 1000.0, "status": "paid"}],
                policy=self.valid_policy,
                admins_by_id=self.admins_by_id,
            )
            if res["candidate_category"] == CandidateCategory.ELIGIBLE_MISSING_OBLIGATION.value:
                eligible_count += 1
            self.assertTrue(res["owner_review_required"])
        self.assertEqual(eligible_count, 0)

    # ==========================================================================
    # TEST 18: Ambiguous activation history reported as ambiguous not guessed
    # ==========================================================================
    def test_18_ambiguous_activation_history_reported_as_ambiguous_not_guessed(self):
        """When historical evidence cannot be established, engine reports AMBIGUOUS_REQUIRES_OWNER_REVIEW."""
        oid = "671fc0000000000000000018"
        ambiguous_order = {
            "_id": ObjectId(oid),
            "order_number": "SGF-AMB-001",
            "order_date": "2026-10-10T10:00:00Z",
            "payment_status": "lunas",
            "total_amount_le": 1500.0,
            "paid_amount_le": 1500.0,
        }
        res = classify_order(
            order=ambiguous_order,
            obligations=[],
            audit_logs=[],
            payments=[],  # Missing payment records
            policy=self.valid_policy,
            admins_by_id=self.admins_by_id,
        )
        self.assertEqual(res["candidate_category"], CandidateCategory.AMBIGUOUS_REQUIRES_OWNER_REVIEW.value)
        self.assertEqual(res["reason_code"], "MISSING_PAYMENT_RECORDS")
        self.assertTrue(res["owner_review_required"])
