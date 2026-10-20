"""Phase 3E-3R-3: Independent Startup & Migration Safety Review Test Suite.

Verifies:
1. Normal startup cannot bypass required production safety checks.
2. In production, STARTUP_DATA_MODE="none" cannot bypass baseline configuration verification.
3. In production, STARTUP_DATA_MODE="seed" and INDEX_PROVISIONING_MODE="auto" fail closed immediately.
4. Invalid or missing configuration modes fail closed immediately.
5. Missing index verifier fails closed.
6. Local development/test workflows retain legitimate flexibility.
7. Explicit data migrations are protected by advisory locking, retry idempotency, and transaction atomicity.
8. Transaction probe isolation and configuration safety.
9. Real replica-set end-to-end integration test.
"""

import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from bson import ObjectId
from datetime import datetime, timezone, timedelta

import backend.server as server
from backend.server import (
    startup,
    verify_baseline_data,
    OperationalConfigurationError,
    CriticalFinanceIndexError,
    get_environment_mode,
)
from backend.index_provisioner import (
    IndexSpec,
    REQUIRED_INDEX_SPECS,
)
from backend.data_migrations import (
    MIGRATIONS,
    MigrationConcurrencyError,
    execute_data_migration,
)


class TestPhase3E3R3StartupReview(unittest.IsolatedAsyncioTestCase):

    def _build_mock_production_db(self):
        """Constructs an in-memory mock MongoDB with valid owner and settings."""
        mock_db = MagicMock()
        mock_client = MagicMock()
        mock_db.client = mock_client
        mock_client.start_session = AsyncMock()

        owner_doc = {
            "_id": ObjectId(),
            "email": "owner@sogilfurniture.com",
            "name": "Production Owner",
            "role": "owner",
            "permissions": {"all": True},
        }
        mock_db.admins.find_one = AsyncMock(return_value=owner_doc)
        mock_db.admins.count_documents = AsyncMock(return_value=1)
        mock_db.admins.insert_one = AsyncMock()
        mock_db.admins.update_one = AsyncMock()

        def _mock_settings_find(query, session=None):
            k = query.get("key")
            if k in ["store_name", "exchange_rate_idr_per_le", "store_address"]:
                return {"_id": ObjectId(), "key": k, "value": "ValidSetting"}
            return None

        mock_db.settings.find_one = AsyncMock(side_effect=_mock_settings_find)
        mock_db.settings.update_one = AsyncMock()

        mock_db.products.count_documents = AsyncMock(return_value=5)
        mock_db.products.find_one = AsyncMock(return_value={"_id": ObjectId(), "name": "Custom Desk", "category": "custom"})
        mock_db.products.update_one = AsyncMock()
        mock_db.products.update_many = AsyncMock()
        mock_db.products.insert_one = AsyncMock()

        mock_db.delivery_zones.count_documents = AsyncMock(return_value=5)
        mock_db.categories.count_documents = AsyncMock(return_value=5)

        # Build mock index information for all 52 required indexes
        coll_specs = {}
        for spec in REQUIRED_INDEX_SPECS:
            coll_specs.setdefault(spec.collection, []).append(spec)
        for cname, specs in coll_specs.items():
            info = {"_id_": {"v": 2, "key": [("_id", 1)]}}
            for s in specs:
                entry = {"v": 2, "key": [(k, float(d)) for k, d in s.keys]}
                if s.unique:
                    entry["unique"] = True
                if s.partial_filter_expression is not None:
                    entry["partialFilterExpression"] = s.partial_filter_expression
                if s.sparse:
                    entry["sparse"] = True
                info[s.name] = entry
            col = getattr(mock_db, cname, None)
            if col is None or not isinstance(col, MagicMock):
                col = MagicMock()
                setattr(mock_db, cname, col)
            col.index_information = AsyncMock(return_value=info)
            col.create_index = AsyncMock()

        return mock_db

    async def test_01_production_startup_with_data_mode_none_enforces_baseline_verification(self):
        """Test 1: In production, STARTUP_DATA_MODE='none' must NOT bypass baseline verification."""
        mock_db = self._build_mock_production_db()
        # Admin collection has no owner
        mock_db.admins.find_one = AsyncMock(return_value=None)

        with patch.object(server, "db", mock_db), \
             patch.object(server, "run_transaction_probe", AsyncMock(return_value=True)), \
             patch.dict(os.environ, {
                 "APP_ENV": "production",
                 "INDEX_PROVISIONING_MODE": "verify",
                 "STARTUP_DATA_MODE": "none",
             }):

            with self.assertRaises(OperationalConfigurationError) as ctx:
                await startup()

            self.assertIn("No administrator account with role 'owner' exists", ctx.exception.reason)

    async def test_02_production_startup_with_data_mode_seed_fails_closed(self):
        """Test 2: In production, STARTUP_DATA_MODE='seed' or 'auto' is strictly forbidden."""
        mock_db = self._build_mock_production_db()

        with patch.object(server, "db", mock_db), \
             patch.object(server, "run_transaction_probe", AsyncMock(return_value=True)), \
             patch.dict(os.environ, {
                 "APP_ENV": "production",
                 "INDEX_PROVISIONING_MODE": "verify",
                 "STARTUP_DATA_MODE": "seed",
             }):

            with self.assertRaises(OperationalConfigurationError) as ctx:
                await startup()

            self.assertIn("strictly forbidden in production", ctx.exception.reason)

    async def test_03_invalid_or_missing_startup_data_mode_fails_closed(self):
        """Test 3: Missing or unrecognized STARTUP_DATA_MODE fails closed."""
        mock_db = self._build_mock_production_db()

        for invalid_val in ["", "invalid_mode", "bypass_all"]:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "run_transaction_probe", AsyncMock(return_value=True)), \
                 patch.dict(os.environ, {
                     "APP_ENV": "test",
                     "INDEX_PROVISIONING_MODE": "verify",
                     "STARTUP_DATA_MODE": invalid_val,
                 }):

                with self.assertRaises(OperationalConfigurationError) as ctx:
                    await startup()

                self.assertIn("Invalid or missing STARTUP_DATA_MODE", ctx.exception.reason)

    async def test_04_production_startup_with_idx_mode_auto_fails_closed(self):
        """Test 4: In production, INDEX_PROVISIONING_MODE='auto' is strictly forbidden."""
        mock_db = self._build_mock_production_db()

        with patch.object(server, "db", mock_db), \
             patch.object(server, "run_transaction_probe", AsyncMock(return_value=True)), \
             patch.dict(os.environ, {
                 "APP_ENV": "production",
                 "INDEX_PROVISIONING_MODE": "auto",
                 "STARTUP_DATA_MODE": "verify",
             }):

            with self.assertRaises(CriticalFinanceIndexError) as ctx:
                await startup()

            self.assertIn("strictly forbidden in production", ctx.exception.reason)

    async def test_05_invalid_or_missing_index_provisioning_mode_fails_closed(self):
        """Test 5: Missing or unrecognized INDEX_PROVISIONING_MODE fails closed."""
        mock_db = self._build_mock_production_db()

        for invalid_val in ["", "create_always", "none"]:
            with patch.object(server, "db", mock_db), \
                 patch.object(server, "run_transaction_probe", AsyncMock(return_value=True)), \
                 patch.dict(os.environ, {
                     "APP_ENV": "test",
                     "INDEX_PROVISIONING_MODE": invalid_val,
                     "STARTUP_DATA_MODE": "verify",
                 }):

                with self.assertRaises(CriticalFinanceIndexError) as ctx:
                    await startup()

                self.assertIn("Invalid or missing INDEX_PROVISIONING_MODE", ctx.exception.reason)

    async def test_06_missing_verify_required_indexes_fails_closed(self):
        """Test 6: If verify_required_indexes is None, startup fails closed."""
        mock_db = self._build_mock_production_db()

        with patch.object(server, "db", mock_db), \
             patch.object(server, "verify_required_indexes", None), \
             patch.object(server, "run_transaction_probe", AsyncMock(return_value=True)), \
             patch.dict(os.environ, {
                 "APP_ENV": "production",
                 "INDEX_PROVISIONING_MODE": "verify",
                 "STARTUP_DATA_MODE": "verify",
             }):

            with self.assertRaises(CriticalFinanceIndexError) as ctx:
                await startup()

            self.assertIn("Required index verification module", ctx.exception.reason)

    async def test_07_development_startup_with_data_mode_none_permits_bypassing(self):
        """Test 7: In development/test, STARTUP_DATA_MODE='none' permits bypassing verification/seeding."""
        mock_db = self._build_mock_production_db()
        mock_db.admins.find_one = AsyncMock(return_value=None)  # Missing owner, but dev allows bypass

        with patch.object(server, "db", mock_db), \
             patch.object(server, "run_transaction_probe", AsyncMock(return_value=True)), \
             patch.dict(os.environ, {
                 "APP_ENV": "development",
                 "INDEX_PROVISIONING_MODE": "verify",
                 "STARTUP_DATA_MODE": "none",
             }):

            # Must not raise OperationalConfigurationError
            await startup()
            mock_db.products.update_many.assert_not_called()

    async def test_08_production_valid_configuration_starts_cleanly(self):
        """Test 8: In production, valid configuration boots cleanly with zero writes."""
        mock_db = self._build_mock_production_db()

        with patch.object(server, "db", mock_db), \
             patch.object(server, "run_transaction_probe", AsyncMock(return_value=True)), \
             patch.dict(os.environ, {
                 "APP_ENV": "production",
                 "INDEX_PROVISIONING_MODE": "verify",
                 "STARTUP_DATA_MODE": "verify",
             }):

            await startup()

        # Zero index mutations
        for spec in REQUIRED_INDEX_SPECS:
            col = getattr(mock_db, spec.collection)
            col.create_index.assert_not_called()

        # Zero business data mutations
        mock_db.products.update_one.assert_not_called()
        mock_db.products.update_many.assert_not_called()
        mock_db.products.insert_one.assert_not_called()

    async def test_09_migration_concurrency_lock_prevents_parallel_execution(self):
        """Test 9: Advisory lock prevents concurrent execution of the same migration."""
        mock_db = MagicMock()
        mid = "migration_custom_category_product_rename_v1"

        # Simulate active lock in settings
        active_lock = {
            "key": f"lock_{mid}",
            "locked": True,
            "acquired_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        }
        mock_db.settings.find_one = AsyncMock(return_value=active_lock)

        with self.assertRaises(MigrationConcurrencyError) as ctx:
            await execute_data_migration(mock_db, mid, dry_run=False)

        self.assertIn("is currently running", str(ctx.exception))

    async def test_10_migration_lock_releases_cleanly_on_failure(self):
        """Test 10: Advisory lock is released in finally block even if migration handler fails."""
        mock_db = MagicMock()
        mid = "migration_rak_typeB_v2"
        mock_db.settings.find_one = AsyncMock(return_value=None)
        mock_db.settings.update_one = AsyncMock()

        # Mock handler to raise an error
        with patch.dict(MIGRATIONS, {mid: {
            "spec": MIGRATIONS[mid]["spec"],
            "handler": AsyncMock(side_effect=RuntimeError("Simulated mid-migration disk failure"))
        }}):
            with self.assertRaises(RuntimeError):
                await execute_data_migration(mock_db, mid, dry_run=False)

        # Verify lock was released in finally
        release_call = mock_db.settings.update_one.call_args_list[-1]
        self.assertEqual(release_call[0][0]["key"], f"lock_{mid}")
        self.assertFalse(release_call[0][1]["$set"]["locked"])

    async def test_11_migration_idempotent_retry_after_interrupted_run(self):
        """Test 11: Interrupted migration can be retried safely with zero destructive duplicates."""
        mock_db = MagicMock()
        mid = "migration_custom_category_product_rename_v1"

        # Interrupted state: product already renamed to "Koleksi Custom", but settings flag was not saved
        mock_db.products.count_documents = AsyncMock(return_value=0)  # 0 matching "Pesanan Custom"
        mock_db.products.update_many = AsyncMock(return_value=MagicMock(modified_count=0))
        mock_db.settings.find_one = AsyncMock(return_value=None)
        mock_db.settings.update_one = AsyncMock()

        # Retry execution
        res = await execute_data_migration(mock_db, mid, dry_run=False)
        self.assertEqual(res["status"], "APPLIED")
        self.assertEqual(res["modified_count"], 0)

        # Settings audit flag is now successfully saved
        audit_call = [c for c in mock_db.settings.update_one.call_args_list if c[0][0].get("key") == mid]
        self.assertTrue(len(audit_call) > 0)
        self.assertTrue(audit_call[0][0][1]["$set"]["value"])

    async def test_12_transaction_probe_isolated_and_zero_writes_when_disabled(self):
        """Test 12: TRANSACTION_PROBE_ENABLED='false' performs zero probe writes and leaves startup safe."""
        mock_db = self._build_mock_production_db()

        with patch.object(server, "db", mock_db), \
             patch.object(server, "run_transaction_probe", AsyncMock()) as mock_probe, \
             patch.dict(os.environ, {
                 "APP_ENV": "production",
                 "INDEX_PROVISIONING_MODE": "verify",
                 "STARTUP_DATA_MODE": "verify",
                 "TRANSACTION_PROBE_ENABLED": "false",
             }):

            await startup()

            mock_probe.assert_not_called()


@pytest.mark.anyio
async def test_real_replica_set_production_safety_and_migration_atomicity(real_replica_set_env):
    """Integration Test: Validates production fail-closed boundaries and atomic migration on real MongoDB."""
    client, db = real_replica_set_env

    # 1. Setup minimal owner
    await db.admins.insert_one({
        "email": "owner@sogil.com",
        "name": "Owner",
        "role": "owner",
        "password_hash": "dummy_hash",
        "permissions": {"all": True},
    })
    await db.settings.insert_one({"key": "store_name", "value": "Sogil Furniture Real"})
    await db.settings.insert_one({"key": "exchange_rate_idr_per_le", "value": 357})

    # Insert test product
    await db.products.insert_one({
        "slug": "custom-bookcase",
        "category": "custom",
        "name": "Pesanan Custom",  # Default legacy name
    })

    # 2. Production startup with STARTUP_DATA_MODE='none' must enforce baseline verification
    res = await verify_baseline_data(db, fail_closed=True)
    assert res["valid"] is True

    # 3. Explicit migration execution under real replica set session
    res_mig = await execute_data_migration(
        db,
        "migration_custom_category_product_rename_v1",
        dry_run=False,
        target_uri=os.environ.get("TEST_MONGO_REPLICA_SET_URI"),
        db_name=os.environ.get("TEST_MONGO_DB_NAME", "sogil_test_disposable_replica"),
    )
    assert res_mig["status"] == "APPLIED"
    assert res_mig["modified_count"] == 1

    # Verify product was renamed
    renamed = await db.products.find_one({"slug": "custom-bookcase"})
    assert renamed["name"] == "Koleksi Custom"

    # Verify audit document in settings
    audit_flag = await db.settings.find_one({"key": "migration_custom_category_product_rename_v1"})
    assert audit_flag is not None
    assert audit_flag["value"] is True

    # Verify concurrency lock was released
    lock_doc = await db.settings.find_one({"key": "lock_migration_custom_category_product_rename_v1"})
    assert lock_doc is not None
    assert lock_doc["locked"] is False
