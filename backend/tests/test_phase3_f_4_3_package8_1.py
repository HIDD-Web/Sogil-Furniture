"""Automated Test Suite for Phase 3.F.4.3 Package 8.1:
Operational Boundary Hardening.

Covers:
Task A: Active Delivery Trip Order Guards
1. Updating order status on trip-bound order raises HTTP 409.
2. Updating prices, delivery fee, or items on trip-bound order raises HTTP 409.
3. Updating payment method on trip-bound order raises HTTP 409.
4. Updating ONLY admin_note on trip-bound order succeeds without error and without clearing active_delivery_trip_id.
5. Permanently deleting trip-bound order raises HTTP 409.
6. Rejected operations do not mutate order, delete it, or alter trip records.
7. Failed-delivery orders retaining active trip binding remain strictly protected (HTTP 409).
8. Legitimately released orders (after trip cancel, stop release, or partial completion) can be updated/deleted.
9. Ordinary unbound orders continue to behave as before.

Task B: Shared Handover Completion Helper
10. execute_order_handover_completion stamps canonical completion fields and recognized revenue.
11. execute_order_handover_completion stamps delivery logistics context metadata.
12. execute_order_handover_completion rejects ineligible order states (HTTP 409).
13. record_delivery_stop_handover_core uses execute_order_handover_completion seamlessly.
"""

import copy
import re
from datetime import datetime, timezone
from bson import ObjectId
from fastapi import HTTPException
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

import server
from server import (
    admin_update_order,
    admin_permanent_delete_order,
    execute_order_handover_completion,
    record_delivery_stop_handover_core,
    OrderStatusUpdate,
    PermanentDeleteInput,
    DeliveryStopHandoverInput,
    DeliveryTripStatus,
    StopOutcome,
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
                else:
                    if doc.get("order_status") != v:
                        return False
            elif k == "status":
                if isinstance(v, dict) and "$in" in v:
                    if doc.get("status") not in v["$in"]:
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
            elif k == "key":
                if doc.get("key") != v:
                    return False
            elif k == "order_id":
                if str(doc.get("order_id")) != str(v):
                    return False
            elif k == "trip_id":
                if str(doc.get("trip_id")) != str(v):
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

    async def update_one(self, filter_q, update_q, upsert=False, array_filters=None, *args, **kwargs):
        matched = None
        for doc in self.docs.values():
            if self._matches(doc, filter_q):
                matched = doc
                break
        res = MagicMock()
        if not matched:
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
                    for s in matched.get("stops", []):
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

    async def find_one_and_update(self, filter_q, update_q, upsert=False, return_document=None, *args, **kwargs):
        for doc_id, doc in self.docs.items():
            if self._matches(doc, filter_q):
                if "$inc" in update_q:
                    for k, v in update_q["$inc"].items():
                        doc[k] = doc.get(k, 0) + v
                return copy.deepcopy(doc)
        if upsert:
            new_doc = copy.deepcopy(filter_q)
            if "$inc" in update_q:
                for k, v in update_q["$inc"].items():
                    new_doc[k] = v
            self.docs[str(new_doc.get("_id", "new"))] = new_doc
            return copy.deepcopy(new_doc)
        return None

    async def count_documents(self, filter_q=None, *args, **kwargs):
        return len([d for d in self.docs.values() if self._matches(d, filter_q)])


class MockDB:
    def __init__(self):
        self.orders = MockCollection("orders")
        self.delivery_trips = MockCollection("delivery_trips")
        self.wage_obligations = MockCollection("wage_obligations")
        self.work_assignments = MockCollection("work_assignments")
        self.admins = MockCollection("admins")
        self.settings = MockCollection("settings")
        self.finance_transactions = MockCollection("finance_transactions")
        self.counters = MockCollection("counters")
        self.audit_logs = MockCollection("audit_logs")


@pytest.fixture
def mock_env():
    mdb = MockDB()
    owner_user = {
        "_id": ObjectId("660000000000000000000001"),
        "id": "660000000000000000000001",
        "name": "Owner Sogil",
        "role": "owner",
        "permissions": {"manage_orders": True, "access_finance": True, "delete_data": True}
    }
    manager_user = {
        "_id": ObjectId("660000000000000000000002"),
        "id": "660000000000000000000002",
        "name": "Manager Logistics",
        "role": "manager",
        "permissions": {"manage_orders": True, "access_finance": True}
    }
    helper_user = {
        "_id": ObjectId("660000000000000000000003"),
        "id": "660000000000000000000003",
        "name": "Helper Toko",
        "role": "staff",
        "permissions": {}
    }
    mdb.admins.docs[str(owner_user["_id"])] = owner_user
    mdb.admins.docs[str(manager_user["_id"])] = manager_user
    mdb.admins.docs[str(helper_user["_id"])] = helper_user

    with patch.object(server, "db", mdb):
        yield mdb, owner_user, manager_user, helper_user


# ---------------------------------------------------------------------------
# Task A Tests: Active Delivery Trip Order Guards
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_01_update_order_status_trip_bound_rejected_409(mock_env):
    """Test 1: Updating order_status on an order with active_delivery_trip_id returns HTTP 409."""
    mdb, owner_user, _, _ = mock_env
    trip_id = ObjectId("670f00000000000000000001")
    ord_id = ObjectId("660f00000000000000000001")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-20261015-001",
        "order_status": "siap",
        "active_delivery_trip_id": str(trip_id),
        "active_delivery_trip_number": "TRP-20261015-0001",
        "delivery_logistics_status": "in_transit",
        "total_le": 1500.0
    })

    with pytest.raises(HTTPException) as exc_info:
        await admin_update_order(
            str(ord_id),
            OrderStatusUpdate(order_status="diproses"),
            admin=owner_user
        )
    assert exc_info.value.status_code == 409
    assert "sedang terikat pada trip pengiriman aktif" in exc_info.value.detail
    assert "TRP-20261015-0001" in exc_info.value.detail


@pytest.mark.anyio
async def test_02_update_order_price_or_items_trip_bound_rejected_409(mock_env):
    """Test 2: Updating pricing, fees, or line items on trip-bound order returns HTTP 409."""
    mdb, owner_user, _, _ = mock_env
    trip_id = ObjectId("670f00000000000000000002")
    ord_id = ObjectId("660f00000000000000000002")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-20261015-002",
        "order_status": "siap",
        "active_delivery_trip_id": str(trip_id),
        "active_delivery_trip_number": "TRP-20261015-0002",
        "total_le": 2000.0
    })

    # Subtotal change rejected
    with pytest.raises(HTTPException) as exc:
        await admin_update_order(str(ord_id), OrderStatusUpdate(subtotal_le=1800.0), admin=owner_user)
    assert exc.value.status_code == 409

    # Delivery fee change rejected
    with pytest.raises(HTTPException) as exc:
        await admin_update_order(str(ord_id), OrderStatusUpdate(delivery_fee_le=100.0), admin=owner_user)
    assert exc.value.status_code == 409

    # Items change rejected
    with pytest.raises(HTTPException) as exc:
        await admin_update_order(str(ord_id), OrderStatusUpdate(items=[{"item_id": "itm_1", "quantity": 1}]), admin=owner_user)
    assert exc.value.status_code == 409


@pytest.mark.anyio
async def test_03_update_order_payment_method_trip_bound_rejected_409(mock_env):
    """Test 3: Updating payment_method on trip-bound order returns HTTP 409."""
    mdb, owner_user, _, _ = mock_env
    trip_id = ObjectId("670f00000000000000000003")
    ord_id = ObjectId("660f00000000000000000003")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-20261015-003",
        "order_status": "siap",
        "payment_method": "cash",
        "active_delivery_trip_id": str(trip_id),
        "active_delivery_trip_number": "TRP-20261015-0003",
        "total_le": 1000.0
    })

    with pytest.raises(HTTPException) as exc:
        await admin_update_order(str(ord_id), OrderStatusUpdate(payment_method="transfer"), admin=owner_user)
    assert exc.value.status_code == 409
    assert "sedang terikat pada trip pengiriman aktif" in exc.value.detail


@pytest.mark.anyio
async def test_04_update_order_admin_note_only_trip_bound_allowed(mock_env):
    """Test 4: Updating ONLY admin_note on trip-bound order is demonstrably safe and succeeds."""
    mdb, owner_user, _, _ = mock_env
    trip_id = ObjectId("670f00000000000000000004")
    ord_id = ObjectId("660f00000000000000000004")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-20261015-004",
        "order_status": "siap",
        "active_delivery_trip_id": str(trip_id),
        "active_delivery_trip_number": "TRP-20261015-0004",
        "admin_note": "Catatan lama",
        "total_le": 1000.0
    })

    res = await admin_update_order(
        str(ord_id),
        OrderStatusUpdate(admin_note="Pelanggan minta bel rumah dipencet 2x"),
        admin=owner_user
    )
    assert res["admin_note"] == "Pelanggan minta bel rumah dipencet 2x"
    assert res["active_delivery_trip_id"] == str(trip_id)
    assert res["order_status"] == "siap"


@pytest.mark.anyio
async def test_05_permanent_delete_trip_bound_rejected_409(mock_env):
    """Test 5: Permanently deleting trip-bound order returns HTTP 409."""
    mdb, owner_user, _, _ = mock_env
    trip_id = ObjectId("670f00000000000000000005")
    ord_id = ObjectId("660f00000000000000000005")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-20261015-005",
        "order_status": "siap",
        "active_delivery_trip_id": str(trip_id),
        "active_delivery_trip_number": "TRP-20261015-0005",
        "total_le": 1000.0
    })

    with pytest.raises(HTTPException) as exc:
        await admin_permanent_delete_order(
            str(ord_id),
            PermanentDeleteInput(confirmation_phrase="HAPUS PERMANEN", reason="Testing delete"),
            admin=owner_user
        )
    assert exc.value.status_code == 409
    assert "sedang terikat pada trip pengiriman aktif" in exc.value.detail


@pytest.mark.anyio
async def test_06_rejected_operations_leave_database_unmodified(mock_env):
    """Test 6: Rejected 409 operations leave order and trip records completely unmodified."""
    mdb, owner_user, _, _ = mock_env
    trip_id = ObjectId("670f00000000000000000006")
    ord_id = ObjectId("660f00000000000000000006")

    initial_order = {
        "_id": ord_id,
        "order_number": "ORD-20261015-006",
        "order_status": "siap",
        "active_delivery_trip_id": str(trip_id),
        "active_delivery_trip_number": "TRP-20261015-0006",
        "total_le": 1000.0
    }
    initial_trip = {
        "_id": trip_id,
        "trip_number": "TRP-20261015-0006",
        "status": "in_transit",
        "stops": [{"order_id": str(ord_id), "outcome": "out_for_delivery"}]
    }
    await mdb.orders.insert_one(initial_order)
    await mdb.delivery_trips.insert_one(initial_trip)

    # Attempt status modification -> fails
    with pytest.raises(HTTPException):
        await admin_update_order(str(ord_id), OrderStatusUpdate(order_status="dibatalkan"), admin=owner_user)

    # Attempt deletion -> fails
    with pytest.raises(HTTPException):
        await admin_permanent_delete_order(
            str(ord_id),
            PermanentDeleteInput(confirmation_phrase="HAPUS PERMANEN", reason="Attempt delete"),
            admin=owner_user
        )

    # Verify order still exists with original status and trip binding
    ord_after = await mdb.orders.find_one({"_id": ord_id})
    assert ord_after is not None
    assert ord_after["order_status"] == "siap"
    assert ord_after["active_delivery_trip_id"] == str(trip_id)

    # Verify trip still exists unchanged
    trip_after = await mdb.delivery_trips.find_one({"_id": trip_id})
    assert trip_after is not None
    assert trip_after["status"] == "in_transit"
    assert len(trip_after["stops"]) == 1


@pytest.mark.anyio
async def test_07_failed_delivery_attempt_retaining_trip_binding_remains_protected(mock_env):
    """Test 7: An order with a failed delivery attempt that retains active trip binding is still protected."""
    mdb, owner_user, _, _ = mock_env
    trip_id = ObjectId("670f00000000000000000007")
    ord_id = ObjectId("660f00000000000000000007")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-20261015-007",
        "order_status": "siap",
        "active_delivery_trip_id": str(trip_id),
        "delivery_logistics_status": "delivery_attempt_failed",
        "total_le": 1000.0
    })

    with pytest.raises(HTTPException) as exc:
        await admin_update_order(str(ord_id), OrderStatusUpdate(order_status="diproses"), admin=owner_user)
    assert exc.value.status_code == 409


@pytest.mark.anyio
async def test_08_released_order_after_trip_cancellation_or_completion_is_modifiable(mock_env):
    """Test 8: An order whose active trip binding was released (active_delivery_trip_id is None) can be updated or deleted."""
    mdb, owner_user, _, _ = mock_env
    ord_id = ObjectId("660f00000000000000000008")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-20261015-008",
        "order_status": "siap",
        "active_delivery_trip_id": None,
        "delivery_logistics_status": "delivery_failed",
        "total_le": 1000.0
    })

    # Status update succeeds
    res = await admin_update_order(str(ord_id), OrderStatusUpdate(order_status="diproses"), admin=owner_user)
    assert res["order_status"] == "diproses"

    # Permanent delete succeeds (no assignments, no obligations)
    del_res = await admin_permanent_delete_order(
        str(ord_id),
        PermanentDeleteInput(confirmation_phrase="HAPUS PERMANEN", reason="Legitimate release delete"),
        admin=owner_user
    )
    assert del_res["ok"] is True
    assert await mdb.orders.find_one({"_id": ord_id}) is None


@pytest.mark.anyio
async def test_09_unbound_order_standard_behavior_preserved(mock_env):
    """Test 9: Ordinary unbound orders (never on a trip) continue standard behavior."""
    mdb, owner_user, _, _ = mock_env
    ord_id = ObjectId("660f00000000000000000009")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-20261015-009",
        "order_status": "siap",
        "total_le": 500.0
    })

    res = await admin_update_order(str(ord_id), OrderStatusUpdate(order_status="dikonfirmasi"), admin=owner_user)
    assert res["order_status"] == "dikonfirmasi"


# ---------------------------------------------------------------------------
# Task B Tests: Shared Handover Completion Helper
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_10_execute_order_handover_completion_stamps_canonical_fields(mock_env):
    """Test 10: execute_order_handover_completion stamps order_status='selesai', recognized_revenue_le, completed_at, and status_history."""
    mdb, owner_user, _, _ = mock_env
    ord_id = ObjectId("660f00000000000000000010")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-20261015-010",
        "order_status": "siap",
        "total_le": 3200.0
    })

    res = await execute_order_handover_completion(
        order_id=str(ord_id),
        admin=owner_user,
        now_iso="2026-10-15T12:00:00Z"
    )

    assert res["order_status"] == "selesai"
    assert res["recognized_revenue_le"] == 3200.0
    assert res["completed_at"] == "2026-10-15T12:00:00Z"
    assert res["completed_by_id"] == str(owner_user["_id"])
    assert len(res.get("status_history", [])) == 1
    assert res["status_history"][0]["from_status"] == "siap"
    assert res["status_history"][0]["to_status"] == "selesai"


@pytest.mark.anyio
async def test_11_execute_order_handover_completion_stamps_delivery_context(mock_env):
    """Test 11: execute_order_handover_completion stamps delivery logistics context metadata."""
    mdb, owner_user, _, _ = mock_env
    trip_id = ObjectId("670f00000000000000000011")
    ord_id = ObjectId("660f00000000000000000011")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-20261015-011",
        "order_status": "siap",
        "active_delivery_trip_id": str(trip_id),
        "total_le": 4500.0
    })

    ctx = {
        "trip_id": str(trip_id),
        "trip_number": "TRP-20261015-0011",
        "reason": "Pengantaran sukses ke customer"
    }

    res = await execute_order_handover_completion(
        order_id=str(ord_id),
        admin=owner_user,
        now_iso="2026-10-15T13:00:00Z",
        delivery_context=ctx
    )

    assert res["order_status"] == "selesai"
    assert res["delivery_logistics_status"] == "delivered"
    assert res["delivered_trip_id"] == str(trip_id)
    assert res["delivered_trip_number"] == "TRP-20261015-0011"
    assert res["status_history"][0]["reason"] == "Pengantaran sukses ke customer"


@pytest.mark.anyio
async def test_12_execute_order_handover_completion_ineligible_order_rejected(mock_env):
    """Test 12: execute_order_handover_completion rejects non-siap status or completed outside trip."""
    mdb, owner_user, _, _ = mock_env
    trip_id = ObjectId("670f00000000000000000012")
    ord_id = ObjectId("660f00000000000000000012")

    # Status not 'siap'
    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-20261015-012",
        "order_status": "diproses",
        "active_delivery_trip_id": str(trip_id),
        "total_le": 1000.0
    })

    ctx = {"trip_id": str(trip_id), "trip_number": "TRP-20261015-0012"}
    with pytest.raises(HTTPException) as exc:
        await execute_order_handover_completion(
            order_id=str(ord_id),
            admin=owner_user,
            delivery_context=ctx
        )
    assert exc.value.status_code == 409
    assert "tidak dalam status siap antar" in exc.value.detail


@pytest.mark.anyio
async def test_13_record_delivery_stop_handover_core_uses_shared_helper(mock_env):
    """Test 13: record_delivery_stop_handover_core successfully executes via execute_order_handover_completion and records wage obligations."""
    mdb, owner_user, _, helper_user = mock_env
    trip_id = ObjectId("670f00000000000000000013")
    ord_id = ObjectId("660f00000000000000000013")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-20261015-013",
        "order_status": "siap",
        "active_delivery_trip_id": str(trip_id),
        "total_le": 1200.0
    })

    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0013",
        "status": DeliveryTripStatus.IN_TRANSIT.value,
        "helpers": [{"helper_id": str(helper_user["_id"]), "helper_name": helper_user["name"]}],
        "stops": [{
            "order_id": str(ord_id),
            "outcome": StopOutcome.OUT_FOR_DELIVERY.value
        }],
        "rate_policy_snapshot": {"applied_rate_le": 50.0}
    })

    payload = DeliveryStopHandoverInput(
        recipient_name="Ahmad Fauzi",
        helper_confirmed=True,
        handover_notes="Diterima utuh dan lengkap"
    )

    res = await record_delivery_stop_handover_core(
        trip_id=str(trip_id),
        order_id=str(ord_id),
        payload=payload,
        admin=owner_user
    )

    assert res["ok"] is True
    # Order was mutated through shared helper
    assert res["order"]["order_status"] == "selesai"
    assert res["order"]["delivery_logistics_status"] == "delivered"
    assert res["order"]["recognized_revenue_le"] == 1200.0

    # Stop was mutated
    trip_after = await mdb.delivery_trips.find_one({"_id": trip_id})
    assert trip_after["stops"][0]["outcome"] == "delivered"
    assert trip_after["stops"][0]["recipient_name"] == "Ahmad Fauzi"
    assert trip_after["stops"][0]["helper_confirmed"] is True

    # Wage obligation was created
    wobs = await mdb.wage_obligations.find({"order_id": str(ord_id)}).to_list()
    assert len(wobs) == 1
    assert wobs[0]["total_amount_le"] == 50.0
    assert wobs[0]["status"] == "accrued"
