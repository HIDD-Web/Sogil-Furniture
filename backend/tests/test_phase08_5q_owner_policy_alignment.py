"""
Test Suite: Phase 08.5Q — Owner Policy Alignment & Configuration Verification
Directly verifies the 15 mandatory business scenarios established by the Owner:

1. An order completed and fully paid before activation receives no automatic obligation.
2. An older order still incomplete and unpaid at activation accrues when it later becomes completed and fully paid while automation is active.
3. An older order completed but not fully paid at activation accrues when payment becomes fully settled while automation is active.
4. An older order fully paid but incomplete at activation accrues when it becomes completed while automation is active.
5. An order that matures during an OFF period does not retroactively accrue merely because automation is re-enabled.
6. An order that is still incomplete or not fully paid at reactivation can accrue when its missing condition becomes true during the active cycle.
7. Valid explicit manual configuration is preserved across global policy changes.
8. Valid manual accrual follows its intended rules while global automatic accrual is OFF.
9. Existing obligations are not duplicated.
10. A previously voided obligation is not silently recreated.
11. A historical order cannot bypass exclusion by supplying forged lifecycle context or a fabricated order snapshot.
12. The configured base rate, warning threshold, and hard cap are read from the actual authoritative policy source (db.settings: 50 LE base, 75 LE threshold, 100 LE cap, Azka recipient).
13. Changes saved through the web app are reflected in backend configuration reads.
14. Invalid values and hard-cap violations fail safely without creating invalid obligations.
15. Missing or unreadable configuration fails safely and does not silently substitute unapproved hardcoded rates.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from fastapi import HTTPException
from pydantic import ValidationError

from server import (
    AdminWagePolicyInput,
    build_admin_wage_accrual_event_key,
    get_order_admin_wage_eligibility,
    get_active_admin_wage_policy,
    process_order_admin_wage_accrual,
    admin_update_wage_policy_endpoint,
)


class TestPhase08_5QOwnerPolicyAlignment(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.owner_user = {
            "id": "600000000000000000000001",
            "_id": ObjectId("600000000000000000000001"),
            "name": "Owner Sogil",
            "role": "owner",
            "permissions": {"access_finance": True, "manage_orders": True},
        }
        self.admin_staff = {
            "id": "600000000000000000000002",
            "_id": ObjectId("600000000000000000000002"),
            "name": "Staff Toko",
            "role": "admin",
            "permissions": {"manage_orders": True},
        }
        # Authoritative configured recipient: Azka
        self.azka_admin = {
            "_id": ObjectId("6a9031b86f261cb1ed5479ad"),
            "id": "6a9031b86f261cb1ed5479ad",
            "name": "Azka",
            "role": "admin",
            "active": True,
        }

        self.mock_session = AsyncMock()
        self.mock_session.__aenter__.return_value = self.mock_session
        self.mock_session.__aexit__.return_value = None
        self.mock_session.start_transaction = MagicMock()
        self.mock_session.start_transaction.return_value.__aenter__ = AsyncMock(return_value=self.mock_session)
        self.mock_session.start_transaction.return_value.__aexit__ = AsyncMock(return_value=None)
        self.mock_session.commit_transaction = AsyncMock()
        self.mock_session.abort_transaction = AsyncMock()

        self.mock_client = MagicMock()
        self.mock_client.start_session = AsyncMock(return_value=self.mock_session)

    def _get_authoritative_policy_doc(self, enabled=False, cycles=None):
        """Returns the Owner's authoritative policy document as persisted in db.settings."""
        if cycles is None:
            cycles = [{
                "cycle_id": "cycle_active_001",
                "enabled_at": "2026-10-29T10:00:00Z",
                "disabled_at": None if enabled else "2026-10-29T18:00:00Z",
                "enabled_by_name": "Owner Sogil",
            }]
        return {
            "key": "admin_wage_policy",
            "value": {
                "default_wage_per_order_le": 50.0,
                "unusual_amount_threshold_le": 75.0,  # Authoritative threshold entered by Owner
                "max_wage_per_order_le": 100.0,       # Authoritative hard cap
                "default_recipient_id": "6a9031b86f261cb1ed5479ad",
                "default_recipient_name": "Azka",      # Authoritative recipient entered by Owner
                "enabled": enabled,
                "currency": "EGP",
                "rounding_policy": "piastre_round_half_up",
                "is_configured": True,
                "activation_cycles": cycles,
                "current_cycle_id": "cycle_active_001" if enabled else None,
                "initial_activation_at": "2026-10-29T10:00:00Z",
            }
        }

    def _setup_mock_db(self, mock_db, policy_enabled=True, cycles=None):
        policy_doc = self._get_authoritative_policy_doc(enabled=policy_enabled, cycles=cycles)

        mock_db.settings.find_one = AsyncMock(side_effect=lambda q, **kw: (
            policy_doc if q.get("key") == "admin_wage_policy"
            else {"key": "exchange_rate_idr_per_le", "value": 357.0}
        ))
        mock_db.settings.update_one = AsyncMock(return_value=MagicMock(matched_count=1, modified_count=1))
        mock_db.system_rates.find_one = AsyncMock(return_value={"rate": 357.0})
        mock_db.counters.find_one_and_update = AsyncMock(return_value={"seq": 201})
        mock_db.customers.update_one = AsyncMock()
        mock_db.finance_transactions.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("707f1f77bcf86cd799439033")))
        mock_db.finance_transactions.update_one = AsyncMock()

        async def mock_admin_find_one(query, *args, **kwargs):
            q_id = str(query.get("_id") or query.get("id") or "")
            if "6a9031b86f261cb1ed5479ad" in q_id:
                return self.azka_admin
            if "600000000000000000000002" in q_id:
                return self.admin_staff
            return None
        mock_db.admins.find_one = AsyncMock(side_effect=mock_admin_find_one)

        mock_db.wage_obligations.find_one = AsyncMock(return_value=None)
        mock_db.wage_obligations.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId("507f1f77bcf86cd799439099")))
        mock_db.wage_obligations.update_one = AsyncMock()

        mock_ob_cursor = MagicMock()
        mock_ob_cursor.to_list = AsyncMock(return_value=[])
        mock_db.wage_obligations.find.return_value = mock_ob_cursor

        mock_asn_cursor = MagicMock()
        mock_asn_cursor.to_list = AsyncMock(return_value=[])
        mock_db.work_assignments.find.return_value = mock_asn_cursor

        mock_db.audit_logs.insert_one = AsyncMock(return_value=MagicMock(inserted_id=ObjectId()))

    # -------------------------------------------------------------------------
    # Scenario 1: Order completed and fully paid before activation receives no automatic obligation
    # -------------------------------------------------------------------------
    @patch("server.db")
    async def test_scenario_01_pre_activation_settled_order_receives_no_automatic_obligation(self, mock_db):
        order_id = ObjectId("507f1f77bcf86cd799439011")
        # Settled at 2026-10-28 (prior to cycle enabled at 2026-10-29T10:00:00Z)
        order = {
            "_id": order_id,
            "order_number": "ORD-HIST-001",
            "order_status": "selesai",
            "payment_status": "lunas",
            "completed_at": "2026-10-28T14:00:00Z",
            "paid_at": "2026-10-28T14:30:00Z",
            "total_price": 5000.0,
            "total_paid": 5000.0,
            "status": "selesai",
        }
        self._setup_mock_db(mock_db, policy_enabled=True)
        mock_db.orders.find_one = AsyncMock(return_value=order)
        mock_db.orders.update_one = AsyncMock()

        with patch("server.db", mock_db):
            policy = await get_active_admin_wage_policy(db_inst=mock_db)
            res = await process_order_admin_wage_accrual(
                order,
                self.owner_user,
                policy=policy,
                lifecycle_event="order_completed",
                transition_context={"from_status": "siap_kirim", "to_status": "selesai", "order_id": str(order_id)}
            )

        self.assertEqual(res["status"], "skipped_unverifiable_transition")
        self.assertEqual(res["eligibility"]["scope_status"], "excluded_historical")
        self.assertEqual(res["eligibility"]["skip_reason"], "settled_prior_to_system_activation")
        mock_db.wage_obligations.insert_one.assert_not_called()

    # -------------------------------------------------------------------------
    # Scenario 2: Older order incomplete and unpaid at activation accrues on maturity while active
    # -------------------------------------------------------------------------
    @patch("server.db")
    async def test_scenario_02_older_incomplete_and_unpaid_order_accrues_on_maturity_while_active(self, mock_db):
        order_id = ObjectId("507f1f77bcf86cd799439012")
        # Created prior to activation, completed and transitioning to lunas while active
        persisted_order = {
            "_id": order_id,
            "order_number": "ORD-OLD-002",
            "order_status": "selesai",
            "payment_status": "belum_lunas",
            "status": "selesai",
            "created_at": "2026-10-28T10:00:00Z",
            "completed_at": "2026-10-29T11:00:00Z",
            "total_price": 4000.0,
            "total_paid": 2000.0,
        }
        self._setup_mock_db(mock_db, policy_enabled=True)
        mock_db.orders.find_one = AsyncMock(return_value=persisted_order)
        mock_db.orders.update_one = AsyncMock()

        with patch("server.db", mock_db):
            policy = await get_active_admin_wage_policy(db_inst=mock_db)
            res = await process_order_admin_wage_accrual(
                persisted_order,
                self.owner_user,
                policy=policy,
                lifecycle_event="payment_lunas",
                transition_context={"from_payment_status": "belum_lunas", "to_payment_status": "lunas", "order_id": str(order_id)}
            )

        self.assertEqual(res["status"], "accrued")
        self.assertEqual(res["obligation"]["amount_le"], 50.0)
        self.assertEqual(res["obligation"]["recipient_name"], "Azka")
        self.assertEqual(res["eligibility"]["scope_status"], "accrued")
        mock_db.wage_obligations.insert_one.assert_called_once()

    # -------------------------------------------------------------------------
    # Scenario 3: Older order completed but not fully paid at activation accrues when paid while active
    # -------------------------------------------------------------------------
    @patch("server.db")
    async def test_scenario_03_older_completed_unpaid_order_accrues_when_paid_while_active(self, mock_db):
        order_id = ObjectId("507f1f77bcf86cd799439013")
        # Completed on 2026-10-28 (before activation), but unpaid
        persisted_order = {
            "_id": order_id,
            "order_number": "ORD-COMP-UNPAID-003",
            "order_status": "selesai",
            "status": "selesai",
            "payment_status": "dp",
            "completed_at": "2026-10-28T12:00:00Z",
            "total_price": 6000.0,
            "total_paid": 3000.0,
        }
        self._setup_mock_db(mock_db, policy_enabled=True)
        mock_db.orders.find_one = AsyncMock(return_value=persisted_order)
        mock_db.orders.update_one = AsyncMock()

        with patch("server.db", mock_db):
            policy = await get_active_admin_wage_policy(db_inst=mock_db)
            res = await process_order_admin_wage_accrual(
                persisted_order,
                self.owner_user,
                policy=policy,
                lifecycle_event="payment_lunas",
                transition_context={"from_payment_status": "dp", "to_payment_status": "lunas", "order_id": str(order_id)}
            )

        self.assertEqual(res["status"], "accrued")
        self.assertEqual(res["obligation"]["amount_le"], 50.0)
        self.assertEqual(res["obligation"]["recipient_id"], "6a9031b86f261cb1ed5479ad")
        self.assertEqual(res["eligibility"]["scope_status"], "accrued")
        mock_db.wage_obligations.insert_one.assert_called_once()

    # -------------------------------------------------------------------------
    # Scenario 4: Older order fully paid but incomplete at activation accrues when completed while active
    # -------------------------------------------------------------------------
    @patch("server.db")
    async def test_scenario_04_older_paid_incomplete_order_accrues_when_completed_while_active(self, mock_db):
        order_id = ObjectId("507f1f77bcf86cd799439014")
        # Paid in full on 2026-10-28 (before activation), but still in production
        persisted_order = {
            "_id": order_id,
            "order_number": "ORD-PAID-INCOMP-004",
            "order_status": "dalam_proses",
            "status": "dalam_proses",
            "payment_status": "lunas",
            "paid_at": "2026-10-28T15:00:00Z",
            "total_price": 4500.0,
            "total_paid": 4500.0,
        }
        self._setup_mock_db(mock_db, policy_enabled=True)
        mock_db.orders.find_one = AsyncMock(return_value=persisted_order)
        mock_db.orders.update_one = AsyncMock()

        with patch("server.db", mock_db):
            policy = await get_active_admin_wage_policy(db_inst=mock_db)
            res = await process_order_admin_wage_accrual(
                persisted_order,
                self.owner_user,
                policy=policy,
                lifecycle_event="order_completed",
                transition_context={"from_status": "dalam_proses", "to_status": "selesai", "order_id": str(order_id)}
            )

        self.assertEqual(res["status"], "accrued")
        self.assertEqual(res["obligation"]["amount_le"], 50.0)
        self.assertEqual(res["obligation"]["recipient_name"], "Azka")
        self.assertEqual(res["eligibility"]["scope_status"], "accrued")
        mock_db.wage_obligations.insert_one.assert_called_once()

    # -------------------------------------------------------------------------
    # Scenario 5: Order that matures during an OFF period does not retroactively accrue when re-enabled
    # -------------------------------------------------------------------------
    @patch("server.db")
    async def test_scenario_05_order_matured_during_off_window_never_retroactively_accrued(self, mock_db):
        order_id = ObjectId("507f1f77bcf86cd799439015")
        cycles = [
            {"cycle_id": "c1", "enabled_at": "2026-10-29T08:00:00Z", "disabled_at": "2026-10-29T12:00:00Z"},
            {"cycle_id": "c2", "enabled_at": "2026-10-29T18:00:00Z", "disabled_at": None},
        ]
        order = {
            "_id": order_id,
            "order_number": "ORD-OFF-005",
            "order_status": "selesai",
            "status": "selesai",
            "payment_status": "lunas",
            "completed_at": "2026-10-29T13:00:00Z",
            "paid_at": "2026-10-29T14:00:00Z",  # Matured in OFF window
            "total_price": 3000.0,
            "total_paid": 3000.0,
        }
        self._setup_mock_db(mock_db, policy_enabled=True, cycles=cycles)
        mock_db.orders.find_one = AsyncMock(return_value=order)
        mock_db.orders.update_one = AsyncMock()

        with patch("server.db", mock_db):
            policy = await get_active_admin_wage_policy(db_inst=mock_db)
            res = await process_order_admin_wage_accrual(
                order,
                self.owner_user,
                policy=policy,
                lifecycle_event="payment_lunas",
                transition_context={"from_payment_status": "dp", "to_payment_status": "lunas", "order_id": str(order_id)}
            )

        self.assertEqual(res["status"], "skipped_unverifiable_transition")
        self.assertEqual(res["eligibility"]["scope_status"], "excluded_historical")
        self.assertEqual(res["eligibility"]["skip_reason"], "settled_prior_to_system_activation")
        mock_db.wage_obligations.insert_one.assert_not_called()

    # -------------------------------------------------------------------------
    # Scenario 6: Order incomplete at reactivation can accrue when missing condition matures while active
    # -------------------------------------------------------------------------
    @patch("server.db")
    async def test_scenario_06_order_incomplete_at_reactivation_accrues_when_matured_while_active(self, mock_db):
        order_id = ObjectId("507f1f77bcf86cd799439016")
        cycles = [
            {"cycle_id": "c1", "enabled_at": "2026-10-29T08:00:00Z", "disabled_at": "2026-10-29T12:00:00Z"},
            {"cycle_id": "c2", "enabled_at": "2026-10-29T18:00:00Z", "disabled_at": None},
        ]
        # Order was paid during OFF period (14:00), but NOT completed!
        persisted_order = {
            "_id": order_id,
            "order_number": "ORD-REACTIVATION-006",
            "order_status": "siap_kirim",
            "status": "siap_kirim",
            "payment_status": "lunas",
            "paid_at": "2026-10-29T14:00:00Z",
            "total_price": 5000.0,
            "total_paid": 5000.0,
        }
        self._setup_mock_db(mock_db, policy_enabled=True, cycles=cycles)
        mock_db.orders.find_one = AsyncMock(return_value=persisted_order)
        mock_db.orders.update_one = AsyncMock()

        with patch("server.db", mock_db):
            policy = await get_active_admin_wage_policy(db_inst=mock_db)
            res = await process_order_admin_wage_accrual(
                persisted_order,
                self.owner_user,
                policy=policy,
                lifecycle_event="order_completed",
                transition_context={"from_status": "siap_kirim", "to_status": "selesai", "order_id": str(order_id)}
            )

        self.assertEqual(res["status"], "accrued")
        self.assertEqual(res["obligation"]["amount_le"], 50.0)
        self.assertEqual(res["obligation"]["recipient_name"], "Azka")
        self.assertEqual(res["eligibility"]["scope_status"], "accrued")
        mock_db.wage_obligations.insert_one.assert_called_once()

    # -------------------------------------------------------------------------
    # Scenario 7: Valid explicit manual configuration is preserved across global policy changes
    # -------------------------------------------------------------------------
    @patch("server.db")
    async def test_scenario_07_manual_override_preserved_across_global_policy_toggle_changes(self, mock_db):
        order_id = ObjectId("507f1f77bcf86cd799439017")
        order_with_override = {
            "_id": order_id,
            "order_number": "ORD-OVR-007",
            "order_status": "selesai",
            "status": "selesai",
            "payment_status": "lunas",
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 65.0,
                "recipient_id": "600000000000000000000002",
                "recipient_name": "Staff Toko",
                "override_reason": "Pesanan rumit dengan penanganan custom",
                "configured_by_name": "Owner Sogil",
                "configured_at": "2026-10-29T09:00:00Z"
            }
        }
        # Test 1: Global policy is OFF -> Manual override still evaluated correctly
        self._setup_mock_db(mock_db, policy_enabled=False)
        with patch("server.db", mock_db):
            policy_off = await get_active_admin_wage_policy(db_inst=mock_db)
            el_off = get_order_admin_wage_eligibility(order_with_override, policy=policy_off)
        self.assertEqual(el_off["governance_mode"], "manual_override")
        self.assertEqual(el_off["scope_status"], "manual_override")

        # Test 2: Global policy becomes ON -> Manual override preserved without reverting to global default
        self._setup_mock_db(mock_db, policy_enabled=True)
        with patch("server.db", mock_db):
            policy_on = await get_active_admin_wage_policy(db_inst=mock_db)
            el_on = get_order_admin_wage_eligibility(order_with_override, policy=policy_on)
        self.assertEqual(el_on["governance_mode"], "manual_override")
        self.assertEqual(el_on["scope_status"], "manual_override")

    # -------------------------------------------------------------------------
    # Scenario 8: Valid manual accrual follows intended rules while global automatic accrual is OFF
    # -------------------------------------------------------------------------
    @patch("server.db")
    async def test_scenario_08_valid_manual_accrual_succeeds_while_global_automation_is_off(self, mock_db):
        order_id = ObjectId("507f1f77bcf86cd799439018")
        order = {
            "_id": order_id,
            "order_number": "ORD-MANUAL-008",
            "order_status": "selesai",
            "status": "selesai",
            "payment_status": "lunas",
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 60.0,
                "recipient_id": "600000000000000000000002",
                "recipient_name": "Staff Toko",
                "override_reason": "Manual commission approved by Owner",
            }
        }
        self._setup_mock_db(mock_db, policy_enabled=False)  # Global policy is OFF
        mock_db.orders.find_one = AsyncMock(return_value=order)
        mock_db.orders.update_one = AsyncMock()

        with patch("server.db", mock_db):
            policy = await get_active_admin_wage_policy(db_inst=mock_db)
            self.assertFalse(policy["enabled"])

            res = await process_order_admin_wage_accrual(
                order,
                self.owner_user,
                policy=policy,
                lifecycle_event="manual_override_approved"
            )

        self.assertEqual(res["status"], "accrued")
        self.assertEqual(res["obligation"]["amount_le"], 60.0)
        self.assertEqual(res["obligation"]["recipient_name"], "Staff Toko")
        self.assertTrue(res["obligation"]["is_override"])
        self.assertEqual(res["eligibility"]["governance_mode"], "manual_override")
        mock_db.wage_obligations.insert_one.assert_called_once()

    # -------------------------------------------------------------------------
    # Scenario 9: Existing obligations are not duplicated
    # -------------------------------------------------------------------------
    @patch("server.db")
    async def test_scenario_09_existing_obligations_are_never_duplicated(self, mock_db):
        order_id = ObjectId("507f1f77bcf86cd799439019")
        order = {
            "_id": order_id,
            "order_number": "ORD-IDEMPOTENT-009",
            "order_status": "selesai",
            "payment_status": "lunas",
            "admin_wage_obligation": {
                "obligation_id": "507f1f77bcf86cd799439099",
                "status": "accrued",
                "amount_le": 50.0,
                "recipient_name": "Azka"
            }
        }
        self._setup_mock_db(mock_db, policy_enabled=True)
        existing_wob = {
            "_id": ObjectId("507f1f77bcf86cd799439099"),
            "obligation_number": "WOB-2026-001",
            "status": "accrued",
            "total_amount_le": 50.0,
            "worker_name": "Azka",
            "accrual_event_key": build_admin_wage_accrual_event_key(str(order_id)),
        }
        mock_db.wage_obligations.find_one = AsyncMock(return_value=existing_wob)
        mock_db.orders.find_one = AsyncMock(return_value=order)
        mock_db.orders.update_one = AsyncMock()

        with patch("server.db", mock_db):
            policy = await get_active_admin_wage_policy(db_inst=mock_db)
            res = await process_order_admin_wage_accrual(
                order,
                self.owner_user,
                policy=policy,
                lifecycle_event="order_completed",
                transition_context={"from_status": "siap_kirim", "to_status": "selesai", "order_id": str(order_id)}
            )

        self.assertEqual(res["status"], "already_accrued")
        mock_db.wage_obligations.insert_one.assert_not_called()

    # -------------------------------------------------------------------------
    # Scenario 10: Previously voided obligation is not silently recreated
    # -------------------------------------------------------------------------
    @patch("server.db")
    async def test_scenario_10_previously_voided_obligation_is_not_silently_recreated(self, mock_db):
        order_id = ObjectId("507f1f77bcf86cd799439020")
        order = {
            "_id": order_id,
            "order_number": "ORD-VOIDED-010",
            "order_status": "selesai",
            "payment_status": "lunas",
            "admin_wage_obligation": {
                "obligation_id": "507f1f77bcf86cd799439088",
                "status": "void",
                "amount_le": 50.0,
                "void_reason": "Pesanan retur pembatalan penuh"
            }
        }
        self._setup_mock_db(mock_db, policy_enabled=True)
        existing_wob = {
            "_id": ObjectId("507f1f77bcf86cd799439088"),
            "obligation_number": "WOB-2026-VOID-001",
            "status": "void",
            "total_amount_le": 50.0,
            "worker_name": "Azka",
            "accrual_event_key": build_admin_wage_accrual_event_key(str(order_id)),
        }
        mock_db.wage_obligations.find_one = AsyncMock(return_value=existing_wob)
        mock_db.orders.find_one = AsyncMock(return_value=order)
        mock_db.orders.update_one = AsyncMock()

        with patch("server.db", mock_db):
            policy = await get_active_admin_wage_policy(db_inst=mock_db)
            res = await process_order_admin_wage_accrual(
                order,
                self.owner_user,
                policy=policy,
                lifecycle_event="payment_lunas",
                transition_context={"from_payment_status": "dp", "to_payment_status": "lunas", "order_id": str(order_id)}
            )

        self.assertEqual(res["status"], "blocked_prior_voided_obligation")
        self.assertEqual(res["eligibility"]["scope_status"], "blocked")
        mock_db.wage_obligations.insert_one.assert_not_called()

    # -------------------------------------------------------------------------
    # Scenario 11: Historical order cannot bypass exclusion via forged context or snapshot
    # -------------------------------------------------------------------------
    @patch("server.db")
    async def test_scenario_11_historical_order_cannot_bypass_via_forged_context_or_snapshot(self, mock_db):
        order_id = ObjectId("507f1f77bcf86cd799439021")
        # Authoritative order in DB: settled on 2026-10-27 (prior to activation)
        authoritative_db_order = {
            "_id": order_id,
            "order_number": "ORD-FORGE-ATTEMPT-011",
            "order_status": "selesai",
            "status": "selesai",
            "payment_status": "lunas",
            "completed_at": "2026-10-27T10:00:00Z",
            "paid_at": "2026-10-27T11:00:00Z",
            "total_price": 7000.0,
            "total_paid": 7000.0,
        }
        # Adversary caller fabricates a snapshot claiming order is new and unpaid
        fake_caller_snapshot = {
            "_id": order_id,
            "order_number": "ORD-FORGE-ATTEMPT-011",
            "order_status": "dalam_proses",
            "payment_status": "belum_lunas",
        }
        self._setup_mock_db(mock_db, policy_enabled=True)
        mock_db.orders.find_one = AsyncMock(return_value=authoritative_db_order)
        mock_db.orders.update_one = AsyncMock()

        with patch("server.db", mock_db):
            policy = await get_active_admin_wage_policy(db_inst=mock_db)
            res = await process_order_admin_wage_accrual(
                fake_caller_snapshot,  # Caller passes fabricated snapshot
                self.owner_user,
                policy=policy,
                lifecycle_event="order_completed",
                transition_context={"from_status": "siap_kirim", "to_status": "selesai", "order_id": str(order_id)}
            )

        # Must reject based on authoritative DB record!
        self.assertEqual(res["status"], "skipped_unverifiable_transition")
        self.assertEqual(res["eligibility"]["scope_status"], "excluded_historical")
        self.assertEqual(res["eligibility"]["skip_reason"], "settled_prior_to_system_activation")
        mock_db.wage_obligations.insert_one.assert_not_called()

    # -------------------------------------------------------------------------
    # Scenario 12: Parameters read authoritatively from db.settings (50 LE, 75 LE, 100 LE, Azka)
    # -------------------------------------------------------------------------
    @patch("server.db")
    async def test_scenario_12_parameters_read_authoritatively_from_db_settings_50_75_100_azka(self, mock_db):
        self._setup_mock_db(mock_db, policy_enabled=False)
        with patch("server.db", mock_db):
            policy = await get_active_admin_wage_policy(db_inst=mock_db)

        self.assertEqual(policy["default_wage_per_order_le"], 50.0)
        self.assertEqual(policy["unusual_amount_threshold_le"], 75.0)
        self.assertEqual(policy["max_wage_per_order_le"], 100.0)
        self.assertEqual(policy["default_recipient_id"], "6a9031b86f261cb1ed5479ad")
        self.assertEqual(policy["default_recipient_name"], "Azka")
        self.assertFalse(policy["enabled"])
        self.assertTrue(policy["is_configured"])
        self.assertEqual(policy["currency"], "EGP")
        self.assertEqual(policy["rounding_policy"], "piastre_round_half_up")

    # -------------------------------------------------------------------------
    # Scenario 13: Web app PUT updates settings and is reflected in backend policy reads
    # -------------------------------------------------------------------------
    @patch("server.db")
    async def test_scenario_13_web_app_put_updates_settings_and_reflected_in_backend_policy_reads(self, mock_db):
        self._setup_mock_db(mock_db, policy_enabled=False)

        stored_doc = self._get_authoritative_policy_doc(enabled=False)
        async def mock_settings_update(query, update, *args, **kwargs):
            if query.get("key") == "admin_wage_policy":
                stored_doc["value"].update(update.get("$set", {}).get("value", {}))
            return MagicMock(matched_count=1, modified_count=1)

        mock_db.settings.update_one = AsyncMock(side_effect=mock_settings_update)
        mock_db.settings.find_one = AsyncMock(side_effect=lambda q, **kw: (
            stored_doc if q.get("key") == "admin_wage_policy" else None
        ))

        # Simulate Owner saving via web app PUT /api/admin/wage-policies/admin
        mock_request = MagicMock()
        mock_request.json = AsyncMock(return_value={
            "default_wage_per_order_le": 50.0,
            "unusual_amount_threshold_le": 75.0,
            "max_wage_per_order_le": 100.0,
            "default_recipient_id": "6a9031b86f261cb1ed5479ad",
            "enabled": True,  # Owner activates feature
            "change_reason": "Aktifkan otomatisasi upah admin dengan parameter Owner",
        })

        with patch("server.db", mock_db), patch("server.require_owner", return_value=lambda: self.owner_user):
            res = await admin_update_wage_policy_endpoint(
                category="admin",
                request=mock_request,
                admin=self.owner_user
            )

        self.assertTrue(res["is_configured"])
        self.assertTrue(res["enabled"])
        self.assertEqual(res["default_wage_per_order_le"], 50.0)
        self.assertEqual(res["unusual_amount_threshold_le"], 75.0)
        self.assertEqual(res["max_wage_per_order_le"], 100.0)

        # Fresh read via get_active_admin_wage_policy reflects saved changes
        with patch("server.db", mock_db):
            updated_policy = await get_active_admin_wage_policy(db_inst=mock_db)
        self.assertTrue(updated_policy["enabled"])
        self.assertEqual(updated_policy["default_wage_per_order_le"], 50.0)
        self.assertEqual(updated_policy["unusual_amount_threshold_le"], 75.0)
        self.assertEqual(updated_policy["max_wage_per_order_le"], 100.0)
        self.assertEqual(updated_policy["default_recipient_name"], "Azka")

    # -------------------------------------------------------------------------
    # Scenario 14: Invalid values and hard-cap violations fail safely
    # -------------------------------------------------------------------------
    @patch("server.db")
    async def test_scenario_14_invalid_rates_and_hard_cap_violations_fail_safely(self, mock_db):
        self._setup_mock_db(mock_db, policy_enabled=True)

        # Case A: Input validation rejects negative rate
        with self.assertRaises(ValidationError):
            AdminWagePolicyInput(
                default_wage_per_order_le=-10.0,
                unusual_amount_threshold_le=75.0,
                max_wage_per_order_le=100.0
            )

        # Case B: Threshold exceeds hard cap -> rejected by endpoint
        mock_request_invalid = MagicMock()
        mock_request_invalid.json = AsyncMock(return_value={
            "default_wage_per_order_le": 50.0,
            "unusual_amount_threshold_le": 120.0,  # Invalid: > hard cap (100)
            "max_wage_per_order_le": 100.0,
            "default_recipient_id": "6a9031b86f261cb1ed5479ad",
            "enabled": True,
        })
        with patch("server.db", mock_db), patch("server.require_owner", return_value=lambda: self.owner_user):
            with self.assertRaises(HTTPException) as ctx:
                await admin_update_wage_policy_endpoint(
                    category="admin",
                    request=mock_request_invalid,
                    admin=self.owner_user
                )
        self.assertEqual(ctx.exception.status_code, 422)

        # Case C: Manual override nominal exceeds active hard cap (100 LE)
        order_id = ObjectId("507f1f77bcf86cd799439024")
        order_exceeds_cap = {
            "_id": order_id,
            "order_number": "ORD-CAP-014",
            "order_status": "selesai",
            "payment_status": "lunas",
            "admin_wage_override": {
                "is_override": True,
                "amount_le": 150.0,  # Exceeds 100.0 LE hard cap!
                "recipient_id": "6a9031b86f261cb1ed5479ad",
                "recipient_name": "Azka",
                "override_reason": "Bonus besar tidak sah",
            }
        }
        mock_db.orders.find_one = AsyncMock(return_value=order_exceeds_cap)
        with patch("server.db", mock_db):
            policy = await get_active_admin_wage_policy(db_inst=mock_db)
            res = await process_order_admin_wage_accrual(
                order_exceeds_cap,
                self.owner_user,
                policy=policy,
                lifecycle_event="manual_override_approved"
            )
        self.assertEqual(res["status"], "blocked_hard_cap_conflict")
        self.assertEqual(res["eligibility"]["scope_status"], "blocked")
        mock_db.wage_obligations.insert_one.assert_not_called()

    # -------------------------------------------------------------------------
    # Scenario 15: Missing or unreadable configuration fails safely without silent substitution
    # -------------------------------------------------------------------------
    @patch("server.db")
    async def test_scenario_15_unconfigured_policy_fails_safely_without_silent_substitution(self, mock_db):
        # Database has no settings document for admin_wage_policy
        mock_db.settings.find_one = AsyncMock(return_value=None)

        with patch("server.db", mock_db):
            policy = await get_active_admin_wage_policy(db_inst=mock_db)
        self.assertFalse(policy["is_configured"])
        self.assertFalse(policy["enabled"])
        self.assertIsNone(policy["default_wage_per_order_le"])
        self.assertIsNone(policy["max_wage_per_order_le"])

        # When evaluated, accrual safely skips without generating any wage obligation
        order_id = ObjectId("507f1f77bcf86cd799439025")
        order = {
            "_id": order_id,
            "order_number": "ORD-UNCONFIGURED-015",
            "order_status": "selesai",
            "payment_status": "lunas",
            "completed_at": "2026-10-29T12:00:00Z",
            "paid_at": "2026-10-29T12:00:00Z",
        }
        mock_db.orders.find_one = AsyncMock(return_value=order)
        with patch("server.db", mock_db):
            res = await process_order_admin_wage_accrual(
                order,
                self.owner_user,
                policy=policy,
                lifecycle_event="order_completed",
                transition_context={"from_status": "siap_kirim", "to_status": "selesai", "order_id": str(order_id)}
            )
        self.assertEqual(res["status"], "skipped_policy_disabled")
        self.assertEqual(res["eligibility"]["scope_status"], "skipped_disabled_window")
        mock_db.wage_obligations.insert_one.assert_not_called()


if __name__ == "__main__":
    unittest.main()
