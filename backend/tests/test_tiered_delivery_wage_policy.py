"""
Comprehensive Test Suite for Sogil Furniture Phase 3.F.4:
Tiered Delivery Helper Wage Policy:
- Base: 50 LE
- Confirmation Threshold: 100 LE
- Hard Cap: 500 LE

Coverage:
1. Nominal <= 100 LE (50 LE, 100 LE boundary) processed without special confirmation.
2. 100 LE < Nominal <= 500 LE (101 LE, 200 LE, 500 LE boundary):
   - Rejected without confirmation checkbox.
   - Rejected if reason is missing, empty, whitespace, or < 5 characters.
   - Accepted with confirmation + valid reason without requiring Owner approval.
3. Nominal > 500 LE (501 LE, 1000 LE):
   - Strictly rejected with HTTP 422.
   - Confirmation checkbox and written reason CANNOT bypass hard cap.
4. Hard Cap Rejection Audit & Financial Safety:
   - Audit log recorded persistently (`delivery_wage_hard_cap_rejection`).
   - Zero wage obligations, zero expense transactions, zero state corruption.
5. Invariant & Policy Validation:
   - base <= threshold < hard_cap strictly enforced.
   - Fail-closed dispatch if policy is missing or incomplete.
6. Multi-Helper Distribution & Exact Piastre Invariance.
7. Preview Endpoint returns tiered warning and hard-cap flags.
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
    admin_update_delivery_trip_status,
    validate_delivery_trip_wage_cap,
    DeliveryWagePolicyInput,
    DeliveryWagePreviewInput,
    DeliveryStopHandoverInput,
    DeliveryTripStatusUpdateInput,
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
                res = MagicMock()
                res.matched_count = 1
                res.modified_count = 1
                return res
        if upsert:
            new_doc = copy.deepcopy(filter_q)
            if "$set" in update_q:
                new_doc.update(copy.deepcopy(update_q["$set"]))
            if "_id" not in new_doc:
                new_doc["_id"] = ObjectId()
            self.docs[str(new_doc["_id"])] = new_doc
            res = MagicMock()
            res.matched_count = 0
            res.modified_count = 1
            res.upserted_id = new_doc["_id"]
            return res
        res = MagicMock()
        res.matched_count = 0
        res.modified_count = 0
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
def tiered_env():
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
    mdb.admins.docs[str(helper_1["_id"])] = helper_1
    mdb.admins.docs[str(helper_2["_id"])] = helper_2
    mdb.admins.docs[str(helper_3["_id"])] = helper_3

    with patch("server.db", mdb), \
         patch("server.client.start_session", side_effect=pymongo.errors.ConfigurationError("mock standalone")), \
         patch("server.is_standalone_fallback_permitted", return_value=True):
        yield mdb, owner_user, finance_user, [helper_1, helper_2, helper_3]


# =============================================================================
# 1. Tiered Policy Configuration & Invariant Validation
# =============================================================================

@pytest.mark.anyio
async def test_01_default_tiered_policy_values(tiered_env):
    """Test 1: Default active policy provides base=50, threshold=100, hard_cap=500."""
    mdb, owner_user, finance_user, _ = tiered_env
    policy = await admin_get_delivery_wage_policy(admin=owner_user)
    assert policy["base_wage_per_order_le"] == 50.0
    assert policy["unusual_amount_threshold_le"] == 100.0
    assert policy["max_helper_wage_per_order_le"] == 500.0
    assert policy["currency"] == "EGP"
    assert policy["rounding_policy"] == "piastre_round_half_up"


@pytest.mark.anyio
async def test_02_policy_validation_invariants(tiered_env):
    """Test 2: Enforce base <= threshold < hard_cap strictly."""
    mdb, owner_user, _, _ = tiered_env

    # 1. threshold < base -> rejected
    with pytest.raises(HTTPException) as ctx1:
        await admin_update_delivery_wage_policy(
            payload=DeliveryWagePolicyInput(
                base_wage_per_order_le=120.0,
                unusual_amount_threshold_le=100.0,
                max_helper_wage_per_order_le=500.0
            ),
            admin=owner_user
        )
    assert ctx1.value.status_code == 422
    assert "tidak boleh lebih kecil" in ctx1.value.detail

    # 2. threshold == hard_cap -> rejected (< strictly required)
    with pytest.raises(HTTPException) as ctx2:
        await admin_update_delivery_wage_policy(
            payload=DeliveryWagePolicyInput(
                base_wage_per_order_le=50.0,
                unusual_amount_threshold_le=500.0,
                max_helper_wage_per_order_le=500.0
            ),
            admin=owner_user
        )
    assert ctx2.value.status_code == 422
    assert "lebih kecil dari batas maksimum keras" in ctx2.value.detail

    # 3. threshold > hard_cap -> rejected
    with pytest.raises(HTTPException) as ctx3:
        await admin_update_delivery_wage_policy(
            payload=DeliveryWagePolicyInput(
                base_wage_per_order_le=50.0,
                unusual_amount_threshold_le=600.0,
                max_helper_wage_per_order_le=500.0
            ),
            admin=owner_user
        )
    assert ctx3.value.status_code == 422
    assert "lebih kecil dari batas maksimum keras" in ctx3.value.detail

    # 4. missing hard_cap -> rejected
    with pytest.raises(HTTPException) as ctx4:
        await admin_update_delivery_wage_policy(
            payload=DeliveryWagePolicyInput(
                base_wage_per_order_le=50.0,
                unusual_amount_threshold_le=100.0,
                max_helper_wage_per_order_le=None
            ),
            admin=owner_user
        )
    assert ctx4.value.status_code == 422
    assert "hard cap" in ctx4.value.detail


# =============================================================================
# 2. Tier 1: Amount <= 100 LE (Normal Processing)
# =============================================================================

@pytest.mark.anyio
async def test_03_amount_at_or_below_100_le_processed_without_confirmation(tiered_env):
    """Test 3: 50 LE and 100 LE boundary succeed without confirmation or reason."""
    mdb, _, finance_user, helpers = tiered_env
    trip_id = ObjectId("670f11111111111111111101")
    ord_id_50 = ObjectId("660f11111111111111111101")
    ord_id_100 = ObjectId("660f11111111111111111102")

    await mdb.orders.insert_one({"_id": ord_id_50, "order_number": "ORD-T1-50", "order_status": "siap", "active_delivery_trip_id": str(trip_id)})
    await mdb.orders.insert_one({"_id": ord_id_100, "order_number": "ORD-T1-100", "order_status": "siap", "active_delivery_trip_id": str(trip_id)})

    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261016-0001",
        "status": "in_transit",
        "trip_wage_rate_le": 50.0,
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [
            {"order_id": str(ord_id_50), "outcome": "out_for_delivery"},
            {"order_id": str(ord_id_100), "outcome": "out_for_delivery"}
        ]
    })

    # Case A: 50 LE (base rate)
    res_50 = await record_delivery_stop_handover_core(
        trip_id=str(trip_id),
        order_id=str(ord_id_50),
        payload=DeliveryStopHandoverInput(recipient_name="Ibrahim", helper_confirmed=True, custom_wage_le=50.0),
        admin=finance_user
    )
    assert res_50["ok"] is True
    assert res_50["wage_obligations"][0]["total_amount_le"] == 50.0
    assert res_50["wage_obligations"][0]["rate_policy_snapshot"]["is_override"] is False

    # Case B: 100 LE (boundary, exact threshold)
    res_100 = await record_delivery_stop_handover_core(
        trip_id=str(trip_id),
        order_id=str(ord_id_100),
        payload=DeliveryStopHandoverInput(recipient_name="Ibrahim", helper_confirmed=True, custom_wage_le=100.0),
        admin=finance_user
    )
    assert res_100["ok"] is True
    assert res_100["wage_obligations"][0]["total_amount_le"] == 100.0
    assert len(res_100["wage_obligations"]) == 1
    # Invariant: No threshold override audit entry or rejection entry generated
    assert (await mdb.audit_logs.find_one({"action": "delivery_wage_threshold_override"})) is None
    assert (await mdb.audit_logs.find_one({"action": "delivery_wage_hard_cap_rejection"})) is None


# =============================================================================
# 3. Tier 2: 100 LE < Amount <= 500 LE (Confirmation + Written Reason Required)
# =============================================================================

@pytest.mark.anyio
async def test_04_amount_above_100_up_to_500_requires_confirmation_and_reason(tiered_env):
    """Test 4: Amounts 101, 200, 500 require checkbox + reason; reject if incomplete; accept if complete."""
    mdb, _, finance_user, helpers = tiered_env
    trip_id = ObjectId("670f22222222222222222202")
    ord_id = ObjectId("660f22222222222222222202")

    await mdb.orders.insert_one({"_id": ord_id, "order_number": "ORD-T2-01", "order_status": "siap", "active_delivery_trip_id": str(trip_id)})
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261016-0002",
        "status": "in_transit",
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": "out_for_delivery"}]
    })

    # Case A: 101 LE without confirmation checkbox -> 422
    with pytest.raises(HTTPException) as ctx_101:
        await record_delivery_stop_handover_core(
            trip_id=str(trip_id),
            order_id=str(ord_id),
            payload=DeliveryStopHandoverInput(recipient_name="Ibrahim", helper_confirmed=True, custom_wage_le=101.0, confirmed_unusual_amount=False),
            admin=finance_user
        )
    assert ctx_101.value.status_code == 422
    assert "melebihi batas konfirmasi" in ctx_101.value.detail

    # Case B: 200 LE with confirmation checkbox BUT empty/whitespace reason -> 422
    for bad_reason in [None, "", "    ", "abc", "ok"]:
        with pytest.raises(HTTPException) as ctx_reason:
            await record_delivery_stop_handover_core(
                trip_id=str(trip_id),
                order_id=str(ord_id),
                payload=DeliveryStopHandoverInput(
                    recipient_name="Ibrahim",
                    helper_confirmed=True,
                    custom_wage_le=200.0,
                    confirmed_unusual_amount=True,
                    override_reason=bad_reason
                ),
                admin=finance_user
            )
        assert ctx_reason.value.status_code == 422
        assert "minimal 5 karakter" in ctx_reason.value.detail

    # Case C: 200 LE with confirmation and valid reason (>= 5 chars) -> 200 OK without Owner approval
    res_200 = await record_delivery_stop_handover_core(
        trip_id=str(trip_id),
        order_id=str(ord_id),
        payload=DeliveryStopHandoverInput(
            recipient_name="Ibrahim",
            helper_confirmed=True,
            custom_wage_le=200.0,
            confirmed_unusual_amount=True,
            override_reason="Bongkar muat lantai 4 tanpa lift"
        ),
        admin=finance_user
    )
    assert res_200["ok"] is True
    assert res_200["wage_obligations"][0]["total_amount_le"] == 200.0
    assert res_200["wage_obligations"][0]["rate_policy_snapshot"]["is_override"] is True
    assert "lantai 4" in res_200["wage_obligations"][0]["rate_policy_snapshot"]["override_reason"]

    # Verify audit log recorded for threshold override
    audit = await mdb.audit_logs.find_one({"action": "delivery_wage_threshold_override"})
    assert audit is not None
    assert audit["metadata"]["recorded_amount_le"] == 200.0


@pytest.mark.anyio
async def test_05_boundary_500_le_permitted_with_confirmation_and_reason(tiered_env):
    """Test 5: 500 LE is the exact upper boundary of Tier 2: accepted with confirmation + reason."""
    mdb, _, finance_user, helpers = tiered_env
    trip_id = ObjectId("670f22222222222222222205")
    ord_id = ObjectId("660f22222222222222222205")

    await mdb.orders.insert_one({"_id": ord_id, "order_number": "ORD-T2-500", "order_status": "siap", "active_delivery_trip_id": str(trip_id)})
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261016-0005",
        "status": "in_transit",
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": "out_for_delivery"}]
    })

    res_500 = await record_delivery_stop_handover_core(
        trip_id=str(trip_id),
        order_id=str(ord_id),
        payload=DeliveryStopHandoverInput(
            recipient_name="Ibrahim",
            helper_confirmed=True,
            custom_wage_le=500.0,
            confirmed_unusual_amount=True,
            override_reason="Pengiriman antar kota dengan perakitan kompleks"
        ),
        admin=finance_user
    )
    assert res_500["ok"] is True
    assert res_500["wage_obligations"][0]["total_amount_le"] == 500.0


# =============================================================================
# 4. Tier 3: Amount > 500 LE (Strict Backend Hard Cap Rejection)
# =============================================================================

@pytest.mark.anyio
async def test_06_amount_above_500_le_strictly_rejected(tiered_env):
    """Test 6: 501 LE and 1000 LE rejected with HTTP 422 even with confirmation and reason."""
    mdb, _, finance_user, helpers = tiered_env
    trip_id = ObjectId("670f33333333333333333306")
    ord_id = ObjectId("660f33333333333333333306")

    await mdb.orders.insert_one({"_id": ord_id, "order_number": "ORD-T3-501", "order_status": "siap", "active_delivery_trip_id": str(trip_id)})
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261016-0006",
        "status": "in_transit",
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": "out_for_delivery"}]
    })

    # Case A: 501 LE (1 LE over hard cap)
    with pytest.raises(HTTPException) as ctx_501:
        await record_delivery_stop_handover_core(
            trip_id=str(trip_id),
            order_id=str(ord_id),
            payload=DeliveryStopHandoverInput(
                recipient_name="Ibrahim",
                helper_confirmed=True,
                custom_wage_le=501.0,
                confirmed_unusual_amount=True,
                override_reason="Alasan sangat mendesak dan sangat penting"
            ),
            admin=finance_user
        )
    assert ctx_501.value.status_code == 422
    assert "melebihi batas maksimum keras" in ctx_501.value.detail
    assert "Konfirmasi dan alasan tidak dapat melewati batas keras" in ctx_501.value.detail

    # Case B: 1000 LE
    with pytest.raises(HTTPException) as ctx_1000:
        await record_delivery_stop_handover_core(
            trip_id=str(trip_id),
            order_id=str(ord_id),
            payload=DeliveryStopHandoverInput(
                recipient_name="Ibrahim",
                helper_confirmed=True,
                custom_wage_le=1000.0,
                confirmed_unusual_amount=True,
                override_reason="Permintaan khusus dari customer VIP"
            ),
            admin=finance_user
        )
    assert ctx_1000.value.status_code == 422
    assert "melebihi batas maksimum keras" in ctx_1000.value.detail


@pytest.mark.anyio
async def test_07_hard_cap_rejection_audit_and_zero_financial_liability(tiered_env):
    """Test 7: Hard cap rejection logs persistent audit but creates NO financial obligation or expense."""
    mdb, _, finance_user, helpers = tiered_env
    trip_id = ObjectId("670f33333333333333333307")
    ord_id = ObjectId("660f33333333333333333307")

    await mdb.orders.insert_one({"_id": ord_id, "order_number": "ORD-T3-AUDIT", "order_status": "siap", "active_delivery_trip_id": str(trip_id)})
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261016-0007",
        "status": "in_transit",
        "helpers": [{"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]}],
        "stops": [{"order_id": str(ord_id), "outcome": "out_for_delivery"}]
    })

    with pytest.raises(HTTPException):
        await record_delivery_stop_handover_core(
            trip_id=str(trip_id),
            order_id=str(ord_id),
            payload=DeliveryStopHandoverInput(
                recipient_name="Ibrahim",
                helper_confirmed=True,
                custom_wage_le=650.0,
                confirmed_unusual_amount=True,
                override_reason="Barang sangat berat 1000kg"
            ),
            admin=finance_user
        )

    # Invariant 1: Audit log entry exists
    audit_entry = await mdb.audit_logs.find_one({"action": "delivery_wage_hard_cap_rejection"})
    assert audit_entry is not None
    assert audit_entry["metadata"]["attempted_amount_le"] == 650.0
    assert audit_entry["metadata"]["hard_cap_le"] == 500.0
    assert audit_entry["metadata"]["order_number"] == "ORD-T3-AUDIT"
    assert audit_entry["metadata"]["trip_number"] == "TRP-20261016-0007"
    assert audit_entry["performed_by_name"] == finance_user["name"]

    # Invariant 2: ZERO wage obligations created
    obligations = await mdb.wage_obligations.find({"order_id": str(ord_id)}).to_list()
    assert len(obligations) == 0

    # Invariant 3: ZERO finance transactions / cash expense created
    assert len(mdb.finance_transactions.docs) == 0

    # Invariant 4: Stop remains out_for_delivery (not marked delivered)
    trip_doc = await mdb.delivery_trips.find_one({"_id": trip_id})
    assert trip_doc["stops"][0]["outcome"] == "out_for_delivery"


# =============================================================================
# 5. Multi-Helper Distribution & Exact Rounding Invariance
# =============================================================================

@pytest.mark.anyio
async def test_08_multi_helper_distribution_tiered_conservation(tiered_env):
    """Test 8: Exact piastre conservation across multiple helpers under tiered amounts."""
    mdb, _, finance_user, helpers = tiered_env
    trip_id = ObjectId("670f44444444444444444408")
    ord_id = ObjectId("660f44444444444444444408")

    # 3 Helpers assigned
    await mdb.orders.insert_one({"_id": ord_id, "order_number": "ORD-T4-MULTI", "order_status": "siap", "active_delivery_trip_id": str(trip_id)})
    await mdb.delivery_trips.insert_one({
        "_id": trip_id,
        "trip_number": "TRP-20261016-0008",
        "status": "in_transit",
        "helpers": [
            {"helper_id": str(helpers[0]["_id"]), "helper_name": helpers[0]["name"]},
            {"helper_id": str(helpers[1]["_id"]), "helper_name": helpers[1]["name"]},
            {"helper_id": str(helpers[2]["_id"]), "helper_name": helpers[2]["name"]}
        ],
        "stops": [{"order_id": str(ord_id), "outcome": "out_for_delivery"}]
    })

    # Handover 200 LE across 3 helpers (Tier 2, confirmed + reason)
    res = await record_delivery_stop_handover_core(
        trip_id=str(trip_id),
        order_id=str(ord_id),
        payload=DeliveryStopHandoverInput(
            recipient_name="Ibrahim",
            helper_confirmed=True,
            custom_wage_le=200.0,
            confirmed_unusual_amount=True,
            override_reason="Bongkar muat 3 personil untuk ranjang jati 2x2 meter"
        ),
        admin=finance_user
    )
    assert res["ok"] is True
    wobs = res["wage_obligations"]
    assert len(wobs) == 3

    # Exact piastre check: 66.67 + 66.67 + 66.66 = 200.00 LE
    amounts = [w["total_amount_le"] for w in wobs]
    assert amounts == [66.67, 66.67, 66.66]
    assert sum(Decimal(str(a)) for a in amounts) == Decimal("200.00")


# =============================================================================
# 6. Fail-Closed on Incomplete or Missing Policy
# =============================================================================

@pytest.mark.anyio
async def test_09_fail_closed_dispatch_when_policy_incomplete(tiered_env):
    """Test 9: Dispatch fails closed with HTTP 422 if cap or threshold is missing from settings."""
    # Case A: Missing policy
    with patch("server.get_setting", new_callable=AsyncMock) as mock_s:
        mock_s.return_value = None
        with pytest.raises(HTTPException) as ctx_none:
            await validate_delivery_trip_wage_cap(50.0)
        assert ctx_none.value.status_code == 422

    # Case B: Missing threshold
    with patch("server.get_setting", new_callable=AsyncMock) as mock_s:
        mock_s.return_value = {"max_helper_wage_per_order_le": 500.0}
        with pytest.raises(HTTPException) as ctx_no_thresh:
            await validate_delivery_trip_wage_cap(50.0)
        assert ctx_no_thresh.value.status_code == 422
        assert "Batas konfirmasi upah pengiriman belum ditetapkan" in ctx_no_thresh.value.detail

    # Case C: Missing cap
    with patch("server.get_setting", new_callable=AsyncMock) as mock_s:
        mock_s.return_value = {"unusual_amount_threshold_le": 100.0}
        with pytest.raises(HTTPException) as ctx_no_cap:
            await validate_delivery_trip_wage_cap(50.0)
        assert ctx_no_cap.value.status_code == 422
        assert "Batas atas upah pengiriman (cap) belum ditetapkan" in ctx_no_cap.value.detail


# =============================================================================
# 7. Wage Allocation Preview Flags
# =============================================================================

@pytest.mark.anyio
async def test_10_preview_wage_allocation_tiered_flags(tiered_env):
    """Test 10: Preview endpoint returns correct requires_confirmation and exceeds_hard_cap flags."""
    _, _, finance_user, helpers = tiered_env

    # 50 LE -> Normal
    p50 = await admin_preview_delivery_wage_allocation(
        payload=DeliveryWagePreviewInput(total_wage_le=50.0, helpers=[helpers[0]]),
        admin=finance_user
    )
    assert p50["requires_confirmation"] is False
    assert p50["exceeds_hard_cap"] is False

    # 100 LE -> Normal (boundary)
    p100 = await admin_preview_delivery_wage_allocation(
        payload=DeliveryWagePreviewInput(total_wage_le=100.0, helpers=[helpers[0]]),
        admin=finance_user
    )
    assert p100["requires_confirmation"] is False
    assert p100["exceeds_hard_cap"] is False

    # 150 LE -> Requires confirmation, below hard cap
    p150 = await admin_preview_delivery_wage_allocation(
        payload=DeliveryWagePreviewInput(total_wage_le=150.0, helpers=[helpers[0]]),
        admin=finance_user
    )
    assert p150["requires_confirmation"] is True
    assert p150["exceeds_hard_cap"] is False

    # 500 LE -> Requires confirmation, at hard cap boundary
    p500 = await admin_preview_delivery_wage_allocation(
        payload=DeliveryWagePreviewInput(total_wage_le=500.0, helpers=[helpers[0]]),
        admin=finance_user
    )
    assert p500["requires_confirmation"] is True
    assert p500["exceeds_hard_cap"] is False

    # 501 LE -> Exceeds hard cap! (cannot be bypassed by confirmation)
    p501 = await admin_preview_delivery_wage_allocation(
        payload=DeliveryWagePreviewInput(total_wage_le=501.0, helpers=[helpers[0]]),
        admin=finance_user
    )
    assert p501["requires_confirmation"] is False
    assert p501["exceeds_hard_cap"] is True
