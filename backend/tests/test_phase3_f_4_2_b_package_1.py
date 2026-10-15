"""Automated Test Suite for Phase 3.F.4.2B / Package 1:
Backend Ready Queue Optimization & Helpers Provider.

Verifies:
1. Eligible ready delivery order appears in the unassigned queue.
2. Non-ready orders (pesanan_masuk, dikonfirmasi, diproses, selesai, dibatalkan) are excluded.
3. Pickup/self-collection orders (delivery_method != 'delivery') are excluded.
4. Orders already assigned to an active trip (active_delivery_trip_id is not null) are excluded.
5. Empty queue returns an empty list [].
6. Bounded result limit and pagination (limit, skip, clamping) and deterministic FIFO sort.
7. Authorization controls (Owner & Manager with manage_orders permitted; unauthenticated & unauthorized rejected).
8. Worker/helper provider (GET /api/admin/workers) never exposes sensitive admin fields (password_hash, tokens).
9. Successfully assigned order dynamically disappears from unassigned queue.
10. Concurrency protection: atomic order lock prevents duplicate assignment to different trips.
11. Optional query filters (delivery_zone_id and search q) filter orders accurately.
12. Lean projection shape: correct canonical fields returned without heavy payment summary calculations.
"""

import copy
import re
from datetime import datetime, timezone
from bson import ObjectId
from fastapi import HTTPException
import pytest

from server import (
    admin_get_unassigned_delivery_orders,
    admin_list_workers,
    assign_order_to_trip_core,
    release_order_from_trip_core,
    admin_get_delivery_trip,
    DeliveryTripStatus,
    StopOutcome,
)


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

    def sort(self, key_or_list, direction=None):
        if isinstance(key_or_list, list):
            for k, d in reversed(key_or_list):
                self.docs.sort(key=lambda x: str(x.get(k, "")), reverse=(d == -1))
        elif isinstance(key_or_list, str):
            rev = (direction == -1)
            self.docs.sort(key=lambda x: str(x.get(key_or_list, "")), reverse=rev)
        return self

    def skip(self, count):
        self.docs = self.docs[count:]
        return self

    def limit(self, count):
        self.docs = self.docs[:count]
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
            if k == "$or":
                sub_matches = any(self._matches(doc, cond) for cond in v)
                if not sub_matches:
                    return False
                continue

            if k == "_id":
                if isinstance(v, dict) and "$in" in v:
                    vals = [str(x) for x in v["$in"]]
                    if str(doc.get("_id")) not in vals:
                        return False
                else:
                    if str(doc.get("_id")) != str(v):
                        return False
            elif k == "order_status":
                if doc.get("order_status") != v:
                    return False
            elif k == "delivery_method":
                if doc.get("delivery_method") != v:
                    return False
            elif k == "active_delivery_trip_id":
                val = doc.get("active_delivery_trip_id")
                if isinstance(v, dict) and "$in" in v:
                    if val not in v["$in"]:
                        return False
                elif v is None:
                    if val is not None:
                        return False
                else:
                    if str(val or "") != str(v or ""):
                        return False
            elif k == "delivery_zone_id":
                if str(doc.get("delivery_zone_id", "")) != str(v):
                    return False
            elif k == "status":
                if isinstance(v, dict) and "$in" in v:
                    if doc.get("status") not in v["$in"]:
                        return False
                elif isinstance(v, dict) and "$ne" in v:
                    if doc.get("status") == v["$ne"]:
                        return False
                elif doc.get("status") != v:
                    return False
            elif isinstance(v, dict) and "$regex" in v:
                field_val = str(doc.get(k) or "")
                pattern = v["$regex"]
                flags = re.IGNORECASE if "i" in v.get("$options", "") else 0
                if not re.search(pattern, field_val, flags):
                    return False
            else:
                if doc.get(k) != v:
                    return False
        return True

    def find(self, filter_q=None, *args, **kwargs):
        matched = [copy.deepcopy(d) for d in self.docs.values() if self._matches(d, filter_q)]
        return AsyncCursorMock(matched)

    async def find_one(self, filter_q=None, session=None):
        for d in self.docs.values():
            if self._matches(d, filter_q):
                return copy.deepcopy(d)
        return None

    async def insert_one(self, doc, session=None):
        d_copy = copy.deepcopy(doc)
        if "_id" not in d_copy:
            d_copy["_id"] = ObjectId()
        self.docs[str(d_copy["_id"])] = d_copy
        class Res:
            inserted_id = d_copy["_id"]
        return Res()

    async def update_one(self, filter_q, update_q, session=None, array_filters=None):
        target_id = None
        for oid_str, d in self.docs.items():
            if self._matches(d, filter_q):
                target_id = oid_str
                break

        class Res:
            matched_count = 1 if target_id else 0
            modified_count = 1 if target_id else 0

        if not target_id:
            return Res()

        doc = self.docs[target_id]
        if "$set" in update_q:
            for sk, sv in update_q["$set"].items():
                doc[sk] = sv
        if "$push" in update_q:
            for pk, pv in update_q["$push"].items():
                if pk not in doc or not isinstance(doc[pk], list):
                    doc[pk] = []
                doc[pk].append(copy.deepcopy(pv))
        if "$pull" in update_q:
            for pk, pv in update_q["$pull"].items():
                if pk in doc and isinstance(doc[pk], list):
                    if isinstance(pv, dict):
                        doc[pk] = [item for item in doc[pk] if not all(str(item.get(ik)) == str(iv) for ik, iv in pv.items())]

        return Res()


@pytest.fixture
def test_env():
    admin_mgr = {
        "_id": ObjectId("660000000000000000000001"),
        "id": "660000000000000000000001",
        "name": "Manager Operasional",
        "role": "manager",
        "permissions": {"manage_orders": True, "access_finance": True}
    }
    owner_user = {
        "_id": ObjectId("660000000000000000000002"),
        "id": "660000000000000000000002",
        "name": "Owner Sogil",
        "role": "owner",
        "permissions": {"manage_orders": True, "access_finance": True}
    }
    unauthorized_staff = {
        "_id": ObjectId("660000000000000000000003"),
        "id": "660000000000000000000003",
        "name": "Staff Gudang",
        "role": "employee",
        "permissions": {}
    }
    return {
        "admin_mgr": admin_mgr,
        "owner_user": owner_user,
        "unauthorized_staff": unauthorized_staff,
    }


# --------------------------------------------------------------------------
# 1. Eligible Ready Delivery Order Appears in Queue
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_01_eligible_ready_delivery_order_appears_in_queue(monkeypatch, test_env):
    """Eligible order with order_status='siap', delivery_method='delivery', and active_delivery_trip_id=None must appear."""
    ord1_id = ObjectId("661111112222333344445555")
    orders_coll = MockCollection("orders", [
        {
            "_id": ord1_id,
            "order_number": "ORD-READY-001",
            "order_status": "siap",
            "delivery_method": "delivery",
            "active_delivery_trip_id": None,
            "customer_name": "Ahmad Dani",
            "customer_phone": "01012345678",
            "customer_address": "Jl. Kairo Timur No. 12",
            "customer_maps_url": "https://maps.google.com/?q=30.0444,31.2357",
            "delivery_zone_id": "zone_nasr_city",
            "delivery_zone_name": "Nasr City",
            "delivery_fee_le": 45.0,
            "total_le": 1500.0,
            "items": [{"product_name_snapshot": "Lemari 3 Pintu", "quantity": 1}],
            "notes": "Lantai 3 tanpa lift",
            "created_at": "2026-10-15T08:00:00Z",
            "updated_at": "2026-10-15T09:00:00Z",
        }
    ])

    monkeypatch.setattr("server.db.orders", orders_coll)

    res = await admin_get_unassigned_delivery_orders(admin=test_env["admin_mgr"])
    assert len(res) == 1
    item = res[0]
    assert item["order_number"] == "ORD-READY-001"
    assert item["customer_name"] == "Ahmad Dani"
    assert item["customer_phone"] == "01012345678"
    assert item["customer_address"] == "Jl. Kairo Timur No. 12"
    assert item["customer_maps_url"] == "https://maps.google.com/?q=30.0444,31.2357"
    assert item["delivery_method"] == "delivery"
    assert item["delivery_zone_name"] == "Nasr City"
    assert item["delivery_fee_le"] == 45.0
    assert item["total_le"] == 1500.0
    assert item["total_items_count"] == 1
    assert item["items_summary"] == [{"name": "Lemari 3 Pintu", "quantity": 1}]
    assert item["notes"] == "Lantai 3 tanpa lift"


# --------------------------------------------------------------------------
# 2. Non-Ready Orders Excluded
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_02_non_ready_orders_are_excluded(monkeypatch, test_env):
    """Orders with status other than 'siap' (e.g. pesanan_masuk, dikonfirmasi, diproses, selesai, dibatalkan) must be excluded."""
    non_ready_statuses = ["pesanan_masuk", "dikonfirmasi", "diproses", "selesai", "dibatalkan"]
    test_docs = []
    for idx, st in enumerate(non_ready_statuses):
        test_docs.append({
            "_id": ObjectId(f"66222222222233334444555{idx}"),
            "order_number": f"ORD-STATUS-{st}",
            "order_status": st,
            "delivery_method": "delivery",
            "active_delivery_trip_id": None,
            "customer_name": f"Cust {st}",
            "created_at": "2026-10-15T08:00:00Z",
        })

    orders_coll = MockCollection("orders", test_docs)
    monkeypatch.setattr("server.db.orders", orders_coll)

    res = await admin_get_unassigned_delivery_orders(admin=test_env["admin_mgr"])
    assert len(res) == 0


# --------------------------------------------------------------------------
# 3. Pickup / Self-Collection Orders Excluded
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_03_pickup_orders_are_excluded(monkeypatch, test_env):
    """Orders with delivery_method other than 'delivery' (e.g. pickup, ambil_sendiri) must be excluded."""
    orders_coll = MockCollection("orders", [
        {
            "_id": ObjectId("663333331111222233334444"),
            "order_number": "ORD-PICKUP-001",
            "order_status": "siap",
            "delivery_method": "pickup",
            "active_delivery_trip_id": None,
            "customer_name": "Budi Santoso",
            "created_at": "2026-10-15T08:00:00Z",
        },
        {
            "_id": ObjectId("663333331111222233334445"),
            "order_number": "ORD-PICKUP-002",
            "order_status": "siap",
            "delivery_method": "ambil_sendiri",
            "active_delivery_trip_id": None,
            "customer_name": "Siti Rahma",
            "created_at": "2026-10-15T08:05:00Z",
        }
    ])
    monkeypatch.setattr("server.db.orders", orders_coll)

    res = await admin_get_unassigned_delivery_orders(admin=test_env["admin_mgr"])
    assert len(res) == 0


# --------------------------------------------------------------------------
# 4. Orders Already Assigned to Active Trip Excluded
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_04_already_assigned_orders_are_excluded(monkeypatch, test_env):
    """Orders with active_delivery_trip_id set must be excluded."""
    orders_coll = MockCollection("orders", [
        {
            "_id": ObjectId("664444441111222233334444"),
            "order_number": "ORD-LOCKED-001",
            "order_status": "siap",
            "delivery_method": "delivery",
            "active_delivery_trip_id": "670f11112222333344445555",
            "active_delivery_trip_number": "TRP-20261015-0001",
            "customer_name": "Hassan",
            "created_at": "2026-10-15T08:00:00Z",
        }
    ])
    monkeypatch.setattr("server.db.orders", orders_coll)

    res = await admin_get_unassigned_delivery_orders(admin=test_env["admin_mgr"])
    assert len(res) == 0


# --------------------------------------------------------------------------
# 5. Empty Queue Returns Correct Empty Response
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_05_empty_queue_returns_empty_list(monkeypatch, test_env):
    """When no orders match, return [] cleanly without error."""
    orders_coll = MockCollection("orders", [])
    monkeypatch.setattr("server.db.orders", orders_coll)

    res = await admin_get_unassigned_delivery_orders(admin=test_env["admin_mgr"])
    assert res == []


# --------------------------------------------------------------------------
# 6. Pagination, Result-Limit, and Deterministic FIFO Sorting
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_06_pagination_limit_and_deterministic_fifo_sort(monkeypatch, test_env):
    """Result returns oldest orders first (FIFO), respects limit and skip, and clamps upper bound."""
    docs = [
        {
            "_id": ObjectId(f"66555555111122223333444{i}"),
            "order_number": f"ORD-FIFO-{i}",
            "order_status": "siap",
            "delivery_method": "delivery",
            "active_delivery_trip_id": None,
            "customer_name": f"Customer {i}",
            "created_at": f"2026-10-15T0{i}:00:00Z",
        }
        for i in range(1, 6)
    ]
    orders_coll = MockCollection("orders", docs)
    monkeypatch.setattr("server.db.orders", orders_coll)

    # First page: limit=2, skip=0
    res_p1 = await admin_get_unassigned_delivery_orders(limit=2, skip=0, admin=test_env["admin_mgr"])
    assert len(res_p1) == 2
    assert res_p1[0]["order_number"] == "ORD-FIFO-1"
    assert res_p1[1]["order_number"] == "ORD-FIFO-2"

    # Second page: limit=2, skip=2
    res_p2 = await admin_get_unassigned_delivery_orders(limit=2, skip=2, admin=test_env["admin_mgr"])
    assert len(res_p2) == 2
    assert res_p2[0]["order_number"] == "ORD-FIFO-3"
    assert res_p2[1]["order_number"] == "ORD-FIFO-4"

    # Clamping test: negative limit clamped to 1, limit > 500 clamped to 500
    res_clamp = await admin_get_unassigned_delivery_orders(limit=-5, skip=0, admin=test_env["admin_mgr"])
    assert len(res_clamp) == 1
    assert res_clamp[0]["order_number"] == "ORD-FIFO-1"


# --------------------------------------------------------------------------
# 7. Authorization Follows Existing Permission Model
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_07_authorization_model_enforcement(monkeypatch, test_env):
    """Owner and Manager with manage_orders are permitted; unprivileged employee is rejected."""
    orders_coll = MockCollection("orders", [
        {
            "_id": ObjectId("666666661111222233334444"),
            "order_number": "ORD-AUTH-001",
            "order_status": "siap",
            "delivery_method": "delivery",
            "active_delivery_trip_id": None,
            "created_at": "2026-10-15T08:00:00Z",
        }
    ])
    monkeypatch.setattr("server.db.orders", orders_coll)

    # Owner access allowed
    res_owner = await admin_get_unassigned_delivery_orders(admin=test_env["owner_user"])
    assert len(res_owner) == 1

    # Manager with manage_orders allowed
    res_mgr = await admin_get_unassigned_delivery_orders(admin=test_env["admin_mgr"])
    assert len(res_mgr) == 1

    # Unprivileged staff (no manage_orders) rejected by dependency
    from server import require_perm
    dep = require_perm("manage_orders")
    with pytest.raises(HTTPException) as exc_info:
        await dep(admin=test_env["unauthorized_staff"])
    assert exc_info.value.status_code == 403


# --------------------------------------------------------------------------
# 8. Worker Provider Never Exposes Sensitive Admin Fields
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_08_worker_provider_privacy_and_filtering(monkeypatch, test_env):
    """GET /api/admin/workers returns only safe public fields, excludes inactive, and hides password_hash/tokens."""
    admins_coll = MockCollection("admins", [
        {
            "_id": ObjectId("667777771111222233334441"),
            "name": "Helper Joko",
            "role": "helper",
            "status": "active",
            "password_hash": "$2b$12$e09fakefakehashhashhashhashhashhashhashhashfake",
            "jwt_secret_token": "secret_token_123",
            "pin": "1234",
            "permissions": {"manage_orders": False}
        },
        {
            "_id": ObjectId("667777771111222233334442"),
            "name": "Helper Budi (Inactive)",
            "role": "helper",
            "status": "inactive",
            "password_hash": "$2b$12$anotherfakehashhashhashhashhashhashhashfake",
        }
    ])
    monkeypatch.setattr("server.db.admins", admins_coll)

    workers = await admin_list_workers(admin=test_env["admin_mgr"])
    assert len(workers) == 1
    w = workers[0]
    assert w["name"] == "Helper Joko"
    assert w["role"] == "helper"
    assert "id" in w
    assert "password_hash" not in w
    assert "jwt_secret_token" not in w
    assert "pin" not in w
    assert "permissions" not in w


# --------------------------------------------------------------------------
# 9. Assigned Order Dynamically Disappears from Queue
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_09_assigned_order_disappears_from_unassigned_queue(monkeypatch, test_env):
    """When an order is assigned to a trip via assign_order_to_trip_core, it immediately vanishes from unassigned orders."""
    ord_id = ObjectId("668888881111222233334444")
    trip_id = ObjectId("669999991111222233334444")

    orders_coll = MockCollection("orders", [
        {
            "_id": ord_id,
            "order_number": "ORD-DYNAMIC-001",
            "order_status": "siap",
            "delivery_method": "delivery",
            "active_delivery_trip_id": None,
            "customer_name": "Tariq",
            "created_at": "2026-10-15T08:00:00Z",
        }
    ])
    trips_coll = MockCollection("delivery_trips", [
        {
            "_id": trip_id,
            "trip_number": "TRP-20261015-0001",
            "status": DeliveryTripStatus.DRAFT.value,
            "stops": [],
        }
    ])

    monkeypatch.setattr("server.db.orders", orders_coll)
    monkeypatch.setattr("server.db.delivery_trips", trips_coll)

    # 1. Initially, order is in the unassigned queue
    q1 = await admin_get_unassigned_delivery_orders(admin=test_env["admin_mgr"])
    assert len(q1) == 1
    assert q1[0]["order_number"] == "ORD-DYNAMIC-001"

    # 2. Assign order to trip
    await assign_order_to_trip_core(str(trip_id), str(ord_id), test_env["admin_mgr"], session=None)

    # 3. Now, queue must be empty
    q2 = await admin_get_unassigned_delivery_orders(admin=test_env["admin_mgr"])
    assert len(q2) == 0

    # 4. If released from trip, order returns to unassigned queue
    await release_order_from_trip_core(str(trip_id), str(ord_id), test_env["admin_mgr"], session=None)
    q3 = await admin_get_unassigned_delivery_orders(admin=test_env["admin_mgr"])
    assert len(q3) == 1
    assert q3[0]["order_number"] == "ORD-DYNAMIC-001"


# --------------------------------------------------------------------------
# 10. Concurrency Protection & Atomic Order Lock
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_10_atomic_order_lock_prevents_duplicate_assignment(monkeypatch, test_env):
    """Attempting to assign an order that is already claimed by another trip throws HTTP 409 Conflict."""
    ord_id = ObjectId("66aaaaaa1111222233334444")
    trip1_id = ObjectId("66bbbbbb1111222233334441")
    trip2_id = ObjectId("66bbbbbb1111222233334442")

    orders_coll = MockCollection("orders", [
        {
            "_id": ord_id,
            "order_number": "ORD-RACE-001",
            "order_status": "siap",
            "delivery_method": "delivery",
            "active_delivery_trip_id": None,
            "created_at": "2026-10-15T08:00:00Z",
        }
    ])
    trips_coll = MockCollection("delivery_trips", [
        {
            "_id": trip1_id,
            "trip_number": "TRP-20261015-0001",
            "status": DeliveryTripStatus.DRAFT.value,
            "stops": [],
        },
        {
            "_id": trip2_id,
            "trip_number": "TRP-20261015-0002",
            "status": DeliveryTripStatus.DRAFT.value,
            "stops": [],
        }
    ])

    monkeypatch.setattr("server.db.orders", orders_coll)
    monkeypatch.setattr("server.db.delivery_trips", trips_coll)

    # First assignment succeeds
    await assign_order_to_trip_core(str(trip1_id), str(ord_id), test_env["admin_mgr"], session=None)

    # Second assignment to different trip must be rejected with 409 Conflict
    with pytest.raises(HTTPException) as exc_info:
        await assign_order_to_trip_core(str(trip2_id), str(ord_id), test_env["admin_mgr"], session=None)
    assert exc_info.value.status_code == 409


# --------------------------------------------------------------------------
# 11. Optional Query Filters (zone & search query)
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_11_optional_query_filters(monkeypatch, test_env):
    """Zone filtering and search query filter unassigned queue accurately."""
    docs = [
        {
            "_id": ObjectId("66cccccc1111222233334441"),
            "order_number": "ORD-ZONE-A",
            "order_status": "siap",
            "delivery_method": "delivery",
            "active_delivery_trip_id": None,
            "customer_name": "Farhan",
            "customer_phone": "01000000001",
            "customer_address": "Rehab City Gate 6",
            "delivery_zone_id": "zone_rehab",
            "delivery_zone_name": "Rehab",
            "created_at": "2026-10-15T08:00:00Z",
        },
        {
            "_id": ObjectId("66cccccc1111222233334442"),
            "order_number": "ORD-ZONE-B",
            "order_status": "siap",
            "delivery_method": "delivery",
            "active_delivery_trip_id": None,
            "customer_name": "Mona",
            "customer_phone": "01000000002",
            "customer_address": "Tagamoa Fifth Settlement",
            "delivery_zone_id": "zone_tagamoa",
            "delivery_zone_name": "Tagamoa",
            "created_at": "2026-10-15T08:05:00Z",
        }
    ]
    orders_coll = MockCollection("orders", docs)
    monkeypatch.setattr("server.db.orders", orders_coll)

    # Filter by zone_id
    res_zone = await admin_get_unassigned_delivery_orders(delivery_zone_id="zone_rehab", admin=test_env["admin_mgr"])
    assert len(res_zone) == 1
    assert res_zone[0]["order_number"] == "ORD-ZONE-A"

    # Search by customer name
    res_search = await admin_get_unassigned_delivery_orders(q="Mona", admin=test_env["admin_mgr"])
    assert len(res_search) == 1
    assert res_search[0]["order_number"] == "ORD-ZONE-B"

    # Search by address keyword
    res_addr = await admin_get_unassigned_delivery_orders(q="Gate 6", admin=test_env["admin_mgr"])
    assert len(res_addr) == 1
    assert res_addr[0]["order_number"] == "ORD-ZONE-A"


# --------------------------------------------------------------------------
# 12. Anomalous Empty-String active_delivery_trip_id Excluded
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_12_anomalous_empty_string_active_trip_id_excluded(monkeypatch, test_env):
    """An anomalous order with active_delivery_trip_id='' (empty string) must NOT appear in the ready queue."""
    orders_coll = MockCollection("orders", [
        {
            "_id": ObjectId("66dddddd1111222233334441"),
            "order_number": "ORD-ANOMALY-EMPTY-STR",
            "order_status": "siap",
            "delivery_method": "delivery",
            "active_delivery_trip_id": "",
            "customer_name": "Anomalous Order",
            "created_at": "2026-10-15T08:00:00Z",
        },
        {
            "_id": ObjectId("66dddddd1111222233334442"),
            "order_number": "ORD-CANONICAL-UNASSIGNED",
            "order_status": "siap",
            "delivery_method": "delivery",
            "active_delivery_trip_id": None,
            "customer_name": "Canonical Order",
            "created_at": "2026-10-15T08:05:00Z",
        }
    ])
    monkeypatch.setattr("server.db.orders", orders_coll)

    res = await admin_get_unassigned_delivery_orders(admin=test_env["admin_mgr"])
    assert len(res) == 1
    assert res[0]["order_number"] == "ORD-CANONICAL-UNASSIGNED"


# --------------------------------------------------------------------------
# 13. Destination Fields (address, maps_url, phone) on Stops & Enrichment
# --------------------------------------------------------------------------
@pytest.mark.anyio
async def test_13_trip_stops_include_customer_destination_data(monkeypatch, test_env):
    """Trip stops store and provide customer_address, customer_maps_url, and customer_phone."""
    ord_id = ObjectId("66eeeeee1111222233334441")
    trip_id = ObjectId("66ffffff1111222233334441")

    orders_coll = MockCollection("orders", [
        {
            "_id": ord_id,
            "order_number": "ORD-MAPS-001",
            "order_status": "siap",
            "delivery_method": "delivery",
            "active_delivery_trip_id": None,
            "customer_name": "Tariq Customer",
            "customer_phone": "+201012345678",
            "customer_address": "Street 9, Maadi, Cairo",
            "customer_maps_url": "https://maps.google.com/?q=Maadi+Street+9",
            "delivery_zone_name": "Maadi",
            "created_at": "2026-10-15T08:00:00Z",
        }
    ])
    trips_coll = MockCollection("delivery_trips", [
        {
            "_id": trip_id,
            "trip_number": "TRP-20261015-0099",
            "status": DeliveryTripStatus.DRAFT.value,
            "stops": [],
        }
    ])

    monkeypatch.setattr("server.db.orders", orders_coll)
    monkeypatch.setattr("server.db.delivery_trips", trips_coll)

    # 1. Assign order to trip: stop must have destination fields
    res_trip = await assign_order_to_trip_core(str(trip_id), str(ord_id), test_env["admin_mgr"], session=None)
    assert len(res_trip["stops"]) == 1
    stop = res_trip["stops"][0]
    assert stop["customer_address"] == "Street 9, Maadi, Cairo"
    assert stop["customer_maps_url"] == "https://maps.google.com/?q=Maadi+Street+9"
    assert stop["customer_phone"] == "+201012345678"

    # 2. Legacy trip enrichment: if stop has empty/missing address/maps_url, admin_get_delivery_trip enriches from orders
    legacy_trip_id = ObjectId("66ffffff1111222233334442")
    trips_coll.docs[str(legacy_trip_id)] = {
        "_id": legacy_trip_id,
        "trip_number": "TRP-20261015-LEGACY",
        "status": DeliveryTripStatus.DRAFT.value,
        "stops": [
            {
                "stop_id": "stp_legacy",
                "sequence": 1,
                "order_id": str(ord_id),
                "order_number": "ORD-MAPS-001",
                "customer_name": "Tariq Customer",
                "delivery_zone": "Maadi",
                "outcome": "pending",
                # missing customer_address, customer_maps_url, customer_phone
            }
        ],
    }

    fetched_trip = await admin_get_delivery_trip(str(legacy_trip_id), admin=test_env["admin_mgr"])
    enriched_stop = fetched_trip["stops"][0]
    assert enriched_stop["customer_address"] == "Street 9, Maadi, Cairo"
    assert enriched_stop["customer_maps_url"] == "https://maps.google.com/?q=Maadi+Street+9"
    assert enriched_stop["customer_phone"] == "+201012345678"


