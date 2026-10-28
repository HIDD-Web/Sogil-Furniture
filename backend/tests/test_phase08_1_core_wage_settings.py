"""
Phase 08.1 — Core Wage Settings & Shared Piastre Allocation Test Suite.

Verifies:
1. Shared Integer Piastre Allocation Utility (distribute_wage_piastres):
   - Strict integer math, zero money drift invariant.
   - Deterministic remainder distribution to first r recipients.
   - Validation against negative amounts and duplicate recipient IDs.
   - Backward compatibility wrapper (calculate_delivery_helper_wage_allocations).
2. Unconfigured State Handling:
   - Fail-closed / unconfigured reporting for production, material purchase, and admin policies.
   - Preserves delivery policy baseline defaults.
3. Centralized Wage Policies API:
   - Role permissions: read requires access_finance, update requires owner.
   - Hierarchical policy validation: 0 <= default <= threshold < max_cap.
   - Specific validation rules (e.g. max_buyers, default_recipient_id lookup).
   - Audit logging on every policy mutation.
   - Backward compatibility with legacy delivery endpoints.
"""

import copy
import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from fastapi import HTTPException, Request
import pytest

from server import (
    distribute_wage_piastres,
    calculate_delivery_helper_wage_allocations,
    get_active_delivery_wage_policy,
    get_active_production_wage_policy,
    get_active_material_purchase_wage_policy,
    get_active_admin_wage_policy,
    get_all_active_wage_policies,
    admin_get_all_wage_policies_endpoint,
    admin_get_wage_policy_by_category,
    admin_update_wage_policy_endpoint,
    admin_get_wage_policy_history_endpoint,
    admin_get_delivery_wage_policy,
    admin_update_delivery_wage_policy,
    record_delivery_stop_handover_core,
    DeliveryWagePolicyInput,
    ProductionWagePolicyInput,
    MaterialPurchaseWagePolicyInput,
    AdminWagePolicyInput,
    DeliveryStopHandoverInput,
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
            elif k == "stops.order_id":
                stop_order_ids = [str(s.get("order_id")) for s in doc.get("stops", [])]
                if str(v) not in stop_order_ids:
                    return False
            elif k == "key":
                if doc.get("key") != v:
                    return False
            elif k == "entity_type":
                if doc.get("entity_type") != v:
                    return False
            elif k == "action":
                if isinstance(v, dict) and "$in" in v:
                    if doc.get("action") not in v["$in"]:
                        return False
                elif doc.get("action") != v:
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
        self.docs[str(d_copy["_id"])] = d_copy
        res = MagicMock()
        res.inserted_id = d_copy["_id"]
        return res

    async def update_one(self, filter_q, update_q, upsert=False, *args, **kwargs):
        for doc in self.docs.values():
            if self._matches(doc, filter_q):
                if "$set" in update_q:
                    for sk, sv in update_q["$set"].items():
                        if sk.startswith("stops.$."):
                            sub = sk.replace("stops.$.", "")
                            target_order_id = filter_q.get("stops.order_id")
                            for s in doc.get("stops", []):
                                if str(s.get("order_id")) == str(target_order_id):
                                    s[sub] = copy.deepcopy(sv)
                        else:
                            doc[sk] = copy.deepcopy(sv)
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


class MockDB:
    def __init__(self):
        self.admins = MockCollection("admins")
        self.settings = MockCollection("settings")
        self.audit_logs = MockCollection("audit_logs")
        self.delivery_trips = MockCollection("delivery_trips")
        self.orders = MockCollection("orders")
        self.wage_obligations = MockCollection("wage_obligations")


def make_mock_request(data: dict):
    req = MagicMock(spec=Request)
    req.json = AsyncMock(return_value=data)
    return req


# =============================================================================
# 1. SHARED INTEGER PIASTRE ALLOCATION TESTS
# =============================================================================

class TestSharedPiastreAllocation:
    def test_single_recipient_receives_exact_full_amount(self):
        allocs = distribute_wage_piastres(75.50, [{"worker_id": "w1", "worker_name": "Tukang Kayu"}])
        assert len(allocs) == 1
        assert allocs[0]["worker_id"] == "w1"
        assert allocs[0]["worker_name"] == "Tukang Kayu"
        assert allocs[0]["amount_piastres"] == 7550
        assert allocs[0]["amount_le"] == 75.50

    def test_two_recipients_equal_split(self):
        allocs = distribute_wage_piastres(50.0, [{"worker_id": "w1"}, {"worker_id": "w2"}])
        assert len(allocs) == 2
        assert allocs[0]["amount_le"] == 25.0
        assert allocs[1]["amount_le"] == 25.0
        assert allocs[0]["amount_piastres"] == 2500
        assert allocs[1]["amount_piastres"] == 2500
        assert sum(a["amount_piastres"] for a in allocs) == 5000

    def test_three_recipients_distributes_remainder_to_first_r(self):
        allocs = distribute_wage_piastres(50.0, [
            {"worker_id": "w1", "worker_name": "Ahmad"},
            {"worker_id": "w2", "worker_name": "Budi"},
            {"worker_id": "w3", "worker_name": "Citra"}
        ])
        assert len(allocs) == 3
        # 5000 // 3 = 1666, remainder = 2
        # w1: 1667, w2: 1667, w3: 1666
        assert allocs[0]["amount_piastres"] == 1667
        assert allocs[0]["amount_le"] == 16.67
        assert allocs[1]["amount_piastres"] == 1667
        assert allocs[1]["amount_le"] == 16.67
        assert allocs[2]["amount_piastres"] == 1666
        assert allocs[2]["amount_le"] == 16.66
        assert sum(a["amount_piastres"] for a in allocs) == 5000

    @pytest.mark.parametrize("total,n", [
        (50.0, 1), (50.0, 2), (50.0, 3), (50.0, 4), (50.0, 5), (50.0, 6), (50.0, 7),
        (75.25, 3), (100.33, 4), (120.0, 3), (250.0, 7), (555.55, 3), (999.99, 6),
        (0.01, 3), (1234.56, 11)
    ])
    def test_invariant_zero_money_drift_across_amounts_and_counts(self, total, n):
        recipients = [{"worker_id": f"worker_{i}"} for i in range(n)]
        allocs = distribute_wage_piastres(total, recipients)
        expected_piastres = int(Decimal(str(total)).quantize(Decimal("0.01")) * 100)
        actual_piastres = sum(a["amount_piastres"] for a in allocs)
        assert actual_piastres == expected_piastres, f"Mismatch: {actual_piastres} != {expected_piastres}"
        assert round(sum(a["amount_le"] for a in allocs), 2) == round(total, 2)

    def test_zero_amount_allocates_zero_piastres_without_error(self):
        allocs = distribute_wage_piastres(0.0, [{"worker_id": "w1"}, {"worker_id": "w2"}])
        assert len(allocs) == 2
        assert allocs[0]["amount_piastres"] == 0
        assert allocs[0]["amount_le"] == 0.0
        assert allocs[1]["amount_piastres"] == 0
        assert allocs[1]["amount_le"] == 0.0

    def test_zero_amount_with_empty_or_none_recipients_returns_empty_list(self):
        assert distribute_wage_piastres(0.0, []) == []
        assert distribute_wage_piastres(0.0, None) == []

    def test_positive_wage_with_empty_or_none_recipients_raises_value_error(self):
        with pytest.raises(ValueError, match="Daftar penerima upah tidak boleh kosong jika nominal upah bernilai positif"):
            distribute_wage_piastres(50.0, [])
        with pytest.raises(ValueError, match="Daftar penerima upah tidak boleh kosong jika nominal upah bernilai positif"):
            distribute_wage_piastres(0.01, None)

    def test_negative_amount_raises_value_error(self):
        with pytest.raises(ValueError, match="Nominal upah tidak boleh bernilai negatif"):
            distribute_wage_piastres(-10.0, [{"worker_id": "w1"}])

    def test_none_or_invalid_amount_raises_value_error(self):
        with pytest.raises(ValueError, match="Nominal upah tidak boleh None"):
            distribute_wage_piastres(None, [{"worker_id": "w1"}])
        with pytest.raises(ValueError, match="Nominal upah tidak valid"):
            distribute_wage_piastres("bukan_angka", [{"worker_id": "w1"}])

    def test_currency_precision_sub_piastre_rounding_boundary(self):
        # 50.125 rounds half up to 50.13 LE (5013 piastres)
        allocs_up = distribute_wage_piastres(50.125, [{"worker_id": "w1"}])
        assert allocs_up[0]["amount_piastres"] == 5013
        assert allocs_up[0]["amount_le"] == 50.13

        # 50.124 rounds half up to 50.12 LE (5012 piastres)
        allocs_down = distribute_wage_piastres(50.124, [{"worker_id": "w1"}])
        assert allocs_down[0]["amount_piastres"] == 5012
        assert allocs_down[0]["amount_le"] == 50.12

        # 100.33333333333333 rounds to 100.33 LE (10033 piastres)
        allocs_repeating = distribute_wage_piastres(100.33333333333333, [{"worker_id": "w1"}])
        assert allocs_repeating[0]["amount_piastres"] == 10033
        assert allocs_repeating[0]["amount_le"] == 100.33

    def test_duplicate_recipients_rejected(self):
        with pytest.raises(ValueError, match="Penerima upah duplikat terdeteksi"):
            distribute_wage_piastres(50.0, [{"worker_id": "w1"}, {"worker_id": "w1"}])

    def test_handles_string_and_objectid_recipients(self):
        oid = ObjectId()
        allocs = distribute_wage_piastres(30.0, ["str_id_1", oid])
        assert len(allocs) == 2
        assert allocs[0]["worker_id"] == "str_id_1"
        assert allocs[1]["worker_id"] == str(oid)
        assert allocs[0]["amount_piastres"] == 1500
        assert allocs[1]["amount_piastres"] == 1500

    def test_calculate_delivery_helper_wage_allocations_delegation(self):
        helpers = [
            {"helper_id": "h1", "helper_name": "Joko"},
            {"helper_id": "h2", "helper_name": "Budi"}
        ]
        allocs = calculate_delivery_helper_wage_allocations(50.0, helpers)
        assert len(allocs) == 2
        assert allocs[0]["worker_id"] == "h1"
        assert allocs[0]["worker_name"] == "Joko"
        assert allocs[0]["amount_le"] == 25.0
        assert allocs[1]["worker_id"] == "h2"
        assert allocs[1]["worker_name"] == "Budi"
        assert allocs[1]["amount_le"] == 25.0

    def test_calculate_delivery_helper_wage_allocations_empty_recipients_contract(self):
        # Without allow_empty, positive wage raises ValueError
        with pytest.raises(ValueError, match="Daftar penerima upah tidak boleh kosong"):
            calculate_delivery_helper_wage_allocations(50.0, [])

        # With allow_empty=True (used by preview endpoint), returns []
        assert calculate_delivery_helper_wage_allocations(50.0, [], allow_empty=True) == []

        # Zero wage with empty helpers returns []
        assert calculate_delivery_helper_wage_allocations(0.0, []) == []


# =============================================================================
# 2. WAGE POLICY GETTERS & UNCONFIGURED STATE TESTS
# =============================================================================

class TestWagePolicyGetters:
    @pytest.mark.anyio
    async def test_unconfigured_policies_report_is_configured_false(self):
        mdb = MockDB()
        prod = await get_active_production_wage_policy(db_inst=mdb)
        assert prod["is_configured"] is False
        assert prod["enabled"] is False
        assert prod["default_wage_per_unit_le"] is None
        assert prod["unusual_amount_threshold_le"] is None
        assert prod["max_wage_per_unit_le"] is None

        mat = await get_active_material_purchase_wage_policy(db_inst=mdb)
        assert mat["is_configured"] is False
        assert mat["enabled"] is False
        assert mat["default_wage_per_purchase_le"] is None
        assert mat["max_buyers"] == 5

        adm = await get_active_admin_wage_policy(db_inst=mdb)
        assert adm["is_configured"] is False
        assert adm["enabled"] is False
        assert adm["default_wage_per_order_le"] is None
        assert adm["default_recipient_id"] is None

        # Delivery policy preserves baseline default values
        deliv = await get_active_delivery_wage_policy(db_inst=mdb)
        assert deliv["base_wage_per_order_le"] == 50.0
        assert deliv["unusual_amount_threshold_le"] == 100.0
        assert deliv["max_helper_wage_per_order_le"] == 500.0
        assert deliv["is_configured"] is False

    @pytest.mark.anyio
    async def test_get_all_active_wage_policies_returns_all_four_categories(self):
        mdb = MockDB()
        all_policies = await get_all_active_wage_policies(db_inst=mdb)
        assert set(all_policies.keys()) == {"production", "delivery", "material_purchase", "admin"}


# =============================================================================
# 3. WAGE POLICY API ENDPOINTS & ROLE PROTECTION
# =============================================================================

class TestWagePolicyAPI:
    @pytest.mark.anyio
    async def test_get_wage_policies_accessible_to_finance_perm(self):
        mdb = MockDB()
        finance_admin = {"id": "fin1", "name": "Finance", "role": "manager", "permissions": {"access_finance": True}}
        with patch("server.db", mdb):
            res = await admin_get_all_wage_policies_endpoint(admin=finance_admin)
            assert "production" in res
            assert "delivery" in res
            assert "material_purchase" in res
            assert "admin" in res

    @pytest.mark.anyio
    async def test_get_single_category_wage_policy(self):
        mdb = MockDB()
        finance_admin = {"id": "fin1", "name": "Finance", "role": "manager", "permissions": {"access_finance": True}}
        with patch("server.db", mdb):
            deliv = await admin_get_wage_policy_by_category("delivery", admin=finance_admin)
            assert deliv["base_wage_per_order_le"] == 50.0

            prod = await admin_get_wage_policy_by_category("production", admin=finance_admin)
            assert prod["is_configured"] is False

            with pytest.raises(HTTPException) as exc:
                await admin_get_wage_policy_by_category("invalid_cat", admin=finance_admin)
            assert exc.value.status_code == 404

    @pytest.mark.anyio
    async def test_non_owner_cannot_update_wage_policy(self):
        mdb = MockDB()
        manager_admin = {"id": "mgr1", "name": "Manager", "role": "manager", "permissions": {"access_finance": True}}
        req = make_mock_request({
            "default_wage_per_unit_le": 100.0,
            "unusual_amount_threshold_le": 200.0,
            "max_wage_per_unit_le": 500.0
        })
        with patch("server.db", mdb):
            with pytest.raises(HTTPException) as exc:
                await admin_update_wage_policy_endpoint("production", req, admin=manager_admin)
            assert exc.value.status_code == 403

    @pytest.mark.anyio
    async def test_owner_updates_production_wage_policy_successfully(self):
        mdb = MockDB()
        owner_admin = {"id": "own1", "name": "Owner Boss", "role": "owner"}
        req = make_mock_request({
            "default_wage_per_unit_le": 75.0,
            "unusual_amount_threshold_le": 150.0,
            "max_wage_per_unit_le": 400.0,
            "enabled": True
        })
        with patch("server.db", mdb), patch("server.record_audit_log", AsyncMock()) as mock_audit:
            res = await admin_update_wage_policy_endpoint("production", req, admin=owner_admin)
            assert res["is_configured"] is True
            assert res["default_wage_per_unit_le"] == 75.0
            assert res["unusual_amount_threshold_le"] == 150.0
            assert res["max_wage_per_unit_le"] == 400.0
            assert res["enabled"] is True

            # Verify saved in db.settings
            saved = await mdb.settings.find_one({"key": "production_wage_policy"})
            assert saved is not None
            assert saved["value"]["default_wage_per_unit_le"] == 75.0

            # Verify audit log recorded
            mock_audit.assert_called_once()
            call_kw = mock_audit.call_args.kwargs
            assert call_kw["action"] == "update_production_wage_policy"
            assert call_kw["entity_type"] == "production_wage_policy"

    @pytest.mark.anyio
    async def test_production_wage_policy_validation_ordering(self):
        mdb = MockDB()
        owner_admin = {"id": "own1", "name": "Owner Boss", "role": "owner"}
        with patch("server.db", mdb):
            # default > threshold
            req1 = make_mock_request({
                "default_wage_per_unit_le": 250.0,
                "unusual_amount_threshold_le": 200.0,
                "max_wage_per_unit_le": 500.0
            })
            with pytest.raises(HTTPException) as exc1:
                await admin_update_wage_policy_endpoint("production", req1, admin=owner_admin)
            assert exc1.value.status_code == 422
            assert "tidak boleh lebih kecil dari tarif dasar" in str(exc1.value.detail)

            # threshold >= max_cap
            req2 = make_mock_request({
                "default_wage_per_unit_le": 100.0,
                "unusual_amount_threshold_le": 500.0,
                "max_wage_per_unit_le": 500.0
            })
            with pytest.raises(HTTPException) as exc2:
                await admin_update_wage_policy_endpoint("production", req2, admin=owner_admin)
            assert exc2.value.status_code == 422
            assert "harus lebih kecil dari batas maksimum keras" in str(exc2.value.detail)

            # negative default
            req3 = make_mock_request({
                "default_wage_per_unit_le": -10.0,
                "unusual_amount_threshold_le": 100.0,
                "max_wage_per_unit_le": 500.0
            })
            with pytest.raises(HTTPException) as exc3:
                await admin_update_wage_policy_endpoint("production", req3, admin=owner_admin)
            assert exc3.value.status_code == 422

    @pytest.mark.anyio
    async def test_owner_updates_material_purchase_wage_policy(self):
        mdb = MockDB()
        owner_admin = {"id": "own1", "name": "Owner Boss", "role": "owner"}
        with patch("server.db", mdb), patch("server.record_audit_log", AsyncMock()):
            # Valid update
            req = make_mock_request({
                "default_wage_per_purchase_le": 50.0,
                "unusual_amount_threshold_le": 100.0,
                "max_wage_per_purchase_le": 300.0,
                "max_buyers": 4,
                "enabled": True
            })
            res = await admin_update_wage_policy_endpoint("material_purchase", req, admin=owner_admin)
            assert res["is_configured"] is True
            assert res["default_wage_per_purchase_le"] == 50.0
            assert res["max_buyers"] == 4

            # Valid boundary max_buyers = 5
            req_boundary_5 = make_mock_request({
                "default_wage_per_purchase_le": 50.0,
                "unusual_amount_threshold_le": 100.0,
                "max_wage_per_purchase_le": 300.0,
                "max_buyers": 5,
                "enabled": True
            })
            res5 = await admin_update_wage_policy_endpoint("material_purchase", req_boundary_5, admin=owner_admin)
            assert res5["max_buyers"] == 5

            # Valid boundary max_buyers = 1
            req_boundary_1 = make_mock_request({
                "default_wage_per_purchase_le": 50.0,
                "unusual_amount_threshold_le": 100.0,
                "max_wage_per_purchase_le": 300.0,
                "max_buyers": 1,
                "enabled": True
            })
            res1 = await admin_update_wage_policy_endpoint("material_purchase", req_boundary_1, admin=owner_admin)
            assert res1["max_buyers"] == 1

            # Invalid max_buyers (> 5, e.g. 6)
            req_bad_buyers_6 = make_mock_request({
                "default_wage_per_purchase_le": 50.0,
                "unusual_amount_threshold_le": 100.0,
                "max_wage_per_purchase_le": 300.0,
                "max_buyers": 6,
                "enabled": True
            })
            with pytest.raises(HTTPException) as exc6:
                await admin_update_wage_policy_endpoint("material_purchase", req_bad_buyers_6, admin=owner_admin)
            assert exc6.value.status_code == 422

            # Invalid max_buyers (< 1, e.g. 0)
            req_bad_buyers_0 = make_mock_request({
                "default_wage_per_purchase_le": 50.0,
                "unusual_amount_threshold_le": 100.0,
                "max_wage_per_purchase_le": 300.0,
                "max_buyers": 0,
                "enabled": True
            })
            with pytest.raises(HTTPException) as exc0:
                await admin_update_wage_policy_endpoint("material_purchase", req_bad_buyers_0, admin=owner_admin)
            assert exc0.value.status_code == 422

    @pytest.mark.anyio
    async def test_owner_updates_admin_wage_policy_with_recipient_lookup(self):
        mdb = MockDB()
        admin_user_id = str(ObjectId())
        await mdb.admins.insert_one({
            "_id": ObjectId(admin_user_id),
            "name": "Sarah Administrasi",
            "role": "admin",
            "status": "active"
        })

        owner_admin = {"id": "own1", "name": "Owner Boss", "role": "owner"}
        with patch("server.db", mdb), patch("server.record_audit_log", AsyncMock()):
            # Test nonexistent recipient rejected
            req_nonexistent = make_mock_request({
                "default_wage_per_order_le": 20.0,
                "default_recipient_id": "nonexistent_id",
                "unusual_amount_threshold_le": 50.0,
                "max_wage_per_order_le": 150.0
            })
            with pytest.raises(HTTPException) as exc_none:
                await admin_update_wage_policy_endpoint("admin", req_nonexistent, admin=owner_admin)
            assert exc_none.value.status_code == 422
            assert "tidak ditemukan" in str(exc_none.value.detail)

            # Test valid recipient
            req_valid = make_mock_request({
                "default_wage_per_order_le": 25.0,
                "default_recipient_id": admin_user_id,
                "unusual_amount_threshold_le": 50.0,
                "max_wage_per_order_le": 150.0,
                "enabled": True
            })
            res = await admin_update_wage_policy_endpoint("admin", req_valid, admin=owner_admin)
            assert res["is_configured"] is True
            assert res["default_wage_per_order_le"] == 25.0
            assert res["default_recipient_id"] == admin_user_id
            assert res["default_recipient_name"] == "Sarah Administrasi"

    @pytest.mark.anyio
    async def test_backward_compatible_delivery_endpoints(self):
        mdb = MockDB()
        owner_admin = {"id": "own1", "name": "Owner Boss", "role": "owner"}
        finance_admin = {"id": "fin1", "name": "Finance Staff", "role": "manager", "permissions": {"access_finance": True}}

        # Seed an existing historical wage obligation to verify immutability
        hist_ob_id = ObjectId()
        await mdb.wage_obligations.insert_one({
            "_id": hist_ob_id,
            "obligation_type": "delivery",
            "amount_le": 50.0,
            "amount_piastres": 5000,
            "status": "pending"
        })

        with patch("server.db", mdb), patch("server.record_audit_log", AsyncMock()):
            # 1. Test GET legacy endpoint before configuration (returns code fallback defaults)
            legacy_get = await admin_get_delivery_wage_policy(admin=finance_admin)
            assert legacy_get["base_wage_per_order_le"] == 50.0
            assert legacy_get["unusual_amount_threshold_le"] == 100.0
            assert legacy_get["max_helper_wage_per_order_le"] == 500.0
            assert legacy_get["is_configured"] is False

            # 2. Test PUT legacy endpoint updates settings
            payload = DeliveryWagePolicyInput(
                base_wage_per_order_le=65.0,
                unusual_amount_threshold_le=120.0,
                max_helper_wage_per_order_le=550.0
            )
            legacy_put = await admin_update_delivery_wage_policy(payload, admin=owner_admin)
            assert legacy_put["base_wage_per_order_le"] == 65.0
            assert legacy_put["unusual_amount_threshold_le"] == 120.0
            assert legacy_put["max_helper_wage_per_order_le"] == 550.0
            assert legacy_put["is_configured"] is True

            # 3. Test GET via new wage-policies endpoint reflects update
            new_get = await admin_get_wage_policy_by_category("delivery", admin=finance_admin)
            assert new_get["base_wage_per_order_le"] == 65.0
            assert new_get["unusual_amount_threshold_le"] == 120.0
            assert new_get["max_helper_wage_per_order_le"] == 550.0
            assert new_get["is_configured"] is True

            # 4. Test PUT via new wage-policies endpoint updates settings
            req_new = make_mock_request({
                "base_wage_per_order_le": 70.0,
                "unusual_amount_threshold_le": 140.0,
                "max_helper_wage_per_order_le": 600.0,
                "enabled": True
            })
            new_put = await admin_update_wage_policy_endpoint("delivery", req_new, admin=owner_admin)
            assert new_put["base_wage_per_order_le"] == 70.0
            assert new_put["unusual_amount_threshold_le"] == 140.0
            assert new_put["max_helper_wage_per_order_le"] == 600.0

            # 5. Test GET legacy endpoint reflects new endpoint's update (bidirectional consistency)
            legacy_get2 = await admin_get_delivery_wage_policy(admin=finance_admin)
            assert legacy_get2["base_wage_per_order_le"] == 70.0
            assert legacy_get2["unusual_amount_threshold_le"] == 140.0
            assert legacy_get2["max_helper_wage_per_order_le"] == 600.0
            assert legacy_get2["is_configured"] is True

            # 6. Verify historical wage obligations remain immutable (no recomputation)
            hist_doc = await mdb.wage_obligations.find_one({"_id": hist_ob_id})
            assert hist_doc["amount_le"] == 50.0
            assert hist_doc["amount_piastres"] == 5000

    @pytest.mark.anyio
    async def test_handover_fails_closed_when_positive_wage_and_empty_helpers(self):
        mdb = MockDB()
        trip_id = ObjectId()
        order_id = ObjectId()
        admin_user = {"id": "adm1", "name": "Admin Tester", "role": "admin"}

        # Order in "siap" status
        await mdb.orders.insert_one({
            "_id": order_id,
            "order_number": "ORD-TEST-001",
            "order_status": "siap",
            "status_history": []
        })

        # Delivery trip with positive wage snapshot but EMPTY helpers list
        await mdb.delivery_trips.insert_one({
            "_id": trip_id,
            "trip_number": "TRIP-TEST-001",
            "status": "in_transit",
            "helpers": [],  # Empty helpers!
            "rate_policy_snapshot": {
                "applied_rate_le": 50.0,
                "unusual_amount_threshold_le": 100.0,
                "max_helper_wage_per_order_le": 500.0
            },
            "stops": [
                {
                    "order_id": str(order_id),
                    "outcome": "out_for_delivery"
                }
            ]
        })

        handover_payload = DeliveryStopHandoverInput(
            recipient_name="Pak Customer",
            helper_confirmed=True
        )

        with patch("server.db", mdb), patch("server.record_audit_log", AsyncMock()):
            with pytest.raises(HTTPException) as exc:
                await record_delivery_stop_handover_core(
                    trip_id=str(trip_id),
                    order_id=str(order_id),
                    payload=handover_payload,
                    admin=admin_user
                )
            assert exc.value.status_code == 422
            assert "tidak memiliki helper terdaftar" in str(exc.value.detail)

            # Ensure zero wage obligations created
            wobs = await mdb.wage_obligations.find({}).to_list(100)
            assert len(wobs) == 0

            # Ensure stop was NOT marked as delivered
            trip_after = await mdb.delivery_trips.find_one({"_id": trip_id})
            assert trip_after["stops"][0]["outcome"] == "out_for_delivery"

    @pytest.mark.anyio
    async def test_get_wage_policy_history_endpoint(self):
        mdb = MockDB()
        finance_admin = {"id": "fin1", "name": "Finance", "role": "manager", "permissions": {"access_finance": True}}
        await mdb.audit_logs.insert_one({
            "action": "update_production_wage_policy",
            "entity_type": "production_wage_policy",
            "performed_by_name": "Boss Owner",
            "timestamp": "2026-10-28T10:00:00Z",
            "metadata": {"changed_fields": ["default_wage_per_unit_le"]}
        })

        with patch("server.db", mdb):
            hist = await admin_get_wage_policy_history_endpoint("production", admin=finance_admin)
            assert len(hist) == 1
            assert hist[0]["action"] == "update_production_wage_policy"

            # Invalid category returns 404
            with pytest.raises(HTTPException):
                await admin_get_wage_policy_history_endpoint("fake_category", admin=finance_admin)
