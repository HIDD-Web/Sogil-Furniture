#!/usr/bin/env python3
"""Local-Only Controlled Migration Script: Legacy Inventory Unit Normalization.

Normalizes exactly four pre-standardization legacy documents for BlockBoard:
  1. stock_forms: ObjectId("6ac35a8131665b7e4febc00c") (Rak 60x20): pcs -> lembar
  2. stock_forms: ObjectId("6ac35a8231665b7e4febc00d") (Rak 80x20): pcs -> lembar
  3. material_stocks: ObjectId("6ac36f34a22e88a9a9aec09d") (ST-20261005-0003): pcs -> lembar
  4. material_stocks: ObjectId("6ac3f85bd059c322df25dc56") (ST-20261005-0024): pcs -> lembar

SAFETY CONTRACT:
1. Target IDs are hardcoded constants. Dynamic/broad discovery is forbidden.
2. Dry-run is the default mode (--dry-run).
3. Production execution is strictly blocked by environment guards.
4. All updates are wrapped in a MongoDB multi-document ACID transaction.
5. Invariants strictly verified: quantities (24.0, 18.0) and dimensions remain unchanged.
6. Unique index collision preflight ensures zero duplicate collisions on uniq_stock_form_spec.
7. Secrets (passwords, connection strings) are never logged or exposed.
"""
import os
import sys
import argparse
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from bson import ObjectId

import pymongo
from pymongo import MongoClient


# Hardcoded target constants
PARENT_MATERIAL_ID = "6ac144838d54d51a83fdf23f"
TARGET_SF1_ID = "6ac35a8131665b7e4febc00c"
TARGET_SF2_ID = "6ac35a8231665b7e4febc00d"
TARGET_MS1_ID = "6ac36f34a22e88a9a9aec09d"
TARGET_MS2_ID = "6ac3f85bd059c322df25dc56"

APPROVED_STOCK_FORM_TARGETS = [TARGET_SF1_ID, TARGET_SF2_ID]
APPROVED_MATERIAL_STOCK_TARGETS = [TARGET_MS1_ID, TARGET_MS2_ID]


class MigrationError(Exception):
    """Raised when migration precondition or invariant check fails."""
    pass


def check_production_guard() -> None:
    """Refuses execution if production environment indicators are detected."""
    # Railway execution check
    if os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_PROJECT_ID"):
        raise MigrationError(
            "ABORT: Production execution blocked! Railway environment detected. "
            "This script is for local/test validation only."
        )

    # General environment flag check
    env_name = (os.environ.get("ENV") or os.environ.get("ENVIRONMENT") or "").strip().lower()
    if env_name in ["production", "prod"]:
        raise MigrationError(
            "ABORT: Production execution blocked! Environment variable indicates production. "
            "This script is for local/test validation only."
        )

    # Database name check
    db_name = (os.environ.get("DB_NAME") or "").strip().lower()
    if any(p in db_name for p in ["prod", "production"]):
        raise MigrationError(
            f"ABORT: Production execution blocked! Database name '{db_name}' appears to be production. "
            "This script is for local/test validation only."
        )


def capture_snapshot(db: Any) -> Dict[str, Any]:
    """Captures complete original documents for all four targets before mutation."""
    sf1 = db.stock_forms.find_one({"_id": ObjectId(TARGET_SF1_ID)})
    sf2 = db.stock_forms.find_one({"_id": ObjectId(TARGET_SF2_ID)})
    ms1 = db.material_stocks.find_one({"_id": ObjectId(TARGET_MS1_ID)})
    ms2 = db.material_stocks.find_one({"_id": ObjectId(TARGET_MS2_ID)})

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stock_forms": [sf1, sf2],
        "material_stocks": [ms1, ms2]
    }


def verify_preconditions(db: Any) -> Dict[str, Any]:
    """Runs all fail-closed precondition checks on target documents and parent material."""
    # 1. Parent Material
    parent = db.materials.find_one({"_id": ObjectId(PARENT_MATERIAL_ID)})
    if not parent:
        raise MigrationError(f"Precondition failed: Parent material '{PARENT_MATERIAL_ID}' not found.")
    if parent.get("name") != "BlockBoard":
        raise MigrationError(f"Precondition failed: Parent material name is '{parent.get('name')}', expected 'BlockBoard'.")
    if parent.get("unit") != "lembar":
        raise MigrationError(f"Precondition failed: Parent material unit is '{parent.get('unit')}', expected 'lembar'.")
    if parent.get("status") != "active":
        raise MigrationError(f"Precondition failed: Parent material status is '{parent.get('status')}', expected 'active'.")

    # 2. Target Stock Form 1 (Rak 60x20)
    sf1 = db.stock_forms.find_one({"_id": ObjectId(TARGET_SF1_ID)})
    if not sf1:
        raise MigrationError(f"Precondition failed: Target Stock Form 1 '{TARGET_SF1_ID}' not found.")
    if str(sf1.get("material_id")) != PARENT_MATERIAL_ID:
        raise MigrationError(f"Precondition failed: sf1 material_id '{sf1.get('material_id')}' != '{PARENT_MATERIAL_ID}'.")
    if sf1.get("form_type") != "standard":
        raise MigrationError(f"Precondition failed: sf1 form_type '{sf1.get('form_type')}' != 'standard'.")
    if sf1.get("label") != "Rak 60x20":
        raise MigrationError(f"Precondition failed: sf1 label '{sf1.get('label')}' != 'Rak 60x20'.")
    if float(sf1.get("width") or 0) != 20.0 or float(sf1.get("length") or 0) != 60.0 or float(sf1.get("thickness") or 0) != 1.6:
        raise MigrationError(f"Precondition failed: sf1 dimensions mismatch: W={sf1.get('width')}, L={sf1.get('length')}, T={sf1.get('thickness')}.")
    if sf1.get("dimension_unit") != "cm":
        raise MigrationError(f"Precondition failed: sf1 dimension_unit '{sf1.get('dimension_unit')}' != 'cm'.")
    if float(sf1.get("current_quantity") or 0) != 24.0:
        raise MigrationError(f"Precondition failed: sf1 current_quantity {sf1.get('current_quantity')} != 24.0.")
    if not sf1.get("is_active"):
        raise MigrationError("Precondition failed: sf1 is_active is not True.")

    # 3. Target Stock Form 2 (Rak 80x20)
    sf2 = db.stock_forms.find_one({"_id": ObjectId(TARGET_SF2_ID)})
    if not sf2:
        raise MigrationError(f"Precondition failed: Target Stock Form 2 '{TARGET_SF2_ID}' not found.")
    if str(sf2.get("material_id")) != PARENT_MATERIAL_ID:
        raise MigrationError(f"Precondition failed: sf2 material_id '{sf2.get('material_id')}' != '{PARENT_MATERIAL_ID}'.")
    if sf2.get("form_type") != "standard":
        raise MigrationError(f"Precondition failed: sf2 form_type '{sf2.get('form_type')}' != 'standard'.")
    if sf2.get("label") != "Rak 80x20":
        raise MigrationError(f"Precondition failed: sf2 label '{sf2.get('label')}' != 'Rak 80x20'.")
    if float(sf2.get("width") or 0) != 20.0 or float(sf2.get("length") or 0) != 80.0 or float(sf2.get("thickness") or 0) != 1.6:
        raise MigrationError(f"Precondition failed: sf2 dimensions mismatch: W={sf2.get('width')}, L={sf2.get('length')}, T={sf2.get('thickness')}.")
    if sf2.get("dimension_unit") != "cm":
        raise MigrationError(f"Precondition failed: sf2 dimension_unit '{sf2.get('dimension_unit')}' != 'cm'.")
    if float(sf2.get("current_quantity") or 0) != 18.0:
        raise MigrationError(f"Precondition failed: sf2 current_quantity {sf2.get('current_quantity')} != 18.0.")
    if not sf2.get("is_active"):
        raise MigrationError("Precondition failed: sf2 is_active is not True.")

    # 4. Target Material Stock 1 (ST-20261005-0003)
    ms1 = db.material_stocks.find_one({"_id": ObjectId(TARGET_MS1_ID)})
    if not ms1:
        raise MigrationError(f"Precondition failed: Target Material Stock 1 '{TARGET_MS1_ID}' not found.")
    if ms1.get("movement_number") != "ST-20261005-0003":
        raise MigrationError(f"Precondition failed: ms1 movement_number '{ms1.get('movement_number')}' != 'ST-20261005-0003'.")
    if str(ms1.get("stock_form_id")) != TARGET_SF1_ID:
        raise MigrationError(f"Precondition failed: ms1 stock_form_id '{ms1.get('stock_form_id')}' != '{TARGET_SF1_ID}'.")
    if str(ms1.get("material_id")) != PARENT_MATERIAL_ID:
        raise MigrationError(f"Precondition failed: ms1 material_id '{ms1.get('material_id')}' != '{PARENT_MATERIAL_ID}'.")
    if ms1.get("movement_type") != "transformation_in":
        raise MigrationError(f"Precondition failed: ms1 movement_type '{ms1.get('movement_type')}' != 'transformation_in'.")
    if float(ms1.get("quantity_delta") or 0) != 24.0:
        raise MigrationError(f"Precondition failed: ms1 quantity_delta {ms1.get('quantity_delta')} != 24.0.")

    # 5. Target Material Stock 2 (ST-20261005-0024)
    ms2 = db.material_stocks.find_one({"_id": ObjectId(TARGET_MS2_ID)})
    if not ms2:
        raise MigrationError(f"Precondition failed: Target Material Stock 2 '{TARGET_MS2_ID}' not found.")
    if ms2.get("movement_number") != "ST-20261005-0024":
        raise MigrationError(f"Precondition failed: ms2 movement_number '{ms2.get('movement_number')}' != 'ST-20261005-0024'.")
    if str(ms2.get("stock_form_id")) != TARGET_SF2_ID:
        raise MigrationError(f"Precondition failed: ms2 stock_form_id '{ms2.get('stock_form_id')}' != '{TARGET_SF2_ID}'.")
    if str(ms2.get("material_id")) != PARENT_MATERIAL_ID:
        raise MigrationError(f"Precondition failed: ms2 material_id '{ms2.get('material_id')}' != '{PARENT_MATERIAL_ID}'.")
    if ms2.get("movement_type") != "adjustment_in":
        raise MigrationError(f"Precondition failed: ms2 movement_type '{ms2.get('movement_type')}' != 'adjustment_in'.")
    if float(ms2.get("quantity_delta") or 0) != 18.0:
        raise MigrationError(f"Precondition failed: ms2 quantity_delta {ms2.get('quantity_delta')} != 18.0.")

    # Check idempotency state
    units = [
        sf1.get("stock_unit"),
        sf2.get("stock_unit"),
        ms1.get("unit"),
        ms2.get("unit")
    ]

    all_lembar = all(u == "lembar" for u in units)
    all_pcs = all(u == "pcs" for u in units)

    if all_lembar:
        return {"status": "ALREADY_COMPLETED", "sf1": sf1, "sf2": sf2, "ms1": ms1, "ms2": ms2}
    elif all_pcs:
        return {"status": "READY_FOR_MIGRATION", "sf1": sf1, "sf2": sf2, "ms1": ms1, "ms2": ms2}
    else:
        raise MigrationError(
            f"Precondition failed: Inconsistent/partial unit state detected across targets: {units}. "
            "Manual human inspection required. Aborting."
        )


def verify_index_and_collision(db: Any) -> None:
    """Verifies uniq_stock_form_spec and checks that target keys in 'lembar' are not taken."""
    # 1. Verify index exists
    indexes = db.stock_forms.index_information()
    if "uniq_stock_form_spec" not in indexes:
        raise MigrationError("Unique index 'uniq_stock_form_spec' is missing from 'stock_forms'.")
    if not indexes["uniq_stock_form_spec"].get("unique"):
        raise MigrationError("Index 'uniq_stock_form_spec' is not marked unique.")

    # 2. Collision check for Rak 60x20 (lembar)
    col1 = db.stock_forms.find_one({
        "_id": {"$ne": ObjectId(TARGET_SF1_ID)},
        "material_id": PARENT_MATERIAL_ID,
        "form_type": "standard",
        "width": 20.0,
        "length": 60.0,
        "thickness": 1.6,
        "dimension_unit": "cm",
        "stock_unit": "lembar",
        "label": "Rak 60x20"
    })
    if col1:
        raise MigrationError(
            f"Collision detected! Existing stock_form '{col1.get('_id')}' already holds target key for Rak 60x20 (lembar)."
        )

    # 3. Collision check for Rak 80x20 (lembar)
    col2 = db.stock_forms.find_one({
        "_id": {"$ne": ObjectId(TARGET_SF2_ID)},
        "material_id": PARENT_MATERIAL_ID,
        "form_type": "standard",
        "width": 20.0,
        "length": 80.0,
        "thickness": 1.6,
        "dimension_unit": "cm",
        "stock_unit": "lembar",
        "label": "Rak 80x20"
    })
    if col2:
        raise MigrationError(
            f"Collision detected! Existing stock_form '{col2.get('_id')}' already holds target key for Rak 80x20 (lembar)."
        )


def verify_invariants_and_global(db: Any, session: Any = None) -> None:
    """Verifies quantities, dimensions, referential integrity, and global consistency."""
    kw = {"session": session} if session else {}

    sf1 = db.stock_forms.find_one({"_id": ObjectId(TARGET_SF1_ID)}, **kw)
    sf2 = db.stock_forms.find_one({"_id": ObjectId(TARGET_SF2_ID)}, **kw)
    ms1 = db.material_stocks.find_one({"_id": ObjectId(TARGET_MS1_ID)}, **kw)
    ms2 = db.material_stocks.find_one({"_id": ObjectId(TARGET_MS2_ID)}, **kw)

    if sf1.get("stock_unit") != "lembar" or sf1.get("current_quantity") != 24.0:
        raise MigrationError(f"Invariant check failed for sf1: unit={sf1.get('stock_unit')}, qty={sf1.get('current_quantity')}")
    if sf2.get("stock_unit") != "lembar" or sf2.get("current_quantity") != 18.0:
        raise MigrationError(f"Invariant check failed for sf2: unit={sf2.get('stock_unit')}, qty={sf2.get('current_quantity')}")
    if ms1.get("unit") != "lembar" or ms1.get("quantity_delta") != 24.0:
        raise MigrationError(f"Invariant check failed for ms1: unit={ms1.get('unit')}, delta={ms1.get('quantity_delta')}")
    if ms2.get("unit") != "lembar" or ms2.get("quantity_delta") != 18.0:
        raise MigrationError(f"Invariant check failed for ms2: unit={ms2.get('unit')}, delta={ms2.get('quantity_delta')}")

    # Check global unit consistency across all stock forms
    for sf in db.stock_forms.find({}, **kw):
        mat = db.materials.find_one({"_id": ObjectId(sf["material_id"])}, **kw)
        if mat and sf.get("stock_unit") != mat.get("unit"):
            raise MigrationError(
                f"Global consistency check failed: Stock Form '{sf.get('_id')}' ({sf.get('label')}) "
                f"has unit '{sf.get('stock_unit')}' which does not match parent unit '{mat.get('unit')}'."
            )


def execute_migration(
    client: Any,
    db: Any,
    dry_run: bool = True
) -> Dict[str, Any]:
    """Executes or dry-runs the legacy inventory unit migration."""
    print("=" * 70)
    print("CONTROLLED MIGRATION: LEGACY INVENTORY UNIT NORMALIZATION")
    print("=" * 70)
    print(f"Mode               : {'DRY RUN (No writes)' if dry_run else 'LOCAL TRANSACTIONAL EXECUTION'}")
    print(f"Target Material    : BlockBoard ({PARENT_MATERIAL_ID})")
    print(f"Target Stock Forms : {APPROVED_STOCK_FORM_TARGETS}")
    print(f"Target Movements   : {APPROVED_MATERIAL_STOCK_TARGETS}")

    # 1. Environment Safety Guard
    check_production_guard()

    # 2. Record Initial Document Counts
    counts_before = {
        "materials": db.materials.count_documents({}),
        "stock_forms": db.stock_forms.count_documents({}),
        "material_stocks": db.material_stocks.count_documents({}),
        "stock_transformations": db.stock_transformations.count_documents({}),
        "material_purchases": db.material_purchases.count_documents({}),
    }

    # 3. Preconditions Check
    precond_result = verify_preconditions(db)
    if precond_result["status"] == "ALREADY_COMPLETED":
        print("\n[PRECHECK] Target documents are ALREADY normalized to 'lembar'.")
        print("MIGRATION ALREADY COMPLETE — NO-OP.")
        return {
            "ok": True,
            "action": "already_completed",
            "writes_executed": 0,
            "dry_run": dry_run
        }

    # 4. Unique Index and Collision Check
    verify_index_and_collision(db)
    print("\n[PRECHECK] Preconditions: PASS | Unique Index & Collisions: PASS (0 collisions)")

    # 5. Capture Snapshot
    snapshot = capture_snapshot(db)
    print(f"[SNAPSHOT] Captured before-state for 4 target documents at {snapshot['timestamp']}.")

    # 6. Display Proposed Changes
    print("\nPROPOSED MUTATIONS:")
    print(f"  1. stock_forms[{TARGET_SF1_ID}] (Rak 60x20)    : stock_unit: 'pcs' -> 'lembar' (qty remains 24.0)")
    print(f"  2. stock_forms[{TARGET_SF2_ID}] (Rak 80x20)    : stock_unit: 'pcs' -> 'lembar' (qty remains 18.0)")
    print(f"  3. material_stocks[{TARGET_MS1_ID}] (ST-0003)    : unit: 'pcs' -> 'lembar' (delta remains +24.0)")
    print(f"  4. material_stocks[{TARGET_MS2_ID}] (ST-0024)    : unit: 'pcs' -> 'lembar' (delta remains +18.0)")

    if dry_run:
        print("\n[DRY-RUN RESULT] All preflight checks passed. 0 writes executed.")
        return {
            "ok": True,
            "action": "dry_run_passed",
            "planned_mutations": 4,
            "writes_executed": 0,
            "dry_run": True
        }

    # 7. Multi-Document Transaction Execution
    print("\n[EXECUTION] Starting MongoDB multi-document ACID transaction...")
    now_iso = datetime.now(timezone.utc).isoformat()

    with client.start_session() as session:
        with session.start_transaction():
            # Update 1: sf1
            res_sf1 = db.stock_forms.update_one(
                {"_id": ObjectId(TARGET_SF1_ID), "stock_unit": "pcs"},
                {"$set": {"stock_unit": "lembar", "updated_at": now_iso}},
                session=session
            )
            if res_sf1.matched_count != 1 or res_sf1.modified_count != 1:
                session.abort_transaction()
                raise MigrationError(f"Update failed for sf1: matched={res_sf1.matched_count}, modified={res_sf1.modified_count}")

            # Update 2: sf2
            res_sf2 = db.stock_forms.update_one(
                {"_id": ObjectId(TARGET_SF2_ID), "stock_unit": "pcs"},
                {"$set": {"stock_unit": "lembar", "updated_at": now_iso}},
                session=session
            )
            if res_sf2.matched_count != 1 or res_sf2.modified_count != 1:
                session.abort_transaction()
                raise MigrationError(f"Update failed for sf2: matched={res_sf2.matched_count}, modified={res_sf2.modified_count}")

            # Update 3: ms1
            res_ms1 = db.material_stocks.update_one(
                {"_id": ObjectId(TARGET_MS1_ID), "unit": "pcs"},
                {"$set": {"unit": "lembar"}},
                session=session
            )
            if res_ms1.matched_count != 1 or res_ms1.modified_count != 1:
                session.abort_transaction()
                raise MigrationError(f"Update failed for ms1: matched={res_ms1.matched_count}, modified={res_ms1.modified_count}")

            # Update 4: ms2
            res_ms2 = db.material_stocks.update_one(
                {"_id": ObjectId(TARGET_MS2_ID), "unit": "pcs"},
                {"$set": {"unit": "lembar"}},
                session=session
            )
            if res_ms2.matched_count != 1 or res_ms2.modified_count != 1:
                session.abort_transaction()
                raise MigrationError(f"Update failed for ms2: matched={res_ms2.matched_count}, modified={res_ms2.modified_count}")

            # Verify inside transaction before commit
            verify_invariants_and_global(db, session=session)

    # 8. Post-Commit Verification
    counts_after = {
        "materials": db.materials.count_documents({}),
        "stock_forms": db.stock_forms.count_documents({}),
        "material_stocks": db.material_stocks.count_documents({}),
        "stock_transformations": db.stock_transformations.count_documents({}),
        "material_purchases": db.material_purchases.count_documents({}),
    }
    if counts_before != counts_after:
        raise MigrationError(f"Document count mismatch after commit! Before={counts_before}, After={counts_after}")

    verify_invariants_and_global(db)

    print("\n[SUCCESS] Transaction committed successfully. 4 documents updated.")
    print("Invariants verified: quantities intact, document counts unchanged, global mismatch count = 0.")
    return {
        "ok": True,
        "action": "migrated_successfully",
        "writes_executed": 4,
        "dry_run": False
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Local-only Controlled Migration for Legacy Inventory Units")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Perform dry-run only (default)")
    parser.add_argument("--execute", action="store_true", help="Execute local migration in multi-document transaction")
    parser.add_argument("--db-name", type=str, default="test", help="Target test database name")
    parser.add_argument("--mongo-url", type=str, default=None, help="Target test MongoDB connection URL")

    args = parser.parse_args()
    is_execute = args.execute
    dry_run = not is_execute

    mongo_url = args.mongo_url or os.environ.get("MONGO_URL") or os.environ.get("MONGODB_URI")
    if not mongo_url:
        print("ERROR: MONGO_URL or --mongo-url is required.")
        return 1

    client = MongoClient(mongo_url)
    db = client[args.db_name]

    try:
        res = execute_migration(client, db, dry_run=dry_run)
        return 0 if res.get("ok") else 1
    except MigrationError as me:
        print(f"\nMIGRATION ABORTED: {me}")
        return 1
    except Exception as exc:
        print(f"\nUNEXPECTED FAILURE: {exc}")
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
