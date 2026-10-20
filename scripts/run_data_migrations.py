#!/usr/bin/env python3
"""CLI Tool: Explicit Data Migrations for Sogil Furniture.

Usage:
    # 1. List all available migrations and status
    python scripts/run_data_migrations.py --list

    # 2. Preview a migration without database writes
    python scripts/run_data_migrations.py --dry-run --migration migration_custom_category_product_rename_v1

    # 3. Apply an explicit migration safely (requires test/staging target isolation)
    python scripts/run_data_migrations.py --apply --migration migration_custom_category_product_rename_v1 \
        --uri "mongodb://127.0.0.1:27101,127.0.0.1:27102,127.0.0.1:27103/?replicaSet=sogil-staging-rs" \
        --db-name "sogil_test_disposable"
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
import json

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"

for p in [str(REPO_ROOT), str(BACKEND_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from motor.motor_asyncio import AsyncIOMotorClient
import certifi

from backend.data_migrations import (
    MIGRATIONS,
    MigrationConcurrencyError,
    MigrationTransactionRequiredError,
    list_available_migrations,
    execute_data_migration,
)
from backend.tests.isolation_guard import (
    validate_test_database_isolation,
    sanitize_uri_for_logging,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Sogil Furniture Explicit Data Migrations CLI"
    )
    action_group = parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument(
        "--list",
        action="store_true",
        help="List all registered data migrations and application status.",
    )
    action_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes that would be made without database writes.",
    )
    action_group.add_argument(
        "--apply",
        action="store_true",
        help="Apply data migration (enforces database isolation guard).",
    )

    parser.add_argument(
        "--migration",
        type=str,
        default="",
        help=f"Target migration ID. Available: {', '.join(MIGRATIONS.keys())}",
    )
    parser.add_argument(
        "--uri",
        type=str,
        default=os.environ.get("MONGO_URL", ""),
        help="Target MongoDB connection URI.",
    )
    parser.add_argument(
        "--db-name",
        type=str,
        default=os.environ.get("DB_NAME", ""),
        help="Target MongoDB database name.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format.",
    )
    return parser.parse_args()


async def main_async():
    args = parse_args()
    uri = args.uri.strip()
    db_name = args.db_name.strip()

    if args.list and (not uri or not db_name):
        print("\nRegistered Data Migrations:")
        for mid, meta in MIGRATIONS.items():
            spec = meta["spec"]
            print(f"  - [{mid}] {spec.description}")
            print(f"      Target collections: {spec.target_collections}")
        sys.exit(0)

    if not uri or not db_name:
        print("ERROR: Both --uri (or MONGO_URL) and --db-name (or DB_NAME) must be specified for --dry-run or --apply.", file=sys.stderr)
        sys.exit(1)

    if args.apply:
        try:
            validate_test_database_isolation(uri, db_name)
        except ValueError as val_err:
            print(f"SECURITY HALT: {val_err}", file=sys.stderr)
            sys.exit(2)

    sanitized = sanitize_uri_for_logging(uri)
    print(f"Connecting to: {sanitized} [DB: {db_name}]")

    client_kwargs = {"serverSelectionTimeoutMS": 5000}
    if "ssl=true" in uri.lower() or "tls=true" in uri.lower() or uri.startswith("mongodb+srv://"):
        client_kwargs["tlsCAFile"] = certifi.where()
    client = AsyncIOMotorClient(uri, **client_kwargs)
    db = client[db_name]

    try:
        if args.list:
            migrations = await list_available_migrations(db)
            if args.json:
                print(json.dumps(migrations, indent=2))
            else:
                print("\nRegistered Data Migrations:")
                for m in migrations:
                    status = f"APPLIED ({m['applied_at']})" if m['applied'] else "PENDING"
                    print(f"  - [{m['migration_id']}] {m['description']}")
                    print(f"      Status: {status} | Target collections: {m['target_collections']}")
            sys.exit(0)

        mid = args.migration.strip()
        if not mid:
            print("ERROR: --migration <id> must be specified for --dry-run or --apply.", file=sys.stderr)
            print(f"Available: {', '.join(MIGRATIONS.keys())}", file=sys.stderr)
            sys.exit(1)

        if mid not in MIGRATIONS:
            print(f"ERROR: Unknown migration '{mid}'. Available: {', '.join(MIGRATIONS.keys())}", file=sys.stderr)
            sys.exit(1)

        is_dry_run = not args.apply
        res = await execute_data_migration(
            db,
            migration_id=mid,
            dry_run=is_dry_run,
            target_uri=uri if args.apply else None,
            db_name=db_name if args.apply else None,
        )

        if args.json:
            print(json.dumps(res, indent=2))
        else:
            mode_str = "DRY-RUN (zero writes)" if is_dry_run else "APPLIED"
            print(f"\nMigration Result [{mid}] - {mode_str}:")
            for k, v in res.items():
                print(f"  {k}: {v}")

    except MigrationConcurrencyError as mce:
        print(f"CONCURRENCY HALT: {mce}", file=sys.stderr)
        sys.exit(3)
    except MigrationTransactionRequiredError as mte:
        print(f"TRANSACTION CAPABILITY HALT: {mte}", file=sys.stderr)
        sys.exit(4)
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main_async())
