"""Unit Tests for Test Database Isolation Guard.
Ensures zero possibility of accidental connections to production MongoDB Atlas, Railway, or shared clusters.
"""

import unittest
import pytest
from backend.tests.isolation_guard import (
    validate_test_database_isolation,
    sanitize_uri_for_logging,
    KNOWN_PRODUCTION_HOSTS,
    FORBIDDEN_HOST_PATTERNS,
    FORBIDDEN_DB_NAMES,
)


class TestDatabaseIsolationGuard(unittest.TestCase):
    """Exhaustively verifies fail-closed security invariants of the isolation guard."""

    def test_approved_local_endpoints_pass(self):
        """Approved local endpoints with disposable test DB names must pass."""
        valid_cases = [
            ("mongodb://localhost:27017", "sogil_test_disposable"),
            ("mongodb://127.0.0.1:27017", "test_disposable_replica"),
            ("mongodb://[::1]:27017", "sogil_test_tx_matrix"),
            ("mongodb://user:pass@127.0.0.1:27017", "sogil_test_auth"),
        ]
        for uri, db_name in valid_cases:
            with self.subTest(uri=uri, db=db_name):
                # Should not raise
                validate_test_database_isolation(uri, db_name)

    def test_reject_known_production_atlas_host(self):
        """Rejects the exact known production Atlas cluster hostname."""
        for prod_host in KNOWN_PRODUCTION_HOSTS:
            uri = f"mongodb+srv://admin:supersecret@{prod_host}/sogil"
            with self.assertRaises(ValueError) as ctx:
                validate_test_database_isolation(uri, "sogil_test_disposable")
            self.assertIn("matches known production Atlas cluster", str(ctx.exception))
            # Critical: Password must NOT be in error message
            self.assertNotIn("supersecret", str(ctx.exception))

    def test_reject_forbidden_host_patterns(self):
        """Rejects any host ending with mongodb.net, railway, or production."""
        forbidden_hosts = [
            "cluster0.abcde.mongodb.net",
            "production-mongo.railway.internal",
            "sogil-db.up.railway.app",
            "production-db.internal",
            "atlas-replica.somedomain.com",
        ]
        for host in forbidden_hosts:
            uri = f"mongodb://admin:secret@{host}:27017"
            with self.assertRaises(ValueError) as ctx:
                validate_test_database_isolation(uri, "sogil_test_disposable")
            self.assertIn("SECURITY ABORT", str(ctx.exception))
            self.assertNotIn("secret", str(ctx.exception))

    def test_reject_unapproved_ambiguous_hosts(self):
        """Hosts not in allowlist must fail closed."""
        unapproved_hosts = [
            "192.168.1.100",
            "10.0.0.5",
            "db.sogilfurniture.com",
            "staging-mongo.internal",
        ]
        for host in unapproved_hosts:
            uri = f"mongodb://{host}:27017"
            with self.assertRaises(ValueError) as ctx:
                validate_test_database_isolation(uri, "sogil_test_disposable")
            self.assertIn("not in the approved test host allowlist", str(ctx.exception))

    def test_custom_allowed_hosts(self):
        """Allows explicitly configured custom test containers."""
        uri = "mongodb://mongo-test-container:27017"
        # Fails without custom allowlist
        with self.assertRaises(ValueError):
            validate_test_database_isolation(uri, "sogil_test_disposable")
        # Passes with custom allowlist
        validate_test_database_isolation(
            uri, "sogil_test_disposable", allowed_hosts=["mongo-test-container"]
        )

    def test_reject_empty_or_malformed_uris(self):
        """Rejects empty, None, or malformed URIs."""
        invalid_uris = [
            "",
            "   ",
            None,
            "http://localhost:27017",
            "redis://127.0.0.1:6379",
            "not-a-url",
        ]
        for bad_uri in invalid_uris:
            with self.assertRaises(ValueError):
                validate_test_database_isolation(bad_uri, "sogil_test_disposable")

    def test_reject_protected_database_names(self):
        """Rejects production or system database names even on localhost."""
        for forbidden_db in FORBIDDEN_DB_NAMES:
            with self.assertRaises(ValueError) as ctx:
                validate_test_database_isolation("mongodb://127.0.0.1:27017", forbidden_db)
            self.assertIn("protected production or system database", str(ctx.exception))

    def test_reject_unprefixed_database_names(self):
        """Rejects database names that do not start with approved test prefixes."""
        unprefixed_dbs = [
            "sogil_dev",
            "furniture_test",
            "my_test_db",
            "temp_db",
        ]
        for bad_db in unprefixed_dbs:
            with self.assertRaises(ValueError) as ctx:
                validate_test_database_isolation("mongodb://127.0.0.1:27017", bad_db)
            self.assertIn("must start with one of", str(ctx.exception))

    def test_sanitize_uri_for_logging(self):
        """Verifies that credentials are unconditionally redacted from logs."""
        raw_uri = "mongodb://user:super_secret_password_123@localhost:27017/sogil_test"
        sanitized = sanitize_uri_for_logging(raw_uri)
        self.assertNotIn("super_secret_password_123", sanitized)
        self.assertIn("***:***@localhost:27017", sanitized)

        # Empty/None handling
        self.assertEqual(sanitize_uri_for_logging(""), "<empty>")
        self.assertEqual(sanitize_uri_for_logging(None), "<empty>")
