#!/usr/bin/env python3
"""Explicit Operator Migration Script: Material Stocks Purchase Idempotency Index.

Migrates 'uniq_purchase_stock_movement' on collection 'material_stocks'
from legacy sparse=True to partialFilterExpression={"related_purchase_id": {"$type": "string"}}.

SAFETY RULES:
1. NEVER executes automatically on application startup or Railway build.
2. Operator must explicitly execute this script with proper MongoDB connection environment.
3. Contains NO hardcoded production credentials. Reads MONGO_URL and DB_NAME from environment.
4. Performs PREFLIGHT VERIFICATION:
   - Verifies the collection exists.
   - Verifies the existing index is indeed the legacy index ('uniq_purchase_stock_movement').
   - Checks for any duplicate genuine purchase movements ({related_purchase_id: <str>, movement_type: <str>}).
     If duplicates are found, ABORTS WITHOUT DROPPING to protect data integrity.
5. Performs controlled replacement:
   - Drops only 'uniq_purchase_stock_movement'.
   - Recreates with exact partialFilterExpression.
   - Verifies the newly created index.
"""
import os
import sys
import asyncio
from typing import Dict, Any, List

import pymongo
from motor.motor_asyncio import AsyncIOMotorClient


async def run_migration(dry_run: bool = False, client: Any = None, db_name: str = None) -> Dict[str, Any]:
    """Executes or plans the index migration."""
    mongo_url = os.environ.get("MONGO_URL") or os.environ.get("MONGODB_URI")
    database_name = db_name or os.environ.get("DB_NAME", "sogil_furniture")

    close_client = False
    if client is None:
        if not mongo_url:
            print("ERROR: MONGO_URL or MONGODB_URI environment variable is required.")
            return {"ok": False, "error": "Missing MONGO_URL/MONGODB_URI environment variable"}
        client = AsyncIOMotorClient(mongo_url)
        close_client = True

    try:
        db = client[database_name]
        coll = db.material_stocks

        print("=" * 60)
        print("SOGIL FURNITURE — INDEX MIGRATION PREFLIGHT CHECK")
        print("=" * 60)
        print(f"Target Database  : {database_name}")
        print(f"Target Collection: material_stocks")
        print(f"Target Index     : uniq_purchase_stock_movement")
        print(f"Execution Mode   : {'DRY RUN (No changes)' if dry_run else 'LIVE MIGRATION'}")

        # 1. Inspect existing indexes
        indexes = await coll.index_information()
        print(f"\n[1/4] Inspecting existing indexes on material_stocks...")
        for name, spec in indexes.items():
            print(f"  - {name}: keys={spec.get('key')}, unique={spec.get('unique', False)}, sparse={spec.get('sparse', False)}, partial={spec.get('partialFilterExpression')}")

        if "uniq_purchase_stock_movement" not in indexes:
            print("\nTarget index 'uniq_purchase_stock_movement' does not exist.")
            if dry_run:
                print("In live run, index would be created fresh with partialFilterExpression.")
                return {"ok": True, "action": "create_fresh", "dry_run": True}
            print("Creating index with partialFilterExpression...")
            await coll.create_index(
                [("related_purchase_id", 1), ("movement_type", 1)],
                unique=True,
                partialFilterExpression={"related_purchase_id": {"$type": "string"}},
                name="uniq_purchase_stock_movement"
            )
            print("SUCCESS: Index created fresh.")
            return {"ok": True, "action": "created_fresh"}

        existing_def = indexes["uniq_purchase_stock_movement"]
        existing_keys = existing_def.get("key", [])
        expected_keys = [("related_purchase_id", 1), ("movement_type", 1)]

        if list(existing_keys) != expected_keys:
            print(f"\nABORT: Unexpected keys on 'uniq_purchase_stock_movement': {existing_keys} (expected {expected_keys})")
            return {"ok": False, "error": f"Unexpected keys: {existing_keys}"}

        # Check if already migrated
        if existing_def.get("partialFilterExpression") == {"related_purchase_id": {"$type": "string"}} and not existing_def.get("sparse"):
            print("\nIndex is ALREADY migrated to partialFilterExpression. No action required.")
            return {"ok": True, "action": "already_migrated"}

        is_legacy_sparse = existing_def.get("sparse", False) or not existing_def.get("partialFilterExpression")
        if not is_legacy_sparse:
            print(f"\nABORT: Index exists with unrecognized definition: {existing_def}")
            return {"ok": False, "error": f"Unrecognized definition: {existing_def}"}

        print("\n[2/4] Legacy index confirmed: sparse=True or missing partialFilterExpression.")

        # 2. Preflight duplicate check for genuine purchase movements
        print("\n[3/4] Running preflight check: Scanning for duplicate genuine purchase movements...")
        pipeline: List[Dict[str, Any]] = [
            {"$match": {"related_purchase_id": {"$type": "string"}, "movement_type": {"$exists": True}}},
            {"$group": {
                "_id": {"related_purchase_id": "$related_purchase_id", "movement_type": "$movement_type"},
                "count": {"$sum": 1},
                "movement_numbers": {"$push": "$movement_number"}
            }},
            {"$match": {"count": {"$gt": 1}}}
        ]
        duplicates_cursor = coll.aggregate(pipeline)
        duplicates = await duplicates_cursor.to_list(100)

        if duplicates:
            print("\nABORT: Duplicate genuine purchase movements detected in database!")
            for d in duplicates:
                print(f"  Conflict: related_purchase_id={d['_id']['related_purchase_id']}, movement_type={d['_id']['movement_type']}, count={d['count']}, numbers={d.get('movement_numbers')}")
            print("\nCANNOT PROCEED. Existing data violates the unique constraint.")
            print("Resolve historical duplicates before running this migration.")
            return {"ok": False, "error": "Duplicate purchase movements detected", "duplicates": duplicates}

        print("Preflight check passed: Zero duplicate genuine purchase movements found.")

        # 3. Migration Action
        if dry_run:
            print("\n[4/4] DRY RUN COMPLETE: Safe to proceed with live migration.")
            print("Planned steps:")
            print("  1. coll.drop_index('uniq_purchase_stock_movement')")
            print("  2. coll.create_index([('related_purchase_id', 1), ('movement_type', 1)], unique=True, partialFilterExpression={'related_purchase_id': {'$type': 'string'}}, name='uniq_purchase_stock_movement')")
            return {"ok": True, "action": "dry_run_passed"}

        print("\n[4/4] Executing migration...")
        print("Dropping legacy index 'uniq_purchase_stock_movement'...")
        await coll.drop_index("uniq_purchase_stock_movement")

        print("Creating replacement index with partialFilterExpression...")
        await coll.create_index(
            [("related_purchase_id", 1), ("movement_type", 1)],
            unique=True,
            partialFilterExpression={"related_purchase_id": {"$type": "string"}},
            name="uniq_purchase_stock_movement"
        )

        # Verify
        new_indexes = await coll.index_information()
        new_def = new_indexes.get("uniq_purchase_stock_movement", {})
        print("\nVerification:")
        print(f"  New index name: uniq_purchase_stock_movement")
        print(f"  Keys          : {new_def.get('key')}")
        print(f"  Unique        : {new_def.get('unique')}")
        print(f"  Sparse        : {new_def.get('sparse', False)}")
        print(f"  Partial Filter: {new_def.get('partialFilterExpression')}")

        if new_def.get("partialFilterExpression") == {"related_purchase_id": {"$type": "string"}}:
            print("\nSUCCESS: Migration completed and verified.")
            return {"ok": True, "action": "migrated_successfully"}
        else:
            print("\nWARNING: Recreated index does not match expected partialFilterExpression.")
            return {"ok": False, "error": "Index definition mismatch after recreation"}

    finally:
        if close_client:
            client.close()


if __name__ == "__main__":
    is_dry = "--dry-run" in sys.argv
    res = asyncio.run(run_migration(dry_run=is_dry))
    if not res.get("ok"):
        sys.exit(1)
    sys.exit(0)
