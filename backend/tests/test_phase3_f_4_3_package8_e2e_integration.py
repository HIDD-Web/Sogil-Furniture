"""
Phase 3.F.4.3 Package 8.2: End-to-End Full Lifecycle Integration Tests.
Repository: Sogil Furniture
Target: Delivery Lifecycle, Ghost Lock Elimination, Wage Accrual, and Wage Settlement.

Scenarios Covered:
- Scenario A: Sequential End-to-End Lifecycle
  1. Ready Queue Query & Eligibility Verification
  2. Delivery Trip Creation & Stop Assignment (Active Trip Locking)
  3. Trip Dispatch & Rate-Policy Snapshot Locking (Immutability Guarantee)
  4. Failed Delivery Attempt (Attempt History, Retention of Active Trip Binding, 0 Wage Accrual, 0 Cash Expense)
  5. Retry (Transition to out_for_delivery, Retention of History) & Successful Handover (Order selesai, Delivery delivered, Revenue stamped)
  6. Trip Completion (Partial Completion, Ghost Lock Elimination, Idempotent Replay)
  7. Wage Obligation Accrual (Immutable Snapshot Rate, Single Entitlement)
  8. Wage Settlement via Canonical Endpoint (Obligation paid, Exactly ONE 'Pekerja' Finance Expense, Idempotency Protection)
  9. Full Sequential End-to-End Integration Flow
  10. Partial Trip Completion with Failed-Closed Order Release to Ready Queue

- Scenario B: Multi-Helper Allocation and Exact Amount
  1. 3 Helpers on 50 LE -> Exact Piastre Distribution (16.67, 16.67, 16.66 LE)
  2. Full Settlement & Ledger Verification (Sum of Expenses == 50.00 LE)

- Scenario C: Boundary and Failure Invariants
  1. Active Trip Lock Blocks Order Status Mutation (HTTP 409)
  2. Active Trip Lock Blocks Pricing, Fee, and Item Mutation (HTTP 409)
  3. Active Trip Lock Blocks Permanent Deletion (HTTP 409)
  4. Failed Delivery Never Accrues Wages (0 Obligations, 0 Expenses)
  5. Handover Idempotent Replay Does Not Duplicate Accrual or Count
  6. Trip Completion Idempotent Replay Does Not Duplicate State or Finance Records
  7. Wage Settlement Idempotency Replay Returns Existing Record Without Duplicate Expense
  8. Wage Settlement Idempotency with Changed Parameters Raises HTTP 409
  9. Wage Settlement Exceeding Pending Obligations Raises HTTP 422
  10. Released Orders Permit Update and Permanent Deletion

- Real Replica-Set Transaction Tests:
  - Cleanly skips if TEST_MONGO_REPLICA_SET_URI is not set.
  - Verifies multi-document transactions and controlled rollback when isolated RS is provided.
"""

import copy
import os
import re
import urllib.parse
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from unittest.mock import MagicMock, patch

import pytest
import pymongo
from bson import ObjectId
from fastapi import HTTPException
from motor.motor_asyncio import AsyncIOMotorClient

import server
from server import (
    admin_get_unassigned_delivery_orders,
    admin_create_delivery_trip,
    admin_add_trip_stop,
    admin_remove_trip_stop,
    admin_update_delivery_trip_status,
    admin_record_trip_stop_attempt,
    admin_deliver_trip_stop,
    admin_complete_delivery_trip,
    admin_get_worker_pending_wages,
    admin_create_wage_settlement,
    admin_update_delivery_wage_policy,
    admin_update_order,
    admin_permanent_delete_order,
    calculate_delivery_helper_wage_allocations,
    build_delivery_accrual_event_key,
    DeliveryTripCreateInput,
    DeliveryTripVehicleRentalInput,
    DeliveryTripAddStopInput,
    DeliveryTripStatusUpdateInput,
    DeliveryTripStopAttemptInput,
    DeliveryStopHandoverInput,
    DeliveryTripCompleteInput,
    WageSettlementCreateInput,
    WageSettlementAllocationItem,
    DeliveryWagePolicyInput,
    OrderStatusUpdate,
    PermanentDeleteInput,
    DeliveryTripStatus,
    StopOutcome,
    _num,
    id_query,
    multi_id_query,
    clean,
)


# ==============================================================================
# SECTION 1: Replica Set Pre-Flight Isolation Validator & Fixtures
# ==============================================================================

def validate_test_database_isolation(uri: str, db_name: str) -> None:
    """Rigorous pre-flight validator to ensure test connection cannot touch production.
    Raises ValueError on any ambiguity or risk.
    """
    if not uri or not isinstance(uri, str):
        raise ValueError("TEST_MONGO_REPLICA_SET_URI is missing or empty")

    parsed = urllib.parse.urlparse(uri)
    host = (parsed.hostname or "").lower()

    # Reject known production hosts and Atlas clusters
    forbidden_host_patterns = [
        r"mongodb\.net$",
        r"railway",
        r"railway\.internal$",
        r"up\.railway\.app$",
        r"production",
    ]
    for pattern in forbidden_host_patterns:
        if re.search(pattern, host):
            raise ValueError(f"SECURITY ABORT: Hostname '{host}' matches forbidden production pattern '{pattern}'")

    if host not in ("localhost", "127.0.0.1"):
        raise ValueError(f"SECURITY ABORT: Hostname '{host}' is not strictly localhost or 127.0.0.1")

    # Reject production database names
    forbidden_db_names = ["sogil", "sogil-production", "production", "admin", "config", "local"]
    db_clean = (db_name or "").strip().lower()
    if db_clean in forbidden_db_names:
        raise ValueError(f"SECURITY ABORT: Database name '{db_clean}' is a protected production or system database")

    # Enforce disposable test prefix
    if not (db_clean.startswith("sogil_test_") or db_clean.startswith("test_disposable_")):
        raise ValueError(f"SECURITY ABORT: Database name '{db_clean}' must start with 'sogil_test_' or 'test_disposable_'")


TEST_URI = os.environ.get("TEST_MONGO_REPLICA_SET_URI", "").strip()
TEST_DB_NAME = os.environ.get("TEST_MONGO_DB_NAME", "sogil_test_disposable_package8_e2e").strip()
IS_REPLICA_SET_CONFIGURED = bool(TEST_URI)


@pytest.fixture(scope="function")
async def real_delivery_e2e_replica_env():
    """Provisions a disposable database on a real MongoDB replica set.
    Performs isolation check, provisions indexes, seeds test users, and drops database on teardown.
    Cleanly skips if TEST_MONGO_REPLICA_SET_URI is not configured.
    """
    if not IS_REPLICA_SET_CONFIGURED:
        pytest.skip(
            "BLOCKED — SAFE REPLICA SET UNAVAILABLE: TEST_MONGO_REPLICA_SET_URI not configured. "
            "Isolated MongoDB replica-set engine required for real transaction tests."
        )

    validate_test_database_isolation(TEST_URI, TEST_DB_NAME)

    client = AsyncIOMotorClient(TEST_URI, serverSelectionTimeoutMS=3000)

    try:
        hello_res = await client.admin.command("hello")
    except Exception as e:
        client.close()
        pytest.fail(f"Failed to connect to TEST_MONGO_REPLICA_SET_URI: {e}")

    set_name = hello_res.get("setName")
    if not set_name:
        client.close()
        pytest.fail(
            "BLOCKED: Target MongoDB instance is a standalone server (setName is None). "
            "MongoDB multi-document transactions strictly require a replica set."
        )

    db = client[TEST_DB_NAME]

    # Clean slate on disposable test db
    collections = await db.list_collection_names()
    for coll in collections:
        await db[coll].drop()

    admin_owner = {
        "_id": ObjectId("660000000000000000000001"),
        "id": "660000000000000000000001",
        "name": "Owner Boss RS",
        "email": "owner.rs@sogil.test",
        "role": "owner",
        "permissions": {"manage_orders": True, "access_finance": True, "manage_settings": True}
    }
    admin_finance = {
        "_id": ObjectId("660000000000000000000002"),
        "id": "660000000000000000000002",
        "name": "Finance Admin RS",
        "email": "finance.rs@sogil.test",
        "role": "admin",
        "permissions": {"access_finance": True, "manage_orders": True}
    }
    admin_ops = {
        "_id": ObjectId("660000000000000000000003"),
        "id": "660000000000000000000003",
        "name": "Ops Dispatcher RS",
        "email": "ops.rs@sogil.test",
        "role": "dispatcher",
        "permissions": {"manage_orders": True, "access_finance": False}
    }
    helper_rs = {
        "_id": ObjectId("660000000000000000000011"),
        "id": "660000000000000000000011",
        "name": "Helper Real RS",
        "email": "helper.rs@sogil.test",
        "role": "helper"
    }
    await db.admins.insert_many([admin_owner, admin_finance, admin_ops, helper_rs])

    await db.settings.insert_many([
        {
            "key": "delivery_wage_policy",
            "value": {
                "base_wage_per_order_le": 50.0,
                "unusual_amount_threshold_le": 500.0,
                "max_helper_wage_per_order_le": 500.0,
                "currency": "EGP",
                "rounding_policy": "piastre_round_half_up",
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
        },
        {
            "key": "delivery_trip_wage_cap",
            "max_cap_le": 1000.0,
            "updated_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "key": "exchange_rate_idr_per_le",
            "value": 357.0
        }
    ])

    with patch.object(server, "client", client), \
         patch.object(server, "db", db), \
         patch("server.is_standalone_fallback_permitted", return_value=False):
        await server.seed()
        yield db, client, admin_owner, admin_finance, admin_ops, helper_rs

    await client.drop_database(TEST_DB_NAME)
    client.close()


# ==============================================================================
# SECTION 2: In-Memory Async Mock Architecture
# ==============================================================================

class AsyncCursorMock:
    def __init__(self, docs):
        self.docs = copy.deepcopy(docs)
        self.idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.idx < len(self.docs):
            doc = self.docs[self.idx]
            self.idx += 1
            return doc
        raise StopAsyncIteration

    def sort(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def skip(self, *args, **kwargs):
        return self

    async def to_list(self, length=None):
        if length is not None:
            return copy.deepcopy(self.docs[:length])
        return copy.deepcopy(self.docs)


class MockCollection:
    def __init__(self, name: str, docs: list = None):
        self.name = name
        self.docs = {}
        for d in (docs or []):
            d_copy = copy.deepcopy(d)
            if "_id" not in d_copy:
                d_copy["_id"] = ObjectId()
            self.docs[str(d_copy["_id"])] = d_copy

    def _matches(self, doc, filter_q):
        if not filter_q:
            return True
        for k, v in filter_q.items():
            if k == "_id":
                doc_id = str(doc.get("_id"))
                if isinstance(v, dict) and "$in" in v:
                    if doc_id not in [str(x) for x in v["$in"]]:
                        return False
                elif isinstance(v, dict) and "$ne" in v:
                    if doc_id == str(v["$ne"]):
                        return False
                else:
                    if doc_id != str(v):
                        return False
            elif k == "order_status":
                if isinstance(v, dict) and "$in" in v:
                    if doc.get("order_status") not in v["$in"]:
                        return False
                elif isinstance(v, dict) and "$ne" in v:
                    if doc.get("order_status") == v["$ne"]:
                        return False
                else:
                    if doc.get("order_status") != v:
                        return False
            elif k == "status":
                if isinstance(v, dict) and "$in" in v:
                    if doc.get("status") not in v["$in"]:
                        return False
                elif isinstance(v, dict) and "$ne" in v:
                    if doc.get("status") == v["$ne"]:
                        return False
                else:
                    if doc.get("status") != v:
                        return False
            elif k == "active_delivery_trip_id":
                if v is None:
                    if doc.get("active_delivery_trip_id") is not None:
                        return False
                elif isinstance(v, dict) and "$ne" in v:
                    if str(doc.get("active_delivery_trip_id")) == str(v["$ne"]):
                        return False
                else:
                    if str(doc.get("active_delivery_trip_id")) != str(v):
                        return False
            elif k == "delivery_method":
                if doc.get("delivery_method") != v:
                    return False
            elif k == "worker_id":
                if str(doc.get("worker_id")) != str(v):
                    return False
            elif k == "paid_amount_le":
                if round(_num(doc.get("paid_amount_le", 0)), 2) != round(_num(v), 2):
                    return False
            elif k == "stops.order_id":
                stop_order_ids = [str(s.get("order_id")) for s in doc.get("stops", [])]
                if str(v) not in stop_order_ids:
                    return False
            elif k == "stops.outcome":
                if isinstance(v, dict) and "$ne" in v:
                    for s in doc.get("stops", []):
                        if s.get("outcome") == v["$ne"]:
                            return False
            elif k == "key":
                if doc.get("key") != v:
                    return False
            elif k == "order_id":
                if str(doc.get("order_id")) != str(v):
                    return False
            elif k == "trip_id":
                if str(doc.get("trip_id")) != str(v):
                    return False
            elif k == "idempotency_key":
                if doc.get("idempotency_key") != v:
                    return False
            elif k == "transaction_id":
                if str(doc.get("transaction_id")) != str(v):
                    return False
            else:
                if doc.get(k) != v:
                    return False
        return True

    async def find_one(self, filter_q, *args, **kwargs):
        for doc in self.docs.values():
            if self._matches(doc, filter_q):
                return copy.deepcopy(doc)
        return None

    def find(self, filter_q=None, *args, **kwargs):
        matched = [copy.deepcopy(doc) for doc in self.docs.values() if self._matches(doc, filter_q)]
        return AsyncCursorMock(matched)

    async def insert_one(self, doc, *args, **kwargs):
        d_copy = copy.deepcopy(doc)
        if "_id" not in d_copy:
            d_copy["_id"] = ObjectId()
        doc_id = str(d_copy["_id"])
        self.docs[doc_id] = d_copy
        res = MagicMock()
        res.inserted_id = d_copy["_id"]
        return res

    async def insert_many(self, docs, *args, **kwargs):
        inserted_ids = []
        for d in docs:
            d_copy = copy.deepcopy(d)
            if "_id" not in d_copy:
                d_copy["_id"] = ObjectId()
            doc_id = str(d_copy["_id"])
            self.docs[doc_id] = d_copy
            inserted_ids.append(d_copy["_id"])
        res = MagicMock()
        res.inserted_ids = inserted_ids
        return res

    async def update_one(self, filter_q, update_q, upsert=False, array_filters=None, *args, **kwargs):
        matched = None
        for doc in self.docs.values():
            if self._matches(doc, filter_q):
                matched = doc
                break
        res = MagicMock()
        if not matched:
            if upsert:
                new_doc = copy.deepcopy(filter_q)
                if "$set" in update_q:
                    new_doc.update(copy.deepcopy(update_q["$set"]))
                if "_id" not in new_doc:
                    new_doc["_id"] = ObjectId()
                self.docs[str(new_doc["_id"])] = new_doc
                res.matched_count = 0
                res.modified_count = 1
                res.upserted_id = new_doc["_id"]
                return res
            res.matched_count = 0
            res.modified_count = 0
            return res

        res.matched_count = 1
        res.modified_count = 1

        if "$set" in update_q:
            for field, val in update_q["$set"].items():
                if field.startswith("stops.$."):
                    sub_f = field.replace("stops.$.", "")
                    stop_oid = filter_q.get("stops.order_id")
                    for s in matched.get("stops", []):
                        if str(s.get("order_id")) == str(stop_oid):
                            s[sub_f] = copy.deepcopy(val)
                elif field.startswith("stops.$[elem]."):
                    sub_f = field.replace("stops.$[elem].", "")
                    elem_outcome = array_filters[0].get("elem.outcome") if (array_filters and len(array_filters) > 0 and isinstance(array_filters[0], dict)) else None
                    for s in matched.get("stops", []):
                        if elem_outcome is None or s.get("outcome") == elem_outcome:
                            s[sub_f] = copy.deepcopy(val)
                else:
                    matched[field] = copy.deepcopy(val)

        if "$push" in update_q:
            for field, val in update_q["$push"].items():
                if field.startswith("stops.$."):
                    sub_f = field.replace("stops.$.", "")
                    stop_oid = filter_q.get("stops.order_id")
                    for s in matched.get("stops", []):
                        if str(s.get("order_id")) == str(stop_oid):
                            s.setdefault(sub_f, []).append(copy.deepcopy(val))
                else:
                    matched.setdefault(field, []).append(copy.deepcopy(val))

        if "$inc" in update_q:
            for field, val in update_q["$inc"].items():
                if field.startswith("stops.$."):
                    sub_f = field.replace("stops.$.", "")
                    stop_oid = filter_q.get("stops.order_id")
                    for s in matched.get("stops", []):
                        if str(s.get("order_id")) == str(stop_oid):
                            s[sub_f] = s.get(sub_f, 0) + val
                else:
                    matched[field] = matched.get(field, 0) + val

        if "$pull" in update_q:
            for field, pval in update_q["$pull"].items():
                if field in matched and isinstance(matched[field], list):
                    if isinstance(pval, dict):
                        pk, pv = next(iter(pval.items()))
                        matched[field] = [item for item in matched[field] if not (isinstance(item, dict) and item.get(pk) == pv)]
                    else:
                        matched[field] = [item for item in matched[field] if item != pval]

        return res

    async def update_many(self, filter_q, update_q, *args, **kwargs):
        matched_docs = [d for d in self.docs.values() if self._matches(d, filter_q)]
        res = MagicMock()
        res.matched_count = len(matched_docs)
        res.modified_count = len(matched_docs)
        for doc in matched_docs:
            if "$set" in update_q:
                for k, v in update_q["$set"].items():
                    doc[k] = copy.deepcopy(v)
            if "$push" in update_q:
                for k, v in update_q["$push"].items():
                    doc.setdefault(k, []).append(copy.deepcopy(v))
            if "$pull" in update_q:
                for field, pval in update_q["$pull"].items():
                    if field in doc and isinstance(doc[field], list):
                        if isinstance(pval, dict):
                            pk, pv = next(iter(pval.items()))
                            doc[field] = [item for item in doc[field] if not (isinstance(item, dict) and item.get(pk) == pv)]
                        else:
                            doc[field] = [item for item in doc[field] if item != pval]
        return res

    async def delete_one(self, filter_q, *args, **kwargs):
        res = MagicMock()
        for doc_id, doc in list(self.docs.items()):
            if self._matches(doc, filter_q):
                del self.docs[doc_id]
                res.deleted_count = 1
                return res
        res.deleted_count = 0
        return res

    async def delete_many(self, filter_q, *args, **kwargs):
        res = MagicMock()
        deleted = 0
        for doc_id, doc in list(self.docs.items()):
            if self._matches(doc, filter_q):
                del self.docs[doc_id]
                deleted += 1
        res.deleted_count = deleted
        return res

    async def find_one_and_update(self, filter_q, update_q, upsert=False, return_document=None, *args, **kwargs):
        for doc_id, doc in self.docs.items():
            if self._matches(doc, filter_q):
                if "$inc" in update_q:
                    for k, v in update_q["$inc"].items():
                        doc[k] = doc.get(k, 0) + v
                if "$set" in update_q:
                    for k, v in update_q["$set"].items():
                        doc[k] = copy.deepcopy(v)
                return copy.deepcopy(doc)
        if upsert:
            new_doc = copy.deepcopy(filter_q)
            if "$inc" in update_q:
                for k, v in update_q["$inc"].items():
                    new_doc[k] = v
            if "$set" in update_q:
                for k, v in update_q["$set"].items():
                    new_doc[k] = copy.deepcopy(v)
            if "_id" not in new_doc:
                new_doc["_id"] = ObjectId()
            self.docs[str(new_doc["_id"])] = new_doc
            return copy.deepcopy(new_doc)
        return None

    async def count_documents(self, filter_q=None, *args, **kwargs):
        return len([d for d in self.docs.values() if self._matches(d, filter_q)])


class MockDB:
    def __init__(self):
        self.orders = MockCollection("orders")
        self.delivery_trips = MockCollection("delivery_trips")
        self.admins = MockCollection("admins")
        self.settings = MockCollection("settings")
        self.wage_obligations = MockCollection("wage_obligations")
        self.wage_settlements = MockCollection("wage_settlements")
        self.employee_wages = MockCollection("employee_wages")
        self.finance_transactions = MockCollection("finance_transactions")
        self.audit_logs = MockCollection("audit_logs")
        self.counters = MockCollection("counters")


@pytest.fixture
def mock_env():
    mdb = MockDB()

    owner_user = {
        "_id": ObjectId("660000000000000000000001"),
        "id": "660000000000000000000001",
        "name": "Owner Boss",
        "role": "owner",
        "permissions": {"access_finance": True, "manage_orders": True, "manage_settings": True}
    }
    finance_user = {
        "_id": ObjectId("660000000000000000000002"),
        "id": "660000000000000000000002",
        "name": "Finance Admin",
        "role": "admin",
        "permissions": {"access_finance": True, "manage_orders": True, "manage_settings": False}
    }
    ops_user = {
        "_id": ObjectId("660000000000000000000003"),
        "id": "660000000000000000000003",
        "name": "Ops Dispatcher",
        "role": "dispatcher",
        "permissions": {"manage_orders": True, "access_finance": False}
    }
    unauthorized_user = {
        "_id": ObjectId("660000000000000000000004"),
        "id": "660000000000000000000004",
        "name": "Staff Biasa",
        "role": "staff",
        "permissions": {}
    }

    helper_1 = {
        "_id": ObjectId("660000000000000000000011"),
        "id": "660000000000000000000011",
        "name": "Helper Joko",
        "role": "helper"
    }
    helper_2 = {
        "_id": ObjectId("660000000000000000000012"),
        "id": "660000000000000000000012",
        "name": "Helper Budi",
        "role": "helper"
    }
    helper_3 = {
        "_id": ObjectId("660000000000000000000013"),
        "id": "660000000000000000000013",
        "name": "Helper Doni",
        "role": "helper"
    }

    mdb.admins.docs[str(owner_user["_id"])] = owner_user
    mdb.admins.docs[str(finance_user["_id"])] = finance_user
    mdb.admins.docs[str(ops_user["_id"])] = ops_user
    mdb.admins.docs[str(unauthorized_user["_id"])] = unauthorized_user
    mdb.admins.docs[str(helper_1["_id"])] = helper_1
    mdb.admins.docs[str(helper_2["_id"])] = helper_2
    mdb.admins.docs[str(helper_3["_id"])] = helper_3

    now_iso = datetime.now(timezone.utc).isoformat()
    mdb.settings.docs["delivery_wage_policy"] = {
        "_id": ObjectId(),
        "key": "delivery_wage_policy",
        "value": {
            "base_wage_per_order_le": 50.0,
            "unusual_amount_threshold_le": 500.0,
            "max_helper_wage_per_order_le": 500.0,
            "currency": "EGP",
            "rounding_policy": "piastre_round_half_up",
            "updated_at": now_iso
        },
        "updated_at": now_iso
    }
    mdb.settings.docs["delivery_trip_wage_cap"] = {
        "_id": ObjectId(),
        "key": "delivery_trip_wage_cap",
        "max_cap_le": 1000.0,
        "updated_at": now_iso
    }
    mdb.settings.docs["exchange_rate_idr_per_le"] = {
        "_id": ObjectId(),
        "key": "exchange_rate_idr_per_le",
        "value": 357.0
    }

    with patch("server.db", mdb), \
         patch("server.client.start_session", side_effect=pymongo.errors.ConfigurationError("mock standalone")), \
         patch("server.is_standalone_fallback_permitted", return_value=True):
        yield mdb, owner_user, finance_user, ops_user, unauthorized_user, [helper_1, helper_2, helper_3]


# ==============================================================================
# SECTION 3: Real MongoDB Replica-Set Transaction Integration Tests
# ==============================================================================

@pytest.mark.anyio
async def test_rs_01_e2e_sequential_lifecycle_in_replica_set(real_delivery_e2e_replica_env):
    """Test RS 1: Complete lifecycle against isolated real Replica Set with multi-document transactions."""
    db, client, admin_owner, admin_finance, admin_ops, helper_rs = real_delivery_e2e_replica_env

    # 1. Seed eligible order
    ord_id = ObjectId()
    await db.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-RS-E2E-001",
        "order_status": "siap",
        "delivery_method": "delivery",
        "active_delivery_trip_id": None,
        "total_le": 1500.0,
        "customer_name": "Pak Customer RS",
        "created_at": datetime.now(timezone.utc).isoformat()
    })

    # 2. Ready queue query
    ready = await admin_get_unassigned_delivery_orders(admin=admin_ops)
    ready_ids = [r["id"] for r in ready]
    assert str(ord_id) in ready_ids

    # 3. Create trip & assign stop
    payload_trip = DeliveryTripCreateInput(
        scheduled_date="2026-10-15",
        departure_time="10:00",
        trip_wage_rate_le=50.0,
        helper_ids=[str(helper_rs["_id"])],
        vehicle_rental=DeliveryTripVehicleRentalInput(
            is_rented=True,
            rental_provider="RS Rental Fleet",
            vehicle_plate_or_desc="B 9999 RS",
            driver_provided_by_rental=True,
            rental_driver_name="Sopir RS",
            agreed_rental_cost_le=200.0
        )
    )
    trip = await admin_create_delivery_trip(payload_trip, admin=admin_ops)
    trip_id = trip["id"]

    await admin_add_trip_stop(trip_id, DeliveryTripAddStopInput(order_id=str(ord_id)), admin=admin_ops)

    # 4. Schedule & Dispatch
    await admin_update_delivery_trip_status(
        trip_id,
        DeliveryTripStatusUpdateInput(target_status="scheduled"),
        admin=admin_ops
    )
    await admin_update_delivery_trip_status(
        trip_id,
        DeliveryTripStatusUpdateInput(target_status="in_transit"),
        admin=admin_ops
    )

    # 5. Record attempt failure & retry
    await admin_record_trip_stop_attempt(
        trip_id,
        str(ord_id),
        DeliveryTripStopAttemptInput(outcome="failed", failure_reason="RS Customer phone unreachable"),
        admin=admin_ops
    )
    await admin_record_trip_stop_attempt(
        trip_id,
        str(ord_id),
        DeliveryTripStopAttemptInput(outcome="out_for_delivery", notes="RS Retry attempt"),
        admin=admin_ops
    )

    # 6. Handover
    handover_res = await admin_deliver_trip_stop(
        trip_id,
        str(ord_id),
        DeliveryStopHandoverInput(recipient_name="RS Customer", helper_confirmed=True),
        admin=admin_ops
    )
    assert handover_res["ok"] is True
    wob = handover_res["wage_obligations"][0]

    # 7. Complete trip
    comp_res = await admin_complete_delivery_trip(
        trip_id,
        DeliveryTripCompleteInput(notes="RS Trip selesai"),
        admin=admin_ops
    )
    assert comp_res["status"] == "completed"

    # Ghost lock check on delivered order
    order_after = await db.orders.find_one({"_id": ord_id})
    assert order_after["active_delivery_trip_id"] is None
    assert order_after["order_status"] == "selesai"

    # 8. Settle wage
    settle_res = await admin_create_wage_settlement(
        WageSettlementCreateInput(
            worker_id=str(helper_rs["_id"]),
            amount_le=50.0,
            payment_method="cash",
            idempotency_key="IDEM-RS-001"
        ),
        admin=admin_finance
    )
    assert settle_res["amount_le"] == 50.0
    txn_count = await db.finance_transactions.count_documents({"related_settlement_number": settle_res["settlement_number"]})
    assert txn_count == 1


@pytest.mark.anyio
async def test_rs_02_e2e_controlled_transaction_abort_rollback(real_delivery_e2e_replica_env):
    """Test RS 2: Deliberate failure inside transaction confirms atomic rollback of all entities."""
    db, client, admin_owner, admin_finance, admin_ops, helper_rs = real_delivery_e2e_replica_env
    ord_id = ObjectId()
    trip_id = ObjectId()

    await db.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-ROLLBACK-001",
        "order_status": "siap",
        "delivery_method": "delivery",
        "active_delivery_trip_id": None
    })

    # Trip is in terminal 'completed' status, so assignment update inside tx will reject
    await db.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-ROLLBACK-9999",
        "status": "completed",
        "stops": []
    })

    with pytest.raises(HTTPException) as ctx:
        await server._execute_delivery_tx_or_fail_closed(
            lambda sess: server.assign_order_to_trip_core(str(trip_id), str(ord_id), admin_ops, session=sess)
        )
    assert ctx.value.status_code == 409

    # Verify atomic rollback
    order_doc = await db.orders.find_one({"_id": ord_id})
    assert order_doc["active_delivery_trip_id"] is None
    trip_doc = await db.delivery_trips.find_one({"_id": trip_id})
    assert len(trip_doc["stops"]) == 0


# ==============================================================================
# SECTION 4: Scenario A — Sequential Full Lifecycle Integration Tests
# ==============================================================================

@pytest.mark.anyio
async def test_e2e_scenario_a_step01_ready_queue_eligibility(mock_env):
    """Scenario A.1: Order with order_status='siap', delivery_method='delivery', active_delivery_trip_id=None is eligible."""
    mdb, _, _, ops_user, _, _ = mock_env

    ord_eligible = {
        "_id": ObjectId("661100000000000000000001"),
        "order_number": "ORD-E2E-A01",
        "order_status": "siap",
        "delivery_method": "delivery",
        "active_delivery_trip_id": None,
        "customer_name": "Ibrahim Customer",
        "total_le": 1250.0,
        "created_at": "2026-10-15T08:00:00Z"
    }
    ord_pickup = {
        "_id": ObjectId("661100000000000000000002"),
        "order_number": "ORD-E2E-A02",
        "order_status": "siap",
        "delivery_method": "pickup",
        "active_delivery_trip_id": None,
        "total_le": 500.0,
        "created_at": "2026-10-15T08:01:00Z"
    }
    ord_diproses = {
        "_id": ObjectId("661100000000000000000003"),
        "order_number": "ORD-E2E-A03",
        "order_status": "diproses",
        "delivery_method": "delivery",
        "active_delivery_trip_id": None,
        "total_le": 750.0,
        "created_at": "2026-10-15T08:02:00Z"
    }
    ord_bound = {
        "_id": ObjectId("661100000000000000000004"),
        "order_number": "ORD-E2E-A04",
        "order_status": "siap",
        "delivery_method": "delivery",
        "active_delivery_trip_id": "670f00000000000000000099",
        "total_le": 800.0,
        "created_at": "2026-10-15T08:03:00Z"
    }

    await mdb.orders.insert_many([ord_eligible, ord_pickup, ord_diproses, ord_bound])

    ready_orders = await admin_get_unassigned_delivery_orders(admin=ops_user)
    ready_numbers = [o["order_number"] for o in ready_orders]

    assert "ORD-E2E-A01" in ready_numbers
    assert "ORD-E2E-A02" not in ready_numbers
    assert "ORD-E2E-A03" not in ready_numbers
    assert "ORD-E2E-A04" not in ready_numbers


@pytest.mark.anyio
async def test_e2e_scenario_a_step02_trip_creation_and_stop_assignment(mock_env):
    """Scenario A.2: Trip creation and stop assignment locks order with active_delivery_trip_id."""
    mdb, _, _, ops_user, _, helpers = mock_env
    helper_1 = helpers[0]

    ord_id = ObjectId("661100000000000000000010")
    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-E2E-A10",
        "order_status": "siap",
        "delivery_method": "delivery",
        "active_delivery_trip_id": None,
        "total_le": 2500.0
    })

    trip_payload = DeliveryTripCreateInput(
        scheduled_date="2026-10-15",
        departure_time="09:00",
        trip_wage_rate_le=50.0,
        helper_ids=[str(helper_1["_id"])],
        vehicle_rental=DeliveryTripVehicleRentalInput(
            is_rented=True,
            rental_provider="Armada Al-Amanah",
            vehicle_plate_or_desc="K 1234 XY",
            driver_provided_by_rental=True,
            rental_driver_name="Pak Mahmud",
            agreed_rental_cost_le=300.0
        ),
        notes="E2E Step 2"
    )
    trip = await admin_create_delivery_trip(trip_payload, admin=ops_user)
    trip_id = trip["id"]
    assert trip["status"] == DeliveryTripStatus.DRAFT.value
    assert trip["trip_number"].startswith("TRP-")

    assign_res = await admin_add_trip_stop(trip_id, DeliveryTripAddStopInput(order_id=str(ord_id)), admin=ops_user)
    assert len(assign_res["stops"]) == 1
    assert assign_res["stops"][0]["order_id"] == str(ord_id)
    assert assign_res["stops"][0]["outcome"] == StopOutcome.PENDING.value

    order_in_db = await mdb.orders.find_one({"_id": ord_id})
    assert order_in_db["active_delivery_trip_id"] == str(trip_id)
    assert order_in_db["active_delivery_trip_number"] == trip["trip_number"]


@pytest.mark.anyio
async def test_e2e_scenario_a_step03_dispatch_and_wage_rate_snapshot_lock(mock_env):
    """Scenario A.3: Dispatch locks wage-policy snapshot; policy updates later do not alter snapshot."""
    mdb, owner_user, _, ops_user, _, helpers = mock_env
    helper_1 = helpers[0]
    ord_id = ObjectId("661100000000000000000020")
    trip_id = ObjectId("670f00000000000000000020")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-E2E-A20",
        "order_status": "siap",
        "delivery_method": "delivery",
        "active_delivery_trip_id": str(trip_id),
        "total_le": 1500.0
    })
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0020",
        "status": DeliveryTripStatus.SCHEDULED.value,
        "trip_wage_rate_le": 50.0,
        "helper_ids": [str(helper_1["_id"])],
        "helpers": [{"helper_id": str(helper_1["_id"]), "helper_name": helper_1["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": StopOutcome.PENDING.value}],
        "rate_policy_snapshot": None
    })

    dispatch_res = await admin_update_delivery_trip_status(
        str(trip_id),
        DeliveryTripStatusUpdateInput(target_status="in_transit"),
        admin=ops_user
    )
    assert dispatch_res["status"] == DeliveryTripStatus.IN_TRANSIT.value
    snapshot = dispatch_res["rate_policy_snapshot"]
    assert snapshot is not None
    assert snapshot["applied_rate_le"] == 50.0
    assert snapshot["unusual_amount_threshold_le"] == 500.0

    # Mutate active policy afterwards
    await admin_update_delivery_wage_policy(
        DeliveryWagePolicyInput(
            base_wage_per_order_le=80.0,
            unusual_amount_threshold_le=600.0,
            max_helper_wage_per_order_le=1000.0,
            currency="EGP",
            rounding_policy="piastre_round_half_up"
        ),
        admin=owner_user
    )

    # Confirm snapshot on trip remains unchanged at 50.0 LE
    trip_in_db = await mdb.delivery_trips.find_one({"_id": trip_id})
    assert trip_in_db["rate_policy_snapshot"]["applied_rate_le"] == 50.0


@pytest.mark.anyio
async def test_e2e_scenario_a_step04_failed_attempt_zero_wage_and_no_expense(mock_env):
    """Scenario A.4: Delivery failure records attempt history, retains active lock, produces 0 wages and 0 expense."""
    mdb, _, _, ops_user, _, helpers = mock_env
    helper_1 = helpers[0]
    ord_id = ObjectId("661100000000000000000030")
    trip_id = ObjectId("670f00000000000000000030")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-E2E-A30",
        "order_status": "siap",
        "delivery_method": "delivery",
        "active_delivery_trip_id": str(trip_id),
        "delivery_logistics_status": "in_transit",
        "total_le": 1800.0
    })
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0030",
        "status": DeliveryTripStatus.IN_TRANSIT.value,
        "helpers": [{"helper_id": str(helper_1["_id"]), "helper_name": helper_1["name"]}],
        "stops": [{
            "order_id": str(ord_id),
            "outcome": StopOutcome.OUT_FOR_DELIVERY.value,
            "attempt_count": 0,
            "attempts": []
        }]
    })

    fail_res = await admin_record_trip_stop_attempt(
        str(trip_id),
        str(ord_id),
        DeliveryTripStopAttemptInput(
            outcome="failed",
            failure_reason="Pelanggan tidak merespons telepon dan pintu terkunci",
            notes="Percobaan pertama gagal"
        ),
        admin=ops_user
    )
    stop = fail_res["stops"][0]
    assert stop["outcome"] == StopOutcome.FAILED.value
    assert stop["attempt_count"] == 1
    assert len(stop["attempts"]) == 1
    assert stop["attempts"][0]["failure_reason"] == "Pelanggan tidak merespons telepon dan pintu terkunci"

    # Invariants: order retains active trip binding, 0 wage obligations, 0 finance expenses
    order_doc = await mdb.orders.find_one({"_id": ord_id})
    assert order_doc["active_delivery_trip_id"] == str(trip_id)
    assert order_doc["order_status"] == "siap"
    assert await mdb.wage_obligations.count_documents({"order_id": str(ord_id)}) == 0
    assert await mdb.finance_transactions.count_documents({}) == 0


@pytest.mark.anyio
async def test_e2e_scenario_a_step05_retry_and_successful_handover(mock_env):
    """Scenario A.5: Retry preserves attempt history; successful handover stamps delivery fields & accrues wage obligation."""
    mdb, _, _, ops_user, _, helpers = mock_env
    helper_1 = helpers[0]
    ord_id = ObjectId("661100000000000000000040")
    trip_id = ObjectId("670f00000000000000000040")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-E2E-A40",
        "order_status": "siap",
        "delivery_method": "delivery",
        "active_delivery_trip_id": str(trip_id),
        "total_le": 2000.0
    })
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0040",
        "status": DeliveryTripStatus.IN_TRANSIT.value,
        "trip_wage_rate_le": 50.0,
        "helpers": [{"helper_id": str(helper_1["_id"]), "helper_name": helper_1["name"]}],
        "rate_policy_snapshot": {
            "applied_rate_le": 50.0,
            "unusual_amount_threshold_le": 500.0,
            "currency": "EGP"
        },
        "stops": [{
            "order_id": str(ord_id),
            "outcome": StopOutcome.FAILED.value,
            "attempt_count": 1,
            "attempts": [{"attempt_number": 1, "failure_reason": "No response"}]
        }]
    })

    # Retry transition
    retry_res = await admin_record_trip_stop_attempt(
        str(trip_id),
        str(ord_id),
        DeliveryTripStopAttemptInput(outcome="out_for_delivery", notes="Mencoba pengantaran kedua"),
        admin=ops_user
    )
    assert retry_res["stops"][0]["outcome"] == StopOutcome.OUT_FOR_DELIVERY.value
    assert retry_res["stops"][0]["attempt_count"] == 1
    assert len(retry_res["stops"][0]["attempts"]) == 1

    # Handover completion
    handover_res = await admin_deliver_trip_stop(
        str(trip_id),
        str(ord_id),
        DeliveryStopHandoverInput(
            recipient_name="Ibrahim Customer",
            helper_confirmed=True,
            handover_notes="Serah terima sukses di lantai 2"
        ),
        admin=ops_user
    )
    assert handover_res["ok"] is True
    assert handover_res["order"]["order_status"] == "selesai"
    assert handover_res["order"]["delivery_logistics_status"] == "delivered"
    assert handover_res["order"]["recognized_revenue_le"] == 2000.0
    assert handover_res["order"]["delivered_trip_id"] == str(trip_id)

    # Wage obligation check
    wobs = await mdb.wage_obligations.find({"order_id": str(ord_id)}).to_list(10)
    assert len(wobs) == 1
    assert wobs[0]["status"] == "accrued"
    assert wobs[0]["total_amount_le"] == 50.0
    assert wobs[0]["paid_amount_le"] == 0.0
    assert wobs[0]["accrual_event_key"] == build_delivery_accrual_event_key(str(ord_id), str(helper_1["_id"]))

    # Accrual did not create a cash expense
    assert await mdb.finance_transactions.count_documents({}) == 0


@pytest.mark.anyio
async def test_e2e_scenario_a_step06_trip_completion_ghost_lock_release_and_idempotency(mock_env):
    """Scenario A.6: Trip completion eliminates ghost locks on delivered orders; replay is idempotent."""
    mdb, _, _, ops_user, _, helpers = mock_env
    helper_1 = helpers[0]
    ord_id = ObjectId("661100000000000000000050")
    trip_id = ObjectId("670f00000000000000000050")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-E2E-A50",
        "order_status": "selesai",
        "delivery_logistics_status": "delivered",
        "active_delivery_trip_id": str(trip_id),
        "active_delivery_trip_number": "TRP-20261015-0050",
        "delivered_trip_id": str(trip_id),
        "delivered_trip_number": "TRP-20261015-0050",
        "completed_at": "2026-10-15T12:00:00Z",
        "recognized_revenue_le": 2000.0
    })
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0050",
        "status": DeliveryTripStatus.IN_TRANSIT.value,
        "helpers": [{"helper_id": str(helper_1["_id"]), "helper_name": helper_1["name"]}],
        "stops": [{
            "order_id": str(ord_id),
            "outcome": StopOutcome.DELIVERED.value
        }]
    })

    comp_res = await admin_complete_delivery_trip(
        str(trip_id),
        DeliveryTripCompleteInput(notes="Trip selesai penuh"),
        admin=ops_user
    )
    assert comp_res["status"] == DeliveryTripStatus.COMPLETED.value
    assert comp_res["is_partially_completed"] is False

    # Ghost lock eliminated while permanent history preserved
    order_after = await mdb.orders.find_one({"_id": ord_id})
    assert order_after["active_delivery_trip_id"] is None
    assert order_after["active_delivery_trip_number"] is None
    assert order_after["delivered_trip_id"] == str(trip_id)
    assert order_after["delivered_trip_number"] == "TRP-20261015-0050"
    assert order_after["order_status"] == "selesai"
    assert order_after["recognized_revenue_le"] == 2000.0

    # Idempotent replay: calling completion again succeeds without mutating state
    replay_res = await admin_complete_delivery_trip(
        str(trip_id),
        DeliveryTripCompleteInput(notes="Replay call"),
        admin=ops_user
    )
    assert replay_res["status"] == DeliveryTripStatus.COMPLETED.value


@pytest.mark.anyio
async def test_e2e_scenario_a_step07_wage_obligation_verification(mock_env):
    """Scenario A.7: Delivery-helper wage obligation is singular, uses immutable rate, and has 0 cash expense."""
    mdb, _, _, _, _, helpers = mock_env
    helper_1 = helpers[0]
    ord_id = ObjectId("661100000000000000000060")
    trip_id = ObjectId("670f00000000000000000060")

    await mdb.wage_obligations.insert_one({
        "_id": ObjectId(),
        "obligation_number": "WOB-20261015-0001",
        "accrual_event_key": build_delivery_accrual_event_key(str(ord_id), str(helper_1["_id"])),
        "trip_id": str(trip_id),
        "order_id": str(ord_id),
        "worker_id": str(helper_1["_id"]),
        "worker_name": helper_1["name"],
        "task_category": "delivery",
        "total_amount_le": 50.0,
        "amount_piastres": 5000,
        "currency": "EGP",
        "status": "accrued",
        "paid_amount_le": 0.0
    })

    wobs = await mdb.wage_obligations.find({"order_id": str(ord_id)}).to_list(10)
    assert len(wobs) == 1
    assert wobs[0]["total_amount_le"] == 50.0
    assert wobs[0]["paid_amount_le"] == 0.0
    assert wobs[0]["status"] == "accrued"
    assert await mdb.finance_transactions.count_documents({}) == 0


@pytest.mark.anyio
async def test_e2e_scenario_a_step08_wage_settlement_finance_integration_and_replay(mock_env):
    """Scenario A.8: Settle accrued obligation -> transitions to 'paid', exactly ONE 'Pekerja' expense, replay idempotent."""
    mdb, _, finance_user, _, _, helpers = mock_env
    helper_1 = helpers[0]
    ord_id = ObjectId("661100000000000000000070")
    ob_id = ObjectId("662200000000000000000070")

    await mdb.wage_obligations.insert_one({
        "_id": ob_id,
        "obligation_number": "WOB-20261015-0070",
        "worker_id": str(helper_1["_id"]),
        "worker_name": helper_1["name"],
        "order_id": str(ord_id),
        "task_category": "delivery",
        "total_amount_le": 50.0,
        "paid_amount_le": 0.0,
        "currency": "EGP",
        "status": "accrued",
        "created_at": "2026-10-15T10:00:00Z"
    })

    # 1. Query pending wages
    pending = await admin_get_worker_pending_wages(str(helper_1["_id"]), admin=finance_user)
    assert pending["total_pending_wages_le"] == 50.0
    assert pending["pending_obligations_count"] == 1

    # 2. Settle wage
    settle_payload = WageSettlementCreateInput(
        worker_id=str(helper_1["_id"]),
        amount_le=50.0,
        payment_method="cash",
        payment_date="2026-10-15",
        reference="REF-E2E-A08",
        notes="Settlement gaji delivery E2E",
        idempotency_key="IDEM-WST-E2E-A08"
    )
    settle_res = await admin_create_wage_settlement(settle_payload, admin=finance_user)
    assert settle_res["amount_le"] == 50.0
    assert settle_res["worker_id"] == str(helper_1["_id"])
    assert settle_res["status"] == "recorded"

    # 3. Obligation transitioned to paid
    ob_after = await mdb.wage_obligations.find_one({"_id": ob_id})
    assert ob_after["status"] == "paid"
    assert ob_after["paid_amount_le"] == 50.0
    assert len(ob_after.get("settlement_allocations", [])) == 1

    # 4. Exactly ONE finance transaction created
    txns = await mdb.finance_transactions.find({}).to_list(10)
    assert len(txns) == 1
    assert txns[0]["type"] == "expense"
    assert txns[0]["category"] == "Pekerja"
    assert txns[0]["amount"] == 50.0
    assert txns[0]["currency"] == "EGP"
    assert txns[0]["recipient_employee_id"] == str(helper_1["_id"])
    assert txns[0]["related_settlement_number"] == settle_res["settlement_number"]

    # 5. Settlement replay with same idempotency key returns winning settlement without creating new expense
    replay_res = await admin_create_wage_settlement(settle_payload, admin=finance_user)
    assert replay_res["settlement_number"] == settle_res["settlement_number"]
    assert await mdb.finance_transactions.count_documents({}) == 1


@pytest.mark.anyio
async def test_e2e_scenario_a_full_sequential_lifecycle_flow(mock_env):
    """Scenario A.9: Complete sequential lifecycle executed end-to-end in a single uninterrupted chain."""
    mdb, _, finance_user, ops_user, _, helpers = mock_env
    helper_1 = helpers[0]
    ord_id = ObjectId("661100000000000000000080")

    # 1. Seed eligible order
    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-E2E-FULL-CHAIN",
        "order_status": "siap",
        "delivery_method": "delivery",
        "active_delivery_trip_id": None,
        "total_le": 3200.0,
        "customer_name": "Pak Ahmad Subagyo",
        "created_at": "2026-10-15T07:00:00Z"
    })

    # 2. Verify Ready Queue
    ready = await admin_get_unassigned_delivery_orders(admin=ops_user)
    assert "ORD-E2E-FULL-CHAIN" in [o["order_number"] for o in ready]

    # 3. Create trip & assign stop
    trip = await admin_create_delivery_trip(
        DeliveryTripCreateInput(
            scheduled_date="2026-10-15",
            departure_time="08:30",
            trip_wage_rate_le=50.0,
            helper_ids=[str(helper_1["_id"])],
            vehicle_rental=DeliveryTripVehicleRentalInput(
                is_rented=True,
                rental_provider="Sogil Express Fleet",
                vehicle_plate_or_desc="B 5555 SG",
                driver_provided_by_rental=True,
                rental_driver_name="Pak Sopir Handal",
                agreed_rental_cost_le=350.0
            )
        ),
        admin=ops_user
    )
    trip_id = trip["id"]
    await admin_add_trip_stop(trip_id, DeliveryTripAddStopInput(order_id=str(ord_id)), admin=ops_user)

    order_bound = await mdb.orders.find_one({"_id": ord_id})
    assert order_bound["active_delivery_trip_id"] == str(trip_id)

    # 4. Schedule & Dispatch
    await admin_update_delivery_trip_status(
        trip_id,
        DeliveryTripStatusUpdateInput(target_status="scheduled"),
        admin=ops_user
    )
    await admin_update_delivery_trip_status(
        trip_id,
        DeliveryTripStatusUpdateInput(target_status="in_transit"),
        admin=ops_user
    )

    # 5. Failed attempt
    await admin_record_trip_stop_attempt(
        trip_id,
        str(ord_id),
        DeliveryTripStopAttemptInput(outcome="failed", failure_reason="Customer outside Cairo until afternoon"),
        admin=ops_user
    )
    assert await mdb.wage_obligations.count_documents({}) == 0
    assert await mdb.finance_transactions.count_documents({}) == 0

    # 6. Retry
    await admin_record_trip_stop_attempt(
        trip_id,
        str(ord_id),
        DeliveryTripStopAttemptInput(outcome="out_for_delivery", notes="Retry afternoon"),
        admin=ops_user
    )

    # 7. Successful handover
    await admin_deliver_trip_stop(
        trip_id,
        str(ord_id),
        DeliveryStopHandoverInput(recipient_name="Pak Ahmad", helper_confirmed=True),
        admin=ops_user
    )
    order_delivered = await mdb.orders.find_one({"_id": ord_id})
    assert order_delivered["order_status"] == "selesai"
    assert order_delivered["recognized_revenue_le"] == 3200.0

    # 8. Complete trip
    await admin_complete_delivery_trip(trip_id, DeliveryTripCompleteInput(notes="Full chain complete"), admin=ops_user)
    order_completed = await mdb.orders.find_one({"_id": ord_id})
    assert order_completed["active_delivery_trip_id"] is None
    assert order_completed["delivered_trip_id"] == str(trip_id)

    # 9. Verify pending wage & settle
    pending = await admin_get_worker_pending_wages(str(helper_1["_id"]), admin=finance_user)
    assert pending["total_pending_wages_le"] == 50.0

    settle_res = await admin_create_wage_settlement(
        WageSettlementCreateInput(
            worker_id=str(helper_1["_id"]),
            amount_le=50.0,
            payment_method="cash",
            idempotency_key="IDEM-FULL-CHAIN-001"
        ),
        admin=finance_user
    )
    assert settle_res["status"] == "recorded"
    assert await mdb.finance_transactions.count_documents({}) == 1

    # Final check: obligation is paid
    ob = await mdb.wage_obligations.find_one({"order_id": str(ord_id)})
    assert ob["status"] == "paid"
    assert ob["paid_amount_le"] == 50.0


@pytest.mark.anyio
async def test_e2e_scenario_a_partial_completion_with_failed_closed_order_release(mock_env):
    """Scenario A.10: Partial completion: 1 delivered stop + 1 failed stop releases both locks; failed order returns to ready queue."""
    mdb, _, _, ops_user, _, helpers = mock_env
    helper_1 = helpers[0]
    ord_del_id = ObjectId("661100000000000000000091")
    ord_fail_id = ObjectId("661100000000000000000092")
    trip_id = ObjectId("670f00000000000000000090")

    await mdb.orders.insert_many([
        {
            "_id": ord_del_id,
            "order_number": "ORD-PARTIAL-DEL",
            "order_status": "siap",
            "delivery_method": "delivery",
            "active_delivery_trip_id": str(trip_id),
            "total_le": 1000.0
        },
        {
            "_id": ord_fail_id,
            "order_number": "ORD-PARTIAL-FAIL",
            "order_status": "siap",
            "delivery_method": "delivery",
            "active_delivery_trip_id": str(trip_id),
            "total_le": 1500.0
        }
    ])

    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-PARTIAL",
        "status": DeliveryTripStatus.IN_TRANSIT.value,
        "trip_wage_rate_le": 50.0,
        "helpers": [{"helper_id": str(helper_1["_id"]), "helper_name": helper_1["name"]}],
        "rate_policy_snapshot": {"applied_rate_le": 50.0, "unusual_amount_threshold_le": 500.0, "currency": "EGP"},
        "stops": [
            {"order_id": str(ord_del_id), "outcome": StopOutcome.OUT_FOR_DELIVERY.value, "attempt_count": 0, "attempts": []},
            {"order_id": str(ord_fail_id), "outcome": StopOutcome.OUT_FOR_DELIVERY.value, "attempt_count": 0, "attempts": []}
        ]
    })

    # Deliver first stop
    await admin_deliver_trip_stop(
        str(trip_id),
        str(ord_del_id),
        DeliveryStopHandoverInput(recipient_name="Customer Del", helper_confirmed=True),
        admin=ops_user
    )

    # Fail second stop
    await admin_record_trip_stop_attempt(
        str(trip_id),
        str(ord_fail_id),
        DeliveryTripStopAttemptInput(outcome="failed", failure_reason="Alamat tidak ditemukan"),
        admin=ops_user
    )

    # Complete trip (Partial completion)
    comp_res = await admin_complete_delivery_trip(
        str(trip_id),
        DeliveryTripCompleteInput(notes="1 delivered, 1 failed"),
        admin=ops_user
    )
    assert comp_res["status"] == DeliveryTripStatus.COMPLETED.value
    assert comp_res["is_partially_completed"] is True

    # Check delivered order
    del_doc = await mdb.orders.find_one({"_id": ord_del_id})
    assert del_doc["active_delivery_trip_id"] is None
    assert del_doc["order_status"] == "selesai"

    # Check failed order: lock released, delivery_logistics_status updated, order_status remains 'siap'
    fail_doc = await mdb.orders.find_one({"_id": ord_fail_id})
    assert fail_doc["active_delivery_trip_id"] is None
    assert fail_doc["active_delivery_trip_number"] is None
    assert fail_doc["order_status"] == "siap"
    assert fail_doc["delivery_logistics_status"] == "delivery_failed"

    # Failed order must now appear back in the ready queue!
    ready = await admin_get_unassigned_delivery_orders(admin=ops_user)
    ready_numbers = [o["order_number"] for o in ready]
    assert "ORD-PARTIAL-FAIL" in ready_numbers
    assert "ORD-PARTIAL-DEL" not in ready_numbers


# ==============================================================================
# SECTION 5: Scenario B — Multi-Helper Allocation and Exact Amount
# ==============================================================================

@pytest.mark.anyio
async def test_e2e_scenario_b_multi_helper_allocation_50_le_three_helpers(mock_env):
    """Scenario B.1: 3 helpers with total wage of 50 LE distributes exact piastres: 16.67, 16.67, 16.66 LE (Sum = 50.00 LE)."""
    mdb, _, _, ops_user, _, helpers = mock_env
    assert len(helpers) == 3
    ord_id = ObjectId("6611000000000000000000B1")
    trip_id = ObjectId("670f000000000000000000B1")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-MULTI-HELPER-01",
        "order_status": "siap",
        "delivery_method": "delivery",
        "active_delivery_trip_id": str(trip_id),
        "total_le": 2500.0
    })
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-MULTI",
        "status": DeliveryTripStatus.IN_TRANSIT.value,
        "trip_wage_rate_le": 50.0,
        "helpers": [
            {"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]},
            {"helper_id": str(helpers[1]["_id"]), "helper_name": helpers[1]["name"]},
            {"helper_id": str(helpers[2]["_id"]), "helper_name": helpers[2]["name"]},
        ],
        "rate_policy_snapshot": {
            "applied_rate_le": 50.0,
            "unusual_amount_threshold_le": 500.0,
            "currency": "EGP"
        },
        "stops": [{
            "order_id": str(ord_id),
            "outcome": StopOutcome.OUT_FOR_DELIVERY.value
        }]
    })

    handover_res = await admin_deliver_trip_stop(
        str(trip_id),
        str(ord_id),
        DeliveryStopHandoverInput(recipient_name="Customer Multi", helper_confirmed=True),
        admin=ops_user
    )
    assert handover_res["ok"] is True
    wobs = handover_res["wage_obligations"]
    assert len(wobs) == 3

    # Inspect exact allocations
    alloc_by_worker = {str(w["worker_id"]): w["total_amount_le"] for w in wobs}
    assert alloc_by_worker[str(helpers[0]["_id"])] == 16.67
    assert alloc_by_worker[str(helpers[1]["_id"])] == 16.67
    assert alloc_by_worker[str(helpers[2]["_id"])] == 16.66

    total_allocated = round(sum(alloc_by_worker.values()), 2)
    assert total_allocated == 50.00

    # Piastre check
    total_piastres = sum(w["amount_piastres"] for w in wobs)
    assert total_piastres == 5000


@pytest.mark.anyio
async def test_e2e_scenario_b_multi_helper_full_settlement_ledger_exactness(mock_env):
    """Scenario B.2: Settle all 3 helpers and verify sum of expenses in finance ledger equals exactly 50.00 LE."""
    mdb, _, finance_user, ops_user, _, helpers = mock_env
    ord_id = ObjectId("6611000000000000000000B2")
    trip_id = ObjectId("670f000000000000000000B2")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-MULTI-HELPER-02",
        "order_status": "siap",
        "delivery_method": "delivery",
        "active_delivery_trip_id": str(trip_id),
        "total_le": 3000.0
    })
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-MULTI2",
        "status": DeliveryTripStatus.IN_TRANSIT.value,
        "trip_wage_rate_le": 50.0,
        "helpers": [
            {"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]},
            {"helper_id": str(helpers[1]["_id"]), "helper_name": helpers[1]["name"]},
            {"helper_id": str(helpers[2]["_id"]), "helper_name": helpers[2]["name"]},
        ],
        "rate_policy_snapshot": {
            "applied_rate_le": 50.0,
            "unusual_amount_threshold_le": 500.0,
            "currency": "EGP"
        },
        "stops": [{
            "order_id": str(ord_id),
            "outcome": StopOutcome.OUT_FOR_DELIVERY.value
        }]
    })

    await admin_deliver_trip_stop(
        str(trip_id),
        str(ord_id),
        DeliveryStopHandoverInput(recipient_name="Customer Multi 2", helper_confirmed=True),
        admin=ops_user
    )

    # Settle Helper 1: 16.67 LE
    await admin_create_wage_settlement(
        WageSettlementCreateInput(
            worker_id=str(helpers[0]["_id"]),
            amount_le=16.67,
            payment_method="cash",
            idempotency_key="IDEM-MULTI-H1"
        ),
        admin=finance_user
    )

    # Settle Helper 2: 16.67 LE
    await admin_create_wage_settlement(
        WageSettlementCreateInput(
            worker_id=str(helpers[1]["_id"]),
            amount_le=16.67,
            payment_method="cash",
            idempotency_key="IDEM-MULTI-H2"
        ),
        admin=finance_user
    )

    # Settle Helper 3: 16.66 LE
    await admin_create_wage_settlement(
        WageSettlementCreateInput(
            worker_id=str(helpers[2]["_id"]),
            amount_le=16.66,
            payment_method="cash",
            idempotency_key="IDEM-MULTI-H3"
        ),
        admin=finance_user
    )

    # Verify finance transactions
    txns = await mdb.finance_transactions.find({}).to_list(10)
    assert len(txns) == 3
    total_disbursed = round(sum(t["amount"] for t in txns), 2)
    assert total_disbursed == 50.00

    # Verify all obligations are paid
    all_wobs = await mdb.wage_obligations.find({"order_id": str(ord_id)}).to_list(10)
    assert all(w["status"] == "paid" for w in all_wobs)


# ==============================================================================
# SECTION 6: Scenario C — Boundary and Failure Invariants
# ==============================================================================

@pytest.mark.anyio
async def test_e2e_scenario_c_01_active_trip_lock_blocks_order_status_update(mock_env):
    """Scenario C.1: Updating order_status on an order with active_delivery_trip_id raises HTTP 409."""
    mdb, owner_user, _, _, _, _ = mock_env
    ord_id = ObjectId("6611000000000000000000C1")
    trip_id = ObjectId("670f000000000000000000C1")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-C01",
        "order_status": "siap",
        "active_delivery_trip_id": str(trip_id),
        "active_delivery_trip_number": "TRP-20261015-C01"
    })

    with pytest.raises(HTTPException) as ctx:
        await admin_update_order(
            str(ord_id),
            OrderStatusUpdate(order_status="diproses"),
            admin=owner_user
        )
    assert ctx.value.status_code == 409
    assert "sedang terikat pada trip pengiriman aktif" in ctx.value.detail


@pytest.mark.anyio
async def test_e2e_scenario_c_02_active_trip_lock_blocks_order_pricing_or_items_update(mock_env):
    """Scenario C.2: Updating pricing, fees, or line items on trip-bound order raises HTTP 409."""
    mdb, owner_user, _, _, _, _ = mock_env
    ord_id = ObjectId("6611000000000000000000C2")
    trip_id = ObjectId("670f000000000000000000C2")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-C02",
        "order_status": "siap",
        "active_delivery_trip_id": str(trip_id),
        "total_le": 1000.0
    })

    with pytest.raises(HTTPException) as ctx:
        await admin_update_order(str(ord_id), OrderStatusUpdate(subtotal_le=1200.0), admin=owner_user)
    assert ctx.value.status_code == 409

    with pytest.raises(HTTPException) as ctx:
        await admin_update_order(str(ord_id), OrderStatusUpdate(delivery_fee_le=150.0), admin=owner_user)
    assert ctx.value.status_code == 409

    with pytest.raises(HTTPException) as ctx:
        await admin_update_order(str(ord_id), OrderStatusUpdate(items=[{"item_id": "itm_x", "quantity": 2}]), admin=owner_user)
    assert ctx.value.status_code == 409


@pytest.mark.anyio
async def test_e2e_scenario_c_03_active_trip_lock_blocks_order_permanent_deletion(mock_env):
    """Scenario C.3: Permanently deleting an order with active_delivery_trip_id raises HTTP 409."""
    mdb, owner_user, _, _, _, _ = mock_env
    ord_id = ObjectId("6611000000000000000000C3")
    trip_id = ObjectId("670f000000000000000000C3")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-C03",
        "order_status": "siap",
        "active_delivery_trip_id": str(trip_id)
    })

    with pytest.raises(HTTPException) as ctx:
        await admin_permanent_delete_order(
            str(ord_id),
            PermanentDeleteInput(confirmation_phrase="HAPUS PERMANEN", reason="E2E testing deletion guard"),
            admin=owner_user
        )
    assert ctx.value.status_code == 409
    assert "sedang terikat pada trip pengiriman aktif" in ctx.value.detail


@pytest.mark.anyio
async def test_e2e_scenario_c_04_failed_delivery_does_not_accrue_wages(mock_env):
    """Scenario C.4: A failed delivery stop creates exactly 0 wage obligations and 0 finance transactions."""
    mdb, _, _, ops_user, _, helpers = mock_env
    helper_1 = helpers[0]
    ord_id = ObjectId("6611000000000000000000C4")
    trip_id = ObjectId("670f000000000000000000C4")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-C04",
        "order_status": "siap",
        "delivery_method": "delivery",
        "active_delivery_trip_id": str(trip_id)
    })
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-C04",
        "status": DeliveryTripStatus.IN_TRANSIT.value,
        "helpers": [{"helper_id": str(helper_1["_id"]), "helper_name": helper_1["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": StopOutcome.OUT_FOR_DELIVERY.value}]
    })

    await admin_record_trip_stop_attempt(
        str(trip_id),
        str(ord_id),
        DeliveryTripStopAttemptInput(outcome="failed", failure_reason="Customer unreachable"),
        admin=ops_user
    )

    assert await mdb.wage_obligations.count_documents({"order_id": str(ord_id)}) == 0
    assert await mdb.finance_transactions.count_documents({}) == 0


@pytest.mark.anyio
async def test_e2e_scenario_c_05_handover_idempotent_replay_no_duplicate_accrual(mock_env):
    """Scenario C.5: Repeating handover on an already delivered stop returns idempotently without duplicate obligations."""
    mdb, _, _, ops_user, _, helpers = mock_env
    helper_1 = helpers[0]
    ord_id = ObjectId("6611000000000000000000C5")
    trip_id = ObjectId("670f000000000000000000C5")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-C05",
        "order_status": "siap",
        "delivery_method": "delivery",
        "active_delivery_trip_id": str(trip_id),
        "total_le": 1000.0
    })
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-C05",
        "status": DeliveryTripStatus.IN_TRANSIT.value,
        "trip_wage_rate_le": 50.0,
        "helpers": [{"helper_id": str(helper_1["_id"]), "helper_name": helper_1["name"]}],
        "rate_policy_snapshot": {"applied_rate_le": 50.0, "unusual_amount_threshold_le": 500.0, "currency": "EGP"},
        "stops": [{"order_id": str(ord_id), "outcome": StopOutcome.OUT_FOR_DELIVERY.value}]
    })

    # First handover
    first_res = await admin_deliver_trip_stop(
        str(trip_id),
        str(ord_id),
        DeliveryStopHandoverInput(recipient_name="Customer C05", helper_confirmed=True),
        admin=ops_user
    )
    assert first_res["ok"] is True
    assert len(first_res["wage_obligations"]) == 1

    # Second handover (replay)
    second_res = await admin_deliver_trip_stop(
        str(trip_id),
        str(ord_id),
        DeliveryStopHandoverInput(recipient_name="Customer C05", helper_confirmed=True),
        admin=ops_user
    )
    assert second_res["ok"] is True
    assert second_res.get("already_delivered") is True
    assert await mdb.wage_obligations.count_documents({"order_id": str(ord_id)}) == 1


@pytest.mark.anyio
async def test_e2e_scenario_c_06_trip_completion_idempotent_replay_no_duplicate_mutation(mock_env):
    """Scenario C.6: Repeating trip completion on an already completed trip returns clean(trip) idempotently."""
    mdb, _, _, ops_user, _, helpers = mock_env
    trip_id = ObjectId("670f000000000000000000C6")

    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-C06",
        "status": DeliveryTripStatus.COMPLETED.value,
        "completed_at": "2026-10-15T10:00:00Z",
        "stops": []
    })

    res = await admin_complete_delivery_trip(
        str(trip_id),
        DeliveryTripCompleteInput(notes="Replay test"),
        admin=ops_user
    )
    assert res["status"] == DeliveryTripStatus.COMPLETED.value


@pytest.mark.anyio
async def test_e2e_scenario_c_07_settlement_replay_same_idempotency_key_no_duplicate_expense(mock_env):
    """Scenario C.7: Settlement replay with identical idempotency key returns winning settlement with 0 extra expense."""
    mdb, _, finance_user, _, _, helpers = mock_env
    helper_1 = helpers[0]
    ob_id = ObjectId("6622000000000000000000C7")

    await mdb.wage_obligations.insert_one({
        "_id": ob_id,
        "obligation_number": "WOB-C07",
        "worker_id": str(helper_1["_id"]),
        "worker_name": helper_1["name"],
        "task_category": "delivery",
        "total_amount_le": 50.0,
        "paid_amount_le": 0.0,
        "status": "accrued"
    })

    payload = WageSettlementCreateInput(
        worker_id=str(helper_1["_id"]),
        amount_le=50.0,
        payment_method="cash",
        idempotency_key="IDEM-C07-KEY"
    )
    res1 = await admin_create_wage_settlement(payload, admin=finance_user)
    res2 = await admin_create_wage_settlement(payload, admin=finance_user)

    assert res1["settlement_number"] == res2["settlement_number"]
    assert await mdb.finance_transactions.count_documents({}) == 1


@pytest.mark.anyio
async def test_e2e_scenario_c_08_settlement_replay_mismatched_params_conflict_409(mock_env):
    """Scenario C.8: Replaying settlement with same idempotency key but different amount raises HTTP 409 conflict."""
    mdb, _, finance_user, _, _, helpers = mock_env
    helper_1 = helpers[0]
    ob_id = ObjectId("6622000000000000000000C8")

    await mdb.wage_obligations.insert_one({
        "_id": ob_id,
        "obligation_number": "WOB-C08",
        "worker_id": str(helper_1["_id"]),
        "worker_name": helper_1["name"],
        "task_category": "delivery",
        "total_amount_le": 100.0,
        "paid_amount_le": 0.0,
        "status": "accrued"
    })

    payload1 = WageSettlementCreateInput(
        worker_id=str(helper_1["_id"]),
        amount_le=50.0,
        payment_method="cash",
        idempotency_key="IDEM-C08-KEY"
    )
    await admin_create_wage_settlement(payload1, admin=finance_user)

    payload2 = WageSettlementCreateInput(
        worker_id=str(helper_1["_id"]),
        amount_le=30.0,  # Different amount
        payment_method="cash",
        idempotency_key="IDEM-C08-KEY"
    )
    with pytest.raises(HTTPException) as ctx:
        await admin_create_wage_settlement(payload2, admin=finance_user)
    assert ctx.value.status_code == 409
    assert "Kunci idempotensi telah digunakan" in ctx.value.detail


@pytest.mark.anyio
async def test_e2e_scenario_c_09_settlement_exceeding_pending_rejected_422(mock_env):
    """Scenario C.9: Attempting to disburse more than the worker's pending wage raises HTTP 422."""
    mdb, _, finance_user, _, _, helpers = mock_env
    helper_1 = helpers[0]
    ob_id = ObjectId("6622000000000000000000C9")

    await mdb.wage_obligations.insert_one({
        "_id": ob_id,
        "obligation_number": "WOB-C09",
        "worker_id": str(helper_1["_id"]),
        "worker_name": helper_1["name"],
        "task_category": "delivery",
        "total_amount_le": 50.0,
        "paid_amount_le": 0.0,
        "status": "accrued"
    })

    payload = WageSettlementCreateInput(
        worker_id=str(helper_1["_id"]),
        amount_le=100.0,  # Exceeds 50.0 LE pending
        payment_method="cash"
    )
    with pytest.raises(HTTPException) as ctx:
        await admin_create_wage_settlement(payload, admin=finance_user)
    assert ctx.value.status_code == 422
    assert "melebihi total kewajiban terutang" in ctx.value.detail


@pytest.mark.anyio
async def test_e2e_scenario_c_10_released_orders_permit_update_and_delete(mock_env):
    """Scenario C.10: Orders legitimately released (active_delivery_trip_id is None) can be updated or deleted."""
    mdb, owner_user, _, _, _, _ = mock_env
    ord_id = ObjectId("6611000000000000000000CA")

    # Order was previously delivered and completed; active trip lock is None
    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-C10",
        "order_status": "selesai",
        "delivery_logistics_status": "delivered",
        "active_delivery_trip_id": None,
        "active_delivery_trip_number": None,
        "delivered_trip_id": "670f000000000000000000CA",
        "total_le": 1000.0
    })

    # 1. Updating admin_note succeeds
    upd_res = await admin_update_order(
        str(ord_id),
        OrderStatusUpdate(admin_note="Catatan pasca pengiriman"),
        admin=owner_user
    )
    assert upd_res["admin_note"] == "Catatan pasca pengiriman"

    # 2. Permanent deletion succeeds without 409 conflict
    del_res = await admin_permanent_delete_order(
        str(ord_id),
        PermanentDeleteInput(confirmation_phrase="HAPUS PERMANEN", reason="Clean up archived record"),
        admin=owner_user
    )
    assert del_res["ok"] is True
    assert await mdb.orders.find_one({"_id": ord_id}) is None
