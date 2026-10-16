"""
Automated Test Suite for Phase 3.F.4.2A: Delivery Wage Policy Settings & Recording.

Covers all 24 required invariant areas:
1. Settings & Authorization (Owner vs Finance vs Unauthorized, Validation, Audit History, Dynamic Threshold)
2. Threshold Override (Normal <= 500, Confirmation > 500, Reason validation, Audit record, Cancel abort)
3. Multi-Helper Distribution & Exact Rounding (1, 2, 3, 4 helpers, Sum conservation, Deterministic retries)
4. Handover Lifecycle & Finance Integration (Failed attempt no wage, Successful creates entitlement, Idempotent retry, Settlement distinction, Snapshot immutability)
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
    get_active_delivery_wage_policy,
    calculate_delivery_helper_wage_allocations,
    record_delivery_stop_handover_core,
    admin_get_delivery_wage_policy,
    admin_update_delivery_wage_policy,
    admin_get_delivery_wage_policy_history,
    admin_preview_delivery_wage_allocation,
    admin_deliver_trip_stop,
    DeliveryWagePolicyInput,
    DeliveryWagePreviewInput,
    DeliveryStopHandoverInput,
    DeliveryTripStopAttemptInput,
    DeliveryTripCompleteInput,
    record_delivery_attempt_core,
    complete_trip_partial_core,
    generate_trip_number,
    build_delivery_accrual_event_key,
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
            if k == "$or":
                if not any(self._matches(doc, cond) for cond in v):
                    return False
            elif k == "_id":
                if isinstance(v, dict) and "$in" in v:
                    vals = [str(x) for x in v["$in"]]
                    if str(doc.get("_id")) not in vals:
                        return False
                else:
                    if str(doc.get("_id")) != str(v):
                        return False
            elif isinstance(v, dict) and "$in" in v:
                if doc.get(k) not in v["$in"]:
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
            elif k == "key":
                if doc.get("key") != v:
                    return False
            elif k == "trip_id":
                if str(doc.get("trip_id")) != str(v):
                    return False
            elif k == "order_id":
                if str(doc.get("order_id")) != str(v):
                    return False
            elif k == "entity_type":
                if doc.get("entity_type") != v:
                    return False
            elif k == "worker_id":
                if str(doc.get("worker_id")) != str(v):
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

    async def update_one(self, filter_q, update_q, upsert=False, array_filters=None, *args, **kwargs):
        matched_any = False
        for doc_id, doc in self.docs.items():
            if self._matches(doc, filter_q):
                matched_any = True
                if "$set" in update_q:
                    for k, val in update_q["$set"].items():
                        if k.startswith("stops.$."):
                            sub_field = k.replace("stops.$.", "")
                            target_order_id = filter_q.get("stops.order_id")
                            for s in doc.get("stops", []):
                                if str(s.get("order_id")) == str(target_order_id):
                                    s[sub_field] = copy.deepcopy(val)
                        elif k == "stops.$[elem].outcome":
                            elem_outcome = array_filters[0].get("elem.outcome") if array_filters else None
                            for s in doc.get("stops", []):
                                if elem_outcome is None or s.get("outcome") == elem_outcome:
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
                    for k, pval in update_q["$push"].items():
                        if k.startswith("stops.$."):
                            sub_field = k.replace("stops.$.", "")
                            target_order_id = filter_q.get("stops.order_id")
                            for s in doc.get("stops", []):
                                if str(s.get("order_id")) == str(target_order_id):
                                    if sub_field not in s:
                                        s[sub_field] = []
                                    s[sub_field].append(copy.deepcopy(pval))
                        else:
                            if k not in doc:
                                doc[k] = []
                            doc[k].append(copy.deepcopy(pval))
                res = MagicMock()
                res.modified_count = 1
                res.matched_count = 1
                return res

        if not matched_any and upsert:
            new_doc = copy.deepcopy(filter_q)
            if "$set" in update_q:
                new_doc.update(copy.deepcopy(update_q["$set"]))
            if "_id" not in new_doc:
                new_doc["_id"] = ObjectId()
            self.docs[str(new_doc["_id"])] = new_doc
            res = MagicMock()
            res.modified_count = 1
            res.matched_count = 0
            res.upserted_id = new_doc["_id"]
            return res

        res = MagicMock()
        res.modified_count = 0
        res.matched_count = 0
        return res

    async def update_many(self, filter_q, update_q, *args, **kwargs):
        res = MagicMock()
        res.modified_count = 0
        res.matched_count = 0
        for doc_id, doc in self.docs.items():
            if self._matches(doc, filter_q):
                res.matched_count += 1
                if "$set" in update_q:
                    for k, v in update_q["$set"].items():
                        doc[k] = copy.deepcopy(v)
                if "$push" in update_q:
                    for k, val in update_q["$push"].items():
                        if k not in doc or not isinstance(doc[k], list):
                            doc[k] = []
                        doc[k].append(copy.deepcopy(val))
                res.modified_count += 1
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


class MockDB:
    def __init__(self):
        self.delivery_trips = MockCollection("delivery_trips")
        self.orders = MockCollection("orders")
        self.admins = MockCollection("admins")
        self.settings = MockCollection("settings")
        self.wage_obligations = MockCollection("wage_obligations")
        self.wage_settlements = MockCollection("wage_settlements")
        self.finance_transactions = MockCollection("finance_transactions")
        self.audit_logs = MockCollection("audit_logs")
        self.counters = MockCollection("counters")


@pytest.fixture
def mock_env():
    mdb = MockDB()

    owner_user = {
        "_id": ObjectId("660000000000000000000001"),
        "id": "660000000000000000000001",
        "name": "Boss Owner",
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

    with patch("server.db", mdb), \
         patch("server.client.start_session", side_effect=pymongo.errors.ConfigurationError("mock standalone")), \
         patch("server.is_standalone_fallback_permitted", return_value=True):
        yield mdb, owner_user, finance_user, ops_user, unauthorized_user, [helper_1, helper_2, helper_3]


# =============================================================================
# 1. Settings and Authorization
# =============================================================================

@pytest.mark.anyio
async def test_01_owner_can_read_and_update_policy(mock_env):
    """Test 1: Authenticated Owner can read active policy and update configurable settings."""
    mdb, owner_user, _, _, _, _ = mock_env

    # 1. Read default policy (before explicit configuration)
    policy = await admin_get_delivery_wage_policy(admin=owner_user)
    assert policy["base_wage_per_order_le"] == 50.0
    assert policy["unusual_amount_threshold_le"] == 100.0
    assert policy["max_helper_wage_per_order_le"] == 500.0

    # 2. Update policy as Owner
    new_input = DeliveryWagePolicyInput(
        base_wage_per_order_le=75.0,
        unusual_amount_threshold_le=200.0,
        max_helper_wage_per_order_le=600.0
    )
    updated = await admin_update_delivery_wage_policy(payload=new_input, admin=owner_user)
    assert updated["base_wage_per_order_le"] == 75.0
    assert updated["unusual_amount_threshold_le"] == 200.0
    assert updated["max_helper_wage_per_order_le"] == 600.0
    assert updated["updated_by_name"] == owner_user["name"]

    # 3. Verify persisted in db.settings
    saved = await mdb.settings.find_one({"key": "delivery_wage_policy"})
    assert saved["value"]["base_wage_per_order_le"] == 75.0
    assert saved["value"]["unusual_amount_threshold_le"] == 200.0
    assert saved["value"]["max_helper_wage_per_order_le"] == 600.0


@pytest.mark.anyio
async def test_02_finance_authorized_non_owner_read_only(mock_env):
    """Test 2: Users with finance permission can read/use active policy, but cannot update it."""
    mdb, owner_user, finance_user, _, _, _ = mock_env

    # 1. Finance user can read policy
    policy = await admin_get_delivery_wage_policy(admin=finance_user)
    assert policy["base_wage_per_order_le"] == 50.0
    assert policy["unusual_amount_threshold_le"] == 100.0
    assert policy["max_helper_wage_per_order_le"] == 500.0

    # 2. Finance user attempting to update policy is rejected with 403 Forbidden
    new_input = DeliveryWagePolicyInput(
        base_wage_per_order_le=100.0,
        unusual_amount_threshold_le=200.0,
        max_helper_wage_per_order_le=800.0
    )
    with pytest.raises(HTTPException) as ctx:
        await admin_update_delivery_wage_policy(payload=new_input, admin=finance_user)
    assert ctx.value.status_code == 403
    assert "Hanya Owner/CEO" in ctx.value.detail


@pytest.mark.anyio
async def test_03_unauthorized_user_rejected(mock_env):
    """Test 3: Users without finance permissions are rejected from reading policy."""
    mdb, _, _, _, unauthorized_user, _ = mock_env

    # Directly invoking dependency logic or endpoint
    with patch("server.get_current_admin", return_value=unauthorized_user):
        from server import require_perm
        check_fin = require_perm("access_finance")
        with pytest.raises(HTTPException) as ctx:
            await check_fin(admin=unauthorized_user)
        assert ctx.value.status_code == 403


@pytest.mark.anyio
async def test_04_invalid_or_negative_values_rejected(mock_env):
    """Test 4: Negative or nonsensical values (e.g. threshold < base_wage) are strictly rejected with 422."""
    mdb, owner_user, _, _, _, _ = mock_env

    # 1. Negative base wage rejected
    with pytest.raises(Exception):
        DeliveryWagePolicyInput(base_wage_per_order_le=-10.0, unusual_amount_threshold_le=100.0, max_helper_wage_per_order_le=500.0)

    # 2. Zero or negative threshold rejected
    with pytest.raises(Exception):
        DeliveryWagePolicyInput(base_wage_per_order_le=50.0, unusual_amount_threshold_le=0.0, max_helper_wage_per_order_le=500.0)

    # 3. Threshold lower than base wage rejected by endpoint validator
    invalid_input = DeliveryWagePolicyInput(
        base_wage_per_order_le=300.0,
        unusual_amount_threshold_le=100.0,
        max_helper_wage_per_order_le=500.0
    )
    with pytest.raises(HTTPException) as ctx:
        await admin_update_delivery_wage_policy(payload=invalid_input, admin=owner_user)
    assert ctx.value.status_code == 422
    assert "tidak boleh lebih kecil" in ctx.value.detail

    # 4. Hard cap missing or <= 0 rejected
    invalid_cap = DeliveryWagePolicyInput(
        base_wage_per_order_le=50.0,
        unusual_amount_threshold_le=100.0,
        max_helper_wage_per_order_le=None
    )
    with pytest.raises(HTTPException) as ctx:
        await admin_update_delivery_wage_policy(payload=invalid_cap, admin=owner_user)
    assert ctx.value.status_code == 422
    assert "hard cap" in ctx.value.detail

    # 5. Threshold >= hard cap rejected
    invalid_tier = DeliveryWagePolicyInput(
        base_wage_per_order_le=50.0,
        unusual_amount_threshold_le=500.0,
        max_helper_wage_per_order_le=500.0
    )
    with pytest.raises(HTTPException) as ctx:
        await admin_update_delivery_wage_policy(payload=invalid_tier, admin=owner_user)
    assert ctx.value.status_code == 422
    assert "lebih kecil dari batas maksimum keras" in ctx.value.detail


@pytest.mark.anyio
async def test_05_policy_change_history_recorded_in_audit_log(mock_env):
    """Test 5: Updates record previous values, new values, changed fields, and user identity in audit history."""
    mdb, owner_user, finance_user, _, _, _ = mock_env

    # Update 1: Set to 60.0 LE
    await admin_update_delivery_wage_policy(
        payload=DeliveryWagePolicyInput(base_wage_per_order_le=60.0, unusual_amount_threshold_le=200.0, max_helper_wage_per_order_le=600.0),
        admin=owner_user
    )

    history = await admin_get_delivery_wage_policy_history(admin=finance_user)
    assert len(history) >= 1
    latest = history[0]
    assert latest["action"] == "update_delivery_wage_policy"
    assert latest["performed_by_name"] == owner_user["name"]
    assert "base_wage_per_order_le" in latest["metadata"]["changed_fields"]
    assert latest["metadata"]["new"]["base_wage_per_order_le"] == 60.0


@pytest.mark.anyio
async def test_06_changing_threshold_affects_future_validations(mock_env):
    """Test 6: Increasing or lowering the threshold dynamically changes the threshold override trigger."""
    mdb, owner_user, finance_user, _, _, helpers = mock_env

    # 1. Set threshold to 300 LE, hard cap 500 LE
    await admin_update_delivery_wage_policy(
        payload=DeliveryWagePolicyInput(base_wage_per_order_le=50.0, unusual_amount_threshold_le=300.0, max_helper_wage_per_order_le=500.0),
        admin=owner_user
    )

    # 2. Preview 350 LE wage: should require confirmation now (350 > 300 and <= 500)
    prev = await admin_preview_delivery_wage_allocation(
        payload=DeliveryWagePreviewInput(total_wage_le=350.0, helpers=[helpers[0]]),
        admin=finance_user
    )
    assert prev["requires_confirmation"] is True
    assert prev["threshold_le"] == 300.0
    assert prev["exceeds_hard_cap"] is False

    # 3. Increase threshold to 1000 LE, hard cap 2000 LE
    await admin_update_delivery_wage_policy(
        payload=DeliveryWagePolicyInput(base_wage_per_order_le=50.0, unusual_amount_threshold_le=1000.0, max_helper_wage_per_order_le=2000.0),
        admin=owner_user
    )

    # 4. Preview 350 LE wage again: should no longer require confirmation (350 <= 1000)
    prev2 = await admin_preview_delivery_wage_allocation(
        payload=DeliveryWagePreviewInput(total_wage_le=350.0, helpers=[helpers[0]]),
        admin=finance_user
    )
    assert prev2["requires_confirmation"] is False
    assert prev2["threshold_le"] == 1000.0
    assert prev2["exceeds_hard_cap"] is False


# =============================================================================
# 2. Threshold Override Flow
# =============================================================================

@pytest.mark.anyio
async def test_07_amount_at_or_below_threshold_normal_flow(mock_env):
    """Test 7: Amounts at or below threshold (e.g. 50 EGP or 80 EGP) do not require override confirmation."""
    mdb, _, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000001")
    ord_id = ObjectId("660f00000000000000000001")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-001",
        "order_status": "siap",
        "active_delivery_trip_id": str(trip_id),
        "total_le": 1500.0
    })
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0001",
        "status": "in_transit",
        "trip_wage_rate_le": 50.0,
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": "out_for_delivery"}]
    })

    # Deliver with normal custom wage 80.0 LE (<= 100 threshold) without confirmation/reason
    res = await record_delivery_stop_handover_core(
        trip_id=str(trip_id),
        order_id=str(ord_id),
        payload=DeliveryStopHandoverInput(recipient_name="Pak Budi", helper_confirmed=True, custom_wage_le=80.0),
        admin=finance_user
    )
    assert res["ok"] is True
    assert len(res["wage_obligations"]) == 1
    assert res["wage_obligations"][0]["total_amount_le"] == 80.0


@pytest.mark.anyio
async def test_08_amount_above_threshold_requires_confirmation(mock_env):
    """Test 8: An amount exceeding 100 EGP (e.g. 250 LE <= 500 hard cap) without confirmed_unusual_amount is rejected with 422."""
    mdb, _, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000002")
    ord_id = ObjectId("660f00000000000000000002")

    await mdb.orders.insert_one({"_id": ord_id, "order_status": "siap", "active_delivery_trip_id": str(trip_id), "total_le": 2000.0})
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0002",
        "status": "in_transit",
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": "out_for_delivery"}]
    })

    # Unconfirmed 250 LE (> 100 threshold, <= 500 hard cap)
    with pytest.raises(HTTPException) as ctx:
        await record_delivery_stop_handover_core(
            trip_id=str(trip_id),
            order_id=str(ord_id),
            payload=DeliveryStopHandoverInput(
                recipient_name="Pak Budi",
                helper_confirmed=True,
                custom_wage_le=250.0,
                confirmed_unusual_amount=False
            ),
            admin=finance_user
        )
    assert ctx.value.status_code == 422
    assert "melebihi batas konfirmasi" in ctx.value.detail


@pytest.mark.anyio
async def test_09_confirming_without_meaningful_reason_rejected(mock_env):
    """Test 9: Confirming amount > threshold without a meaningful reason (empty or < 5 chars) is rejected."""
    mdb, _, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000003")
    ord_id = ObjectId("660f00000000000000000003")

    await mdb.orders.insert_one({"_id": ord_id, "order_status": "siap", "active_delivery_trip_id": str(trip_id), "total_le": 2000.0})
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0003",
        "status": "in_transit",
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": "out_for_delivery"}]
    })

    with pytest.raises(HTTPException) as ctx:
        await record_delivery_stop_handover_core(
            trip_id=str(trip_id),
            order_id=str(ord_id),
            payload=DeliveryStopHandoverInput(
                recipient_name="Pak Budi",
                helper_confirmed=True,
                custom_wage_le=250.0,
                confirmed_unusual_amount=True,
                override_reason="ok"  # Too short
            ),
            admin=finance_user
        )
    assert ctx.value.status_code == 422
    assert "minimal 5 karakter" in ctx.value.detail


@pytest.mark.anyio
async def test_10_valid_confirmation_and_reason_permits_recording_without_owner_approval(mock_env):
    """Test 10: Valid confirmation and meaningful reason permits recording directly without Owner approval."""
    mdb, _, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000004")
    ord_id = ObjectId("660f00000000000000000004")

    await mdb.orders.insert_one({"_id": ord_id, "order_number": "ORD-004", "order_status": "siap", "active_delivery_trip_id": str(trip_id), "total_le": 2000.0})
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0004",
        "status": "in_transit",
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": "out_for_delivery"}]
    })

    res = await record_delivery_stop_handover_core(
        trip_id=str(trip_id),
        order_id=str(ord_id),
        payload=DeliveryStopHandoverInput(
            recipient_name="Pak Budi",
            helper_confirmed=True,
            custom_wage_le=350.0,
            confirmed_unusual_amount=True,
            override_reason="Pengantaran naik ke lantai 5 tanpa lift untuk lemari 3 pintu jati"
        ),
        admin=finance_user
    )
    assert res["ok"] is True
    assert res["wage_obligations"][0]["total_amount_le"] == 350.0
    assert res["wage_obligations"][0]["rate_policy_snapshot"]["is_override"] is True
    assert "lantai 5" in res["wage_obligations"][0]["rate_policy_snapshot"]["override_reason"]


@pytest.mark.anyio
async def test_11_saved_audit_record_contains_full_override_context(mock_env):
    """Test 11: Audit log contains amount, reason, recording user, trip, and order context."""
    mdb, _, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000005")
    ord_id = ObjectId("660f00000000000000000005")

    await mdb.orders.insert_one({"_id": ord_id, "order_number": "ORD-005", "order_status": "siap", "active_delivery_trip_id": str(trip_id), "total_le": 2000.0})
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0005",
        "status": "in_transit",
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": "out_for_delivery"}]
    })

    await record_delivery_stop_handover_core(
        trip_id=str(trip_id),
        order_id=str(ord_id),
        payload=DeliveryStopHandoverInput(
            recipient_name="Pak Budi",
            helper_confirmed=True,
            custom_wage_le=400.0,
            confirmed_unusual_amount=True,
            override_reason="Bongkar muat khusus lokasi terpencil luar kota"
        ),
        admin=finance_user
    )

    audit_entry = await mdb.audit_logs.find_one({"action": "delivery_wage_threshold_override"})
    assert audit_entry is not None
    assert audit_entry["performed_by_name"] == finance_user["name"]
    assert audit_entry["metadata"]["recorded_amount_le"] == 400.0
    assert audit_entry["metadata"]["trip_number"] == "TRP-20261015-0005"
    assert audit_entry["metadata"]["order_number"] == "ORD-005"
    assert "lokasi terpencil" in audit_entry["metadata"]["override_reason"]


@pytest.mark.anyio
async def test_12_cancelled_confirmation_does_not_create_financial_record(mock_env):
    """Test 12: If confirmation is aborted/cancelled by user, zero obligations and zero revenue mutations occur."""
    mdb, _, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000006")
    ord_id = ObjectId("660f00000000000000000006")

    await mdb.orders.insert_one({"_id": ord_id, "order_number": "ORD-006", "order_status": "siap", "active_delivery_trip_id": str(trip_id), "total_le": 2000.0})
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0006",
        "status": "in_transit",
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": "out_for_delivery"}]
    })

    # User cancels modal -> confirmed_unusual_amount is False or request is aborted
    with pytest.raises(HTTPException):
        await record_delivery_stop_handover_core(
            trip_id=str(trip_id),
            order_id=str(ord_id),
            payload=DeliveryStopHandoverInput(
                recipient_name="Pak Budi",
                helper_confirmed=True,
                custom_wage_le=800.0,
                confirmed_unusual_amount=False
            ),
            admin=finance_user
        )

    # Order remains siap, 0 wage obligations created
    ord_after = await mdb.orders.find_one({"_id": ord_id})
    assert ord_after["order_status"] == "siap"
    assert len(mdb.wage_obligations.docs) == 0


# =============================================================================
# 3. Multi-Helper Distribution and Exact Rounding
# =============================================================================

def test_13_one_helper_receives_entire_base_wage():
    """Test 13: 1 helper receives 50.00 EGP (100% of base wage)."""
    helpers = [{"helper_id": "h1", "helper_name": "Joko"}]
    allocs = calculate_delivery_helper_wage_allocations(50.0, helpers)
    assert len(allocs) == 1
    assert allocs[0]["amount_le"] == 50.0
    assert allocs[0]["amount_piastres"] == 5000


def test_14_two_helpers_receive_equal_allocations():
    """Test 14: 2 helpers receive 25.00 EGP each."""
    helpers = [{"helper_id": "h1", "helper_name": "Joko"}, {"helper_id": "h2", "helper_name": "Budi"}]
    allocs = calculate_delivery_helper_wage_allocations(50.0, helpers)
    assert len(allocs) == 2
    assert allocs[0]["amount_le"] == 25.0
    assert allocs[1]["amount_le"] == 25.0
    assert sum(a["amount_piastres"] for a in allocs) == 5000


def test_15_three_helpers_receive_16_67_16_67_and_16_66():
    """Test 15: 3 helpers receive 16.67, 16.67, and 16.66 EGP respectively."""
    helpers = [
        {"helper_id": "h1", "helper_name": "Joko"},
        {"helper_id": "h2", "helper_name": "Budi"},
        {"helper_id": "h3", "helper_name": "Doni"}
    ]
    allocs = calculate_delivery_helper_wage_allocations(50.0, helpers)
    assert len(allocs) == 3
    assert allocs[0]["amount_le"] == 16.67
    assert allocs[1]["amount_le"] == 16.67
    assert allocs[2]["amount_le"] == 16.66
    assert sum(a["amount_piastres"] for a in allocs) == 5000
    assert sum(a["amount_le"] for a in allocs) == 50.0


def test_16_four_helpers_receive_12_50_each():
    """Test 16: 4 helpers receive 12.50 EGP each."""
    helpers = [
        {"helper_id": f"h{i}", "helper_name": f"H{i}"} for i in range(1, 5)
    ]
    allocs = calculate_delivery_helper_wage_allocations(50.0, helpers)
    assert len(allocs) == 4
    for a in allocs:
        assert a["amount_le"] == 12.50
        assert a["amount_piastres"] == 1250
    assert sum(a["amount_piastres"] for a in allocs) == 5000


@pytest.mark.parametrize("total,n", [
    (50.0, 1), (50.0, 2), (50.0, 3), (50.0, 4), (50.0, 5), (50.0, 6), (50.0, 7),
    (75.25, 3), (100.33, 4), (120.0, 3), (250.0, 7), (555.55, 3), (999.99, 6)
])
def test_17_all_allocations_sum_exactly_to_base_wage_no_money_lost_or_created(total, n):
    """Test 17: Invariant check across diverse helper counts and amounts: zero money drift."""
    helpers = [{"helper_id": f"h{i}", "helper_name": f"H{i}"} for i in range(n)]
    allocs = calculate_delivery_helper_wage_allocations(total, helpers)
    expected_piastres = int(Decimal(str(total)).quantize(Decimal("0.01")) * 100)
    actual_piastres = sum(a["amount_piastres"] for a in allocs)
    assert actual_piastres == expected_piastres, f"Mismatch: {actual_piastres} != {expected_piastres}"
    assert round(sum(a["amount_le"] for a in allocs), 2) == round(total, 2)


def test_18_repeated_calculations_and_retries_deterministic_duplicate_free():
    """Test 18: Calculations are purely deterministic across repeated executions."""
    helpers = [{"helper_id": f"h{i}", "helper_name": f"H{i}"} for i in range(3)]
    res1 = calculate_delivery_helper_wage_allocations(50.0, helpers)
    res2 = calculate_delivery_helper_wage_allocations(50.0, helpers)
    assert res1 == res2


# =============================================================================
# 4. Handover Lifecycle and Finance Integration
# =============================================================================

@pytest.mark.anyio
async def test_19_failed_handover_attempt_does_not_create_wage_obligations(mock_env):
    """Test 19: An unsuccessful delivery attempt does not generate any wage obligation."""
    mdb, _, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000010")
    ord_id = ObjectId("660f00000000000000000010")

    await mdb.orders.insert_one({"_id": ord_id, "order_status": "siap", "active_delivery_trip_id": str(trip_id)})
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0010",
        "status": "in_transit",
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": "out_for_delivery", "attempts": []}]
    })

    # Record failed attempt
    await record_delivery_attempt_core(
        trip_id=str(trip_id),
        order_id=str(ord_id),
        payload=DeliveryTripStopAttemptInput(outcome="failed", failure_reason="Penerima tidak ada"),
        admin=finance_user
    )

    # Invariant: 0 wage obligations created
    assert len(mdb.wage_obligations.docs) == 0


@pytest.mark.anyio
async def test_20_successful_handover_creates_correct_entitlement(mock_env):
    """Test 20: Successful handover marks order delivered, recognizes revenue, and creates accrued wage obligations."""
    mdb, _, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000011")
    ord_id = ObjectId("660f00000000000000000011")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-011",
        "order_status": "siap",
        "active_delivery_trip_id": str(trip_id),
        "total_le": 2500.0
    })
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0011",
        "status": "in_transit",
        "trip_wage_rate_le": 50.0,
        "helpers": [
            {"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]},
            {"helper_id": str(helpers[1]["_id"]), "helper_name": helpers[1]["name"]}
        ],
        "stops": [{"order_id": str(ord_id), "outcome": "out_for_delivery"}],
        "rate_policy_snapshot": {"applied_rate_le": 50.0, "locked_at": "2026-10-15T01:00:00Z"}
    })

    res = await record_delivery_stop_handover_core(
        trip_id=str(trip_id),
        order_id=str(ord_id),
        payload=DeliveryStopHandoverInput(recipient_name="Ibu Fatimah", handover_notes="Diterima rapi", helper_confirmed=True),
        admin=finance_user
    )

    assert res["ok"] is True
    # Order invariants
    ord_doc = await mdb.orders.find_one({"_id": ord_id})
    assert ord_doc["order_status"] == "selesai"
    assert ord_doc["recognized_revenue_le"] == 2500.0
    assert ord_doc["delivery_logistics_status"] == "delivered"

    # Wage obligations: 2 helpers -> 25.00 each
    wobs = await mdb.wage_obligations.find({"order_id": str(ord_id)}).to_list()
    assert len(wobs) == 2
    for w in wobs:
        assert w["total_amount_le"] == 25.0
        assert w["status"] == "accrued"
        assert w["task_category"] == "delivery"


@pytest.mark.anyio
async def test_21_repeated_handover_requests_do_not_duplicate_entitlements(mock_env):
    """Test 21: Idempotency replay check: sending deliver again on already delivered stop returns success without duplicates."""
    mdb, _, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000012")
    ord_id = ObjectId("660f00000000000000000012")

    await mdb.orders.insert_one({"_id": ord_id, "order_number": "ORD-012", "order_status": "siap", "active_delivery_trip_id": str(trip_id), "total_le": 1000.0})
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0012",
        "status": "in_transit",
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": "out_for_delivery"}],
        "rate_policy_snapshot": {"applied_rate_le": 50.0, "locked_at": "2026-10-15T01:00:00Z"}
    })

    # Call 1: Success
    res1 = await record_delivery_stop_handover_core(
        trip_id=str(trip_id),
        order_id=str(ord_id),
        payload=DeliveryStopHandoverInput(recipient_name="Pak Budi", helper_confirmed=True),
        admin=finance_user
    )
    assert res1["ok"] is True
    assert len(mdb.wage_obligations.docs) == 1

    # Call 2: Replay (idempotent)
    res2 = await record_delivery_stop_handover_core(
        trip_id=str(trip_id),
        order_id=str(ord_id),
        payload=DeliveryStopHandoverInput(recipient_name="Pak Budi", helper_confirmed=True),
        admin=finance_user
    )
    assert res2["ok"] is True
    assert res2.get("already_delivered") is True
    # Total wage obligations in DB remains exactly 1!
    assert len(mdb.wage_obligations.docs) == 1


@pytest.mark.anyio
async def test_22_settling_delivery_wage_does_not_count_same_expense_twice(mock_env):
    """Test 22: Accrual creates obligation; cash expense is only recorded upon settlement, preventing double-counting."""
    mdb, _, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000013")
    ord_id = ObjectId("660f00000000000000000013")

    await mdb.orders.insert_one({"_id": ord_id, "order_number": "ORD-013", "order_status": "siap", "active_delivery_trip_id": str(trip_id), "total_le": 1000.0})
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0013",
        "status": "in_transit",
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": "out_for_delivery"}],
        "rate_policy_snapshot": {"applied_rate_le": 50.0, "locked_at": "2026-10-15T01:00:00Z"}
    })

    # Handover -> creates wage obligation
    await record_delivery_stop_handover_core(
        trip_id=str(trip_id),
        order_id=str(ord_id),
        payload=DeliveryStopHandoverInput(recipient_name="Pak Budi", helper_confirmed=True),
        admin=finance_user
    )

    # Invariant: finance_transactions count is 0 (obligation is not cash expense)
    assert len(mdb.finance_transactions.docs) == 0


@pytest.mark.anyio
async def test_23_historical_allocations_remain_unchanged_after_policy_update(mock_env):
    """Test 23: Subsequent Owner updates to policy do not mutate historical records."""
    mdb, owner_user, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000014")
    ord_id = ObjectId("660f00000000000000000014")

    await mdb.orders.insert_one({"_id": ord_id, "order_number": "ORD-014", "order_status": "siap", "active_delivery_trip_id": str(trip_id), "total_le": 1000.0})
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0014",
        "status": "in_transit",
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": "out_for_delivery"}],
        "rate_policy_snapshot": {"applied_rate_le": 50.0, "locked_at": "2026-10-15T01:00:00Z"}
    })

    # 1. Handover recorded under initial 50 LE policy
    await record_delivery_stop_handover_core(
        trip_id=str(trip_id),
        order_id=str(ord_id),
        payload=DeliveryStopHandoverInput(recipient_name="Pak Budi", helper_confirmed=True),
        admin=finance_user
    )
    wob = (await mdb.wage_obligations.find({"order_id": str(ord_id)}).to_list())[0]
    assert wob["total_amount_le"] == 50.0

    # 2. Owner raises policy base wage to 100 LE
    await admin_update_delivery_wage_policy(
        payload=DeliveryWagePolicyInput(base_wage_per_order_le=100.0, unusual_amount_threshold_le=200.0, max_helper_wage_per_order_le=700.0),
        admin=owner_user
    )

    # 3. Invariant: Historical obligation remains 50.0 LE!
    wob_after = (await mdb.wage_obligations.find({"order_id": str(ord_id)}).to_list())[0]
    assert wob_after["total_amount_le"] == 50.0


@pytest.mark.anyio
async def test_24_dispatch_snapshot_consistency(mock_env):
    """Test 24: Dispatch snapshot locked at departure time is used during handover."""
    mdb, _, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000015")
    ord_id = ObjectId("660f00000000000000000015")

    await mdb.orders.insert_one({"_id": ord_id, "order_number": "ORD-015", "order_status": "siap", "active_delivery_trip_id": str(trip_id), "total_le": 1000.0})
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0015",
        "status": "in_transit",
        "trip_wage_rate_le": 65.0,
        "rate_policy_snapshot": {
            "applied_rate_le": 65.0,
            "max_cap_at_dispatch_le": 500.0,
            "locked_at": "2026-10-15T01:00:00Z"
        },
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": "out_for_delivery"}]
    })

    # Handover uses the locked 65.0 LE dispatch snapshot
    res = await record_delivery_stop_handover_core(
        trip_id=str(trip_id),
        order_id=str(ord_id),
        payload=DeliveryStopHandoverInput(recipient_name="Pak Budi", helper_confirmed=True),
        admin=finance_user
    )
    assert res["wage_obligations"][0]["total_amount_le"] == 65.0


@pytest.mark.anyio
async def test_25_dispatch_captures_active_policy_when_trip_rate_zero(mock_env):
    """Test 25: Dispatching a trip with trip_wage_rate_le == 0 captures the active policy base wage (50 LE)."""
    from server import admin_update_delivery_trip_status, DeliveryTripStatusUpdateInput
    mdb, owner_user, _, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000025")
    ord_id = ObjectId("660f00000000000000000025")

    # Seed cap in settings
    await mdb.settings.insert_one({
        "key": "delivery_wage_policy",
        "value": {
            "base_wage_per_order_le": 50.0,
            "unusual_amount_threshold_le": 500.0,
            "max_helper_wage_per_order_le": 500.0,
            "currency": "EGP",
            "rounding_policy": "piastre_round_half_up"
        }
    })

    await mdb.orders.insert_one({"_id": ord_id, "order_number": "ORD-025", "order_status": "siap", "active_delivery_trip_id": str(trip_id), "total_le": 1000.0})
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0025",
        "status": "scheduled",
        "trip_wage_rate_le": 0.0,
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": "pending"}]
    })

    res = await admin_update_delivery_trip_status(
        trip_id=str(trip_id),
        payload=DeliveryTripStatusUpdateInput(target_status="in_transit"),
        admin=owner_user
    )
    assert res["status"] == "in_transit"
    snapshot = res["rate_policy_snapshot"]
    assert snapshot["applied_rate_le"] == 50.0
    assert snapshot["is_custom_rate"] is False
    assert snapshot["currency"] == "EGP"


@pytest.mark.anyio
async def test_26_policy_update_after_dispatch_does_not_affect_running_trip(mock_env):
    """Test 26: Dispatching at 50 LE, then Owner raising policy to 80 LE, ensures running trip still hands over at 50 LE."""
    from server import admin_update_delivery_trip_status, DeliveryTripStatusUpdateInput
    mdb, owner_user, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000026")
    ord_id = ObjectId("660f00000000000000000026")

    # Initial policy 50 LE
    await mdb.settings.insert_one({
        "key": "delivery_wage_policy",
        "value": {
            "base_wage_per_order_le": 50.0,
            "unusual_amount_threshold_le": 500.0,
            "max_helper_wage_per_order_le": 500.0,
            "currency": "EGP",
            "rounding_policy": "piastre_round_half_up"
        }
    })

    await mdb.orders.insert_one({"_id": ord_id, "order_number": "ORD-026", "order_status": "siap", "active_delivery_trip_id": str(trip_id), "total_le": 1000.0})
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0026",
        "status": "scheduled",
        "trip_wage_rate_le": 0.0,
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": "pending"}]
    })

    # Dispatch trip -> locks 50 LE snapshot
    await admin_update_delivery_trip_status(
        trip_id=str(trip_id),
        payload=DeliveryTripStatusUpdateInput(target_status="in_transit"),
        admin=owner_user
    )

    # Owner changes active policy to 80 LE
    await admin_update_delivery_wage_policy(
        payload=DeliveryWagePolicyInput(base_wage_per_order_le=80.0, unusual_amount_threshold_le=200.0, max_helper_wage_per_order_le=800.0),
        admin=owner_user
    )

    # Handover occurs on the running trip without custom_wage_le
    res = await record_delivery_stop_handover_core(
        trip_id=str(trip_id),
        order_id=str(ord_id),
        payload=DeliveryStopHandoverInput(recipient_name="Pak Budi", helper_confirmed=True),
        admin=finance_user
    )
    # Obligation must be 50.0 LE (the immutable dispatch snapshot rate), NOT 80.0 LE!
    assert res["wage_obligations"][0]["total_amount_le"] == 50.0


@pytest.mark.anyio
async def test_27_legacy_trip_without_snapshot_fails_closed(mock_env):
    """Test 27: An already-dispatched legacy trip lacking a rate_policy_snapshot rejects default handover with HTTP 422."""
    mdb, _, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000027")
    ord_id = ObjectId("660f00000000000000000027")

    await mdb.orders.insert_one({"_id": ord_id, "order_number": "ORD-027", "order_status": "siap", "active_delivery_trip_id": str(trip_id), "total_le": 1000.0})
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0027",
        "status": "in_transit",
        "rate_policy_snapshot": None,  # Legacy trip without snapshot
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": "out_for_delivery"}]
    })

    with pytest.raises(HTTPException) as ctx:
        await record_delivery_stop_handover_core(
            trip_id=str(trip_id),
            order_id=str(ord_id),
            payload=DeliveryStopHandoverInput(recipient_name="Pak Budi", helper_confirmed=True),
            admin=finance_user
        )
    assert ctx.value.status_code == 422
    assert "Legacy / Unversioned Trip" in ctx.value.detail


@pytest.mark.anyio
async def test_28_legacy_trip_with_custom_wage_succeeds_as_recovery_path(mock_env):
    """Test 28: A legacy trip without snapshot can be safely recovered by specifying custom_wage_le explicitly."""
    mdb, _, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000028")
    ord_id = ObjectId("660f00000000000000000028")

    await mdb.orders.insert_one({"_id": ord_id, "order_number": "ORD-028", "order_status": "siap", "active_delivery_trip_id": str(trip_id), "total_le": 1000.0})
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0028",
        "status": "in_transit",
        "rate_policy_snapshot": None,
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": "out_for_delivery"}]
    })

    res = await record_delivery_stop_handover_core(
        trip_id=str(trip_id),
        order_id=str(ord_id),
        payload=DeliveryStopHandoverInput(recipient_name="Pak Budi", helper_confirmed=True, custom_wage_le=55.0),
        admin=finance_user
    )
    assert res["ok"] is True
    assert res["wage_obligations"][0]["total_amount_le"] == 55.0


@pytest.mark.anyio
async def test_29_helper_confirmation_and_recipient_proof_requirements(mock_env):
    """Test 29: Handover strictly requires non-empty recipient_name and explicit helper_confirmed=True; rejects otherwise with HTTP 422."""
    mdb, _, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000029")
    ord_id = ObjectId("660f00000000000000000029")

    await mdb.orders.insert_one({"_id": ord_id, "order_number": "ORD-029", "order_status": "siap", "active_delivery_trip_id": str(trip_id), "total_le": 1000.0})
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0029",
        "status": "in_transit",
        "rate_policy_snapshot": {"applied_rate_le": 50.0, "locked_at": "2026-10-15T01:00:00Z"},
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [
            {"order_id": str(ord_id), "outcome": "out_for_delivery", "helper_confirmed": False}
        ]
    })

    # Case A: Missing recipient_name (None / omitted)
    with pytest.raises(HTTPException) as ctx_a:
        await record_delivery_stop_handover_core(
            trip_id=str(trip_id),
            order_id=str(ord_id),
            payload=DeliveryStopHandoverInput(helper_confirmed=True),
            admin=finance_user
        )
    assert ctx_a.value.status_code == 422
    assert "Nama penerima" in ctx_a.value.detail

    # Case B: Blank / whitespace-only recipient_name
    for blank_val in ["", "   ", "\t  \n"]:
        with pytest.raises(HTTPException) as ctx_b:
            await record_delivery_stop_handover_core(
                trip_id=str(trip_id),
                order_id=str(ord_id),
                payload=DeliveryStopHandoverInput(recipient_name=blank_val, helper_confirmed=True),
                admin=finance_user
            )
        assert ctx_b.value.status_code == 422
        assert "Nama penerima" in ctx_b.value.detail

    # Case C: Missing helper_confirmed (default False / omitted)
    with pytest.raises(HTTPException) as ctx_c:
        await record_delivery_stop_handover_core(
            trip_id=str(trip_id),
            order_id=str(ord_id),
            payload=DeliveryStopHandoverInput(recipient_name="Pak Budi"),
            admin=finance_user
        )
    assert ctx_c.value.status_code == 422
    assert "helper wajib dicentang" in ctx_c.value.detail

    # Case D: Explicit helper_confirmed=False
    with pytest.raises(HTTPException) as ctx_d:
        await record_delivery_stop_handover_core(
            trip_id=str(trip_id),
            order_id=str(ord_id),
            payload=DeliveryStopHandoverInput(recipient_name="Pak Budi", helper_confirmed=False),
            admin=finance_user
        )
    assert ctx_d.value.status_code == 422
    assert "helper wajib dicentang" in ctx_d.value.detail

    # Case E: Valid recipient_name and explicit helper_confirmed=True succeeds
    res = await record_delivery_stop_handover_core(
        trip_id=str(trip_id),
        order_id=str(ord_id),
        payload=DeliveryStopHandoverInput(recipient_name="  Pak Budi  ", helper_confirmed=True),
        admin=finance_user
    )
    assert res["ok"] is True
    stop = next(s for s in res["trip"]["stops"] if s["order_id"] == str(ord_id))
    assert stop["helper_confirmed"] is True
    assert stop["recipient_name"] == "Pak Budi"


@pytest.mark.anyio
async def test_30_rejected_handover_creates_no_mutations_or_entitlements(mock_env):
    """Test 30: When handover is rejected for invalid proof, zero wage obligations, zero stop mutations, zero order mutations, and zero revenue recognition occur."""
    mdb, _, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000030")
    ord_id = ObjectId("660f00000000000000000030")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-030",
        "order_status": "siap",
        "active_delivery_trip_id": str(trip_id),
        "total_le": 1500.0,
        "recognized_revenue_le": None
    })
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0030",
        "status": "in_transit",
        "delivered_stops_count": 0,
        "rate_policy_snapshot": {"applied_rate_le": 50.0, "locked_at": "2026-10-15T01:00:00Z"},
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [
            {
                "order_id": str(ord_id),
                "outcome": "out_for_delivery",
                "delivered_at": None,
                "recipient_name": None,
                "helper_confirmed": False
            }
        ]
    })

    # Attempt handover without helper confirmation
    with pytest.raises(HTTPException):
        await record_delivery_stop_handover_core(
            trip_id=str(trip_id),
            order_id=str(ord_id),
            payload=DeliveryStopHandoverInput(recipient_name="Pak Budi", helper_confirmed=False),
            admin=finance_user
        )

    # Invariant 1: No wage obligations created
    assert len(mdb.wage_obligations.docs) == 0

    # Invariant 2: Order remains in 'siap' status with zero revenue recognition
    ord_after = await mdb.orders.find_one({"_id": ord_id})
    assert ord_after["order_status"] == "siap"
    assert ord_after.get("recognized_revenue_le") is None
    assert ord_after.get("delivery_logistics_status") != "delivered"

    # Invariant 3: Stop remains 'out_for_delivery' and trip delivered count remains 0
    trip_after = await mdb.delivery_trips.find_one({"_id": trip_id})
    assert trip_after["delivered_stops_count"] == 0
    stop_after = trip_after["stops"][0]
    assert stop_after["outcome"] == "out_for_delivery"
    assert stop_after.get("delivered_at") is None
    assert stop_after.get("helper_confirmed") is False


@pytest.mark.anyio
async def test_31_delivery_failure_reason_validation(mock_env):
    """Test 31: Recording delivery failure requires a non-empty failure reason of at least 3 trimmed chars."""
    mdb, _, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000031")
    ord_id = ObjectId("660f00000000000000000031")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-F31",
        "order_status": "siap",
        "delivery_logistics_status": "scheduled",
        "active_delivery_trip_id": str(trip_id),
    })
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0031",
        "status": "in_transit",
        "rate_policy_snapshot": {"applied_rate_le": 50.0},
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [
            {
                "order_id": str(ord_id),
                "outcome": "out_for_delivery",
                "attempt_count": 0,
                "attempts": []
            }
        ]
    })

    # None / empty / whitespace / < 3 chars must raise HTTP 422
    for bad_reason in [None, "", "  ", "ab", " a "]:
        with pytest.raises(HTTPException) as exc_info:
            await record_delivery_attempt_core(
                trip_id=str(trip_id),
                order_id=str(ord_id),
                payload=DeliveryTripStopAttemptInput(outcome="failed", failure_reason=bad_reason),
                admin=finance_user
            )
        assert exc_info.value.status_code == 422

    # Stop and order remain unmutated
    trip = await mdb.delivery_trips.find_one({"_id": trip_id})
    assert trip["stops"][0]["outcome"] == "out_for_delivery"
    assert trip["stops"][0]["attempt_count"] == 0


@pytest.mark.anyio
async def test_32_stop_lifecycle_transition_enforcement(mock_env):
    """Test 32: Stop transitions to 'failed' are only valid from 'out_for_delivery'."""
    mdb, _, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000032")
    ord_id = ObjectId("660f00000000000000000032")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-F32",
        "order_status": "siap",
        "active_delivery_trip_id": str(trip_id),
    })
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0032",
        "status": "in_transit",
        "rate_policy_snapshot": {"applied_rate_le": 50.0},
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [
            {
                "order_id": str(ord_id),
                "outcome": "pending",  # Invalid: cannot fail directly from pending
                "attempt_count": 0,
                "attempts": []
            }
        ]
    })

    # Attempting to fail a pending stop must raise HTTP 400
    with pytest.raises(HTTPException) as exc_info:
        await record_delivery_attempt_core(
            trip_id=str(trip_id),
            order_id=str(ord_id),
            payload=DeliveryTripStopAttemptInput(outcome="failed", failure_reason="Rumah kosong"),
            admin=finance_user
        )
    assert exc_info.value.status_code == 400
    assert "Transisi status stop tidak valid" in exc_info.value.detail

    # Similarly, a delivered stop cannot transition to failed
    await mdb.delivery_trips.update_one(
        {"_id": trip_id, "stops.order_id": str(ord_id)},
        {"$set": {"stops.$.outcome": "delivered"}}
    )
    with pytest.raises(HTTPException) as exc_info:
        await record_delivery_attempt_core(
            trip_id=str(trip_id),
            order_id=str(ord_id),
            payload=DeliveryTripStopAttemptInput(outcome="failed", failure_reason="Customer komplain"),
            admin=finance_user
        )
    assert exc_info.value.status_code == 400


@pytest.mark.anyio
async def test_33_delivery_failure_creates_zero_wages_and_updates_history(mock_env):
    """Test 33: A recorded delivery failure creates zero wage obligations, zero finance records, and records attempt history."""
    mdb, _, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000033")
    ord_id = ObjectId("660f00000000000000000033")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-F33",
        "order_status": "siap",
        "delivery_logistics_status": "out_for_delivery",
        "active_delivery_trip_id": str(trip_id),
        "status_history": []
    })
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0033",
        "status": "in_transit",
        "rate_policy_snapshot": {"applied_rate_le": 50.0},
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [
            {
                "order_id": str(ord_id),
                "outcome": "out_for_delivery",
                "attempt_count": 0,
                "attempts": []
            }
        ]
    })

    await record_delivery_attempt_core(
        trip_id=str(trip_id),
        order_id=str(ord_id),
        payload=DeliveryTripStopAttemptInput(
            outcome="failed",
            failure_reason="Penerima tidak dapat dihubungi",
            notes="Sudah telepon 3 kali via WhatsApp"
        ),
        admin=finance_user
    )

    # Invariant 1: Exactly ZERO wage obligations created
    assert len(mdb.wage_obligations.docs) == 0

    # Invariant 2: Trip stop outcome is 'failed', attempt_count is 1
    updated_trip = await mdb.delivery_trips.find_one({"_id": trip_id})
    stop = updated_trip["stops"][0]
    assert stop["outcome"] == "failed"
    assert stop["attempt_count"] == 1
    assert len(stop["attempts"]) == 1
    attempt = stop["attempts"][0]
    assert attempt["attempt_number"] == 1
    assert attempt["outcome"] == "failed"
    assert attempt["failure_reason"] == "Penerima tidak dapat dihubungi"
    assert attempt["notes"] == "Sudah telepon 3 kali via WhatsApp"
    assert attempt["recorded_by_name"] == finance_user["name"]

    # Invariant 3: Order remains in 'siap' status with logistics status 'delivery_attempt_failed'
    ord_after = await mdb.orders.find_one({"_id": ord_id})
    assert ord_after["order_status"] == "siap"
    assert ord_after["delivery_logistics_status"] == "delivery_attempt_failed"
    assert len(ord_after["status_history"]) == 1
    assert "Percobaan pengantaran #1 gagal" in ord_after["status_history"][0]["reason"]


@pytest.mark.anyio
async def test_34_retry_workflow_transitions_back_to_out_for_delivery(mock_env):
    """Test 34: A failed stop can be retried back to 'out_for_delivery' with status history recorded."""
    mdb, _, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000034")
    ord_id = ObjectId("660f00000000000000000034")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-F34",
        "order_status": "siap",
        "delivery_logistics_status": "delivery_attempt_failed",
        "active_delivery_trip_id": str(trip_id),
        "status_history": []
    })
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0034",
        "status": "in_transit",
        "rate_policy_snapshot": {"applied_rate_le": 50.0},
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [
            {
                "order_id": str(ord_id),
                "outcome": "failed",
                "attempt_count": 1,
                "failure_reason": "Alamat salah",
                "attempts": [
                    {
                        "attempt_number": 1,
                        "outcome": "failed",
                        "failure_reason": "Alamat salah"
                    }
                ]
            }
        ]
    })

    # Execute retry
    await record_delivery_attempt_core(
        trip_id=str(trip_id),
        order_id=str(ord_id),
        payload=DeliveryTripStopAttemptInput(outcome="out_for_delivery"),
        admin=finance_user
    )

    # Invariant 1: Stop outcome transitions back to 'out_for_delivery'
    updated_trip = await mdb.delivery_trips.find_one({"_id": trip_id})
    stop = updated_trip["stops"][0]
    assert stop["outcome"] == "out_for_delivery"
    # attempt_count remains 1 (retrying does not increment attempt count)
    assert stop["attempt_count"] == 1
    assert len(stop["attempts"]) == 1

    # Invariant 2: Order logistics status updated to 'retry_in_progress' and order_status is still 'siap'
    ord_after = await mdb.orders.find_one({"_id": ord_id})
    assert ord_after["order_status"] == "siap"
    assert ord_after["delivery_logistics_status"] == "retry_in_progress"
    assert len(ord_after["status_history"]) == 1
    assert "Retry" in ord_after["status_history"][0]["reason"]


@pytest.mark.anyio
async def test_35_handover_after_retry_creates_no_duplicate_wages(mock_env):
    """Test 35: Subsequent successful handover after retry creates exactly one wage entitlement per helper, no duplicates."""
    mdb, _, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000035")
    ord_id = ObjectId("660f00000000000000000035")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-F35",
        "order_status": "siap",
        "delivery_logistics_status": "retry_in_progress",
        "active_delivery_trip_id": str(trip_id),
        "total_le": 2000.0,
        "recognized_revenue_le": None,
        "status_history": []
    })
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0035",
        "status": "in_transit",
        "rate_policy_snapshot": {"applied_rate_le": 60.0, "locked_at": "2026-10-15T02:00:00Z"},
        "helpers": [
            {"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]},
            {"helper_id": str(helpers[1]["_id"]), "helper_name": helpers[1]["name"]}
        ],
        "delivered_stops_count": 0,
        "stops": [
            {
                "order_id": str(ord_id),
                "outcome": "out_for_delivery",  # retried
                "attempt_count": 1,
                "failure_reason": "Penerima tidak ada",
                "attempts": [
                    {
                        "attempt_number": 1,
                        "outcome": "failed",
                        "failure_reason": "Penerima tidak ada"
                    }
                ]
            }
        ]
    })

    # Perform handover with Package 5 proof requirements
    await record_delivery_stop_handover_core(
        trip_id=str(trip_id),
        order_id=str(ord_id),
        payload=DeliveryStopHandoverInput(
            recipient_name="Ibu Siti",
            helper_confirmed=True,
            handover_notes="Diterima tetangga sebelah rumah"
        ),
        admin=finance_user
    )

    # Invariant 1: Exactly 2 wage obligations created (1 for each helper), total 60.0 LE (30.0 LE each)
    assert len(mdb.wage_obligations.docs) == 2
    wobs = list(mdb.wage_obligations.docs.values())
    assert sum(w["total_amount_le"] for w in wobs) == 60.0
    for w in wobs:
        assert w["status"] == "accrued"
        assert w["order_id"] == str(ord_id)

    # Invariant 2: Order is completed with revenue recognized
    ord_after = await mdb.orders.find_one({"_id": ord_id})
    assert ord_after["order_status"] == "selesai"
    assert ord_after["delivery_logistics_status"] == "delivered"
    assert ord_after["recognized_revenue_le"] == 2000.0

    # Invariant 3: Calling handover again is idempotent and creates NO extra wage obligations
    await record_delivery_stop_handover_core(
        trip_id=str(trip_id),
        order_id=str(ord_id),
        payload=DeliveryStopHandoverInput(
            recipient_name="Ibu Siti",
            helper_confirmed=True
        ),
        admin=finance_user
    )
    assert len(mdb.wage_obligations.docs) == 2


@pytest.mark.anyio
async def test_36_multiple_failure_attempts_accumulate_history(mock_env):
    """Test 36: Repeated failure attempts accumulate structured history with distinct attempt numbers and maintain zero wage obligations."""
    mdb, _, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000036")
    ord_id = ObjectId("660f00000000000000000036")

    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-F36",
        "order_status": "siap",
        "delivery_logistics_status": "out_for_delivery",
        "active_delivery_trip_id": str(trip_id),
        "status_history": []
    })
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0036",
        "status": "in_transit",
        "rate_policy_snapshot": {"applied_rate_le": 50.0},
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [
            {
                "order_id": str(ord_id),
                "outcome": "out_for_delivery",
                "attempt_count": 0,
                "attempts": []
            }
        ]
    })

    # Attempt 1: Failed
    await record_delivery_attempt_core(
        trip_id=str(trip_id),
        order_id=str(ord_id),
        payload=DeliveryTripStopAttemptInput(outcome="failed", failure_reason="Penerima tidak ada"),
        admin=finance_user
    )

    # Retry 1: back to out_for_delivery
    await record_delivery_attempt_core(
        trip_id=str(trip_id),
        order_id=str(ord_id),
        payload=DeliveryTripStopAttemptInput(outcome="out_for_delivery"),
        admin=finance_user
    )

    # Attempt 2: Failed again with different reason
    await record_delivery_attempt_core(
        trip_id=str(trip_id),
        order_id=str(ord_id),
        payload=DeliveryTripStopAttemptInput(outcome="failed", failure_reason="Akses jalan ditutup warga", notes="Ada hajatan"),
        admin=finance_user
    )

    # Verification:
    # 1. Total attempt_count is 2
    trip_doc = await mdb.delivery_trips.find_one({"_id": trip_id})
    stop = trip_doc["stops"][0]
    assert stop["outcome"] == "failed"
    assert stop["attempt_count"] == 2
    assert len(stop["attempts"]) == 2
    assert stop["attempts"][0]["attempt_number"] == 1
    assert stop["attempts"][0]["failure_reason"] == "Penerima tidak ada"
    assert stop["attempts"][1]["attempt_number"] == 2
    assert stop["attempts"][1]["failure_reason"] == "Akses jalan ditutup warga"
    assert stop["attempts"][1]["notes"] == "Ada hajatan"

    # 2. Wage obligations are STILL ZERO
    assert len(mdb.wage_obligations.docs) == 0


# -----------------------------------------------------------------------------
# 11. Trip Completion Engine & Ghost Lock Elimination (Package 7A)
# -----------------------------------------------------------------------------

@pytest.mark.anyio
async def test_37_complete_trip_all_delivered_eliminates_ghost_locks_and_preserves_history(mock_env):
    """Test 37: Complete trip with all delivered stops unsets active trip locks on delivered orders while preserving historical stamps."""
    mdb, _, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000037")
    ord_id_1 = ObjectId("660f00000000000000000037")
    ord_id_2 = ObjectId("660f00000000000000000038")

    await mdb.orders.insert_one({
        "_id": ord_id_1,
        "order_number": "ORD-T37-1",
        "order_status": "selesai",
        "delivery_logistics_status": "delivered",
        "active_delivery_trip_id": str(trip_id),
        "active_delivery_trip_number": "TRP-20261015-0037",
        "delivered_trip_id": str(trip_id),
        "delivered_trip_number": "TRP-20261015-0037",
        "recognized_revenue_le": 1500.0,
        "completed_at": "2026-10-15T10:00:00+00:00",
        "status_history": []
    })
    await mdb.orders.insert_one({
        "_id": ord_id_2,
        "order_number": "ORD-T37-2",
        "order_status": "selesai",
        "delivery_logistics_status": "delivered",
        "active_delivery_trip_id": str(trip_id),
        "active_delivery_trip_number": "TRP-20261015-0037",
        "delivered_trip_id": str(trip_id),
        "delivered_trip_number": "TRP-20261015-0037",
        "recognized_revenue_le": 2500.0,
        "completed_at": "2026-10-15T10:30:00+00:00",
        "status_history": []
    })
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0037",
        "status": "in_transit",
        "stops": [
            {"stop_id": "stp_1", "order_id": str(ord_id_1), "outcome": "delivered"},
            {"stop_id": "stp_2", "order_id": str(ord_id_2), "outcome": "delivered"}
        ]
    })

    res = await complete_trip_partial_core(str(trip_id), "Semua pesanan selesai dengan lancar", finance_user)

    # 1. Trip document assertions
    assert res["status"] == "completed"
    assert res["is_partially_completed"] is False
    assert res["delivered_stops_count"] == 2
    assert res["failed_stops_count"] == 0
    assert res["completed_at"] is not None
    assert res["completion_notes"] == "Semua pesanan selesai dengan lancar"

    # 2. Ghost lock eliminated on delivered orders
    ord_1_after = await mdb.orders.find_one({"_id": ord_id_1})
    assert ord_1_after["active_delivery_trip_id"] is None
    assert ord_1_after["active_delivery_trip_number"] is None
    assert ord_1_after["order_status"] == "selesai"
    assert ord_1_after["delivery_logistics_status"] == "delivered"
    assert ord_1_after["delivered_trip_id"] == str(trip_id)
    assert ord_1_after["delivered_trip_number"] == "TRP-20261015-0037"
    assert ord_1_after["recognized_revenue_le"] == 1500.0
    assert ord_1_after["completed_at"] == "2026-10-15T10:00:00+00:00"

    ord_2_after = await mdb.orders.find_one({"_id": ord_id_2})
    assert ord_2_after["active_delivery_trip_id"] is None
    assert ord_2_after["active_delivery_trip_number"] is None
    assert ord_2_after["order_status"] == "selesai"
    assert ord_2_after["delivery_logistics_status"] == "delivered"
    assert ord_2_after["delivered_trip_id"] == str(trip_id)
    assert ord_2_after["delivered_trip_number"] == "TRP-20261015-0037"
    assert ord_2_after["recognized_revenue_le"] == 2500.0
    assert ord_2_after["completed_at"] == "2026-10-15T10:30:00+00:00"


@pytest.mark.anyio
async def test_38_complete_trip_mixed_stops_canonical_status_and_failed_order_release(mock_env):
    """Test 38: Mixed delivered and failed stops set canonical completed status, is_partially_completed=True, transitions stops to failed_closed, and releases failed orders to ready queue."""
    mdb, _, finance_user, _, _, _ = mock_env
    trip_id = ObjectId("670f00000000000000000038")
    ord_deliv_id = ObjectId("660f00000000000000000039")
    ord_failed_id = ObjectId("660f0000000000000000003a")

    await mdb.orders.insert_one({
        "_id": ord_deliv_id,
        "order_number": "ORD-T38-DELIV",
        "order_status": "selesai",
        "delivery_logistics_status": "delivered",
        "active_delivery_trip_id": str(trip_id),
        "active_delivery_trip_number": "TRP-20261015-0038",
        "delivered_trip_id": str(trip_id),
        "delivered_trip_number": "TRP-20261015-0038",
        "recognized_revenue_le": 1800.0,
        "completed_at": "2026-10-15T11:00:00+00:00",
        "status_history": []
    })
    await mdb.orders.insert_one({
        "_id": ord_failed_id,
        "order_number": "ORD-T38-FAILED",
        "order_status": "siap",
        "delivery_logistics_status": "in_transit",
        "active_delivery_trip_id": str(trip_id),
        "active_delivery_trip_number": "TRP-20261015-0038",
        "status_history": []
    })
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0038",
        "status": "in_transit",
        "stops": [
            {"stop_id": "stp_1", "order_id": str(ord_deliv_id), "outcome": "delivered"},
            {"stop_id": "stp_2", "order_id": str(ord_failed_id), "outcome": "failed"}
        ]
    })

    res = await complete_trip_partial_core(str(trip_id), "1 sukses, 1 gagal alamat salah", finance_user)

    # 1. Canonical trip status must be completed, with is_partially_completed True
    assert res["status"] == "completed"
    assert res["is_partially_completed"] is True
    assert res["delivered_stops_count"] == 1
    assert res["failed_stops_count"] == 1
    assert res["completion_notes"] == "1 sukses, 1 gagal alamat salah"
    assert res["stops"][1]["outcome"] == "failed_closed"

    # 2. Delivered order ghost lock eliminated
    ord_deliv_after = await mdb.orders.find_one({"_id": ord_deliv_id})
    assert ord_deliv_after["active_delivery_trip_id"] is None
    assert ord_deliv_after["active_delivery_trip_number"] is None
    assert ord_deliv_after["order_status"] == "selesai"

    # 3. Failed order released to ready queue
    ord_failed_after = await mdb.orders.find_one({"_id": ord_failed_id})
    assert ord_failed_after["active_delivery_trip_id"] is None
    assert ord_failed_after["active_delivery_trip_number"] is None
    assert ord_failed_after["order_status"] == "siap"
    assert ord_failed_after["delivery_logistics_status"] == "delivery_failed"
    assert len(ord_failed_after["status_history"]) == 1
    assert ord_failed_after["status_history"][0]["from_status"] == "siap"
    assert ord_failed_after["status_history"][0]["to_status"] == "siap"
    assert "Kembali ke antrean siap kirim" in ord_failed_after["status_history"][0]["reason"]


@pytest.mark.anyio
async def test_39_complete_trip_zero_delivered_rejected(mock_env):
    """Test 39: Rejection of trip completion when delivered count is 0 (HTTP 409)."""
    mdb, _, finance_user, _, _, _ = mock_env
    trip_id = ObjectId("670f00000000000000000039")
    ord_failed_id = ObjectId("660f0000000000000000003b")

    await mdb.orders.insert_one({
        "_id": ord_failed_id,
        "order_number": "ORD-T39",
        "order_status": "siap",
        "delivery_logistics_status": "in_transit",
        "active_delivery_trip_id": str(trip_id),
        "status_history": []
    })
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0039",
        "status": "in_transit",
        "stops": [
            {"stop_id": "stp_1", "order_id": str(ord_failed_id), "outcome": "failed"}
        ]
    })

    with pytest.raises(HTTPException) as ctx:
        await complete_trip_partial_core(str(trip_id), "Mau complete tapi 0 delivered", finance_user)
    assert ctx.value.status_code == 409
    assert "tidak memiliki stop yang berhasil diserahterimakan" in ctx.value.detail

    # Trip remains in_transit
    trip_doc = await mdb.delivery_trips.find_one({"_id": trip_id})
    assert trip_doc["status"] == "in_transit"
    # Order remains locked
    ord_doc = await mdb.orders.find_one({"_id": ord_failed_id})
    assert ord_doc["active_delivery_trip_id"] == str(trip_id)


@pytest.mark.anyio
async def test_40_complete_trip_with_active_stops_rejected(mock_env):
    """Test 40: Rejection of trip completion while stops remain active (pending or out_for_delivery) (HTTP 409)."""
    mdb, _, finance_user, _, _, _ = mock_env
    trip_id = ObjectId("670f00000000000000000040")
    ord_deliv_id = ObjectId("660f00000000000000000040")
    ord_active_id = ObjectId("660f00000000000000000041")

    await mdb.orders.insert_one({
        "_id": ord_deliv_id,
        "order_number": "ORD-T40-1",
        "order_status": "selesai",
        "active_delivery_trip_id": str(trip_id)
    })
    await mdb.orders.insert_one({
        "_id": ord_active_id,
        "order_number": "ORD-T40-2",
        "order_status": "siap",
        "active_delivery_trip_id": str(trip_id)
    })
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0040",
        "status": "in_transit",
        "stops": [
            {"stop_id": "stp_1", "order_id": str(ord_deliv_id), "outcome": "delivered"},
            {"stop_id": "stp_2", "order_id": str(ord_active_id), "outcome": "out_for_delivery"}
        ]
    })

    with pytest.raises(HTTPException) as ctx:
        await complete_trip_partial_core(str(trip_id), "Coba selesaikan sebelum semua stop beres", finance_user)
    assert ctx.value.status_code == 409
    assert "Masih terdapat 1 stop aktif" in ctx.value.detail

    trip_doc = await mdb.delivery_trips.find_one({"_id": trip_id})
    assert trip_doc["status"] == "in_transit"


@pytest.mark.anyio
async def test_41_complete_trip_idempotent_replay(mock_env):
    """Test 41: Idempotent replay of completion on an already completed trip returns clean trip without duplicate mutations."""
    mdb, _, finance_user, _, _, _ = mock_env
    trip_id = ObjectId("670f00000000000000000041")

    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0041",
        "status": "completed",
        "is_partially_completed": False,
        "completed_at": "2026-10-15T12:00:00+00:00",
        "completion_notes": "Selesai pertama kali",
        "delivered_stops_count": 2,
        "failed_stops_count": 0,
        "stops": [
            {"stop_id": "stp_1", "order_id": "ord_1", "outcome": "delivered"},
            {"stop_id": "stp_2", "order_id": "ord_2", "outcome": "delivered"}
        ]
    })

    # Replay completion with different notes
    res = await complete_trip_partial_core(str(trip_id), "Catatan kedua yang tidak boleh menimpa", finance_user)

    assert res["status"] == "completed"
    assert res["completion_notes"] == "Selesai pertama kali"
    assert res["completed_at"] == "2026-10-15T12:00:00+00:00"


@pytest.mark.anyio
async def test_42_complete_trip_preserves_wage_accruals_and_creates_zero_financial_mutations(mock_env):
    """Test 42: Completing a trip creates ZERO wage obligations, creates ZERO finance transactions, and leaves existing obligations in accrued."""
    mdb, _, finance_user, _, _, helpers = mock_env
    trip_id = ObjectId("670f00000000000000000042")
    ord_id = ObjectId("660f00000000000000000042")
    wob_id = ObjectId("680f00000000000000000001")

    # Order delivered with wage already accrued at handover time
    await mdb.orders.insert_one({
        "_id": ord_id,
        "order_number": "ORD-T42",
        "order_status": "selesai",
        "delivery_logistics_status": "delivered",
        "active_delivery_trip_id": str(trip_id),
        "active_delivery_trip_number": "TRP-20261015-0042"
    })
    # Existing wage obligation in accrued status
    await mdb.wage_obligations.insert_one({
        "_id": wob_id,
        "key": build_delivery_accrual_event_key(str(ord_id), str(helpers[0]["_id"])),
        "order_id": str(ord_id),
        "trip_id": str(trip_id),
        "worker_id": str(helpers[0]["_id"]),
        "total_amount_le": 50.0,
        "status": "accrued",
        "task_category": "delivery"
    })
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261015-0042",
        "status": "in_transit",
        "stops": [
            {"stop_id": "stp_1", "order_id": str(ord_id), "outcome": "delivered"}
        ]
    })

    initial_wob_count = len(mdb.wage_obligations.docs)
    initial_fin_count = len(mdb.finance_transactions.docs)
    initial_settlement_count = len(mdb.wage_settlements.docs)

    await complete_trip_partial_core(str(trip_id), "Penutupan trip dengan upah tetap accrued", finance_user)

    # Invariant: Zero wage obligations created or deleted
    assert len(mdb.wage_obligations.docs) == initial_wob_count == 1
    # Existing obligation remains strictly accrued (not settled or paid)
    wob_after = await mdb.wage_obligations.find_one({"_id": wob_id})
    assert wob_after["status"] == "accrued"

    # Invariant: Zero finance transactions or settlements created
    assert len(mdb.finance_transactions.docs) == initial_fin_count == 0
    assert len(mdb.wage_settlements.docs) == initial_settlement_count == 0


@pytest.mark.anyio
async def test_43_order_belonging_to_another_trip_not_released_by_trip_lock_guard(mock_env):
    """Test 43: Complete trip update strictly guards with active_delivery_trip_id and does NOT release an order assigned to another trip."""
    mdb, _, finance_user, _, _, _ = mock_env
    trip_1_id = ObjectId("670f00000000000000000043")
    trip_2_id = ObjectId("670f00000000000000000044")
    ord_a_id = ObjectId("660f00000000000000000043")
    ord_b_id = ObjectId("660f00000000000000000044")

    # Order A is legitimately assigned to Trip 1
    await mdb.orders.insert_one({
        "_id": ord_a_id,
        "order_number": "ORD-T43-A",
        "order_status": "selesai",
        "delivery_logistics_status": "delivered",
        "active_delivery_trip_id": str(trip_1_id),
        "active_delivery_trip_number": "TRP-20261015-0043"
    })
    # Order B is concurrently assigned to Trip 2
    await mdb.orders.insert_one({
        "_id": ord_b_id,
        "order_number": "ORD-T43-B",
        "order_status": "selesai",
        "delivery_logistics_status": "delivered",
        "active_delivery_trip_id": str(trip_2_id),
        "active_delivery_trip_number": "TRP-20261015-0044"
    })

    # Trip 1 stops list has both Order A and Order B
    await mdb.delivery_trips.insert_one({
        "_id": trip_1_id,
        "trip_number": "TRP-20261015-0043",
        "status": "in_transit",
        "stops": [
            {"stop_id": "stp_1", "order_id": str(ord_a_id), "outcome": "delivered"},
            {"stop_id": "stp_2", "order_id": str(ord_b_id), "outcome": "delivered"}
        ]
    })

    await complete_trip_partial_core(str(trip_1_id), "Selesai trip 1", finance_user)

    # Order A belonging to Trip 1 had its lock eliminated
    ord_a_after = await mdb.orders.find_one({"_id": ord_a_id})
    assert ord_a_after["active_delivery_trip_id"] is None
    assert ord_a_after["active_delivery_trip_number"] is None

    # Order B belonging to Trip 2 was NOT released!
    ord_b_after = await mdb.orders.find_one({"_id": ord_b_id})
    assert ord_b_after["active_delivery_trip_id"] == str(trip_2_id)
    assert ord_b_after["active_delivery_trip_number"] == "TRP-20261015-0044"


