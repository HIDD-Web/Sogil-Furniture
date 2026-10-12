"""Unit tests for Phase 3.F.1.4: Critical finance index initialization hardening.

Verifies that critical unique indexes (payments, customer_credit_events, finance_adjustments)
are strictly protected against silent failure during seed(), and fail-closed with
CriticalFinanceIndexError, while non-critical lookup/reporting indexes log warnings without blocking.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import pymongo.errors

from server import seed, CriticalFinanceIndexError


class MockAsyncCollection:
    def __init__(self):
        self.create_index = AsyncMock()
        self.find_one = AsyncMock(return_value=None)
        self.insert_one = AsyncMock()
        self.insert_many = AsyncMock()
        self.update_one = AsyncMock()
        self.update_many = AsyncMock()
        self.count_documents = AsyncMock(return_value=1)
        self.index_information = AsyncMock(return_value={})
        self.drop_index = AsyncMock()


class MockAsyncDatabase:
    def __init__(self):
        self._collections = {}
        self.create_collection = AsyncMock()

    def __getattr__(self, name):
        if name not in self._collections:
            self._collections[name] = MockAsyncCollection()
        return self._collections[name]

    def __getitem__(self, name):
        return self.__getattr__(name)


class TestPhase3FCriticalIndexHardening(unittest.IsolatedAsyncioTestCase):
    def _create_mock_db(self):
        mock_db = MockAsyncDatabase()
        # Seed admin mock
        mock_db.admins.find_one = AsyncMock(return_value={"_id": "owner_id", "email": "sogil.furniture@gmail.com", "role": "owner"})
        return mock_db

    async def test_successful_creation_of_all_critical_and_noncritical_indexes(self):
        """Case 1: All indexes succeed. seed() must complete cleanly without exception."""
        mock_db = self._create_mock_db()
        with patch("server.db", mock_db), patch("server.set_setting", AsyncMock()):
            await seed()

        # Verify payments critical unique indexes called
        payments_calls = mock_db.payments.create_index.call_args_list
        index_names_called = [call.kwargs.get("name") for call in payments_calls]
        self.assertIn("uniq_payment_number", index_names_called)
        self.assertIn("uniq_payments_idempotency", index_names_called)
        self.assertIn("idx_payments_order_status", index_names_called)
        self.assertIn("idx_payments_finance_txn", index_names_called)

        # Verify customer_credit_events critical unique indexes called
        cce_calls = mock_db.customer_credit_events.create_index.call_args_list
        cce_names = [call.kwargs.get("name") for call in cce_calls]
        self.assertIn("uniq_credit_event_number", cce_names)
        self.assertIn("uniq_credit_event_source_payment", cce_names)
        self.assertIn("uniq_credit_events_idempotency", cce_names)
        self.assertIn("idx_credit_events_customer_currency", cce_names)
        self.assertIn("idx_credit_events_source_order", cce_names)

        # Verify finance_adjustments critical unique indexes called
        adj_calls = mock_db.finance_adjustments.create_index.call_args_list
        adj_names = [call.kwargs.get("name") for call in adj_calls]
        self.assertIn("uniq_adjustment_id", adj_names)
        self.assertIn("uniq_adjustments_idempotency", adj_names)
        self.assertIn("idx_adjustments_order_lookup", adj_names)
        self.assertIn("idx_adjustments_period_reporting", adj_names)

    async def test_failure_creating_critical_payment_idempotency_index_fails_closed(self):
        """Case 2: Failure on uniq_payments_idempotency raises CriticalFinanceIndexError."""
        mock_db = self._create_mock_db()

        async def _mock_payments_create_index(keys, **kwargs):
            if kwargs.get("name") == "uniq_payments_idempotency":
                raise pymongo.errors.OperationFailure("Index build failed: duplicate key error")
            return "index_ok"

        mock_db.payments.create_index.side_effect = _mock_payments_create_index

        with patch("server.db", mock_db), patch("server.set_setting", AsyncMock()):
            with self.assertRaises(CriticalFinanceIndexError) as ctx:
                await seed()

            err = ctx.exception
            self.assertEqual(err.collection_name, "payments")
            self.assertEqual(err.index_name, "uniq_payments_idempotency")
            self.assertIn("duplicate key error", err.reason)

    async def test_failure_creating_critical_credit_event_idempotency_index_fails_closed(self):
        """Case 3: Failure on uniq_credit_events_idempotency raises CriticalFinanceIndexError."""
        mock_db = self._create_mock_db()

        async def _mock_cce_create_index(keys, **kwargs):
            if kwargs.get("name") == "uniq_credit_events_idempotency":
                raise pymongo.errors.OperationFailure("Permission denied: cannot create index")
            return "index_ok"

        mock_db.customer_credit_events.create_index.side_effect = _mock_cce_create_index

        with patch("server.db", mock_db), patch("server.set_setting", AsyncMock()):
            with self.assertRaises(CriticalFinanceIndexError) as ctx:
                await seed()

            err = ctx.exception
            self.assertEqual(err.collection_name, "customer_credit_events")
            self.assertEqual(err.index_name, "uniq_credit_events_idempotency")
            self.assertIn("cannot create index", err.reason)

    async def test_failure_creating_critical_adjustment_idempotency_index_fails_closed(self):
        """Case 4: Failure on uniq_adjustments_idempotency raises CriticalFinanceIndexError."""
        mock_db = self._create_mock_db()

        async def _mock_adj_create_index(keys, **kwargs):
            if kwargs.get("name") == "uniq_adjustments_idempotency":
                raise pymongo.errors.OperationFailure("Write timeout during index build")
            return "index_ok"

        mock_db.finance_adjustments.create_index.side_effect = _mock_adj_create_index

        with patch("server.db", mock_db), patch("server.set_setting", AsyncMock()):
            with self.assertRaises(CriticalFinanceIndexError) as ctx:
                await seed()

            err = ctx.exception
            self.assertEqual(err.collection_name, "finance_adjustments")
            self.assertEqual(err.index_name, "uniq_adjustments_idempotency")
            self.assertIn("Write timeout", err.reason)

    async def test_failure_creating_critical_credit_source_payment_index_fails_closed(self):
        """Case 5: Failure on uniq_credit_event_source_payment raises CriticalFinanceIndexError."""
        mock_db = self._create_mock_db()

        async def _mock_cce_create_index(keys, **kwargs):
            if kwargs.get("name") == "uniq_credit_event_source_payment":
                raise pymongo.errors.OperationFailure("Cluster lock error")
            return "index_ok"

        mock_db.customer_credit_events.create_index.side_effect = _mock_cce_create_index

        with patch("server.db", mock_db), patch("server.set_setting", AsyncMock()):
            with self.assertRaises(CriticalFinanceIndexError) as ctx:
                await seed()

            err = ctx.exception
            self.assertEqual(err.collection_name, "customer_credit_events")
            self.assertEqual(err.index_name, "uniq_credit_event_source_payment")

    async def test_safe_error_logging_without_secrets_or_payloads(self):
        """Case 6: Error logging logs collection and index name without exposing environment secrets."""
        mock_db = self._create_mock_db()
        mock_db.payments.create_index.side_effect = pymongo.errors.OperationFailure("Simulated DB index error")

        with patch("server.db", mock_db), patch("server.set_setting", AsyncMock()), patch("server.logger") as mock_logger:
            with self.assertRaises(CriticalFinanceIndexError):
                await seed()

            mock_logger.error.assert_called_once()
            log_msg = mock_logger.error.call_args[0][0]
            self.assertIn("CRITICAL INDEX FAILURE: payments 'uniq_payment_number'", log_msg)
            # Ensure no credentials or uri leakage
            self.assertNotIn("mongodb+srv://", log_msg)
            self.assertNotIn("password", log_msg.lower())

    async def test_noncritical_index_failure_is_logged_as_warning_and_does_not_abort_seed(self):
        """Case 7: Non-critical lookup/reporting index failure logs warning without aborting seed()."""
        mock_db = self._create_mock_db()

        async def _mock_payments_create_index(keys, **kwargs):
            name = kwargs.get("name")
            if name == "idx_payments_order_status":
                raise pymongo.errors.OperationFailure("Temporary lock on secondary index")
            return "index_ok"

        mock_db.payments.create_index.side_effect = _mock_payments_create_index

        with patch("server.db", mock_db), patch("server.set_setting", AsyncMock()), patch("server.logger") as mock_logger:
            # Must not raise CriticalFinanceIndexError
            await seed()

            # Warning must be logged for non-critical failure
            warning_calls = [c[0][0] for c in mock_logger.warning.call_args_list]
            self.assertTrue(any("Non-critical payments index provisioning warning" in msg for msg in warning_calls))

    async def test_legacy_partial_filter_specifications_preserved_identically(self):
        """Case 8: Ensure partialFilterExpression remains identical to canonical specification."""
        mock_db = self._create_mock_db()
        with patch("server.db", mock_db), patch("server.set_setting", AsyncMock()):
            await seed()

        # Check payments idempotency partial filter
        pmt_calls = {call.kwargs.get("name"): call.kwargs for call in mock_db.payments.create_index.call_args_list}
        self.assertEqual(pmt_calls["uniq_payments_idempotency"]["partialFilterExpression"], {"idempotency_key": {"$type": "string"}})
        self.assertTrue(pmt_calls["uniq_payments_idempotency"]["unique"])

        # Check credit event source payment partial filter
        cce_calls = {call.kwargs.get("name"): call.kwargs for call in mock_db.customer_credit_events.create_index.call_args_list}
        self.assertEqual(cce_calls["uniq_credit_event_source_payment"]["partialFilterExpression"], {"source_payment_id": {"$type": "string"}})
        self.assertTrue(cce_calls["uniq_credit_event_source_payment"]["unique"])
        self.assertEqual(cce_calls["uniq_credit_events_idempotency"]["partialFilterExpression"], {"idempotency_key": {"$type": "string"}})
        self.assertTrue(cce_calls["uniq_credit_events_idempotency"]["unique"])

        # Check adjustment idempotency partial filter
        adj_calls = {call.kwargs.get("name"): call.kwargs for call in mock_db.finance_adjustments.create_index.call_args_list}
        self.assertEqual(adj_calls["uniq_adjustments_idempotency"]["partialFilterExpression"], {"idempotency_key": {"$type": "string"}})
        self.assertTrue(adj_calls["uniq_adjustments_idempotency"]["unique"])


if __name__ == "__main__":
    unittest.main()
