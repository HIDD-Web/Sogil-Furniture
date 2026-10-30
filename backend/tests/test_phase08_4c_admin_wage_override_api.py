"""
Phase 08.4C — Owner Admin Wage Override API Test Suite.
Sogil Furniture | Financial Integrity First

Comprehensive coverage for all 38 Phase 08.4C requirements:
- Scenarios 1-7: Authentication and Authorization
- Scenarios 8-19: Payload Validation
- Scenarios 20-24: Policy and Hard Cap Enforcement
- Scenarios 25-33: Lifecycle Protection & State Guards
- Scenarios 34-38: Audit Logging and Concurrency Control (OCC)
"""

import copy
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from datetime import datetime, timezone
from fastapi import HTTPException
from pydantic import ValidationError
import pymongo
import pymongo.errors
import pytest
import unittest

from server import (
    AdminWageOverrideInput,
    admin_get_order_admin_wage,
    admin_update_order_admin_wage,
    build_admin_wage_accrual_event_key,
    require_owner,
    get_current_admin,
)


_NOT_SET = object()

class TestPhase08_4CAdminWageOverrideAPI(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mock_session = AsyncMock()
        self.mock_session.__aenter__.return_value = self.mock_session
        self.mock_session.__aexit__.return_value = None
        self.mock_session.start_transaction = MagicMock()
        self.mock_session.start_transaction.return_value.__aenter__ = AsyncMock(return_value=self.mock_session)
        self.mock_session.start_transaction.return_value.__aexit__ = AsyncMock(return_value=None)

        self.mock_client = MagicMock()
        self.mock_client.start_session = AsyncMock(return_value=self.mock_session)

        self.owner_admin = {
            "id": "600000000000000000000001",
            "_id": ObjectId("600000000000000000000001"),
            "name": "Syahid Owner",
            "role": "owner",
            "permissions": {"manage_orders": True, "access_finance": True},
        }
        self.staff_admin = {
            "id": "600000000000000000000002",
            "_id": ObjectId("600000000000000000000002"),
            "name": "Budi Staff",
            "role": "admin",
            "permissions": {"manage_orders": True, "access_finance": False},
        }
        self.recipient_admin = {
            "id": "600000000000000000000003",
            "_id": ObjectId("600000000000000000000003"),
            "name": "Siti Admin",
            "role": "admin",
            "permissions": {"manage_orders": True},
        }
        self.default_policy_doc = {
            "key": "admin_wage_policy",
            "value": {
                "default_wage_per_order_le": 150.0,
                "default_recipient_id": "600000000000000000000003",
                "default_recipient_name": "Siti Admin",
                "unusual_amount_threshold_le": 300.0,
                "max_wage_per_order_le": 500.0,
                "enabled": True,
                "currency": "EGP",
                "rounding_policy": "piastre_round_half_up",
                "updated_at": "2026-10-28T00:00:00Z",
                "updated_by_id": "600000000000000000000001",
                "updated_by_name": "Syahid Owner",
                "last_change_reason": "Kebijakan dasar upah admin",
            }
        }
        self.sample_order = {
            "_id": ObjectId("600000000000000000000010"),
            "order_number": "ORD-2026-0010",
            "total_le": 5000.0,
            "paid_amount_le": 0.0,
            "outstanding_amount_le": 5000.0,
            "payment_status": "unpaid",
            "updated_at": "2026-10-28T10:00:00Z",
            "updated_by_name": "System",
        }

    def _setup_mock_db(self, mock_db, policy_doc=_NOT_SET, order_doc=None, wob_doc=None):
        pol = policy_doc if policy_doc is not _NOT_SET else self.default_policy_doc
        mock_db.settings.find_one = AsyncMock(side_effect=lambda q, **kw: (
            pol if q.get("key") == "admin_wage_policy" else None
        ))
        
        ord_doc = order_doc if order_doc is not None else copy.deepcopy(self.sample_order)
        mock_db.orders.find_one = AsyncMock(return_value=ord_doc)
        mock_db.orders.update_one = AsyncMock(return_value=MagicMock(matched_count=1, modified_count=1))

        mock_db.wage_obligations.find_one = AsyncMock(return_value=wob_doc)
        mock_db.wage_obligations.insert_one = AsyncMock()
        mock_db.wage_obligations.update_one = AsyncMock()

        mock_db.audit_logs.insert_one = AsyncMock()

        async def mock_admin_find(query, **kwargs):
            q_id = str(query.get("_id") or "")
            if "600000000000000000000003" in q_id:
                return self.recipient_admin
            if "600000000000000000000002" in q_id:
                return self.staff_admin
            if "600000000000000000000001" in q_id:
                return self.owner_admin
            return None

        mock_db.admins.find_one = AsyncMock(side_effect=mock_admin_find)

    # --------------------------------------------------------------------------
    # GROUP 1: Authentication and Authorization (Scenarios 1 - 7)
    # --------------------------------------------------------------------------

    async def test_01_owner_can_read_configuration(self):
        """1. Valid Owner can read configuration via GET."""
        order_doc = copy.deepcopy(self.sample_order)
        order_doc["admin_wage_override"] = {
            "is_override": True,
            "amount_le": 200.0,
            "recipient_id": "600000000000000000000003",
            "recipient_name": "Siti Admin",
            "override_reason": "Order kustom kompleks",
        }
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, order_doc=order_doc)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            resp = await admin_get_order_admin_wage(
                order_id="600000000000000000000010",
                admin=self.owner_admin
            )
        self.assertEqual(resp["order_id"], "600000000000000000000010")
        self.assertTrue(resp["is_override"])
        self.assertEqual(resp["effective_configuration"]["amount_le"], 200.0)
        self.assertTrue(resp["is_editable"])
        self.assertIsNone(resp["editing_restriction_reason"])

    async def test_02_owner_can_create_override(self):
        """2. Valid Owner can create an override via PUT."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        payload = AdminWageOverrideInput(
            is_override=True,
            amount_le=220.0,
            recipient_id="600000000000000000000003",
            override_reason="Bonus penanganan pesanan besar"
        )

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            resp = await admin_update_order_admin_wage(
                order_id="600000000000000000000010",
                payload=payload,
                admin=self.owner_admin
            )
        self.assertEqual(resp["order_id"], "600000000000000000000010")
        self.assertTrue(resp["saved_override"]["is_override"])
        self.assertEqual(resp["saved_override"]["amount_le"], 220.0)
        self.assertEqual(resp["effective_configuration"]["amount_le"], 220.0)

        # Audit log written with order_admin_wage_override_set
        audit_call = mock_db.audit_logs.insert_one.call_args[0][0]
        self.assertEqual(audit_call["action"], "order_admin_wage_override_set")

    async def test_03_owner_can_update_override(self):
        """3. Valid Owner can update an existing override via PUT."""
        order_doc = copy.deepcopy(self.sample_order)
        order_doc["admin_wage_override"] = {
            "is_override": True,
            "amount_le": 220.0,
            "recipient_id": "600000000000000000000003",
            "recipient_name": "Siti Admin",
        }
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, order_doc=order_doc)

        payload = AdminWageOverrideInput(
            is_override=True,
            amount_le=250.0,
            recipient_id="600000000000000000000003",
            override_reason="Penyesuaian spesifikasi tambahan"
        )

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            resp = await admin_update_order_admin_wage(
                order_id="600000000000000000000010",
                payload=payload,
                admin=self.owner_admin
            )
        self.assertEqual(resp["saved_override"]["amount_le"], 250.0)

        audit_call = mock_db.audit_logs.insert_one.call_args[0][0]
        self.assertEqual(audit_call["action"], "order_admin_wage_override_updated")

    async def test_04_non_owner_cannot_mutate_configuration(self):
        """4. Non-Owner cannot mutate configuration (HTTP 403 Forbidden)."""
        dep = require_owner()
        with self.assertRaises(HTTPException) as ctx:
            await dep(admin=self.staff_admin)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Hanya Owner/CEO", ctx.exception.detail)

    async def test_05_unauthenticated_caller_rejected(self):
        """5. Unauthenticated caller is rejected (HTTP 401)."""
        mock_req = MagicMock()
        mock_req.cookies = {}
        mock_req.headers = {}
        with self.assertRaises(HTTPException) as ctx:
            await get_current_admin(mock_req)
        self.assertEqual(ctx.exception.status_code, 401)

    async def test_06_unknown_order_id_returns_404(self):
        """6. Unknown order ID returns HTTP 404 Not Found."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        mock_db.orders.find_one = AsyncMock(return_value=None)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as ctx_get:
                await admin_get_order_admin_wage("600000000000000000000099", admin=self.owner_admin)
            self.assertEqual(ctx_get.exception.status_code, 404)

            payload = AdminWageOverrideInput(is_override=False)
            with self.assertRaises(HTTPException) as ctx_put:
                await admin_update_order_admin_wage("600000000000000000000099", payload=payload, admin=self.owner_admin)
            self.assertEqual(ctx_put.exception.status_code, 404)

    async def test_07_recipient_id_does_not_permit_privilege_escalation(self):
        """7. Recipient ID does not permit privilege escalation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        payload = AdminWageOverrideInput(
            is_override=True,
            amount_le=180.0,
            recipient_id="600000000000000000000002"
        )
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            await admin_update_order_admin_wage(
                order_id="600000000000000000000010",
                payload=payload,
                admin=self.owner_admin
            )

        # The staff admin recipient document is untouched (no role/permission elevation)
        self.assertEqual(self.staff_admin["role"], "admin")
        self.assertFalse(self.staff_admin["permissions"]["access_finance"])

    # --------------------------------------------------------------------------
    # GROUP 2: Payload Validation (Scenarios 8 - 19)
    # --------------------------------------------------------------------------

    def test_08_valid_amount_and_recipient(self):
        """8. Valid amount and recipient in payload accepted."""
        p = AdminWageOverrideInput(is_override=True, amount_le=175.5, recipient_id="600000000000000000000003")
        self.assertTrue(p.is_override)
        self.assertEqual(p.amount_le, 175.5)
        self.assertEqual(p.recipient_id, "600000000000000000000003")

    async def test_09_amount_only_override_uses_policy_default_recipient(self):
        """9. Valid amount-only override falls back to policy default recipient."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        payload = AdminWageOverrideInput(is_override=True, amount_le=210.0, recipient_id=None)
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            resp = await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)

        self.assertEqual(resp["saved_override"]["recipient_id"], "600000000000000000000003")
        self.assertEqual(resp["saved_override"]["recipient_name"], "Siti Admin")

    async def test_10_disabled_override(self):
        """10. Disabled override payload (is_override: False)."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        payload = AdminWageOverrideInput(is_override=False)
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            resp = await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)

        self.assertFalse(resp["saved_override"]["is_override"])
        self.assertIsNone(resp["saved_override"]["amount_le"])
        self.assertEqual(resp["effective_configuration"]["source"], "policy_default")

    async def test_11_explicit_clearing_of_override(self):
        """11. Explicit clearing of an override restores policy default."""
        order_doc = copy.deepcopy(self.sample_order)
        order_doc["admin_wage_override"] = {
            "is_override": True,
            "amount_le": 250.0,
            "recipient_id": "600000000000000000000003",
        }
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, order_doc=order_doc)

        payload = AdminWageOverrideInput(is_override=False, override_reason="Kembali ke tarif standar")
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            resp = await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)

        self.assertFalse(resp["saved_override"]["is_override"])
        self.assertEqual(resp["effective_configuration"]["amount_le"], 150.0)

        audit_call = mock_db.audit_logs.insert_one.call_args[0][0]
        self.assertEqual(audit_call["action"], "order_admin_wage_override_cleared")

    def test_12_negative_amount_rejected(self):
        """12. Negative amount rejected with validation error."""
        with self.assertRaises(ValidationError) as ctx:
            AdminWageOverrideInput(is_override=True, amount_le=-50.0)
        self.assertIn("Nominal upah harus lebih besar dari 0", str(ctx.exception))

    def test_13_boolean_amount_rejected(self):
        """13. Boolean supplied as amount rejected (does not coerce to 1.0 or 0.0)."""
        with self.assertRaises(ValidationError) as ctx_true:
            AdminWageOverrideInput(is_override=True, amount_le=True)
        self.assertIn("Nominal upah tidak boleh berupa boolean", str(ctx_true.exception))

        with self.assertRaises(ValidationError) as ctx_false:
            AdminWageOverrideInput(is_override=True, amount_le=False)
        self.assertIn("Nominal upah tidak boleh berupa boolean", str(ctx_false.exception))

    def test_14_nan_and_infinity_rejected(self):
        """14. NaN and infinity rejected."""
        with self.assertRaises(ValidationError) as ctx_nan:
            AdminWageOverrideInput(is_override=True, amount_le=float("nan"))
        self.assertIn("Nominal upah tidak boleh NaN atau Infinity", str(ctx_nan.exception))

        with self.assertRaises(ValidationError) as ctx_inf:
            AdminWageOverrideInput(is_override=True, amount_le=float("inf"))
        self.assertIn("Nominal upah tidak boleh NaN atau Infinity", str(ctx_inf.exception))

    async def test_15_malformed_recipient_id_rejected(self):
        """15. Malformed recipient ID rejected with HTTP 422."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        payload = AdminWageOverrideInput(is_override=True, amount_le=200.0, recipient_id="invalid#id!@#")
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as ctx:
                await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("tidak ditemukan di sistem", ctx.exception.detail)

    async def test_16_nonexistent_recipient_rejected(self):
        """16. Nonexistent recipient rejected when explicit recipient is given."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        payload = AdminWageOverrideInput(is_override=True, amount_le=200.0, recipient_id="600000000000000000000999")
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as ctx:
                await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_17_unknown_fields_handled_according_to_conventions(self):
        """17. Unknown fields ignored or handled safely according to conventions."""
        p = AdminWageOverrideInput(is_override=True, amount_le=200.0, unexpected_field="should_be_ignored")
        self.assertTrue(p.is_override)
        self.assertEqual(p.amount_le, 200.0)
        self.assertFalse(hasattr(p, "unexpected_field"))

    async def test_18_missing_required_fields_rejected(self):
        """18. Missing required fields rejected."""
        # Missing is_override entirely raises ValidationError
        with self.assertRaises(ValidationError):
            AdminWageOverrideInput()

        # is_override: True with both amount_le and recipient_id missing raises HTTPException(422)
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        payload = AdminWageOverrideInput(is_override=True)
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as ctx:
                await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("memerlukan nominal (amount_le) atau penerima (recipient_id)", ctx.exception.detail)

    def test_19_zero_amount_rejected(self):
        """19. Zero amount handled according to documented policy (rejected with 422)."""
        with self.assertRaises(ValidationError) as ctx:
            AdminWageOverrideInput(is_override=True, amount_le=0.0)
        self.assertIn("Nominal upah harus lebih besar dari 0", str(ctx.exception))

    # --------------------------------------------------------------------------
    # GROUP 3: Policy and Hard Cap (Scenarios 20 - 24)
    # --------------------------------------------------------------------------

    async def test_20_valid_amount_below_cap_accepted(self):
        """20. Valid amount below hard cap accepted."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        payload = AdminWageOverrideInput(
            is_override=True,
            amount_le=450.0,
            recipient_id="600000000000000000000003",
            override_reason="Pesanan proyek hotel kustom besar"
        )
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            resp = await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)
        self.assertEqual(resp["saved_override"]["amount_le"], 450.0)

    async def test_21_amount_above_hard_cap_rejected_without_saving(self):
        """21. Amount above hard cap rejected without saving (HTTP 422)."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        payload = AdminWageOverrideInput(
            is_override=True,
            amount_le=550.0,
            recipient_id="600000000000000000000003"
        )
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as ctx:
                await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("melebihi batas maksimum", ctx.exception.detail)

    async def test_22_missing_or_disabled_policy_handled_safely(self):
        """22. Missing or disabled policy handled safely."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, policy_doc=None)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            # GET reports policy unconfigured safely
            resp_get = await admin_get_order_admin_wage("600000000000000000000010", admin=self.owner_admin)
            self.assertFalse(resp_get["policy_context"]["is_configured"])
            self.assertFalse(resp_get["policy_context"]["enabled"])

            # PUT with explicit amount and recipient succeeds safely
            payload = AdminWageOverrideInput(
                is_override=True,
                amount_le=200.0,
                recipient_id="600000000000000000000003"
            )
            resp_put = await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)
            self.assertEqual(resp_put["saved_override"]["amount_le"], 200.0)

    async def test_23_global_policy_remains_unchanged(self):
        """23. Global policy remains unchanged after override update."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        payload = AdminWageOverrideInput(
            is_override=True,
            amount_le=350.0,
            recipient_id="600000000000000000000003",
            override_reason="Alasan valid 350 LE"
        )
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)

        # Ensure update was only applied to db.orders, NOT db.settings
        self.assertFalse(mock_db.settings.update_one.called)

    async def test_24_no_wage_obligation_created_during_read_or_update(self):
        """24. No wage obligation is created during a read or configuration update."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            # Read
            await admin_get_order_admin_wage("600000000000000000000010", admin=self.owner_admin)

            # Update
            payload = AdminWageOverrideInput(is_override=True, amount_le=200.0, recipient_id="600000000000000000000003")
            await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)

        # Ensure no insert into db.wage_obligations occurred
        self.assertFalse(mock_db.wage_obligations.insert_one.called)

    # --------------------------------------------------------------------------
    # GROUP 4: Lifecycle Protection (Scenarios 25 - 33)
    # --------------------------------------------------------------------------

    async def test_25_eligible_order_before_accrual_can_be_configured(self):
        """25. Eligible order before accrual can be configured."""
        order_doc = copy.deepcopy(self.sample_order)
        order_doc["payment_status"] = "dp"
        order_doc["paid_amount_le"] = 2500.0

        mock_db = MagicMock()
        self._setup_mock_db(mock_db, order_doc=order_doc)

        payload = AdminWageOverrideInput(is_override=True, amount_le=200.0, recipient_id="600000000000000000000003")
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            resp = await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)

        self.assertEqual(resp["saved_override"]["amount_le"], 200.0)
        self.assertIsNone(resp["existing_obligation"])

    async def test_26_existing_accrued_obligation_remains_unchanged_after_edit(self):
        """26. Existing accrued obligation remains unchanged after configuration edit."""
        order_doc = copy.deepcopy(self.sample_order)
        order_doc["payment_status"] = "lunas"

        existing_wob = {
            "_id": ObjectId("600000000000000000000050"),
            "obligation_number": "WOB-2026-0050",
            "task_category": "admin",
            "status": "accrued",
            "total_amount_le": 150.0,
            "worker_id": "600000000000000000000003",
            "worker_name": "Siti Admin",
            "accrued_at": "2026-10-28T12:00:00Z",
            "is_override": False,
        }

        mock_db = MagicMock()
        self._setup_mock_db(mock_db, order_doc=order_doc, wob_doc=existing_wob)

        payload = AdminWageOverrideInput(
            is_override=True,
            amount_le=250.0,
            recipient_id="600000000000000000000002",
            override_reason="Catatan override untuk pesanan lunas"
        )
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            resp = await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)

        # The saved override is updated
        self.assertEqual(resp["saved_override"]["amount_le"], 250.0)
        self.assertEqual(resp["saved_override"]["recipient_id"], "600000000000000000000002")

        # But existing obligation remains unchanged at 150.0 and Siti Admin
        self.assertIsNotNone(resp["existing_obligation"])
        self.assertEqual(resp["existing_obligation"]["amount_le"], 150.0)
        self.assertEqual(resp["existing_obligation"]["worker_name"], "Siti Admin")

        # Ensure db.wage_obligations was NOT updated
        self.assertFalse(mock_db.wage_obligations.update_one.called)

    async def test_27_reassignment_configuration_change_is_auditable(self):
        """27. Any permitted reassignment/configuration change is auditable."""
        order_doc = copy.deepcopy(self.sample_order)
        order_doc["admin_wage_override"] = {
            "is_override": True,
            "amount_le": 200.0,
            "recipient_id": "600000000000000000000003",
            "recipient_name": "Siti Admin",
        }

        mock_db = MagicMock()
        self._setup_mock_db(mock_db, order_doc=order_doc)

        payload = AdminWageOverrideInput(
            is_override=True,
            amount_le=200.0,
            recipient_id="600000000000000000000002",
            override_reason="Alihkan penerima ke Budi"
        )
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)

        audit_call = mock_db.audit_logs.insert_one.call_args[0][0]
        self.assertEqual(audit_call["action"], "order_admin_wage_override_updated")
        self.assertEqual(audit_call["metadata"]["previous_override"]["recipient_id"], "600000000000000000000003")
        self.assertEqual(audit_call["metadata"]["new_override"]["recipient_id"], "600000000000000000000002")

    async def test_28_partially_paid_obligation_blocked_409(self):
        """28. Partially paid obligation cannot be modified (HTTP 409 Conflict)."""
        partially_paid_wob = {
            "_id": ObjectId("600000000000000000000051"),
            "obligation_number": "WOB-2026-0051",
            "task_category": "admin",
            "status": "partially_paid",
            "total_amount_le": 150.0,
            "paid_amount_le": 50.0,
        }
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, wob_doc=partially_paid_wob)

        payload = AdminWageOverrideInput(is_override=True, amount_le=200.0)
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as ctx:
                await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("partially_paid", ctx.exception.detail)

    async def test_29_fully_paid_obligation_blocked_409(self):
        """29. Fully paid obligation cannot be modified (HTTP 409 Conflict)."""
        paid_wob = {
            "_id": ObjectId("600000000000000000000052"),
            "obligation_number": "WOB-2026-0052",
            "task_category": "admin",
            "status": "paid",
            "total_amount_le": 150.0,
            "paid_amount_le": 150.0,
        }
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, wob_doc=paid_wob)

        payload = AdminWageOverrideInput(is_override=False)
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as ctx:
                await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("paid", ctx.exception.detail)

    async def test_30_voided_obligation_blocked_409(self):
        """30. Voided obligation cannot be revived (HTTP 409 Conflict)."""
        voided_wob = {
            "_id": ObjectId("600000000000000000000053"),
            "obligation_number": "WOB-2026-0053",
            "task_category": "admin",
            "status": "voided",
            "total_amount_le": 150.0,
        }
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, wob_doc=voided_wob)

        payload = AdminWageOverrideInput(is_override=True, amount_le=180.0)
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as ctx:
                await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("voided", ctx.exception.detail)

    async def test_31_legacy_reconciled_order_blocked_409(self):
        """31. Legacy-reconciled order cannot bypass its guard (HTTP 409 Conflict)."""
        order_doc = copy.deepcopy(self.sample_order)
        order_doc["admin_wage_legacy_reconciled"] = True

        mock_db = MagicMock()
        self._setup_mock_db(mock_db, order_doc=order_doc)

        payload = AdminWageOverrideInput(is_override=True, amount_le=200.0)
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as ctx:
                await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("admin_wage_legacy_reconciled", ctx.exception.detail)

    async def test_32_blocked_state_resolved_safely_without_auto_accrual(self):
        """32. Existing admin_wage_blocked state is resolved safely without auto-accrual."""
        order_doc = copy.deepcopy(self.sample_order)
        order_doc["admin_wage_blocked"] = {
            "status": "blocked_hard_cap_conflict",
            "reason": "Nominal upah override (600 LE) melebihi batas maksimum aktif (500 LE)",
            "attempted_amount_le": 600.0,
            "max_wage_per_order_le": 500.0,
            "blocked_at": "2026-10-28T11:00:00Z",
        }

        mock_db = MagicMock()
        self._setup_mock_db(mock_db, order_doc=order_doc)

        # Owner submits corrective override within hard cap (e.g. 400 LE)
        payload = AdminWageOverrideInput(
            is_override=True,
            amount_le=400.0,
            recipient_id="600000000000000000000003",
            override_reason="Koreksi nominal sesuai batas maksimum"
        )
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            resp = await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)

        # Blocked state is resolved
        self.assertIsNotNone(resp["resolved_blocked_state"])
        self.assertEqual(resp["resolved_blocked_state"]["status"], "blocked_hard_cap_conflict")

        # In db.orders update, admin_wage_blocked was set to None
        update_call = mock_db.orders.update_one.call_args[0][1]["$set"]
        self.assertIsNone(update_call["admin_wage_blocked"])

        # No wage obligation was auto-accrued
        self.assertFalse(mock_db.wage_obligations.insert_one.called)

    async def test_33_configuration_update_does_not_settle_obligation(self):
        """33. Configuration update does not create or settle an obligation."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        payload = AdminWageOverrideInput(is_override=True, amount_le=200.0, recipient_id="600000000000000000000003")
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)

        # Verify no calls to wage_obligations or wage_settlements
        self.assertFalse(mock_db.wage_obligations.insert_one.called)
        self.assertFalse(mock_db.wage_obligations.update_one.called)

    # --------------------------------------------------------------------------
    # GROUP 5: Audit and Integrity (Scenarios 34 - 38)
    # --------------------------------------------------------------------------

    async def test_34_successful_mutation_produces_expected_audit_event(self):
        """34. Successful mutation produces the expected audit event in db.audit_logs."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        payload = AdminWageOverrideInput(is_override=True, amount_le=200.0, recipient_id="600000000000000000000003")
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)

        audit_call = mock_db.audit_logs.insert_one.call_args[0][0]
        self.assertEqual(audit_call["action"], "order_admin_wage_override_set")
        self.assertEqual(audit_call["entity_type"], "order")
        self.assertEqual(audit_call["performed_by_id"], "600000000000000000000001")

    async def test_35_audit_record_contains_correct_before_after_values(self):
        """35. Audit record contains the correct before and after values."""
        order_doc = copy.deepcopy(self.sample_order)
        order_doc["admin_wage_override"] = {
            "is_override": True,
            "amount_le": 190.0,
            "recipient_id": "600000000000000000000003",
        }
        mock_db = MagicMock()
        self._setup_mock_db(mock_db, order_doc=order_doc)

        payload = AdminWageOverrideInput(is_override=True, amount_le=220.0, recipient_id="600000000000000000000003")
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)

        audit_doc = mock_db.audit_logs.insert_one.call_args[0][0]
        self.assertEqual(audit_doc["metadata"]["previous_override"]["amount_le"], 190.0)
        self.assertEqual(audit_doc["metadata"]["new_override"]["amount_le"], 220.0)

    async def test_36_audit_failure_aborts_mutation(self):
        """36. Audit failure is handled according to consistency contract (propagates exception)."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)
        mock_db.audit_logs.insert_one = AsyncMock(side_effect=pymongo.errors.PyMongoError("Audit collection write failure"))

        payload = AdminWageOverrideInput(is_override=True, amount_le=200.0, recipient_id="600000000000000000000003")
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(pymongo.errors.PyMongoError):
                await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)

    async def test_37_failed_validation_does_not_leave_partial_update(self):
        """37. Failed validation does not leave a partial configuration update."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        # Attempting override above hard cap (e.g. 999 LE)
        payload = AdminWageOverrideInput(is_override=True, amount_le=999.0, recipient_id="600000000000000000000003")
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException):
                await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)

        # Ensure update was NEVER called
        self.assertFalse(mock_db.orders.update_one.called)

    async def test_38_optimistic_concurrency_conflict_returns_409(self):
        """38. Concurrent or stale-state update is handled safely via OCC (returns 409 Conflict)."""
        mock_db = MagicMock()
        self._setup_mock_db(mock_db)

        # Simulate concurrent update: matched_count = 0
        mock_db.orders.update_one = AsyncMock(return_value=MagicMock(matched_count=0))

        payload = AdminWageOverrideInput(is_override=True, amount_le=200.0, recipient_id="600000000000000000000003")
        with patch("server.db", mock_db), patch("server.client", self.mock_client):
            with self.assertRaises(HTTPException) as ctx:
                await admin_update_order_admin_wage("600000000000000000000010", payload=payload, admin=self.owner_admin)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("Konflik konkurensi", ctx.exception.detail)
