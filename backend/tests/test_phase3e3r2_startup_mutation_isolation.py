"""Phase 3E-3R-2: Startup Data Mutation Isolation & Migration Safety Regression Tests.

Verifies:
1. Normal verification-mode startup performs zero index mutations.
2. Normal production-mode startup does not overwrite existing product names or prices.
3. Existing customized 'custom' category product names remain unchanged.
4. Existing customized 'rak' prices remain unchanged when migrations are not explicitly invoked.
5. Whiteboard pricing migration does not execute during normal startup.
6. Pricing type cleanup does not execute during normal startup.
7. Missing required baseline configuration fails closed with actionable diagnostic error.
8. Explicit migration execution performs only intended changes with dry-run support.
9. Migration reruns do not repeat destructive effects and preserve user customizations.
10. Transaction probe isolation and configurability via TRANSACTION_PROBE_ENABLED.
11. Real MongoDB replica set integration test for baseline verification and explicit migration lifecycle.
"""

import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from bson import ObjectId

from backend.server import (
    verify_baseline_data,
    seed_baseline_data_only,
    OperationalConfigurationError,
    startup,
)
import backend.server as server
from backend.data_migrations import (
    MIGRATIONS,
    list_available_migrations,
    execute_data_migration,
)
from backend.index_provisioner import REQUIRED_INDEX_SPECS, CriticalFinanceIndexError


class TestPhase3E3R2StartupMutationIsolation(unittest.IsolatedAsyncioTestCase):
    """Rigorous unit and mock-based safety tests for startup data isolation and migrations."""

    def _build_mock_production_db(self):
        """Constructs a mock DB representing an active production database
        with customized product names, custom prices, and an established owner admin.
        """
        mock_db = MagicMock()

        # Admin: established owner
        owner_doc = {
            "_id": ObjectId(),
            "email": "owner@sogilfurniture.com",
            "name": "Production Owner",
            "role": "owner",
            "permissions": {"all": True},
        }
        mock_db.admins.count_documents = AsyncMock(return_value=1)
        mock_db.admins.find_one = AsyncMock(return_value=owner_doc)
        mock_db.admins.insert_one = AsyncMock()
        mock_db.admins.update_one = AsyncMock()

        # Settings: all essential settings present
        def _mock_settings_find(query):
            k = query.get("key")
            if k in ["store_name", "exchange_rate_idr_per_le", "store_address"]:
                return {"_id": ObjectId(), "key": k, "value": "Present"}
            return None

        mock_db.settings.find_one = AsyncMock(side_effect=_mock_settings_find)
        mock_db.settings.update_one = AsyncMock()

        # Products: customized products
        custom_product = {
            "_id": ObjectId(),
            "slug": "pesanan-custom",
            "category": "custom",
            "name": "Custom Executive Mahogony Desk",  # Customized by store owner!
            "starting_price_le": 5500,
            "pricing": {"types": ["B", "A", "A+"]},  # Contains legacy A+
        }
        rak_product = {
            "_id": ObjectId(),
            "slug": "rak-kayu",
            "category": "rak",
            "name": "Rak Kayu Jati Pilihan",
            "starting_price_le": 9999,  # Customized price!
            "pricing": {"base_prices": {"60_2": 9999}},
        }
        papan_tulis_product = {
            "_id": ObjectId(),
            "slug": "papan-tulis",
            "category": "papan_tulis",
            "name": "Papan Tulis Premium",
            "pricing": {"groups": [{"key": "size", "options": ["80x60 cm"]}], "base_prices": {}},
        }

        mock_db.products.count_documents = AsyncMock(return_value=3)
        mock_db.products.insert_one = AsyncMock()
        mock_db.products.update_one = AsyncMock()
        mock_db.products.update_many = AsyncMock()

        def _mock_products_find(query):
            if query.get("category") == "custom":
                return custom_product
            if query.get("category") == "rak":
                return rak_product
            if query.get("slug") == "papan-tulis":
                return papan_tulis_product
            return None

        mock_db.products.find_one = AsyncMock(side_effect=_mock_products_find)

        # Non-empty delivery zones and categories
        mock_db.delivery_zones.count_documents = AsyncMock(return_value=7)
        mock_db.delivery_zones.insert_one = AsyncMock()
        mock_db.categories.count_documents = AsyncMock(return_value=7)
        mock_db.categories.insert_many = AsyncMock()

        # Mock indexes: all 52 required indexes present
        for spec in REQUIRED_INDEX_SPECS:
            col = getattr(mock_db, spec.collection, None)
            if col is None or not isinstance(col, MagicMock):
                col = MagicMock()
                setattr(mock_db, spec.collection, col)
                mock_db[spec.collection] = col
            col.create_index = AsyncMock(return_value="index_ok")

        # Setup index_information
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

        return mock_db, custom_product, rak_product

    async def test_01_verification_mode_performs_zero_index_mutations(self):
        """Test 1: Verification-mode startup performs zero create_index calls on any collection."""
        mock_db, _, _ = self._build_mock_production_db()

        with patch.object(server, "db", mock_db), \
             patch.object(server, "run_transaction_probe", AsyncMock(return_value=True)), \
             patch.dict(os.environ, {"INDEX_PROVISIONING_MODE": "verify", "STARTUP_DATA_MODE": "verify"}):

            await startup()

        for spec in REQUIRED_INDEX_SPECS:
            col = getattr(mock_db, spec.collection)
            col.create_index.assert_not_called()

    async def test_02_production_startup_does_not_overwrite_product_names_or_prices(self):
        """Test 2: Normal production-mode startup does not mutate products collection."""
        mock_db, custom_prod, rak_prod = self._build_mock_production_db()

        with patch.object(server, "db", mock_db), \
             patch.object(server, "run_transaction_probe", AsyncMock(return_value=True)), \
             patch.dict(os.environ, {"INDEX_PROVISIONING_MODE": "verify", "STARTUP_DATA_MODE": "verify"}):

            await startup()

        mock_db.products.update_one.assert_not_called()
        mock_db.products.update_many.assert_not_called()
        mock_db.products.insert_one.assert_not_called()

    async def test_03_existing_customized_custom_category_product_names_remain_unchanged(self):
        """Test 3: Existing customized 'custom' category product names are preserved in verify and seed modes."""
        mock_db, custom_prod, _ = self._build_mock_production_db()

        # Run in verify mode
        res = await verify_baseline_data(mock_db, fail_closed=True)
        self.assertTrue(res["valid"])
        mock_db.products.update_many.assert_not_called()
        self.assertEqual(custom_prod["name"], "Custom Executive Mahogony Desk")

        # Run in seed_baseline mode on non-empty catalog
        await seed_baseline_data_only(mock_db)
        mock_db.products.update_many.assert_not_called()
        self.assertEqual(custom_prod["name"], "Custom Executive Mahogony Desk")

    async def test_04_existing_customized_rak_prices_remain_unchanged_on_startup(self):
        """Test 4: Existing customized rak prices remain unchanged on startup."""
        mock_db, _, rak_prod = self._build_mock_production_db()

        # Run startup in verify mode
        with patch.object(server, "db", mock_db), \
             patch.object(server, "run_transaction_probe", AsyncMock(return_value=True)), \
             patch.dict(os.environ, {"INDEX_PROVISIONING_MODE": "verify", "STARTUP_DATA_MODE": "verify"}):

            await startup()

        self.assertEqual(rak_prod["starting_price_le"], 9999)
        self.assertEqual(rak_prod["pricing"]["base_prices"]["60_2"], 9999)
        mock_db.products.update_one.assert_not_called()

    async def test_05_whiteboard_pricing_migration_does_not_execute_during_startup(self):
        """Test 5: Whiteboard pricing migration does not execute during normal startup."""
        mock_db, _, _ = self._build_mock_production_db()

        with patch.object(server, "db", mock_db), \
             patch.object(server, "run_transaction_probe", AsyncMock(return_value=True)), \
             patch.dict(os.environ, {"INDEX_PROVISIONING_MODE": "verify", "STARTUP_DATA_MODE": "verify"}):

            await startup()

        # Setting migration_papan_tulis_small_sizes_v1 must not be inserted or updated during startup
        mock_db.settings.update_one.assert_not_called()

    async def test_06_pricing_type_cleanup_does_not_execute_during_startup(self):
        """Test 6: Pricing type cleanup does not execute during normal startup."""
        mock_db, custom_prod, _ = self._build_mock_production_db()

        with patch.object(server, "db", mock_db), \
             patch.object(server, "run_transaction_probe", AsyncMock(return_value=True)), \
             patch.dict(os.environ, {"INDEX_PROVISIONING_MODE": "verify", "STARTUP_DATA_MODE": "verify"}):

            await startup()

        # pricing.types still contains legacy A+ because no startup migration stripped it
        self.assertIn("A+", custom_prod["pricing"]["types"])
        mock_db.products.update_many.assert_not_called()

    async def test_07_missing_required_baseline_configuration_fails_closed(self):
        """Test 7: Missing required baseline configuration fails closed with OperationalConfigurationError."""
        mock_db, _, _ = self._build_mock_production_db()

        # Case A: No owner admin exists in database
        mock_db.admins.find_one = AsyncMock(return_value=None)
        with self.assertRaises(OperationalConfigurationError) as ctx:
            await verify_baseline_data(mock_db, fail_closed=True)
        self.assertIn("No administrator account with role 'owner' exists", ctx.exception.reason)

        # Reset admin find_one
        mock_db.admins.find_one = AsyncMock(return_value={"_id": ObjectId(), "role": "owner"})

        # Case B: Essential store settings missing
        mock_db.settings.find_one = AsyncMock(return_value=None)
        with self.assertRaises(OperationalConfigurationError) as ctx2:
            await verify_baseline_data(mock_db, fail_closed=True)
        self.assertIn("Essential store settings missing", ctx2.exception.reason)

    async def test_08_explicit_migration_execution_performs_only_intended_changes(self):
        """Test 8: Explicit migration execution performs only intended changes with dry-run support."""
        mock_db = MagicMock()
        custom_product = {
            "_id": ObjectId(),
            "category": "custom",
            "name": "Pesanan Custom",  # Default legacy name
        }
        mock_db.products.count_documents = AsyncMock(return_value=1)
        mock_db.products.update_many = AsyncMock(return_value=MagicMock(modified_count=1))
        mock_db.settings.update_one = AsyncMock()

        # 1. Dry run: 0 database writes
        res_dry = await execute_data_migration(mock_db, "migration_custom_category_product_rename_v1", dry_run=True)
        self.assertEqual(res_dry["status"], "PREVIEW")
        self.assertEqual(res_dry["legacy_default_matching_count"], 1)
        mock_db.products.update_many.assert_not_called()
        mock_db.settings.update_one.assert_not_called()

        # 2. Apply: updates legacy product and records migration in settings
        res_apply = await execute_data_migration(mock_db, "migration_custom_category_product_rename_v1", dry_run=False)
        mock_db.products.update_many.assert_called_once_with(
            {"category": "custom", "name": "Pesanan Custom"},
            {"$set": {"name": "Koleksi Custom"}}
        )
        audit_call = [c for c in mock_db.settings.update_one.call_args_list if c[0][0].get("key") == "migration_custom_category_product_rename_v1"]
        self.assertTrue(len(audit_call) > 0)
        self.assertTrue(audit_call[0][0][1]["$set"]["value"])

    async def test_09_migration_reruns_do_not_repeat_destructive_effects(self):
        """Test 9: Migration reruns preserve user-customized product names."""
        mock_db = MagicMock()
        mock_db.products.count_documents = AsyncMock(return_value=0)  # No legacy "Pesanan Custom" left
        mock_db.products.update_many = AsyncMock(return_value=MagicMock(modified_count=0))
        mock_db.settings.update_one = AsyncMock()

        # Re-run migration: 0 records modified
        res = await execute_data_migration(mock_db, "migration_custom_category_product_rename_v1", dry_run=False)
        self.assertEqual(res["modified_count"], 0)
        mock_db.products.update_many.assert_called_once_with(
            {"category": "custom", "name": "Pesanan Custom"},
            {"$set": {"name": "Koleksi Custom"}}
        )

    async def test_10_transaction_probe_isolated_and_configurable(self):
        """Test 10: Transaction probe is configurable via TRANSACTION_PROBE_ENABLED."""
        mock_db, _, _ = self._build_mock_production_db()

        # Case A: Disabled via env var
        with patch.object(server, "db", mock_db), \
             patch.object(server, "run_transaction_probe", AsyncMock(return_value=True)) as mock_probe, \
             patch.dict(os.environ, {
                 "INDEX_PROVISIONING_MODE": "verify",
                 "STARTUP_DATA_MODE": "verify",
                 "TRANSACTION_PROBE_ENABLED": "false",
             }):

            await startup()
            mock_probe.assert_not_called()

        # Case B: Enabled (default)
        with patch.object(server, "db", mock_db), \
             patch.object(server, "run_transaction_probe", AsyncMock(return_value=True)) as mock_probe, \
             patch.dict(os.environ, {
                 "INDEX_PROVISIONING_MODE": "verify",
                 "STARTUP_DATA_MODE": "verify",
                 "TRANSACTION_PROBE_ENABLED": "true",
             }):

            await startup()
            mock_probe.assert_called_once()


@pytest.mark.anyio
async def test_real_replica_set_startup_data_isolation(real_replica_set_env):
    """Integration Test: Validates read-only baseline verification and explicit migration on real MongoDB."""
    client, db = real_replica_set_env

    # 1. Setup clean baseline in test database
    await db.admins.insert_one({
        "email": "owner@sogil.com",
        "name": "Owner",
        "role": "owner",
        "password_hash": "dummy_hash",
        "permissions": {"all": True},
    })
    await db.settings.insert_one({"key": "store_name", "value": "Sogil Real"})
    await db.settings.insert_one({"key": "exchange_rate_idr_per_le", "value": 357})

    # Insert customized product
    await db.products.insert_one({
        "slug": "custom-table",
        "category": "custom",
        "name": "Handmade Artisan Table",  # Customized
        "starting_price_le": 12000,
    })

    # 2. Verify baseline data in read-only mode -> passes cleanly
    res = await verify_baseline_data(db, fail_closed=True)
    assert res["valid"] is True
    assert res["owner_present"] is True

    # 3. Verify product was NOT renamed
    prod = await db.products.find_one({"category": "custom"})
    assert prod["name"] == "Handmade Artisan Table"

    # 4. Explicitly run migration_custom_category_product_rename_v1
    mig_res = await execute_data_migration(db, "migration_custom_category_product_rename_v1", dry_run=False)
    assert mig_res["status"] == "APPLIED"
    assert mig_res["modified_count"] == 0  # Did not overwrite customized name!

    # 5. Verify product name STILL untouched
    prod_after = await db.products.find_one({"category": "custom"})
    assert prod_after["name"] == "Handmade Artisan Table"
