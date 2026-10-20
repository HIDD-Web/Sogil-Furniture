"""Global Test Configuration & Safety Harness for Sogil Furniture.

SAFETY & ISOLATION ENFORCEMENT:
1. Intercepts environment configuration BEFORE server.py is imported or loads backend/.env.
2. Prevents any accidental connection to MongoDB Atlas or production clusters.
3. Automatically skips real replica-set tests when TEST_MONGO_REPLICA_SET_URI is not provided.
4. Drops disposable test databases on teardown.
"""

import os
import sys
from pathlib import Path
import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from unittest.mock import AsyncMock, MagicMock

# Ensure backend directory and repo root are on sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
for p in (str(BACKEND_DIR), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from backend.tests.isolation_guard import (
    validate_test_database_isolation,
    sanitize_uri_for_logging,
)

# Intercept and set safe test environment variables before anything else loads
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("INDEX_PROVISIONING_MODE", "auto")
os.environ.setdefault("STARTUP_DATA_MODE", "seed")
TEST_URI = os.environ.get("TEST_MONGO_REPLICA_SET_URI", "").strip()
TEST_DB_NAME = os.environ.get("TEST_MONGO_DB_NAME", "sogil_test_disposable_replica").strip()

if not TEST_URI:
    # Set dummy local fallback so that importing server.py never reads backend/.env for Atlas
    os.environ["MONGO_URL"] = "mongodb://127.0.0.1:27017/sogil_test_disposable_guard"
    os.environ["DB_NAME"] = "sogil_test_disposable_guard"
    os.environ["JWT_SECRET"] = "test_jwt_secret_for_isolation_guard_only"
    IS_REPLICA_SET_CONFIGURED = False
else:
    # If a real test replica set URI is supplied, validate it immediately
    validate_test_database_isolation(TEST_URI, TEST_DB_NAME)
    os.environ["MONGO_URL"] = TEST_URI
    os.environ["DB_NAME"] = TEST_DB_NAME
    os.environ["JWT_SECRET"] = os.environ.get("JWT_SECRET", "test_jwt_secret_for_isolation_guard_only")
    IS_REPLICA_SET_CONFIGURED = True


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="function")
async def real_replica_set_env():
    """Provisions a disposable database on a verified MongoDB replica set.
    Fails closed or skips cleanly if the replica set is not available.
    """
    if not IS_REPLICA_SET_CONFIGURED:
        pytest.skip(
            "BLOCKED BY ENVIRONMENT: TEST_MONGO_REPLICA_SET_URI not configured. "
            "Isolated MongoDB replica-set engine required for real transaction tests."
        )

    import uuid
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "local")
    test_db_name = f"sogil_test_disp_{worker_id}_{uuid.uuid4().hex[:8]}"
    validate_test_database_isolation(TEST_URI, test_db_name)

    client = AsyncIOMotorClient(TEST_URI, serverSelectionTimeoutMS=3000)

    try:
        hello_res = await client.admin.command("hello")
    except Exception as conn_err:
        client.close()
        pytest.fail(f"Failed to connect to TEST_MONGO_REPLICA_SET_URI: {conn_err}")

    set_name = hello_res.get("setName")
    if not set_name:
        client.close()
        pytest.fail(
            "BLOCKED: Target MongoDB instance is a standalone server (setName is None). "
            "MongoDB multi-document transactions strictly require a replica set."
        )

    db = client[test_db_name]

    # Pre-create standard collections for transaction compatibility
    for col_name in [
        "work_assignments",
        "wage_obligations",
        "wage_settlements",
        "finance_transactions",
        "assignment_groups",
        "item_instances",
        "outbox_events",
        "audit_logs",
    ]:
        try:
            await db.create_collection(col_name)
        except Exception:
            pass

    try:
        yield client, db
    finally:
        # Automatic clean teardown of disposable test database
        try:
            await client.drop_database(test_db_name)
        except Exception:
            pass
        client.close()


@pytest.fixture(scope="function")
def mock_db():
    """Provides a synthetic mock database for unit tests."""
    mdb = MagicMock()
    mdb.work_assignments = MagicMock()
    mdb.wage_obligations = MagicMock()
    mdb.wage_settlements = MagicMock()
    mdb.finance_transactions = MagicMock()
    mdb.assignment_groups = MagicMock()
    mdb.item_instances = MagicMock()
    mdb.outbox_events = MagicMock()
    mdb.audit_logs = MagicMock()
    return mdb
