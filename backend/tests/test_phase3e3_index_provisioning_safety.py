"""Phase 3E-3: Comprehensive Index Provisioning Safety Regression Tests.

Verifies:
1. Successful verification: All required indexes exist and match specifications.
2. Missing index detection: Missing required unique index causes startup verification to fail closed.
3. Incompatible index detection: Index with conflicting options fails closed.
4. Duplicate preflight detection: Conflicting records detected before create_index, producing actionable diagnostic report.
5. Swallowed exception elimination: Unique index failures raise CriticalFinanceIndexError instead of pass/warning.
6. Partial failure reporting: Failure midway produces clear list of completed, failed, and pending indexes.
7. Dry-run mode: Performs zero database writes (create_index call count == 0).
8. Database isolation: Apply mode rejects unapproved, ambiguous, or production database targets.
9. Startup separation: Normal API startup in verify mode does not attempt create_index.
10. Backward compatibility: Existing seed() interface continues to function smoothly for test harness.
"""

import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from bson import ObjectId

from backend.index_provisioner import (
    IndexSpec,
    REQUIRED_INDEX_SPECS,
    check_duplicate_records,
    verify_required_indexes,
    provision_indexes,
    CriticalFinanceIndexError,
    DuplicateRecordError,
    format_duplicate_report,
)
import backend.server as server


class TestPhase3E3IndexProvisioningSafety(unittest.IsolatedAsyncioTestCase):
    """Rigorous unit and mock-based safety tests for index provisioning and startup verification."""

    def _build_full_mock_db(self):
        """Creates a mock database where all required indexes exist with expected options."""
        mock_db = MagicMock()
        for spec in REQUIRED_INDEX_SPECS:
            col_mock = getattr(mock_db, spec.collection, None)
            if col_mock is None or not isinstance(col_mock, MagicMock):
                col_mock = MagicMock()
                setattr(mock_db, spec.collection, col_mock)
                mock_db[spec.collection] = col_mock

        # Setup index_information on each collection to match REQUIRED_INDEX_SPECS
        collection_specs = {}
        for spec in REQUIRED_INDEX_SPECS:
            collection_specs.setdefault(spec.collection, []).append(spec)

        for col_name, specs in collection_specs.items():
            info_dict = {"_id_": {"v": 2, "key": [("_id", 1)]}}
            for s in specs:
                entry = {
                    "v": 2,
                    "key": [(k, float(d)) for k, d in s.keys],
                }
                if s.unique:
                    entry["unique"] = True
                if s.partial_filter_expression is not None:
                    entry["partialFilterExpression"] = s.partial_filter_expression
                if s.sparse:
                    entry["sparse"] = True
                info_dict[s.name] = entry

            col = getattr(mock_db, col_name)
            col.index_information = AsyncMock(return_value=info_dict)
            col.create_index = AsyncMock(return_value="index_ok")
            col.find_one = AsyncMock(return_value={"_id": ObjectId(), "role": "owner", "email": "admin@example.com", "key": "k", "pricing": {}})
            col.count_documents = AsyncMock(return_value=1)
            col.update_one = AsyncMock()
            col.update_many = AsyncMock()
            col.insert_one = AsyncMock()
            col.insert_many = AsyncMock()

        # Mock non-indexed collections required during seed_data_only()
        extra_cols = ["settings", "categories", "delivery_zones", "products", "admins", "orders", "customers", "referrals", "invoices", "audit_logs", "claim_attempts"]
        for c in extra_cols:
            if not hasattr(mock_db, c) or not isinstance(getattr(mock_db, c), MagicMock):
                col = MagicMock()
                setattr(mock_db, c, col)
                mock_db[c] = col
            col = getattr(mock_db, c)
            if not isinstance(getattr(col, "find_one", None), AsyncMock):
                col.find_one = AsyncMock(return_value={"_id": ObjectId(), "key": "k", "role": "owner", "email": "admin@example.com", "pricing": {}})
            if not isinstance(getattr(col, "count_documents", None), AsyncMock):
                col.count_documents = AsyncMock(return_value=1)
            if not isinstance(getattr(col, "update_one", None), AsyncMock):
                col.update_one = AsyncMock()
            if not isinstance(getattr(col, "update_many", None), AsyncMock):
                col.update_many = AsyncMock()
            if not isinstance(getattr(col, "insert_one", None), AsyncMock):
                col.insert_one = AsyncMock()
            if not isinstance(getattr(col, "insert_many", None), AsyncMock):
                col.insert_many = AsyncMock()
            if not isinstance(getattr(col, "index_information", None), AsyncMock):
                col.index_information = AsyncMock(return_value={})
            if not isinstance(getattr(col, "create_index", None), AsyncMock):
                col.create_index = AsyncMock(return_value="index_ok")

        return mock_db

    async def test_01_successful_verification_of_required_indexes(self):
        """Test 1: All required indexes exist and match specifications -> verification passes."""
        mock_db = self._build_full_mock_db()
        result = await verify_required_indexes(mock_db, specs=REQUIRED_INDEX_SPECS, fail_closed=True)
        self.assertTrue(result["valid"], "Index verification should succeed when all indexes match")
        self.assertEqual(len(result["missing"]), 0)
        self.assertEqual(len(result["incompatible"]), 0)
        self.assertEqual(len(result["verified"]), len(REQUIRED_INDEX_SPECS))

    async def test_02_missing_required_unique_index_causes_startup_to_fail_closed(self):
        """Test 2: A missing required unique index causes startup verification to fail closed."""
        mock_db = self._build_full_mock_db()

        # Remove critical unique index 'uniq_payment_number' from payments
        payments_info = await mock_db.payments.index_information()
        del payments_info["uniq_payment_number"]
        mock_db.payments.index_information = AsyncMock(return_value=payments_info)

        # 1. verify_required_indexes with fail_closed=False reports missing
        res = await verify_required_indexes(mock_db, specs=REQUIRED_INDEX_SPECS, fail_closed=False)
        self.assertFalse(res["valid"])
        missing_names = [m["spec"].name for m in res["missing"]]
        self.assertIn("uniq_payment_number", missing_names)

        # 2. verify_required_indexes with fail_closed=True raises CriticalFinanceIndexError
        with self.assertRaises(CriticalFinanceIndexError) as ctx:
            await verify_required_indexes(mock_db, specs=REQUIRED_INDEX_SPECS, fail_closed=True)
        self.assertEqual(ctx.exception.collection_name, "payments")
        self.assertEqual(ctx.exception.index_name, "uniq_payment_number")

    async def test_03_incompatible_unique_index_definition_is_rejected(self):
        """Test 3: An existing index with conflicting options is rejected with fail-closed error."""
        mock_db = self._build_full_mock_db()

        # Incompatible option: uniq_purchase_stock_movement has sparse=True instead of partialFilterExpression
        stocks_info = await mock_db.material_stocks.index_information()
        stocks_info["uniq_purchase_stock_movement"] = {
            "key": [("related_purchase_id", 1.0), ("movement_type", 1.0)],
            "unique": True,
            "sparse": True,  # Conflicting option: missing partialFilterExpression
        }
        mock_db.material_stocks.index_information = AsyncMock(return_value=stocks_info)

        with self.assertRaises(CriticalFinanceIndexError) as ctx:
            await verify_required_indexes(mock_db, specs=REQUIRED_INDEX_SPECS, fail_closed=True)

        err = ctx.exception
        self.assertEqual(err.collection_name, "material_stocks")
        self.assertEqual(err.index_name, "uniq_purchase_stock_movement")
        self.assertIn("partialFilterExpression mismatch", err.reason)

    async def test_04_duplicate_records_detected_before_unique_index_creation(self):
        """Test 4: Duplicate records detected before create_index; creation aborted with report."""
        mock_db = MagicMock()
        mock_col = MagicMock()

        # Simulate aggregate returning duplicate groups
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[
            {
                "_id": {"payment_number": "PAY-2026-DUP"},
                "count": 2,
                "sample_ids": ["doc_id_111", "doc_id_222"],
            }
        ])
        mock_col.aggregate = MagicMock(return_value=mock_cursor)
        mock_col.create_index = AsyncMock()
        mock_col.index_information = AsyncMock(return_value={})
        mock_db.payments = mock_col

        spec = IndexSpec(
            collection="payments",
            keys=[("payment_number", 1)],
            name="uniq_payment_number",
            unique=True,
            category="critical_unique",
        )

        # 1. check_duplicate_records detects duplicates
        dups = await check_duplicate_records(mock_db, spec)
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]["count"], 2)
        self.assertEqual(dups[0]["sample_ids"], ["doc_id_111", "doc_id_222"])

        # 2. format_duplicate_report generates actionable message
        report = format_duplicate_report("payments", "uniq_payment_number", dups)
        self.assertIn("DUPLICATE KEY CONFLICT IN [payments] FOR INDEX 'uniq_payment_number'", report)
        self.assertIn("PAY-2026-DUP", report)
        self.assertIn("doc_id_111", report)

        # 3. provision_indexes aborts before create_index
        with self.assertRaises(DuplicateRecordError) as ctx:
            await provision_indexes(mock_db, specs=[spec], dry_run=False, fail_closed=True)

        mock_col.create_index.assert_not_called()
        self.assertIn("PAY-2026-DUP", str(ctx.exception))

    async def test_05_swallowed_exception_elimination_on_unique_indexes(self):
        """Test 5: Unique index creation errors are never silently swallowed in seed()."""
        mock_db = self._build_full_mock_db()

        # Case A: materials unique index failure
        mock_db.materials.create_index.side_effect = RuntimeError("Disk full / duplicate key")
        with patch.object(server, "db", mock_db), patch.object(server, "set_setting", AsyncMock()):
            with self.assertRaises(CriticalFinanceIndexError) as ctx:
                await server.seed()
            self.assertEqual(ctx.exception.collection_name, "materials")
            self.assertEqual(ctx.exception.index_name, "uniq_material_name_specs")

        # Reset materials
        mock_db.materials.create_index.side_effect = None

        # Case B: work_assignments unique active task index failure
        async def _mock_wa_create_index(keys, **kwargs):
            if kwargs.get("name") == "uniq_active_worker_task_per_item":
                raise RuntimeError("Failed to build index: conflict")
            return "index_ok"

        mock_db.work_assignments.create_index.side_effect = _mock_wa_create_index
        with patch.object(server, "db", mock_db), patch.object(server, "set_setting", AsyncMock()):
            with self.assertRaises(CriticalFinanceIndexError) as ctx:
                await server.seed()
            self.assertEqual(ctx.exception.collection_name, "work_assignments")
            self.assertEqual(ctx.exception.index_name, "uniq_active_worker_task_per_item")

        # Reset work_assignments
        mock_db.work_assignments.create_index.side_effect = None

        # Case C: outbox_events unique event_id failure
        async def _mock_outbox_create_index(keys, **kwargs):
            if kwargs.get("name") == "uniq_outbox_event_id":
                raise RuntimeError("Outbox unique constraint violated")
            return "index_ok"

        mock_db.outbox_events.create_index.side_effect = _mock_outbox_create_index
        with patch.object(server, "db", mock_db), patch.object(server, "set_setting", AsyncMock()):
            with self.assertRaises(CriticalFinanceIndexError) as ctx:
                await server.seed()
            self.assertEqual(ctx.exception.collection_name, "outbox_events")
            self.assertEqual(ctx.exception.index_name, "uniq_outbox_event_id")

    async def test_06_failure_midway_produces_clear_report_of_completed_and_failed(self):
        """Test 6: Failure midway produces clear list of completed, failed, and pending indexes."""
        mock_db = MagicMock()

        spec1 = IndexSpec(collection="col_a", keys=[("k1", 1)], name="idx_a", unique=False)
        spec2 = IndexSpec(collection="col_b", keys=[("k2", 1)], name="idx_b", unique=True)
        spec3 = IndexSpec(collection="col_c", keys=[("k3", 1)], name="idx_c", unique=False)

        col_a = MagicMock()
        col_a.index_information = AsyncMock(return_value={})
        col_a.create_index = AsyncMock(return_value="ok_a")
        mock_db.col_a = col_a

        col_b = MagicMock()
        col_b.index_information = AsyncMock(return_value={})
        col_b.aggregate = MagicMock(return_value=MagicMock(to_list=AsyncMock(return_value=[])))
        col_b.create_index = AsyncMock(side_effect=RuntimeError("Hardware failure on col_b"))
        mock_db.col_b = col_b

        col_c = MagicMock()
        col_c.index_information = AsyncMock(return_value={})
        col_c.create_index = AsyncMock(return_value="ok_c")
        mock_db.col_c = col_c

        # Running with fail_closed=False to inspect complete status report
        res = await provision_indexes(mock_db, specs=[spec1, spec2, spec3], dry_run=False, fail_closed=False)

        self.assertEqual(res["status"], "PARTIAL_FAILURE")
        self.assertIn("idx_a", res["completed"])
        self.assertEqual(len(res["failed"]), 1)
        self.assertEqual(res["failed"][0]["spec"].name, "idx_b")
        self.assertIn("Hardware failure", res["failed"][0]["error"])

        # And running with fail_closed=True raises CriticalFinanceIndexError with progress
        with self.assertRaises(CriticalFinanceIndexError) as ctx:
            await provision_indexes(mock_db, specs=[spec1, spec2, spec3], dry_run=False, fail_closed=True)
        self.assertIn("Completed: ['idx_a']", str(ctx.exception))
        self.assertIn("Failed: ['idx_b']", str(ctx.exception))

    async def test_07_dry_run_performs_zero_database_writes(self):
        """Test 7: Dry-run generates plan without invoking create_index on any collection."""
        mock_db = MagicMock()
        for spec in REQUIRED_INDEX_SPECS:
            col = MagicMock()
            col.index_information = AsyncMock(return_value={})
            col.aggregate = MagicMock(return_value=MagicMock(to_list=AsyncMock(return_value=[])))
            col.create_index = AsyncMock()
            setattr(mock_db, spec.collection, col)
            mock_db[spec.collection] = col

        res = await provision_indexes(mock_db, specs=REQUIRED_INDEX_SPECS, dry_run=True)
        self.assertTrue(res["dry_run"])
        self.assertEqual(res["status"], "PLAN_GENERATED")
        self.assertEqual(len(res["planned_creations"]), len(REQUIRED_INDEX_SPECS))

        # Strict check: create_index was NEVER called
        for spec in REQUIRED_INDEX_SPECS:
            col = getattr(mock_db, spec.collection)
            col.create_index.assert_not_called()

    async def test_08_apply_mode_rejects_unapproved_database_target(self):
        """Test 8: Apply mode rejects unapproved host or protected database names."""
        mock_db = MagicMock()

        # Attempt 1: Atlas URI
        atlas_uri = "mongodb+srv://admin:pass@sogil-furniture.7djg3j5.mongodb.net/sogil_test"
        with self.assertRaises(ValueError) as ctx:
            await provision_indexes(
                mock_db,
                specs=REQUIRED_INDEX_SPECS[:1],
                dry_run=False,
                target_uri=atlas_uri,
                db_name="sogil_test_disposable"
            )
        self.assertIn("SECURITY ABORT", str(ctx.exception))

        # Attempt 2: Protected production database name 'sogil'
        local_uri = "mongodb://127.0.0.1:27099"
        with self.assertRaises(ValueError) as ctx2:
            await provision_indexes(
                mock_db,
                specs=REQUIRED_INDEX_SPECS[:1],
                dry_run=False,
                target_uri=local_uri,
                db_name="sogil"
            )
        self.assertIn("SECURITY ABORT", str(ctx2.exception))

    async def test_09_normal_api_startup_does_not_automatically_provision_indexes(self):
        """Test 9: Normal API startup in verify mode performs 0 create_index calls."""
        mock_db = self._build_full_mock_db()

        with patch.object(server, "db", mock_db), \
             patch.object(server, "set_setting", AsyncMock()), \
             patch.object(server, "run_transaction_probe", AsyncMock(return_value=True)), \
             patch.dict(os.environ, {"INDEX_PROVISIONING_MODE": "verify"}):

            await server.startup()

        # Strict assertion: create_index must NEVER be called during verify-mode startup
        for spec in REQUIRED_INDEX_SPECS:
            col = getattr(mock_db, spec.collection)
            col.create_index.assert_not_called()

    async def test_10_backward_compatibility_seed_and_existing_tests_function(self):
        """Test 10: Existing seed() interface continues to function seamlessly with full indexes."""
        mock_db = self._build_full_mock_db()

        with patch.object(server, "db", mock_db), \
             patch.object(server, "set_setting", AsyncMock()), \
             patch.object(server, "ensure_probe_infrastructure", AsyncMock()):

            await server.seed()

        # Assert key unique indexes were registered
        mock_db.payments.create_index.assert_any_call(
            [("payment_number", 1)], unique=True, name="uniq_payment_number"
        )
        mock_db.wage_obligations.create_index.assert_any_call(
            [("accrual_event_key", 1)], unique=True, name="uniq_wage_obligation_accrual_event"
        )
        mock_db.outbox_events.create_index.assert_any_call(
            [("event_id", 1)], unique=True, name="uniq_outbox_event_id"
        )

    async def test_11_adversarial_correct_name_wrong_indexed_field(self):
        """Adversarial 1: Correct name but wrong indexed field fails closed with key structure mismatch."""
        mock_db = self._build_full_mock_db()

        payments_info = await mock_db.payments.index_information()
        payments_info["uniq_payment_number"] = {
            "v": 2,
            "key": [("tampered_code", 1)],
            "unique": True,
        }
        mock_db.payments.index_information = AsyncMock(return_value=payments_info)

        # 1. Non-fail-closed reports incompatible
        res = await verify_required_indexes(mock_db, specs=REQUIRED_INDEX_SPECS, fail_closed=False)
        self.assertFalse(res["valid"])
        incompatible_names = [i["spec"].name for i in res["incompatible"]]
        self.assertIn("uniq_payment_number", incompatible_names)
        self.assertIn("key structure mismatch", res["incompatible"][0]["reason"])

        # 2. Fail-closed raises CriticalFinanceIndexError
        with self.assertRaises(CriticalFinanceIndexError) as ctx:
            await verify_required_indexes(mock_db, specs=REQUIRED_INDEX_SPECS, fail_closed=True)
        self.assertEqual(ctx.exception.collection_name, "payments")
        self.assertEqual(ctx.exception.index_name, "uniq_payment_number")
        self.assertIn("key structure mismatch", ctx.exception.reason)

    async def test_12_adversarial_correct_name_reversed_compound_key_order(self):
        """Adversarial 2: Correct name but reversed compound key order fails closed."""
        mock_db = self._build_full_mock_db()

        wa_info = await mock_db.work_assignments.index_information()
        wa_info["uniq_active_worker_task_per_item"] = {
            "v": 2,
            "key": [("task_id", 1), ("work_assignment_id", 1)],
            "unique": True,
            "partialFilterExpression": {"status": {"$in": ["assigned", "in_progress"]}},
        }
        mock_db.work_assignments.index_information = AsyncMock(return_value=wa_info)

        res = await verify_required_indexes(mock_db, specs=REQUIRED_INDEX_SPECS, fail_closed=False)
        self.assertFalse(res["valid"])
        incompatible_names = [i["spec"].name for i in res["incompatible"]]
        self.assertIn("uniq_active_worker_task_per_item", incompatible_names)

        with self.assertRaises(CriticalFinanceIndexError) as ctx:
            await verify_required_indexes(mock_db, specs=REQUIRED_INDEX_SPECS, fail_closed=True)
        self.assertEqual(ctx.exception.collection_name, "work_assignments")
        self.assertEqual(ctx.exception.index_name, "uniq_active_worker_task_per_item")
        self.assertIn("key structure mismatch", ctx.exception.reason)

    async def test_13_adversarial_correct_name_and_keys_wrong_unique_setting(self):
        """Adversarial 3: Correct name and keys but wrong unique setting fails closed."""
        mock_db = self._build_full_mock_db()

        # Case A: Unique expected, but found unique=False
        wo_info = await mock_db.wage_obligations.index_information()
        wo_info["uniq_wage_obligation_accrual_event"] = {
            "v": 2,
            "key": [("accrual_event_key", 1)],
            "unique": False,
        }
        mock_db.wage_obligations.index_information = AsyncMock(return_value=wo_info)

        with self.assertRaises(CriticalFinanceIndexError) as ctx:
            await verify_required_indexes(mock_db, specs=REQUIRED_INDEX_SPECS, fail_closed=True)
        self.assertEqual(ctx.exception.collection_name, "wage_obligations")
        self.assertEqual(ctx.exception.index_name, "uniq_wage_obligation_accrual_event")
        self.assertIn("unique mismatch", ctx.exception.reason)

        # Reset wage_obligations
        mock_db = self._build_full_mock_db()

        # Case B: Performance index (unique=False expected), but found unique=True
        wa_info = await mock_db.work_assignments.index_information()
        wa_info["idx_work_assignments_worker_status"] = {
            "v": 2,
            "key": [("worker_id", 1), ("status", 1)],
            "unique": True,
        }
        mock_db.work_assignments.index_information = AsyncMock(return_value=wa_info)

        with self.assertRaises(CriticalFinanceIndexError) as ctx:
            await verify_required_indexes(mock_db, specs=REQUIRED_INDEX_SPECS, fail_closed=True)
        self.assertEqual(ctx.exception.collection_name, "work_assignments")
        self.assertEqual(ctx.exception.index_name, "idx_work_assignments_worker_status")
        self.assertIn("unique mismatch", ctx.exception.reason)

    async def test_14_adversarial_correct_name_and_keys_incompatible_partial_filter(self):
        """Adversarial 4: Correct name and keys but incompatible partial filter fails closed."""
        mock_db = self._build_full_mock_db()

        payments_info = await mock_db.payments.index_information()
        payments_info["uniq_payments_idempotency"] = {
            "v": 2,
            "key": [("idempotency_key", 1)],
            "unique": True,
            "partialFilterExpression": {"idempotency_key": {"$type": "int"}},
        }
        mock_db.payments.index_information = AsyncMock(return_value=payments_info)

        with self.assertRaises(CriticalFinanceIndexError) as ctx:
            await verify_required_indexes(mock_db, specs=REQUIRED_INDEX_SPECS, fail_closed=True)
        self.assertEqual(ctx.exception.collection_name, "payments")
        self.assertEqual(ctx.exception.index_name, "uniq_payments_idempotency")
        self.assertIn("partialFilterExpression mismatch", ctx.exception.reason)

    async def test_15_adversarial_correctly_defined_index_is_accepted(self):
        """Adversarial 5: Correctly defined index with matching keys and options is accepted."""
        mock_db = self._build_full_mock_db()

        res = await verify_required_indexes(mock_db, specs=REQUIRED_INDEX_SPECS, fail_closed=True)
        self.assertTrue(res["valid"])
        self.assertEqual(len(res["missing"]), 0)
        self.assertEqual(len(res["incompatible"]), 0)
        self.assertEqual(len(res["verified"]), len(REQUIRED_INDEX_SPECS))

    async def test_16_adversarial_startup_fails_closed_on_incompatible_or_missing_index(self):
        """Adversarial 6: Normal API startup in verify mode fails closed on incompatible or missing index."""
        mock_db = self._build_full_mock_db()

        # Incompatible index on payments
        payments_info = await mock_db.payments.index_information()
        payments_info["uniq_payment_number"]["key"] = [("wrong_field", 1)]
        mock_db.payments.index_information = AsyncMock(return_value=payments_info)

        with patch.object(server, "db", mock_db), \
             patch.object(server, "set_setting", AsyncMock()), \
             patch.object(server, "run_transaction_probe", AsyncMock(return_value=True)), \
             patch.dict(os.environ, {"INDEX_PROVISIONING_MODE": "verify"}):

            with self.assertRaises(CriticalFinanceIndexError) as ctx:
                await server.startup()

            self.assertEqual(ctx.exception.collection_name, "payments")
            self.assertEqual(ctx.exception.index_name, "uniq_payment_number")
            self.assertIn("key structure mismatch", ctx.exception.reason)


@pytest.mark.anyio
async def test_real_replica_set_duplicate_preflight_and_provisioning(real_replica_set_env):
    """Integration Test: Validates duplicate preflight and index creation against real replica set."""
    client, db = real_replica_set_env

    # 1. Insert duplicate documents into test database
    await db.payments.insert_one({"payment_number": "PAY-REAL-DUP-1", "amount": 100})
    await db.payments.insert_one({"payment_number": "PAY-REAL-DUP-1", "amount": 200})

    spec = IndexSpec(
        collection="payments",
        keys=[("payment_number", 1)],
        name="uniq_payment_number",
        unique=True,
        category="critical_unique",
    )

    # 2. Check duplicates with aggregation on real MongoDB
    dups = await check_duplicate_records(db, spec)
    assert len(dups) == 1
    assert dups[0]["count"] == 2

    # 3. Provisioner must abort before attempting create_index
    with pytest.raises(DuplicateRecordError) as exc_info:
        await provision_indexes(db, specs=[spec], dry_run=False, fail_closed=True)
    assert "PAY-REAL-DUP-1" in str(exc_info.value)

    # 4. Clean up duplicate and apply index cleanly
    await db.payments.delete_many({"payment_number": "PAY-REAL-DUP-1"})
    await db.payments.insert_one({"payment_number": "PAY-CLEAN-1", "amount": 100})

    res = await provision_indexes(db, specs=[spec], dry_run=False, fail_closed=True)
    assert "uniq_payment_number" in res["completed"]

    # 5. Verify index exists on real MongoDB
    info = await db.payments.index_information()
    assert "uniq_payment_number" in info
    assert info["uniq_payment_number"]["unique"] is True


@pytest.mark.anyio
async def test_real_replica_set_index_key_verification_adversarial(real_replica_set_env):
    """Integration Test: Validates that wrong index keys on real MongoDB fail verification, and correct keys pass."""
    client, db = real_replica_set_env

    # 1. Create index with expected name 'uniq_payment_number', but wrong field 'wrong_real_key'
    await db.payments.create_index([("wrong_real_key", 1)], unique=True, name="uniq_payment_number")

    spec = IndexSpec(
        collection="payments",
        keys=[("payment_number", 1)],
        name="uniq_payment_number",
        unique=True,
        category="critical_unique",
    )

    # 2. Verify: must report incompatible due to key mismatch
    res = await verify_required_indexes(db, specs=[spec], fail_closed=False)
    assert not res["valid"]
    assert len(res["incompatible"]) == 1
    assert "key structure mismatch" in res["incompatible"][0]["reason"]

    # 3. Fail-closed must raise CriticalFinanceIndexError
    with pytest.raises(CriticalFinanceIndexError) as exc_info:
        await verify_required_indexes(db, specs=[spec], fail_closed=True)
    assert exc_info.value.index_name == "uniq_payment_number"

    # 4. Drop the invalid index and create the correct index
    await db.payments.drop_index("uniq_payment_number")
    await db.payments.create_index([("payment_number", 1)], unique=True, name="uniq_payment_number")

    # 5. Verify: now passes cleanly
    res_clean = await verify_required_indexes(db, specs=[spec], fail_closed=True)
    assert res_clean["valid"]
    assert len(res_clean["verified"]) == 1
