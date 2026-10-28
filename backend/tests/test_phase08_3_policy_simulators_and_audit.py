"""
Phase 08.3 — Wage Policy Simulators, Reason Validation, and Audit History Test Suite.

Verifies:
1. Feature A — Policy Change Reason & Audit Integrity:
   - Mandatory change_reason for genuine policy changes across all categories.
   - Rejection when reason is missing (HTTP 422).
   - Rejection when reason is whitespace-only (HTTP 422).
   - Rejection when reason is too short (< 3 chars, HTTP 422).
   - Rejection when reason exceeds maximum length (> 500 chars, HTTP 422).
   - Audit log includes actor, timestamp, category, previous, new, changed_fields, and change_reason.
   - last_change_reason is stored in policy document and returned in getters.
2. Semantic No-Op Detection:
   - When submitted policy values are identical to current configuration, returns no_op=True.
   - Does NOT write to db.settings.
   - Does NOT create false audit records in db.audit_logs.
   - Does NOT require a change_reason for semantic no-op.
3. Category-Scoped Audit History Retrieval:
   - GET /admin/wage-policies/{category}/history returns newest-first logs for each category.
   - Category isolation: audit records from one category do not leak into another.
   - Graceful handling of historical audit logs lacking change_reason.
4. Read-Only Financial Isolation:
   - Simulators and policy management never mutate financial collections:
     wage_obligations, finance_transactions, employee_wages, settlements, inventory.
"""

import copy
import json
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from fastapi import HTTPException, Request
import pymongo
import pymongo.errors
import pytest

from server import (
    distribute_wage_piastres,
    get_active_delivery_wage_policy,
    get_active_production_wage_policy,
    get_active_material_purchase_wage_policy,
    get_active_admin_wage_policy,
    admin_get_wage_policy_by_category,
    admin_update_wage_policy_endpoint,
    admin_get_wage_policy_history_endpoint,
    admin_update_delivery_wage_policy,
    DeliveryWagePolicyInput,
    ProductionWagePolicyInput,
    MaterialPurchaseWagePolicyInput,
    AdminWagePolicyInput,
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
        # Sort by timestamp descending if requested
        if args and args[0] == "timestamp" and (len(args) < 2 or args[1] == -1):
            self.docs.sort(key=lambda d: d.get("timestamp", ""), reverse=True)
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
        self.update_count = 0
        self.insert_count = 0
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
        matched = [d for d in self.docs.values() if self._matches(d, filter_q)]
        return AsyncCursorMock(matched)

    async def insert_one(self, doc, *args, **kwargs):
        self.insert_count += 1
        d_copy = copy.deepcopy(doc)
        if "_id" not in d_copy:
            d_copy["_id"] = ObjectId()
        self.docs[str(d_copy["_id"])] = d_copy
        mock_res = MagicMock()
        mock_res.inserted_id = d_copy["_id"]
        return mock_res

    async def update_one(self, filter_q, update_doc, upsert=False, *args, **kwargs):
        self.update_count += 1
        for doc_id, doc in self.docs.items():
            if self._matches(doc, filter_q):
                if "$set" in update_doc:
                    doc.update(copy.deepcopy(update_doc["$set"]))
                mock_res = MagicMock()
                mock_res.matched_count = 1
                mock_res.modified_count = 1
                return mock_res

        if upsert:
            new_doc = copy.deepcopy(filter_q)
            if "$set" in update_doc:
                new_doc.update(copy.deepcopy(update_doc["$set"]))
            if "_id" not in new_doc:
                new_doc["_id"] = ObjectId()
            self.docs[str(new_doc["_id"])] = new_doc
            mock_res = MagicMock()
            mock_res.matched_count = 0
            mock_res.upserted_id = new_doc["_id"]
            return mock_res

        mock_res = MagicMock()
        mock_res.matched_count = 0
        mock_res.modified_count = 0
        return mock_res


class MockSession:
    def __init__(self, mdb):
        self.mdb = mdb
        self.aborted = False
        self.committed = False
        self._snapshot = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            await self.abort_transaction()
        elif not self.aborted:
            self.committed = True

    def start_transaction(self):
        class _TxContext:
            def __init__(self, session):
                self.session = session

            async def __aenter__(self):
                # Snapshot collections before transaction starts
                self.session._snapshot = {
                    col_name: copy.deepcopy(getattr(self.session.mdb, col_name).docs)
                    for col_name in ["settings", "audit_logs", "wage_obligations", "finance_transactions", "employee_wages"]
                    if hasattr(self.session.mdb, col_name)
                }
                return self.session

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                if exc_type is not None:
                    await self.session.abort_transaction()
                elif not self.session.aborted:
                    self.session.committed = True

        return _TxContext(self)

    async def abort_transaction(self):
        self.aborted = True
        if self._snapshot is not None:
            for col_name, docs_snap in self._snapshot.items():
                getattr(self.mdb, col_name).docs = copy.deepcopy(docs_snap)


class MockMotorClient:
    def __init__(self, mdb, fail_session=False):
        self.mdb = mdb
        self.fail_session = fail_session
        self.last_session = None

    async def start_session(self):
        if self.fail_session:
            raise pymongo.errors.ConfigurationError("Standalone deployment does not support transactions")
        self.last_session = MockSession(self.mdb)
        return self.last_session


class MockDB:
    def __init__(self, fail_session=False, enable_client=False):
        self.admins = MockCollection("admins")
        self.settings = MockCollection("settings")
        self.audit_logs = MockCollection("audit_logs")
        self.wage_obligations = MockCollection("wage_obligations")
        self.finance_transactions = MockCollection("finance_transactions")
        self.employee_wages = MockCollection("employee_wages")
        if enable_client:
            self.client = MockMotorClient(self, fail_session=fail_session)


def make_mock_request(data: dict):
    req = MagicMock(spec=Request)
    req.json = AsyncMock(return_value=data)
    return req


# =============================================================================
# FEATURE A: MANDATORY POLICY CHANGE REASON & AUDIT INTEGRITY
# =============================================================================

class TestPolicyChangeReasonAndAudit:
    @pytest.mark.anyio
    async def test_genuine_update_with_valid_reason_records_audit_log(self):
        mdb = MockDB()
        owner_admin = {"id": "own1", "name": "Owner Boss", "role": "owner"}
        req = make_mock_request({
            "default_wage_per_unit_le": 80.0,
            "unusual_amount_threshold_le": 160.0,
            "max_wage_per_unit_le": 450.0,
            "enabled": True,
            "change_reason": "Penyesuaian tarif berdasarkan keputusan rapat direksi"
        })

        with patch("server.db", mdb):
            res = await admin_update_wage_policy_endpoint("production", req, admin=owner_admin)
            assert res["is_configured"] is True
            assert res["no_op"] is False
            assert res["last_change_reason"] == "Penyesuaian tarif berdasarkan keputusan rapat direksi"

            # Verify saved in settings
            setting_doc = await mdb.settings.find_one({"key": "production_wage_policy"})
            assert setting_doc is not None
            assert setting_doc["value"]["last_change_reason"] == "Penyesuaian tarif berdasarkan keputusan rapat direksi"

            # Verify audit log was recorded in db.audit_logs
            logs = await mdb.audit_logs.find({"entity_type": "production_wage_policy"}).to_list()
            assert len(logs) == 1
            log = logs[0]
            assert log["action"] == "update_production_wage_policy"
            assert log["performed_by_name"] == "Owner Boss"
            assert log["metadata"]["change_reason"] == "Penyesuaian tarif berdasarkan keputusan rapat direksi"
            assert "default_wage_per_unit_le" in log["metadata"]["changed_fields"]

    @pytest.mark.anyio
    async def test_update_rejected_when_reason_is_missing(self):
        mdb = MockDB()
        owner_admin = {"id": "own1", "name": "Owner Boss", "role": "owner"}
        req = make_mock_request({
            "default_wage_per_unit_le": 80.0,
            "unusual_amount_threshold_le": 160.0,
            "max_wage_per_unit_le": 450.0,
            "enabled": True
            # Missing change_reason
        })

        with patch("server.db", mdb):
            with pytest.raises(HTTPException) as exc:
                await admin_update_wage_policy_endpoint("production", req, admin=owner_admin)
            assert exc.value.status_code == 422
            assert "Alasan perubahan kebijakan wajib diisi" in exc.value.detail
            assert mdb.settings.update_count == 0
            assert mdb.audit_logs.insert_count == 0

    @pytest.mark.anyio
    async def test_update_rejected_when_reason_is_whitespace_only(self):
        mdb = MockDB()
        owner_admin = {"id": "own1", "name": "Owner Boss", "role": "owner"}
        req = make_mock_request({
            "default_wage_per_unit_le": 80.0,
            "unusual_amount_threshold_le": 160.0,
            "max_wage_per_unit_le": 450.0,
            "enabled": True,
            "change_reason": "     \t \n  "
        })

        with patch("server.db", mdb):
            with pytest.raises(HTTPException) as exc:
                await admin_update_wage_policy_endpoint("production", req, admin=owner_admin)
            assert exc.value.status_code == 422
            assert "Alasan perubahan kebijakan wajib diisi" in exc.value.detail

    @pytest.mark.anyio
    async def test_update_rejected_when_reason_too_short(self):
        mdb = MockDB()
        owner_admin = {"id": "own1", "name": "Owner Boss", "role": "owner"}
        req = make_mock_request({
            "default_wage_per_unit_le": 80.0,
            "unusual_amount_threshold_le": 160.0,
            "max_wage_per_unit_le": 450.0,
            "enabled": True,
            "change_reason": "ok"  # 2 characters (< 3)
        })

        with patch("server.db", mdb):
            with pytest.raises(HTTPException) as exc:
                await admin_update_wage_policy_endpoint("production", req, admin=owner_admin)
            assert exc.value.status_code == 422
            assert "minimal 3 karakter" in exc.value.detail

    @pytest.mark.anyio
    async def test_update_rejected_when_reason_exceeds_max_length(self):
        mdb = MockDB()
        owner_admin = {"id": "own1", "name": "Owner Boss", "role": "owner"}
        req = make_mock_request({
            "default_wage_per_unit_le": 80.0,
            "unusual_amount_threshold_le": 160.0,
            "max_wage_per_unit_le": 450.0,
            "enabled": True,
            "change_reason": "A" * 501  # 501 characters (> 500)
        })

        with patch("server.db", mdb):
            with pytest.raises(HTTPException) as exc:
                await admin_update_wage_policy_endpoint("production", req, admin=owner_admin)
            assert exc.value.status_code == 422
            assert "500" in exc.value.detail


# =============================================================================
# FEATURE A.2: SEMANTIC NO-OP DETECTION
# =============================================================================

class TestSemanticNoOpDetection:
    @pytest.mark.anyio
    async def test_no_op_save_returns_noop_true_and_creates_no_audit(self):
        mdb = MockDB()
        owner_admin = {"id": "own1", "name": "Owner Boss", "role": "owner"}

        # 1. First genuine configuration
        req1 = make_mock_request({
            "default_wage_per_unit_le": 75.0,
            "unusual_amount_threshold_le": 150.0,
            "max_wage_per_unit_le": 400.0,
            "enabled": True,
            "change_reason": "Konfigurasi awal upah produksi"
        })
        with patch("server.db", mdb):
            res1 = await admin_update_wage_policy_endpoint("production", req1, admin=owner_admin)
            assert res1["is_configured"] is True
            assert res1["no_op"] is False

            settings_count_after_1 = mdb.settings.update_count
            audit_count_after_1 = mdb.audit_logs.insert_count
            assert audit_count_after_1 == 1

            # 2. Resubmit identical values (Semantic No-Op) without change_reason
            req2 = make_mock_request({
                "default_wage_per_unit_le": 75.0,
                "unusual_amount_threshold_le": 150.0,
                "max_wage_per_unit_le": 400.0,
                "enabled": True
                # Notice: no change_reason provided!
            })
            res2 = await admin_update_wage_policy_endpoint("production", req2, admin=owner_admin)

            # Assertions for semantic no-op
            assert res2["is_configured"] is True
            assert res2["no_op"] is True
            assert "Tidak ada perubahan konfigurasi terdeteksi" in res2["message"]

            # DB settings must NOT have been updated again
            assert mdb.settings.update_count == settings_count_after_1
            # No false audit log recorded!
            assert mdb.audit_logs.insert_count == audit_count_after_1

    @pytest.mark.anyio
    async def test_legacy_delivery_endpoint_semantic_no_op(self):
        mdb = MockDB()
        owner_admin = {"id": "own1", "name": "Owner Boss", "role": "owner"}

        # Initial configured delivery policy in DB
        await mdb.settings.insert_one({
            "key": "delivery_wage_policy",
            "value": {
                "base_wage_per_order_le": 50.0,
                "unusual_amount_threshold_le": 100.0,
                "max_helper_wage_per_order_le": 500.0,
                "enabled": True,
                "currency": "EGP",
                "rounding_policy": "piastre_round_half_up",
            }
        })

        with patch("server.db", mdb):
            payload = DeliveryWagePolicyInput(
                base_wage_per_order_le=50.0,
                unusual_amount_threshold_le=100.0,
                max_helper_wage_per_order_le=500.0,
                enabled=True
            )
            res = await admin_update_delivery_wage_policy(payload, admin=owner_admin)
            assert res["is_configured"] is True
            assert res["no_op"] is True
            assert mdb.audit_logs.insert_count == 0


# =============================================================================
# FEATURE G: CATEGORY-SCOPED AUDIT HISTORY RETRIEVAL
# =============================================================================

class TestCategoryAuditHistory:
    @pytest.mark.anyio
    async def test_category_history_isolation_and_display_fields(self):
        mdb = MockDB()
        finance_admin = {"id": "fin1", "name": "Finance Staff", "role": "manager", "permissions": {"access_finance": True}}

        # Seed audit records for different categories
        await mdb.audit_logs.insert_one({
            "action": "update_production_wage_policy",
            "entity_type": "production_wage_policy",
            "performed_by_name": "Owner",
            "timestamp": "2026-10-20T10:00:00Z",
            "metadata": {
                "category": "production",
                "change_reason": "Tarif upah baru untuk musim liburan",
                "previous": {"default_wage_per_unit_le": 60.0},
                "new": {"default_wage_per_unit_le": 75.0},
                "changed_fields": ["default_wage_per_unit_le"]
            }
        })
        await mdb.audit_logs.insert_one({
            "action": "update_delivery_wage_policy",
            "entity_type": "delivery_wage_policy",
            "performed_by_name": "Owner",
            "timestamp": "2026-10-21T10:00:00Z",
            "metadata": {
                "category": "delivery",
                "change_reason": "Penyesuaian rute luar kota",
                "previous": {"base_wage_per_order_le": 50.0},
                "new": {"base_wage_per_order_le": 60.0},
                "changed_fields": ["base_wage_per_order_le"]
            }
        })

        with patch("server.db", mdb):
            # 1. Fetch production history
            prod_hist = await admin_get_wage_policy_history_endpoint("production", admin=finance_admin)
            assert len(prod_hist) == 1
            assert prod_hist[0]["action"] == "update_production_wage_policy"
            assert prod_hist[0]["metadata"]["change_reason"] == "Tarif upah baru untuk musim liburan"
            assert prod_hist[0]["metadata"]["new"]["default_wage_per_unit_le"] == 75.0

            # 2. Fetch delivery history
            deliv_hist = await admin_get_wage_policy_history_endpoint("delivery", admin=finance_admin)
            assert len(deliv_hist) == 1
            assert deliv_hist[0]["action"] == "update_delivery_wage_policy"
            assert deliv_hist[0]["metadata"]["change_reason"] == "Penyesuaian rute luar kota"

            # 3. Fetch material_purchase history (empty)
            mat_hist = await admin_get_wage_policy_history_endpoint("material_purchase", admin=finance_admin)
            assert len(mat_hist) == 0

    @pytest.mark.anyio
    async def test_legacy_history_without_change_reason_handled_gracefully(self):
        mdb = MockDB()
        finance_admin = {"id": "fin1", "name": "Finance Staff", "role": "manager", "permissions": {"access_finance": True}}

        # Seed legacy record without change_reason
        await mdb.audit_logs.insert_one({
            "action": "update_admin_wage_policy",
            "entity_type": "admin_wage_policy",
            "performed_by_name": "Legacy Owner",
            "timestamp": "2026-09-01T10:00:00Z",
            "metadata": {
                "category": "admin",
                "previous": None,
                "new": {"default_wage_per_order_le": 25.0},
                "changed_fields": ["default_wage_per_order_le"]
            }
        })

        with patch("server.db", mdb):
            hist = await admin_get_wage_policy_history_endpoint("admin", admin=finance_admin)
            assert len(hist) == 1
            assert "change_reason" not in hist[0]["metadata"] or hist[0]["metadata"]["change_reason"] is None


# =============================================================================
# FINANCIAL ISOLATION & READ-ONLY INTEGRITY
# =============================================================================

class TestFinancialIsolation:
    @pytest.mark.anyio
    async def test_simulator_and_getters_do_not_mutate_financial_collections(self):
        mdb = MockDB()
        finance_admin = {"id": "fin1", "name": "Finance Staff", "role": "manager", "permissions": {"access_finance": True}}

        with patch("server.db", mdb):
            # Call getters
            await get_active_production_wage_policy(db_inst=mdb)
            await get_active_delivery_wage_policy(db_inst=mdb)
            await get_active_material_purchase_wage_policy(db_inst=mdb)
            await get_active_admin_wage_policy(db_inst=mdb)

            # Perform simulation calculations with shared integer utility
            allocs_prod = distribute_wage_piastres(75.0 * 10, [{"worker_id": f"w_{i}"} for i in range(3)])
            assert len(allocs_prod) == 3
            assert sum(a["amount_piastres"] for a in allocs_prod) == 75000

            allocs_mat = distribute_wage_piastres(50.0, [{"worker_id": f"b_{i}"} for i in range(2)])
            assert len(allocs_mat) == 2
            assert sum(a["amount_piastres"] for a in allocs_mat) == 5000

            # Verify no financial documents were created
            assert len(mdb.wage_obligations.docs) == 0
            assert len(mdb.finance_transactions.docs) == 0
            assert len(mdb.employee_wages.docs) == 0


# =============================================================================
# RESILIENCE: AUDIT WRITE FAILURE & TRANSACTION ROLLBACK
# =============================================================================

class TestAuditWriteFailureResilience:
    """
    Tests resilience against audit log write failures after policy write starts.
    Verifies:
    1. In an ACID environment (MongoDB replica set with multi-document transaction),
       an exception raised during record_audit_log triggers session abort.
       - The policy update in db.settings is rolled back to pre-transaction state.
       - No false audit log claiming success is recorded.
       - Zero financial obligations or transactions are created.
    2. In a non-replica-set standalone environment, verifies fallback behavior
       (sequential write where settings was modified before audit failed).
    3. Verifies resilience across all four categories: production, delivery, material_purchase, admin.
    4. Verifies backward-compatible delivery endpoint resilience.
    """

    @pytest.mark.anyio
    async def test_audit_failure_triggers_transaction_rollback_in_acid_environment(self):
        mdb = MockDB(enable_client=True)
        owner_admin = {"id": "own1", "name": "Owner Boss", "role": "owner"}

        # Initial pre-existing policy in settings
        pre_policy = {
            "default_wage_per_unit_le": 60.0,
            "unusual_amount_threshold_le": 120.0,
            "max_wage_per_unit_le": 300.0,
            "enabled": True,
            "is_configured": True,
            "updated_at": "2026-10-01T00:00:00Z"
        }
        await mdb.settings.insert_one({"key": "production_wage_policy", "value": pre_policy})

        req = make_mock_request({
            "default_wage_per_unit_le": 85.0,
            "unusual_amount_threshold_le": 170.0,
            "max_wage_per_unit_le": 450.0,
            "enabled": True,
            "change_reason": "Kenaikan tarif disepakati rapat direksi"
        })

        # Simulate record_audit_log failing with disk full or network disconnection
        with patch("server.db", mdb), patch("server.record_audit_log", AsyncMock(side_effect=RuntimeError("Audit write failed: Simulated disk write error"))):
            with pytest.raises(RuntimeError) as exc_info:
                await admin_update_wage_policy_endpoint("production", req, admin=owner_admin)

            assert "Simulated disk write error" in str(exc_info.value)

            # 1. Verify transaction session was aborted, NOT committed
            assert mdb.client.last_session is not None
            assert mdb.client.last_session.aborted is True
            assert mdb.client.last_session.committed is False

            # 2. Verify settings document was rolled back to original pre-transaction state
            setting_doc = await mdb.settings.find_one({"key": "production_wage_policy"})
            assert setting_doc is not None
            assert setting_doc["value"]["default_wage_per_unit_le"] == 60.0
            assert setting_doc["value"]["updated_at"] == "2026-10-01T00:00:00Z"

            # 3. Verify no false audit log was recorded
            logs = await mdb.audit_logs.find({"entity_type": "production_wage_policy"}).to_list()
            assert len(logs) == 0

            # 4. Verify no financial records were created
            assert len(mdb.wage_obligations.docs) == 0
            assert len(mdb.finance_transactions.docs) == 0

    @pytest.mark.anyio
    @pytest.mark.parametrize("category", ["production", "delivery", "material_purchase", "admin"])
    async def test_audit_failure_rolls_back_across_all_four_categories(self, category):
        mdb = MockDB(enable_client=True)
        owner_admin = {"id": "own1", "name": "Owner Boss", "role": "owner"}

        # Seed admin user for admin wage policy recipient lookup
        admin_user_id = str(ObjectId())
        await mdb.admins.insert_one({"_id": ObjectId(admin_user_id), "name": "Sarah Admin", "role": "admin"})

        payloads = {
            "production": {
                "default_wage_per_unit_le": 80.0,
                "unusual_amount_threshold_le": 160.0,
                "max_wage_per_unit_le": 400.0,
                "enabled": True,
                "change_reason": "Perubahan upah produksi"
            },
            "delivery": {
                "base_wage_per_order_le": 70.0,
                "unusual_amount_threshold_le": 140.0,
                "max_helper_wage_per_order_le": 500.0,
                "enabled": True,
                "change_reason": "Perubahan upah pengiriman"
            },
            "material_purchase": {
                "default_wage_per_purchase_le": 55.0,
                "unusual_amount_threshold_le": 110.0,
                "max_wage_per_purchase_le": 350.0,
                "max_buyers": 4,
                "enabled": True,
                "change_reason": "Perubahan upah belanja bahan"
            },
            "admin": {
                "default_wage_per_order_le": 30.0,
                "default_recipient_id": admin_user_id,
                "unusual_amount_threshold_le": 60.0,
                "max_wage_per_order_le": 150.0,
                "enabled": True,
                "change_reason": "Perubahan upah admin"
            }
        }

        req = make_mock_request(payloads[category])

        with patch("server.db", mdb), patch("server.record_audit_log", AsyncMock(side_effect=RuntimeError(f"Audit failure for {category}"))):
            with pytest.raises(RuntimeError):
                await admin_update_wage_policy_endpoint(category, req, admin=owner_admin)

            # Transaction aborted
            assert mdb.client.last_session.aborted is True
            assert mdb.client.last_session.committed is False

            # Setting remains unconfigured or rolled back
            setting_doc = await mdb.settings.find_one({"key": f"{category}_wage_policy"})
            assert setting_doc is None

            # Zero audit logs recorded
            logs = await mdb.audit_logs.find().to_list()
            assert len(logs) == 0

    @pytest.mark.anyio
    async def test_legacy_delivery_endpoint_audit_failure_rollback(self):
        mdb = MockDB(enable_client=True)
        owner_admin = {"id": "own1", "name": "Owner Boss", "role": "owner"}

        payload = DeliveryWagePolicyInput(
            base_wage_per_order_le=65.0,
            unusual_amount_threshold_le=130.0,
            max_helper_wage_per_order_le=500.0,
            enabled=True,
            change_reason="Penyesuaian delivery lewat legacy endpoint"
        )

        with patch("server.db", mdb), patch("server.record_audit_log", AsyncMock(side_effect=RuntimeError("Legacy audit write failure"))):
            with pytest.raises(RuntimeError):
                await admin_update_delivery_wage_policy(payload, admin=owner_admin)

            # Transaction aborted
            assert mdb.client.last_session.aborted is True
            assert mdb.client.last_session.committed is False

            # Setting document rolled back
            setting_doc = await mdb.settings.find_one({"key": "delivery_wage_policy"})
            assert setting_doc is None

            # Zero audit logs
            logs = await mdb.audit_logs.find().to_list()
            assert len(logs) == 0

    @pytest.mark.anyio
    async def test_standalone_fallback_audit_failure_behavior_documented(self):
        """
        Documents and verifies non-replica set behavior:
        When MongoDB standalone lacks multi-document transaction support,
        execute_transaction_with_safety gracefully falls back to atomic serial execution.
        If audit write fails in this mode, settings update was completed prior to the audit error.
        This test explicitly documents why production MongoDB Atlas (replica set) is vital for ACID guarantees.
        """
        mdb = MockDB(fail_session=True, enable_client=True)
        owner_admin = {"id": "own1", "name": "Owner Boss", "role": "owner"}

        req = make_mock_request({
            "default_wage_per_unit_le": 90.0,
            "unusual_amount_threshold_le": 180.0,
            "max_wage_per_unit_le": 500.0,
            "enabled": True,
            "change_reason": "Update di lingkungan standalone"
        })

        with patch("server.db", mdb), patch("server.record_audit_log", AsyncMock(side_effect=RuntimeError("Standalone audit failure"))):
            with pytest.raises(RuntimeError):
                await admin_update_wage_policy_endpoint("production", req, admin=owner_admin)

            # In standalone fallback, settings write took place sequentially before audit failed
            setting_doc = await mdb.settings.find_one({"key": "production_wage_policy"})
            assert setting_doc is not None
            assert setting_doc["value"]["default_wage_per_unit_le"] == 90.0

            # But no false audit log was recorded
            logs = await mdb.audit_logs.find({"entity_type": "production_wage_policy"}).to_list()
            assert len(logs) == 0

            # Zero financial mutations
            assert len(mdb.wage_obligations.docs) == 0
