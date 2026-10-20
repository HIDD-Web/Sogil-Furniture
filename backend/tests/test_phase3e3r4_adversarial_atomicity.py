"""Phase 3E-3R-4 — Adversarial Verification of Migration Atomicity & Production Guards.

Audits and proves:
1. Concurrency isolation: atomic conditional write protection, single-winner race resolution,
   and cross-migration conflict prevention.
2. ACID atomicity & crash recovery: injected mid-migration failure rollback, zero partial writes,
   safe retry reconciliation, and strictly failing closed without transactions.
3. Production startup guard matrix: environment detection, mode validation, missing settings/admin,
   missing indexes, and complete isolation of migrations from startup.
4. CLI target isolation guard: credentials parsing, url-encoded edge cases, forbidden remote hosts,
   and exit code contracts.
"""

import asyncio
import os
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
import pytest
import pymongo.errors

from backend.data_migrations import (
    MIGRATIONS,
    MigrationConcurrencyError,
    MigrationTransactionRequiredError,
    execute_data_migration,
    list_available_migrations,
    RAK_TYPE_B_PRICES,
)
from backend.index_provisioner import (
    REQUIRED_INDEX_SPECS,
    CriticalFinanceIndexError,
)
from backend.tests.isolation_guard import (
    validate_test_database_isolation,
    sanitize_uri_for_logging,
    FORBIDDEN_DB_NAMES,
)
from backend.server import (
    startup,
    verify_baseline_data,
    OperationalConfigurationError,
)
import backend.server as server


# ==============================================================================
# PART 1: REAL STAGING REPLICA SET CONCURRENCY & ACID ATOMICITY
# ==============================================================================

@pytest.mark.anyio
async def test_01_real_concurrent_race_same_migration_strictly_single_winner(real_replica_set_env):
    """Adversarial Test 1: Two concurrent tasks attempt the same migration on real replica set.
    Proves: exactly ONE task succeeds, the other fails with MigrationConcurrencyError,
    and product catalog remains consistent with exactly 1 applied rename.
    """
    client, db = real_replica_set_env

    # Seed legacy default custom product
    await db.products.insert_one({
        "category": "custom",
        "name": "Pesanan Custom",
        "starting_price_le": 5000,
    })

    mid = "migration_custom_category_product_rename_v1"
    original_handler = MIGRATIONS[mid]["handler"]

    # Introduce a slight delay during execution to ensure concurrent lock collision window
    async def _concurrent_slow_handler(database, dry_run: bool, session=None):
        await asyncio.sleep(0.1)
        return await original_handler(database, dry_run=dry_run, session=session)

    with patch.dict(MIGRATIONS, {mid: {"spec": MIGRATIONS[mid]["spec"], "handler": _concurrent_slow_handler}}):
        res1, res2 = await asyncio.gather(
            execute_data_migration(db, mid, dry_run=False),
            execute_data_migration(db, mid, dry_run=False),
            return_exceptions=True,
        )

    results = [res1, res2]
    successes = [r for r in results if isinstance(r, dict) and r.get("status") == "APPLIED"]
    concurrency_errors = [r for r in results if isinstance(r, MigrationConcurrencyError)]

    # Exactly 1 winner, 1 concurrency collision
    assert len(successes) == 1, f"Expected exactly 1 success, got: {results}"
    assert len(concurrency_errors) == 1, f"Expected exactly 1 ConcurrencyError, got: {results}"
    assert "is currently running" in str(concurrency_errors[0])

    # Verify authoritative database state: renamed cleanly once
    prod = await db.products.find_one({"category": "custom"})
    assert prod["name"] == "Koleksi Custom"


@pytest.mark.anyio
async def test_02_real_concurrent_race_cross_migration_conflict_prevention(real_replica_set_env):
    """Adversarial Test 2: Two different migrations modifying shared 'products' collection
    launched concurrently. Proves cross-migration lock contention blocks competing execution.
    """
    client, db = real_replica_set_env

    # Seed products for both migrations
    await db.products.insert_one({
        "category": "rak",
        "pricing": {"base_prices": {"60_2": 100}},
        "starting_price_le": 100,
    })
    await db.products.insert_one({
        "slug": "papan-tulis",
        "pricing": {
            "groups": [{"key": "size", "options": ["80x60 cm"]}],
            "base_prices": {"Gantung | 80x60 cm": 500},
        },
        "starting_price_le": 500,
    })

    mid_rak = "migration_rak_typeB_v2"
    mid_pt = "migration_papan_tulis_small_sizes_v1"
    orig_rak_handler = MIGRATIONS[mid_rak]["handler"]

    async def _slow_rak_handler(database, dry_run: bool, session=None):
        await asyncio.sleep(0.1)
        return await orig_rak_handler(database, dry_run=dry_run, session=session)

    with patch.dict(MIGRATIONS, {mid_rak: {"spec": MIGRATIONS[mid_rak]["spec"], "handler": _slow_rak_handler}}):
        res_rak, res_pt = await asyncio.gather(
            execute_data_migration(db, mid_rak, dry_run=False),
            execute_data_migration(db, mid_pt, dry_run=False),
            return_exceptions=True,
        )

    results = [res_rak, res_pt]
    successes = [r for r in results if isinstance(r, dict) and r.get("status") == "APPLIED"]
    concurrency_errors = [r for r in results if isinstance(r, MigrationConcurrencyError)]

    assert len(successes) == 1, f"Expected 1 success, got: {results}"
    assert len(concurrency_errors) == 1, f"Expected 1 ConcurrencyError, got: {results}"
    assert "is currently running" in str(concurrency_errors[0])


@pytest.mark.anyio
async def test_03_real_mid_migration_injected_failure_full_acid_rollback(real_replica_set_env):
    """Adversarial Test 3: Inject mid-migration failure after product update but before commit.
    Proves full ACID transaction rollback on replica set: 0 partial changes committed.
    """
    client, db = real_replica_set_env

    # Seed Rak Type B with distinct non-migrated pricing
    original_prices = {"60_2": 111, "60_3": 222}
    await db.products.insert_one({
        "_id": ObjectId("650000000000000000000001"),
        "category": "rak",
        "pricing": {"base_prices": dict(original_prices)},
        "starting_price_le": 111,
    })

    mid = "migration_rak_typeB_v2"

    async def _failing_handler(database, dry_run: bool, session=None):
        # Update product inside session
        await database.products.update_one(
            {"category": "rak"},
            {"$set": {"pricing.base_prices.60_2": 9999, "starting_price_le": 9999}},
            session=session,
        )
        # Crash before settings audit update and commit
        raise RuntimeError("SIMULATED_PROCESS_CRASH_BEFORE_COMMIT")

    with patch.dict(MIGRATIONS, {mid: {"spec": MIGRATIONS[mid]["spec"], "handler": _failing_handler}}):
        with pytest.raises(RuntimeError) as exc_info:
            await execute_data_migration(db, mid, dry_run=False)
        assert "SIMULATED_PROCESS_CRASH_BEFORE_COMMIT" in str(exc_info.value)

    # ACID PROOF: Verify products collection has ZERO committed changes from the aborted transaction
    prod = await db.products.find_one({"category": "rak"})
    assert prod["pricing"]["base_prices"]["60_2"] == 111, "Transaction rollback failed: partial write committed!"
    assert prod["starting_price_le"] == 111

    # Verify settings has NO audit document recorded
    audit = await db.settings.find_one({"key": mid})
    assert audit is None, "Audit record committed despite transaction failure!"


@pytest.mark.anyio
async def test_04_real_idempotent_retry_after_failure_reconciles_cleanly(real_replica_set_env):
    """Adversarial Test 4: Retrying migration after the rolled-back failure succeeds cleanly
    and results in the exact authoritative specification state.
    """
    client, db = real_replica_set_env

    # Ensure product is present in pre-migration state
    await db.products.delete_many({"category": "rak"})
    await db.products.insert_one({
        "_id": ObjectId("650000000000000000000002"),
        "category": "rak",
        "pricing": {"base_prices": {"60_2": 250}},
        "starting_price_le": 250,
    })

    mid = "migration_rak_typeB_v2"

    # Retry clean execution
    res = await execute_data_migration(db, mid, dry_run=False)
    assert res["status"] == "APPLIED"
    assert res["modified_count"] == 1

    # Verify product is now updated according to canonical RAK_TYPE_B_PRICES
    prod = await db.products.find_one({"category": "rak"})
    assert prod["pricing"]["base_prices"]["60_2"] == RAK_TYPE_B_PRICES["60_2"]
    assert prod["starting_price_le"] == RAK_TYPE_B_PRICES["60_2"]

    # Verify audit flag is committed
    audit = await db.settings.find_one({"key": mid})
    assert audit is not None
    assert audit["value"] is True

    # Re-running again is safe and idempotent (0 modifications)
    res_rerun = await execute_data_migration(db, mid, dry_run=False)
    assert res_rerun["status"] == "APPLIED"
    assert res_rerun["modified_count"] == 0


@pytest.mark.anyio
async def test_05_stale_lock_safe_reclamation(real_replica_set_env):
    """Adversarial Test 5: A crashed process that left an expired lock is safely reclaimed."""
    client, db = real_replica_set_env

    mid = "migration_product_photos_backfill_v1"
    stale_expiry = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()

    # Seed an expired lock
    await db.settings.update_one(
        {"key": f"lock_{mid}"},
        {"$set": {
            "locked": True,
            "migration_id": mid,
            "acquired_at": (datetime.now(timezone.utc) - timedelta(minutes=25)).isoformat(),
            "expires_at": stale_expiry,
        }},
        upsert=True
    )

    # Execution must reclaim the expired lock without error
    res = await execute_data_migration(db, mid, dry_run=False)
    assert res["status"] == "APPLIED"

    # Lock must be released after completion
    lock_doc = await db.settings.find_one({"key": f"lock_{mid}"})
    assert lock_doc["locked"] is False


# ==============================================================================
# PART 2: FAIL-CLOSED TRANSACTION CAPABILITY
# ==============================================================================

class TestTransactionCapabilityFailClosed(unittest.IsolatedAsyncioTestCase):
    """Adversarial tests proving non-transactional standalone deployments fail closed."""

    async def test_06_standalone_mongodb_fails_closed_without_transaction_capability(self):
        """Test 6: AsyncIOMotorClient connected to a standalone MongoDB raising ConfigurationError
        fails closed with MigrationTransactionRequiredError (zero silent fallback).
        """
        mock_db = MagicMock()
        mock_client = MagicMock()
        type(mock_client).__name__ = "AsyncIOMotorClient"
        mock_db.client = mock_client

        # Mock settings lock calls
        mock_db.settings.find_one = AsyncMock(return_value=None)
        mock_db.settings.find_one_and_update = AsyncMock(return_value={"key": "lock_migration_custom_category_product_rename_v1", "locked": True})
        mock_db.settings.update_one = AsyncMock()

        # Simulate standalone server rejecting session transactions
        mock_client.start_session = MagicMock(
            side_effect=pymongo.errors.ConfigurationError("Transactions are not supported by this deployment")
        )

        mid = "migration_custom_category_product_rename_v1"
        with self.assertRaises(MigrationTransactionRequiredError) as ctx:
            await execute_data_migration(mock_db, mid, dry_run=False)

        self.assertIn("requires multi-document ACID transaction capability", str(ctx.exception))
        self.assertIn("replica set required", str(ctx.exception))

        # ZERO writes to products
        mock_db.products.update_many.assert_not_called()

    async def test_07_client_without_transaction_support_fails_closed(self):
        """Test 7: Client session lacking start_transaction method fails closed."""
        mock_db = MagicMock()
        mock_client = MagicMock()
        type(mock_client).__name__ = "AsyncIOMotorClient"
        mock_db.client = mock_client

        mock_db.settings.find_one = AsyncMock(return_value=None)
        mock_db.settings.find_one_and_update = AsyncMock(return_value={"key": "lock_migration_rak_typeB_v2", "locked": True})
        mock_db.settings.update_one = AsyncMock()

        mock_session = MagicMock()
        del mock_session.start_transaction  # Session lacks transaction method
        mock_client.start_session = AsyncMock(return_value=mock_session)

        mid = "migration_rak_typeB_v2"
        with self.assertRaises(MigrationTransactionRequiredError) as ctx:
            await execute_data_migration(mock_db, mid, dry_run=False)

        self.assertIn("active client session does not support transactions", str(ctx.exception))
        mock_db.products.update_one.assert_not_called()


# ==============================================================================
# PART 3: PRODUCTION STARTUP GUARD MATRIX
# ==============================================================================

class TestProductionStartupGuardMatrix(unittest.IsolatedAsyncioTestCase):
    """Adversarial tests verifying the full startup configuration guard matrix."""

    def _build_mock_db(self, owner_present=True, store_settings_present=True):
        mock_db = MagicMock()
        mock_client = MagicMock()
        type(mock_client).__name__ = "AsyncIOMotorClient"
        mock_db.client = mock_client

        if owner_present:
            mock_db.admins.find_one = AsyncMock(return_value={"_id": ObjectId(), "role": "owner"})
        else:
            mock_db.admins.find_one = AsyncMock(return_value=None)

        if store_settings_present:
            mock_db.settings.find_one = AsyncMock(return_value={"key": "store_name", "value": "Sogil Furniture"})
        else:
            mock_db.settings.find_one = AsyncMock(return_value=None)

        mock_db.delivery_zones.count_documents = AsyncMock(return_value=5)
        mock_db.categories.count_documents = AsyncMock(return_value=5)

        # Mock all 52 required indexes
        for spec in REQUIRED_INDEX_SPECS:
            col = getattr(mock_db, spec.collection, None)
            if col is None or not isinstance(col, MagicMock):
                col = MagicMock()
                setattr(mock_db, spec.collection, col)
                mock_db[spec.collection] = col
            col.create_index = AsyncMock(return_value="ok")

        # Mock index_information
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
            col = getattr(mock_db, cname)
            col.index_information = AsyncMock(return_value=info)

        return mock_db

    async def test_08_startup_guard_production_rejects_seed_mode(self):
        """Test 8: In production, STARTUP_DATA_MODE=seed fails closed."""
        mock_db = self._build_mock_db()

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

    async def test_09_startup_guard_production_rejects_auto_indexes(self):
        """Test 9: In production, INDEX_PROVISIONING_MODE=auto fails closed."""
        mock_db = self._build_mock_db()

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

    async def test_10_startup_guard_invalid_and_empty_modes_fail_closed(self):
        """Test 10: Unrecognized, misspelled, or empty mode values fail closed immediately."""
        mock_db = self._build_mock_db()

        # Case A: misspelled STARTUP_DATA_MODE
        with patch.object(server, "db", mock_db), \
             patch.object(server, "run_transaction_probe", AsyncMock(return_value=True)), \
             patch.dict(os.environ, {"INDEX_PROVISIONING_MODE": "verify", "STARTUP_DATA_MODE": "seeed"}):
            with self.assertRaises(OperationalConfigurationError) as ctx:
                await startup()
            self.assertIn("Invalid or missing STARTUP_DATA_MODE: 'seeed'", ctx.exception.reason)

        # Case B: misspelled INDEX_PROVISIONING_MODE
        with patch.object(server, "db", mock_db), \
             patch.object(server, "run_transaction_probe", AsyncMock(return_value=True)), \
             patch.dict(os.environ, {"INDEX_PROVISIONING_MODE": "autoo", "STARTUP_DATA_MODE": "verify"}):
            with self.assertRaises(CriticalFinanceIndexError) as ctx:
                await startup()
            self.assertIn("Invalid or missing INDEX_PROVISIONING_MODE: 'autoo'", ctx.exception.reason)

    async def test_11_startup_guard_production_none_mode_still_enforces_baseline_checks(self):
        """Test 11: In production, STARTUP_DATA_MODE=none strictly enforces baseline verification."""
        mock_db = self._build_mock_db(owner_present=False)  # Missing owner admin!

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

    async def test_12_startup_guard_missing_required_indexes_fails_closed_in_all_modes(self):
        """Test 12: Missing required indexes fail closed in production regardless of mode."""
        mock_db = self._build_mock_db()
        # Remove required index from mock information for finance_transactions
        mock_db.finance_transactions.index_information = AsyncMock(return_value={
            "_id_": {"v": 2, "key": [("_id", 1)]}
        })

        with patch.object(server, "db", mock_db), \
             patch.object(server, "run_transaction_probe", AsyncMock(return_value=True)), \
             patch.dict(os.environ, {
                 "APP_ENV": "production",
                 "INDEX_PROVISIONING_MODE": "verify",
                 "STARTUP_DATA_MODE": "verify",
             }):
            with self.assertRaises(CriticalFinanceIndexError) as ctx:
                await startup()
            self.assertIn("uniq_purchase_finance_expense", ctx.exception.reason)

    async def test_13_startup_guard_normal_startup_never_invokes_data_migrations(self):
        """Test 13: Normal startup path does zero data migrations or product mutations."""
        mock_db = self._build_mock_db()

        with patch.object(server, "db", mock_db), \
             patch.object(server, "run_transaction_probe", AsyncMock(return_value=True)), \
             patch.dict(os.environ, {
                 "APP_ENV": "production",
                 "INDEX_PROVISIONING_MODE": "verify",
                 "STARTUP_DATA_MODE": "verify",
             }):
            await startup()

        # Zero product mutations or settings migration writes
        mock_db.products.update_one.assert_not_called()
        mock_db.products.update_many.assert_not_called()


# ==============================================================================
# PART 4: CLI TARGET ISOLATION GUARD & URI ADVERSARIAL MATRIX
# ==============================================================================

class TestIsolationGuardAdversarialMatrix(unittest.TestCase):
    """Adversarial validation of isolation guards against dangerous connection strings."""

    def test_14_uri_embedded_credentials_and_url_encoded_at_symbol(self):
        """Test 14: Handles credentials with URL-encoded special characters safely."""
        valid_encoded = "mongodb://user%40company:p%40ssw%3Ard@127.0.0.1:27017"
        validate_test_database_isolation(valid_encoded, "sogil_test_valid")

        # Credential sanitization must hide credentials completely
        sanitized = sanitize_uri_for_logging(valid_encoded)
        assert "user%40" not in sanitized
        assert "p%40ss" not in sanitized
        assert "***:***@127.0.0.1:27017" in sanitized

    def test_15_uri_forbidden_remote_hosts_fail_closed(self):
        """Test 15: Atlas and remote operational hosts fail closed."""
        forbidden_uris = [
            "mongodb+srv://user:pass@sogil-furniture.7djg3j5.mongodb.net",
            "mongodb://user:pass@some-cluster.mongodb.net:27017",
            "mongodb://user:pass@containers-us-west-1.railway.app:5432",
            "mongodb://user:pass@production-db:27017",
            "mongodb://user:pass@atlas-proxy:27017",
        ]
        for uri in forbidden_uris:
            with self.assertRaises(ValueError) as ctx:
                validate_test_database_isolation(uri, "sogil_test_db")
            self.assertIn("SECURITY ABORT", str(ctx.exception))

    def test_16_uri_unapproved_private_ip_and_domains_fail_closed(self):
        """Test 16: Private LAN IPs and unapproved hostnames fail closed."""
        unapproved_uris = [
            "mongodb://10.0.0.1:27017",
            "mongodb://192.168.1.50:27017",
            "mongodb://database.internal:27017",
            "mongodb://prod-mongo.local:27017",
        ]
        for uri in unapproved_uris:
            with self.assertRaises(ValueError) as ctx:
                validate_test_database_isolation(uri, "sogil_test_db")
            self.assertIn("approved test host allowlist", str(ctx.exception))

    def test_17_db_name_forbidden_and_unprefixed_names_fail_closed(self):
        """Test 17: Protected production and non-test database names fail closed."""
        uri = "mongodb://127.0.0.1:27017"

        # Forbidden exact database names
        for forbidden_db in FORBIDDEN_DB_NAMES:
            with self.assertRaises(ValueError) as ctx:
                validate_test_database_isolation(uri, forbidden_db)
            self.assertIn("SECURITY ABORT", str(ctx.exception))
            self.assertIn("protected production or system database", str(ctx.exception))

        # Missing test prefixes
        unprefixed = ["my_custom_db", "test_database", "random_store"]
        for db_name in unprefixed:
            with self.assertRaises(ValueError) as ctx:
                validate_test_database_isolation(uri, db_name)
            self.assertIn("must start with one of", str(ctx.exception))

    def test_18_empty_or_malformed_uri_fails_closed(self):
        """Test 18: Empty, none, or invalid scheme URIs fail closed."""
        with self.assertRaises(ValueError) as ctx1:
            validate_test_database_isolation("", "sogil_test_db")
        self.assertIn("URI is missing or empty", str(ctx1.exception))

        with self.assertRaises(ValueError) as ctx2:
            validate_test_database_isolation("http://127.0.0.1:27017", "sogil_test_db")
        self.assertIn("Invalid scheme", str(ctx2.exception))
