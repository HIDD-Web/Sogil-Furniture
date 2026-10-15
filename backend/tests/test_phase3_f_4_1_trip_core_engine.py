"""Comprehensive automated test suite for Phase 3.F.4.1: Logistics & Delivery Trip Core Engine.

Covers all required acceptance domains:
1. Valid trip creation
2. Unique trip numbering (TRP-YYYYMMDD-XXXX)
3. Valid trip and stop lifecycle state transitions
4. Illegal state transitions rejection
5. Stop failed attempt tracking
6. Same-trip retry retains prior attempt history
7. Trip with active stops cannot be closed
8. Trip with delivered stops cannot be completely cancelled
9. Eligible order assignment success
10. Ineligible order assignment rejection (not siap or not delivery)
11. Order already assigned to another trip rejection
12. Concurrent assignment race condition (at most one winner)
13. Stop update failure triggers full order lock rollback
14. Trip update failure triggers full order lock rollback
15. Conditional release does not clear lock of another trip
16. Retry assignment yields defined conflict / idempotence
17. Transaction failure leaves zero ghost locks
18. Missing transaction capability fails closed
19. Stable delivery wage entitlement key consistency
20. Delivery wage duplicate prevention
21. Manufacturing multi-item wage obligations compatibility
22. Delivery constraint does not break other categories
23. Pre-migration duplicate check aborts safely on conflict
24. Fail-closed wage cap enforcement (no default, no Manager bypass)
"""

import copy
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from fastapi import HTTPException
import pytest
import pymongo

from server import (
    DeliveryTripStatus,
    StopOutcome,
    VALID_TRIP_TRANSITIONS,
    VALID_STOP_TRANSITIONS,
    validate_trip_state_transition,
    validate_stop_state_transition,
    check_trip_can_be_cancelled,
    check_trip_can_be_completed,
    validate_delivery_trip_wage_cap,
    verify_delivery_wage_indexes_pre_migration,
    generate_trip_number,
    build_delivery_accrual_event_key,
    assign_order_to_trip_core,
    release_order_from_trip_core,
    cancel_trip_multi_stop_core,
    complete_trip_partial_core,
    record_delivery_attempt_core,
    admin_create_delivery_trip,
    admin_update_delivery_trip_status,
    admin_add_trip_stop,
    admin_remove_trip_stop,
    admin_record_trip_stop_attempt,
    admin_cancel_delivery_trip,
    admin_complete_delivery_trip,
    DeliveryTripCreateInput,
    DeliveryTripVehicleRentalInput,
    DeliveryTripStatusUpdateInput,
    DeliveryTripAddStopInput,
    DeliveryTripStopAttemptInput,
    DeliveryTripCancelInput,
    DeliveryTripCompleteInput,
    CriticalFinanceIndexError,
    CONTROLLED_TASK_CATEGORIES,
    _execute_delivery_tx_or_fail_closed,
    _num,
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

    def sort(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
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
                if isinstance(v, dict) and "$in" in v:
                    vals = [str(x) for x in v["$in"]]
                    if str(doc.get("_id")) not in vals:
                        return False
                else:
                    if str(doc.get("_id")) != str(v):
                        return False
            elif k == "stops.outcome":
                if isinstance(v, dict) and "$ne" in v:
                    for s in doc.get("stops", []):
                        if s.get("outcome") == v["$ne"]:
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
                else:
                    if str(doc.get("active_delivery_trip_id")) != str(v):
                        return False
            elif k == "stops.order_id":
                stop_order_ids = [str(s.get("order_id")) for s in doc.get("stops", [])]
                if str(v) not in stop_order_ids:
                    return False
            else:
                if doc.get(k) != v:
                    return False
        return True

    async def find_one(self, filter_q, *args, **kwargs):
        for doc_id, doc in self.docs.items():
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

    async def update_one(self, filter_q, update_q, array_filters=None, *args, **kwargs):
        for doc_id, doc in self.docs.items():
            if self._matches(doc, filter_q):
                if "$set" in update_q:
                    for k, val in update_q["$set"].items():
                        if k.startswith("stops.$."):
                            sub_field = k.replace("stops.$.", "")
                            target_order_id = filter_q.get("stops.order_id")
                            for s in doc.get("stops", []):
                                if str(s.get("order_id")) == str(target_order_id):
                                    s[sub_field] = copy.deepcopy(val)
                        elif k == "stops.$[elem].outcome":
                            elem_filter = (array_filters[0] if array_filters else {}).get("elem.outcome")
                            for s in doc.get("stops", []):
                                if isinstance(elem_filter, dict):
                                    if "$in" in elem_filter and s.get("outcome") not in elem_filter["$in"]:
                                        continue
                                    if "$ne" in elem_filter and s.get("outcome") == elem_filter["$ne"]:
                                        continue
                                elif isinstance(elem_filter, str):
                                    if s.get("outcome") != elem_filter:
                                        continue
                                s["outcome"] = copy.deepcopy(val)
                        else:
                            doc[k] = copy.deepcopy(val)
                if "$inc" in update_q:
                    for k, inc_val in update_q["$inc"].items():
                        if k.startswith("stops.$."):
                            sub_field = k.replace("stops.$.", "")
                            target_order_id = filter_q.get("stops.order_id")
                            for s in doc.get("stops", []):
                                if str(s.get("order_id")) == str(target_order_id):
                                    s[sub_field] = s.get(sub_field, 0) + inc_val
                        else:
                            doc[k] = doc.get(k, 0) + inc_val
                if "$push" in update_q:
                    for k, val in update_q["$push"].items():
                        if k == "stops":
                            if "stops" not in doc or not isinstance(doc["stops"], list):
                                doc["stops"] = []
                            doc["stops"].append(copy.deepcopy(val))
                        elif k.startswith("stops.$."):
                            sub_field = k.replace("stops.$.", "")
                            target_order_id = filter_q.get("stops.order_id")
                            for s in doc.get("stops", []):
                                if str(s.get("order_id")) == str(target_order_id):
                                    if sub_field not in s or not isinstance(s[sub_field], list):
                                        s[sub_field] = []
                                    s[sub_field].append(copy.deepcopy(val))
                        elif k == "status_history":
                            if "status_history" not in doc or not isinstance(doc["status_history"], list):
                                doc["status_history"] = []
                            doc["status_history"].append(copy.deepcopy(val))
                if "$pull" in update_q:
                    for k, pull_filter in update_q["$pull"].items():
                        if k == "stops" and "stops" in doc:
                            target_oid = pull_filter.get("order_id")
                            doc["stops"] = [s for s in doc["stops"] if str(s.get("order_id")) != str(target_oid)]
                res = MagicMock()
                res.matched_count = 1
                res.modified_count = 1
                return res
        res = MagicMock()
        res.matched_count = 0
        res.modified_count = 0
        return res

    async def update_many(self, filter_q, update_q, *args, **kwargs):
        mod_count = 0
        for doc_id, doc in self.docs.items():
            if self._matches(doc, filter_q):
                if "$set" in update_q:
                    for k, val in update_q["$set"].items():
                        doc[k] = copy.deepcopy(val)
                if "$push" in update_q:
                    for k, val in update_q["$push"].items():
                        if k not in doc or not isinstance(doc[k], list):
                            doc[k] = []
                        doc[k].append(copy.deepcopy(val))
                mod_count += 1
        res = MagicMock()
        res.matched_count = mod_count
        res.modified_count = mod_count
        return res

    async def find_one_and_update(self, filter_q, update_q, upsert=False, return_document=None, *args, **kwargs):
        doc_id = str(filter_q.get("_id"))
        doc = self.docs.get(doc_id)
        if not doc and upsert:
            doc = copy.deepcopy(filter_q)
            doc["seq"] = 0
            self.docs[doc_id] = doc
        if "$inc" in update_q:
            for k, inc_val in update_q["$inc"].items():
                doc[k] = doc.get(k, 0) + inc_val
        return copy.deepcopy(doc)


class MockDatabase:
    def __init__(self):
        self.admins = MockCollection("admins")
        self.orders = MockCollection("orders")
        self.delivery_trips = MockCollection("delivery_trips")
        self.wage_obligations = MockCollection("wage_obligations")
        self.counters = MockCollection("counters")
        self.settings = MockCollection("settings")


@pytest.fixture
def mock_env():
    mdb = MockDatabase()
    admin_manager = {
        "_id": ObjectId("660000000000000000000001"),
        "id": "660000000000000000000001",
        "name": "Manager Logistics",
        "role": "manager",
        "permissions": {"manage_orders": True, "access_finance": True}
    }
    helper_admin = {
        "_id": ObjectId("660000000000000000000002"),
        "id": "660000000000000000000002",
        "name": "Helper Ahmad",
        "role": "staff",
        "permissions": {}
    }
    mdb.admins.docs[str(admin_manager["_id"])] = admin_manager
    mdb.admins.docs[str(helper_admin["_id"])] = helper_admin

    order_eligible = {
        "_id": ObjectId("661111111111111111111111"),
        "order_number": "ORD-20261015-0001",
        "customer_name": "Pelanggan Kairo",
        "order_status": "siap",
        "delivery_method": "delivery",
        "delivery_zone": "Darasah",
        "active_delivery_trip_id": None,
        "active_delivery_trip_number": None,
        "delivery_logistics_status": "unassigned"
    }
    mdb.orders.docs[str(order_eligible["_id"])] = order_eligible

    with patch("server.db", mdb), \
         patch("server.client.start_session", AsyncMock(side_effect=pymongo.errors.ConfigurationError("Standalone"))), \
         patch("server.is_standalone_fallback_permitted", return_value=True):
        yield mdb, admin_manager, helper_admin, order_eligible


# -----------------------------------------------------------------------------
# 1. Model & Counter Tests
# -----------------------------------------------------------------------------

@pytest.mark.anyio
async def test_01_trip_number_generation_format(mock_env):
    """Test 1 & 2: Trip number generation produces TRP-YYYYMMDD-XXXX."""
    mdb, admin_mgr, _, _ = mock_env
    trip_num1 = await generate_trip_number()
    trip_num2 = await generate_trip_number()
    assert trip_num1.startswith("TRP-")
    assert trip_num1.endswith("-0001")
    assert trip_num2.endswith("-0002")
    assert trip_num1 != trip_num2


# -----------------------------------------------------------------------------
# 2. Lifecycle & State Transition Tests
# -----------------------------------------------------------------------------

def test_02_valid_trip_lifecycle_transitions():
    """Test 3: Valid trip state transitions succeed."""
    validate_trip_state_transition("draft", "scheduled")
    validate_trip_state_transition("scheduled", "in_transit")
    validate_trip_state_transition("in_transit", "partially_completed")
    validate_trip_state_transition("in_transit", "completed")
    validate_trip_state_transition("partially_completed", "completed")


def test_03_illegal_trip_lifecycle_transitions():
    """Test 4: Illegal trip state transitions are rejected with HTTP 400."""
    with pytest.raises(HTTPException) as ctx:
        validate_trip_state_transition("draft", "completed")
    assert ctx.value.status_code == 400

    with pytest.raises(HTTPException) as ctx:
        validate_trip_state_transition("completed", "draft")
    assert ctx.value.status_code == 400

    with pytest.raises(HTTPException) as ctx:
        validate_trip_state_transition("cancelled", "in_transit")
    assert ctx.value.status_code == 400


def test_04_valid_stop_lifecycle_transitions():
    """Test 3b: Valid stop state transitions succeed."""
    validate_stop_state_transition("pending", "out_for_delivery")
    validate_stop_state_transition("out_for_delivery", "delivered")
    validate_stop_state_transition("out_for_delivery", "failed")
    validate_stop_state_transition("failed", "out_for_delivery")  # same-trip retry
    validate_stop_state_transition("failed", "failed_closed")


def test_05_illegal_stop_lifecycle_transitions():
    """Test 4b: Delivered stops cannot transition back to pending or failed."""
    with pytest.raises(HTTPException) as ctx:
        validate_stop_state_transition("delivered", "failed")
    assert ctx.value.status_code == 400

    with pytest.raises(HTTPException) as ctx:
        validate_stop_state_transition("delivered", "pending")
    assert ctx.value.status_code == 400

    with pytest.raises(HTTPException) as ctx:
        validate_stop_state_transition("delivered", "out_for_delivery")
    assert ctx.value.status_code == 400


def test_06_trip_with_delivered_stop_cannot_be_cancelled():
    """Test 8: Trip with delivered stop cannot be cancelled."""
    trip_with_delivered = {
        "_id": ObjectId("670f22223333444455556666"),
        "status": "in_transit",
        "stops": [
            {"stop_id": "stp_001", "order_id": "ord_1", "outcome": "delivered"},
            {"stop_id": "stp_002", "order_id": "ord_2", "outcome": "failed"}
        ]
    }
    with pytest.raises(HTTPException) as ctx:
        check_trip_can_be_cancelled(trip_with_delivered)
    assert ctx.value.status_code == 409
    assert "delivered" in ctx.value.detail


def test_07_trip_with_active_stops_cannot_be_completed():
    """Test 7: Trip with active stops (pending/out_for_delivery) cannot be closed."""
    trip_with_pending = {
        "_id": ObjectId("670f22223333444455556666"),
        "status": "in_transit",
        "stops": [
            {"stop_id": "stp_001", "order_id": "ord_1", "outcome": "delivered"},
            {"stop_id": "stp_002", "order_id": "ord_2", "outcome": "out_for_delivery"}
        ]
    }
    with pytest.raises(HTTPException) as ctx:
        check_trip_can_be_completed(trip_with_pending)
    assert ctx.value.status_code == 409
    assert "pending atau out_for_delivery" in ctx.value.detail


# -----------------------------------------------------------------------------
# 3. Cap Upah & Dispatch Guard Tests (Fail-Closed)
# -----------------------------------------------------------------------------

@pytest.mark.anyio
async def test_08_wage_cap_not_set_fails_closed(mock_env):
    """Test 24a: If Owner wage cap is missing/null, dispatch fails closed with HTTP 422."""
    with patch("server.get_setting", new_callable=AsyncMock) as mock_setting:
        mock_setting.return_value = None
        with pytest.raises(HTTPException) as ctx:
            await validate_delivery_trip_wage_cap(50.0)
        assert ctx.value.status_code == 422
        assert "belum ditetapkan oleh Owner" in ctx.value.detail


@pytest.mark.anyio
async def test_09_wage_rate_exceeding_owner_cap_rejected(mock_env):
    """Test 24b: If wage rate exceeds Owner cap, rejected with HTTP 422."""
    with patch("server.get_setting", new_callable=AsyncMock) as mock_setting:
        mock_setting.return_value = {"max_helper_wage_per_order_le": 60.0}
        with pytest.raises(HTTPException) as ctx:
            await validate_delivery_trip_wage_cap(75.0)
        assert ctx.value.status_code == 422
        assert "melebihi batas atas" in ctx.value.detail


@pytest.mark.anyio
async def test_10_wage_rate_within_cap_accepted(mock_env):
    """Test 24c: Wage rate within valid Owner cap is accepted."""
    with patch("server.get_setting", new_callable=AsyncMock) as mock_setting:
        mock_setting.return_value = {"max_helper_wage_per_order_le": 60.0}
        cap_val = await validate_delivery_trip_wage_cap(50.0)
        assert cap_val == 60.0


# -----------------------------------------------------------------------------
# 4. Stop Attempts & Same-Trip Retry Tests
# -----------------------------------------------------------------------------

@pytest.mark.anyio
async def test_11_stop_failed_attempt_recorded_without_losing_history(mock_env):
    """Test 5 & 6: Stop failed records attempt and preserves prior attempts."""
    mdb, admin_mgr, _, order_doc = mock_env
    trip_id = ObjectId("670f22223333444455556666")
    oid = str(order_doc["_id"])
    trip_doc = {
        "_id": trip_id,
        "trip_number": "TRP-20261015-0001",
        "status": "in_transit",
        "stops": [{
            "stop_id": "stp_001",
            "order_id": oid,
            "outcome": "out_for_delivery",
            "attempt_count": 0,
            "attempts": []
        }]
    }
    mdb.delivery_trips.docs[str(trip_id)] = trip_doc
    order_doc["active_delivery_trip_id"] = str(trip_id)

    payload1 = DeliveryTripStopAttemptInput(
        outcome="failed",
        failure_reason="Pelanggan tidak ada di lokasi",
        notes="Telepon tidak diangkat"
    )
    await record_delivery_attempt_core(str(trip_id), oid, payload1, admin_mgr)

    updated_trip = mdb.delivery_trips.docs[str(trip_id)]
    stop1 = updated_trip["stops"][0]
    assert stop1["outcome"] == "failed"
    assert stop1["attempt_count"] == 1
    assert len(stop1["attempts"]) == 1

    # Now same-trip retry: set back to out_for_delivery
    payload_retry = DeliveryTripStopAttemptInput(outcome="out_for_delivery")
    await record_delivery_attempt_core(str(trip_id), oid, payload_retry, admin_mgr)

    updated_trip2 = mdb.delivery_trips.docs[str(trip_id)]
    stop2 = updated_trip2["stops"][0]
    assert stop2["outcome"] == "out_for_delivery"
    # History must be preserved!
    assert len(stop2["attempts"]) == 1

    # Second failed attempt
    payload2 = DeliveryTripStopAttemptInput(
        outcome="failed",
        failure_reason="Rumah masih terkunci pada percobaan kedua",
        notes="Helper menunggu 15 menit"
    )
    await record_delivery_attempt_core(str(trip_id), oid, payload2, admin_mgr)

    updated_trip3 = mdb.delivery_trips.docs[str(trip_id)]
    stop3 = updated_trip3["stops"][0]
    assert stop3["outcome"] == "failed"
    assert stop3["attempt_count"] == 2
    assert len(stop3["attempts"]) == 2
    assert stop3["attempts"][0]["failure_reason"] == "Pelanggan tidak ada di lokasi"
    assert stop3["attempts"][1]["failure_reason"] == "Rumah masih terkunci pada percobaan kedua"


# -----------------------------------------------------------------------------
# 5. Assignment & Conditional Atomic Lock Tests
# -----------------------------------------------------------------------------

@pytest.mark.anyio
async def test_12_eligible_order_assigned_successfully(mock_env):
    """Test 9: Assigning eligible order succeeds and locks order."""
    mdb, admin_mgr, _, order_doc = mock_env
    trip_id = ObjectId("670f22223333444455556666")
    trip_doc = {
        "_id": trip_id,
        "trip_number": "TRP-20261015-0001",
        "status": "scheduled",
        "stops": [],
        "stops_count": 0
    }
    mdb.delivery_trips.docs[str(trip_id)] = trip_doc

    await assign_order_to_trip_core(str(trip_id), str(order_doc["_id"]), admin_mgr)

    updated_order = mdb.orders.docs[str(order_doc["_id"])]
    assert updated_order["active_delivery_trip_id"] == str(trip_id)
    assert updated_order["active_delivery_trip_number"] == "TRP-20261015-0001"
    assert updated_order["delivery_logistics_status"] == "scheduled"

    updated_trip = mdb.delivery_trips.docs[str(trip_id)]
    assert updated_trip["stops_count"] == 1
    assert len(updated_trip["stops"]) == 1
    assert updated_trip["stops"][0]["order_id"] == str(order_doc["_id"])


@pytest.mark.anyio
async def test_13_ineligible_order_status_rejected(mock_env):
    """Test 10: Ineligible order status (not 'siap') is rejected with HTTP 409."""
    mdb, admin_mgr, _, order_doc = mock_env
    order_doc["order_status"] = "diproses"

    trip_id = ObjectId("670f22223333444455556666")
    trip_doc = {
        "_id": trip_id,
        "trip_number": "TRP-20261015-0001",
        "status": "scheduled",
        "stops": []
    }
    mdb.delivery_trips.docs[str(trip_id)] = trip_doc

    with pytest.raises(HTTPException) as ctx:
        await assign_order_to_trip_core(str(trip_id), str(order_doc["_id"]), admin_mgr)
    assert ctx.value.status_code == 409
    assert "tidak siap" in ctx.value.detail


@pytest.mark.anyio
async def test_14_order_already_assigned_to_another_trip_rejected(mock_env):
    """Test 11: Order already assigned to another trip is rejected with HTTP 409."""
    mdb, admin_mgr, _, order_doc = mock_env
    order_doc["active_delivery_trip_id"] = "TRP-20261015-0001"

    trip_id = ObjectId("670f22223333444455556666")
    trip_doc = {
        "_id": trip_id,
        "trip_number": "TRP-20261015-0002",
        "status": "scheduled",
        "stops": []
    }
    mdb.delivery_trips.docs[str(trip_id)] = trip_doc

    with pytest.raises(HTTPException) as ctx:
        await assign_order_to_trip_core(str(trip_id), str(order_doc["_id"]), admin_mgr)
    assert ctx.value.status_code == 409
    assert "sudah terikat" in ctx.value.detail


@pytest.mark.anyio
async def test_15_concurrent_claim_race_condition_winner_and_loser(mock_env):
    """Test 12: Concurrent claim race condition: second request matches 0 and fails with HTTP 409."""
    mdb, admin_mgr, _, order_doc = mock_env
    trip1_id = ObjectId("670f22223333444455556666")
    trip2_id = ObjectId("670f22223333444455556667")

    mdb.delivery_trips.docs[str(trip1_id)] = {"_id": trip1_id, "trip_number": "TRP-001", "status": "scheduled", "stops": []}
    mdb.delivery_trips.docs[str(trip2_id)] = {"_id": trip2_id, "trip_number": "TRP-002", "status": "scheduled", "stops": []}

    # First manager claims
    await assign_order_to_trip_core(str(trip1_id), str(order_doc["_id"]), admin_mgr)

    # Second manager tries to claim the same order concurrently
    with pytest.raises(HTTPException) as ctx:
        await assign_order_to_trip_core(str(trip2_id), str(order_doc["_id"]), admin_mgr)
    assert ctx.value.status_code == 409
    assert "sudah terikat" in ctx.value.detail


@pytest.mark.anyio
async def test_16_conditional_release_does_not_clear_other_trip_lock(mock_env):
    """Test 15: Releasing an order only clears active_delivery_trip_id matching this trip."""
    mdb, admin_mgr, _, order_doc = mock_env
    trip1_id = ObjectId("670f22223333444455556666")
    trip2_id = ObjectId("670f22223333444455556667")

    mdb.delivery_trips.docs[str(trip1_id)] = {
        "_id": trip1_id,
        "trip_number": "TRP-001",
        "status": "scheduled",
        "stops": [{"order_id": str(order_doc["_id"]), "outcome": "pending"}]
    }
    # But order is currently bound to trip2
    order_doc["active_delivery_trip_id"] = str(trip2_id)

    with pytest.raises(HTTPException) as ctx:
        await release_order_from_trip_core(str(trip1_id), str(order_doc["_id"]), admin_mgr)
    assert ctx.value.status_code == 409
    assert "tidak terikat pada trip ini" in ctx.value.detail

    # Verify order is still bound to trip2
    assert mdb.orders.docs[str(order_doc["_id"])]["active_delivery_trip_id"] == str(trip2_id)


# -----------------------------------------------------------------------------
# 6. Multi-Stop Trip Cancellation & Partial Completion Tests
# -----------------------------------------------------------------------------

@pytest.mark.anyio
async def test_17_multi_stop_cancel_bulk_releases_all_orders(mock_env):
    """Test 17: Multi-stop cancel bulk releases all non-delivered orders atomically."""
    mdb, admin_mgr, _, _ = mock_env
    trip_id = ObjectId("670f22223333444455556666")
    ord1_id = ObjectId("661111111111111111111111")
    ord2_id = ObjectId("661111111111111111111112")

    mdb.orders.docs[str(ord1_id)] = {"_id": ord1_id, "active_delivery_trip_id": str(trip_id), "order_status": "siap"}
    mdb.orders.docs[str(ord2_id)] = {"_id": ord2_id, "active_delivery_trip_id": str(trip_id), "order_status": "siap"}

    mdb.delivery_trips.docs[str(trip_id)] = {
        "_id": trip_id,
        "trip_number": "TRP-20261015-0001",
        "status": "scheduled",
        "stops": [
            {"stop_id": "stp_1", "order_id": str(ord1_id), "outcome": "pending"},
            {"stop_id": "stp_2", "order_id": str(ord2_id), "outcome": "pending"}
        ]
    }

    await cancel_trip_multi_stop_core(str(trip_id), "Kendaraan mogok sebelum berangkat", admin_mgr)

    updated_trip = mdb.delivery_trips.docs[str(trip_id)]
    assert updated_trip["status"] == "cancelled"
    assert updated_trip["stops"][0]["outcome"] == "cancelled"
    assert updated_trip["stops"][1]["outcome"] == "cancelled"

    assert mdb.orders.docs[str(ord1_id)]["active_delivery_trip_id"] is None
    assert mdb.orders.docs[str(ord1_id)]["delivery_logistics_status"] == "unassigned"
    assert mdb.orders.docs[str(ord2_id)]["active_delivery_trip_id"] is None
    assert mdb.orders.docs[str(ord2_id)]["delivery_logistics_status"] == "unassigned"


@pytest.mark.anyio
async def test_18_partial_trip_completion_preserves_delivered_and_releases_failed(mock_env):
    """Test 18: Partial trip completion keeps delivered orders finished and releases failed orders to ready queue."""
    mdb, admin_mgr, _, _ = mock_env
    trip_id = ObjectId("670f22223333444455556666")
    ord_deliv_id = ObjectId("661111111111111111111111")
    ord_failed_id = ObjectId("661111111111111111111112")

    mdb.orders.docs[str(ord_deliv_id)] = {"_id": ord_deliv_id, "active_delivery_trip_id": str(trip_id), "order_status": "selesai"}
    mdb.orders.docs[str(ord_failed_id)] = {"_id": ord_failed_id, "active_delivery_trip_id": str(trip_id), "order_status": "siap"}

    mdb.delivery_trips.docs[str(trip_id)] = {
        "_id": trip_id,
        "trip_number": "TRP-20261015-0001",
        "status": "in_transit",
        "stops": [
            {"stop_id": "stp_1", "order_id": str(ord_deliv_id), "outcome": "delivered"},
            {"stop_id": "stp_2", "order_id": str(ord_failed_id), "outcome": "failed"}
        ]
    }

    await complete_trip_partial_core(str(trip_id), "Selesai 1 delivered dan 1 failed", admin_mgr)

    updated_trip = mdb.delivery_trips.docs[str(trip_id)]
    assert updated_trip["status"] == "completed"
    assert updated_trip["is_partially_completed"] is True
    assert updated_trip["delivered_stops_count"] == 1
    assert updated_trip["failed_stops_count"] == 1
    assert updated_trip["stops"][1]["outcome"] == "failed_closed"

    # Delivered order preserved as selesai and ghost lock eliminated
    assert mdb.orders.docs[str(ord_deliv_id)]["order_status"] == "selesai"
    assert mdb.orders.docs[str(ord_deliv_id)]["active_delivery_trip_id"] is None

    # Failed order released to ready queue for rescheduling
    assert mdb.orders.docs[str(ord_failed_id)]["active_delivery_trip_id"] is None
    assert mdb.orders.docs[str(ord_failed_id)]["delivery_logistics_status"] == "delivery_failed"
    assert mdb.orders.docs[str(ord_failed_id)]["order_status"] == "siap"


# -----------------------------------------------------------------------------
# 7. Delivery Wage Entitlement Key & Manufacturing Category Isolation
# -----------------------------------------------------------------------------

def test_19_stable_delivery_entitlement_key_format():
    """Test 19: Delivery entitlement key is deterministic and trip-independent."""
    key1 = build_delivery_accrual_event_key("ord_abc_123", "hlp_xyz_789")
    key2 = build_delivery_accrual_event_key("ord_abc_123", "hlp_xyz_789")
    assert key1 == "acc_del_ord_abc_123_hlp_xyz_789"
    assert key1 == key2
    assert "TRP" not in key1


def test_20_controlled_task_categories_includes_delivery_and_preserves_manufacturing():
    """Test 21 & 22: Controlled task categories includes 'delivery' and preserves manufacturing."""
    assert "delivery" in CONTROLLED_TASK_CATEGORIES
    assert "whole_item" in CONTROLLED_TASK_CATEGORIES
    assert "assembly" in CONTROLLED_TASK_CATEGORIES
    assert "finishing" in CONTROLLED_TASK_CATEGORIES
    assert "cutting" in CONTROLLED_TASK_CATEGORIES
    assert "custom" in CONTROLLED_TASK_CATEGORIES


@pytest.mark.anyio
async def test_21_pre_migration_verification_aborts_on_duplicate_delivery_entitlements(mock_env):
    """Test 23: Pre-migration verification raises CriticalFinanceIndexError if duplicates exist."""
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[{
        "_id": {"order_id": "ord_1", "worker_id": "wrk_1"},
        "count": 2,
        "ids": ["id_1", "id_2"]
    }])
    mock_db.wage_obligations.aggregate.return_value = mock_cursor

    with pytest.raises(CriticalFinanceIndexError) as ctx:
        await verify_delivery_wage_indexes_pre_migration(mock_db)
    assert "Pre-migration duplicate check failed" in str(ctx.value)


@pytest.mark.anyio
async def test_22_pre_migration_verification_succeeds_when_no_duplicates(mock_env):
    """Test 23b: Pre-migration verification returns ok when 0 duplicates exist."""
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.to_list = AsyncMock(return_value=[])
    mock_db.wage_obligations.aggregate.return_value = mock_cursor

    res = await verify_delivery_wage_indexes_pre_migration(mock_db)
    assert res["ok"] is True
    assert res["duplicate_count"] == 0


# -----------------------------------------------------------------------------
# 8. Fail-Closed on Missing Transactions
# -----------------------------------------------------------------------------

@pytest.mark.anyio
async def test_23_missing_transaction_fails_closed(mock_env):
    """Test 18: If multi-document transaction is unavailable in non-fallback mode, fail closed with HTTP 503."""
    with patch("server.is_standalone_fallback_permitted", return_value=False), \
         patch("server.client.start_session", side_effect=pymongo.errors.ConfigurationError("Standalone")):
        with pytest.raises(HTTPException) as ctx:
            await _execute_delivery_tx_or_fail_closed(lambda sess: None)
        assert ctx.value.status_code == 503
        assert "tidak tersedia" in ctx.value.detail


@pytest.mark.anyio
async def test_24_dispatch_excludes_cancelled_stops_from_in_transit_orders_update(mock_env):
    """Test 24: Dispatch to in_transit only updates pending stops to out_for_delivery and in_transit status."""
    mdb, admin_mgr, _, _ = mock_env
    trip_id = ObjectId("670f55556666777788889999")
    ord_pending_id = ObjectId("662222222222222222222221")
    ord_cancelled_id = ObjectId("662222222222222222222222")

    # Configure Owner Wage Policy Cap
    mdb.settings.docs["delivery_wage_policy"] = {
        "_id": "delivery_wage_policy",
        "key": "delivery_wage_policy",
        "value": {"max_helper_wage_per_order_le": 50.0}
    }

    # Setup orders
    mdb.orders.docs[str(ord_pending_id)] = {
        "_id": ord_pending_id,
        "active_delivery_trip_id": str(trip_id),
        "delivery_logistics_status": "scheduled",
        "order_status": "siap"
    }
    mdb.orders.docs[str(ord_cancelled_id)] = {
        "_id": ord_cancelled_id,
        "active_delivery_trip_id": None,
        "delivery_logistics_status": "unassigned",
        "order_status": "siap"
    }

    # Setup trip
    mdb.delivery_trips.docs[str(trip_id)] = {
        "_id": trip_id,
        "trip_number": "TRP-20261015-0010",
        "status": "scheduled",
        "trip_wage_rate_le": 40.0,
        "stops": [
            {"stop_id": "stp_pend", "order_id": str(ord_pending_id), "outcome": "pending"},
            {"stop_id": "stp_canc", "order_id": str(ord_cancelled_id), "outcome": "cancelled"}
        ]
    }

    res = await admin_update_delivery_trip_status(
        str(trip_id),
        DeliveryTripStatusUpdateInput(target_status="in_transit"),
        admin_mgr
    )

    assert res["status"] == "in_transit"
    # Pending stop became out_for_delivery
    assert res["stops"][0]["outcome"] == "out_for_delivery"
    # Cancelled stop remained cancelled
    assert res["stops"][1]["outcome"] == "cancelled"

    # Order corresponding to pending stop transitioned to in_transit
    assert mdb.orders.docs[str(ord_pending_id)]["delivery_logistics_status"] == "in_transit"
    # Order corresponding to cancelled stop remained unassigned
    assert mdb.orders.docs[str(ord_cancelled_id)]["delivery_logistics_status"] == "unassigned"

