#!/usr/bin/env python3
"""CLI Tool: Index Provisioning and Verification for Sogil Furniture.

Usage:
    # 1. Read-only verification of existing indexes against specifications
    python scripts/provision_indexes.py --verify

    # 2. Dry-run inspection (generates plan and checks for duplicates, 0 writes)
    python scripts/provision_indexes.py --dry-run

    # 3. Apply missing indexes safely (requires isolated test/dev database target)
    python scripts/provision_indexes.py --apply --uri "mongodb://127.0.0.1:27099" --db-name "sogil_test_disposable"
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
import json

# Ensure repo root and backend are on sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"

for p in [str(REPO_ROOT), str(BACKEND_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from motor.motor_asyncio import AsyncIOMotorClient
import certifi

from backend.index_provisioner import (
    REQUIRED_INDEX_SPECS,
    verify_required_indexes,
    provision_indexes,
    format_duplicate_report,
    CriticalFinanceIndexError,
    DuplicateRecordError,
)
from backend.tests.isolation_guard import (
    validate_test_database_isolation,
    sanitize_uri_for_logging,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Sogil Furniture Index Provisioning & Verification CLI"
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--verify",
        action="store_true",
        help="Run read-only verification of required indexes without any changes.",
    )
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Generate an index creation plan and perform duplicate checks without writing (default).",
    )
    mode_group.add_argument(
        "--apply",
        action="store_true",
        help="Apply missing indexes to the database (enforces isolation guard).",
    )

    parser.add_argument(
        "--uri",
        type=str,
        default=os.environ.get("MONGO_URL", ""),
        help="Target MongoDB connection URI (default: MONGO_URL env var).",
    )
    parser.add_argument(
        "--db-name",
        type=str,
        default=os.environ.get("DB_NAME", ""),
        help="Target MongoDB database name (default: DB_NAME env var).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format.",
    )
    return parser.parse_args()


async def main_async():
    args = parse_args()

    uri = args.uri.strip()
    db_name = args.db_name.strip()

    if not uri or not db_name:
        print("ERROR: Both --uri (or MONGO_URL) and --db-name (or DB_NAME) must be specified.", file=sys.stderr)
        sys.exit(1)

    is_apply = args.apply
    is_verify = args.verify
    is_dry_run = not is_apply and not is_verify

    # Guard: apply mode requires isolation validation
    if is_apply:
        try:
            validate_test_database_isolation(uri, db_name)
        except ValueError as val_err:
            print(f"SECURITY HALT: {val_err}", file=sys.stderr)
            sys.exit(2)

    sanitized_uri = sanitize_uri_for_logging(uri)
    print(f"Connecting to: {sanitized_uri} [DB: {db_name}]")

    client_kwargs = {"serverSelectionTimeoutMS": 5000}
    if "ssl=true" in uri.lower() or "tls=true" in uri.lower() or uri.startswith("mongodb+srv://"):
        client_kwargs["tlsCAFile"] = certifi.where()
    client = AsyncIOMotorClient(uri, **client_kwargs)
    db = client[db_name]

    try:
        if is_verify:
            print("Running index verification...")
            res = await verify_required_indexes(db, specs=REQUIRED_INDEX_SPECS, fail_closed=False)
            if args.json:
                print(json.dumps({
                    "valid": res["valid"],
                    "verified_count": len(res["verified"]),
                    "missing_count": len(res["missing"]),
                    "incompatible_count": len(res["incompatible"]),
                    "missing": [m["spec"].name for m in res["missing"]],
                    "incompatible": [i["spec"].name for i in res["incompatible"]],
                }, indent=2))
            else:
                print(f"Status: {'VALID' if res['valid'] else 'INVALID'}")
                print(f"Verified: {len(res['verified'])}/{len(REQUIRED_INDEX_SPECS)}")
                if res["missing"]:
                    print(f"Missing indexes ({len(res['missing'])}):")
                    for m in res["missing"]:
                        print(f"  - [{m['collection']}] {m['spec'].name} ({m['spec'].category})")
                if res["incompatible"]:
                    print(f"Incompatible indexes ({len(res['incompatible'])}):")
                    for inc in res["incompatible"]:
                        print(f"  - [{inc['collection']}] {inc['spec'].name}: {inc['reason']}")

            if not res["valid"]:
                sys.exit(1)

        elif is_dry_run:
            print("Running index provisioning in DRY-RUN mode (zero database writes)...")
            res = await provision_indexes(
                db,
                specs=REQUIRED_INDEX_SPECS,
                dry_run=True,
                fail_closed=False,
            )
            if args.json:
                print(json.dumps(res, indent=2))
            else:
                print(f"Plan Status: {res['status']}")
                print(f"Verified: {res['verified_count']}")
                print(f"Missing: {res['missing_count']}")
                print(f"Incompatible: {res['incompatible_count']}")
                print(f"Planned Creations ({len(res['planned_creations'])}):")
                for name in res["planned_creations"]:
                    print(f"  + {name}")
                if res["duplicates_detected"]:
                    print(f"WARNING: Duplicates detected for {len(res['duplicates_detected'])} index(es)!")
                    for idx_name, dups in res["duplicates_detected"].items():
                        print(f"  - {idx_name}: {len(dups)} conflict(s)")

        elif is_apply:
            print("Applying indexes with duplicate preflight checks...")
            res = await provision_indexes(
                db,
                specs=REQUIRED_INDEX_SPECS,
                dry_run=False,
                target_uri=uri,
                db_name=db_name,
                fail_closed=True,
            )
            if args.json:
                print(json.dumps(res, indent=2))
            else:
                print(f"Provisioning Status: {res['status']}")
                print(f"Completed ({len(res['completed'])}):")
                for name in res["completed"]:
                    print(f"  ✓ {name}")
                if res["failed"]:
                    print(f"Failed ({len(res['failed'])}):", file=sys.stderr)
                    for f in res["failed"]:
                        print(f"  ✗ {f['spec'].name}: {f['error']}", file=sys.stderr)
                    sys.exit(1)

    except DuplicateRecordError as dup_err:
        print(f"\nPREFLIGHT DUPLICATE ERROR:\n{dup_err}", file=sys.stderr)
        sys.exit(3)
    except CriticalFinanceIndexError as crit_err:
        print(f"\nCRITICAL INDEX ERROR:\n{crit_err}", file=sys.stderr)
        sys.exit(4)
    finally:
        client.close()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
