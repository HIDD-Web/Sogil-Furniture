"""Database Isolation Guard for Sogil Furniture Test Suites.

SECURITY INVARIANT:
Tests must NEVER touch production MongoDB Atlas, staging, Railway, or shared operational databases.
Any attempt to pass an unverified, ambiguous, or forbidden database URI or database name
MUST FAIL CLOSED immediately before any network packet is dispatched.
"""

import os
import re
import urllib.parse
from typing import List, Optional


KNOWN_PRODUCTION_HOSTS = [
    "sogil-furniture.7djg3j5.mongodb.net",
]

FORBIDDEN_HOST_PATTERNS = [
    r"mongodb\.net$",
    r"railway",
    r"railway\.internal$",
    r"up\.railway\.app$",
    r"production",
    r"atlas",
]

FORBIDDEN_DB_NAMES = [
    "sogil",
    "sogil-production",
    "sogil_production",
    "production",
    "admin",
    "config",
    "local",
    "sogil_live",
    "live",
]

REQUIRED_TEST_DB_PREFIXES = (
    "sogil_test_",
    "test_disposable_",
)

DEFAULT_APPROVED_HOSTS = [
    "localhost",
    "127.0.0.1",
    "::1",
    "[::1]",
]


def sanitize_uri_for_logging(uri: str) -> str:
    """Redacts credentials from a MongoDB URI to prevent secret leakage in test logs.
    """
    if not uri or not isinstance(uri, str):
        return "<empty>"
    try:
        parsed = urllib.parse.urlparse(uri)
        if parsed.password or parsed.username:
            netloc = parsed.netloc
            if "@" in netloc:
                host_part = netloc.split("@")[-1]
                netloc = f"***:***@{host_part}"
            sanitized = parsed._replace(netloc=netloc)
            return urllib.parse.urlunparse(sanitized)
        return uri
    except Exception:
        return "<unparseable-uri>"


def validate_test_database_isolation(
    uri: Optional[str],
    db_name: Optional[str],
    allowed_hosts: Optional[List[str]] = None,
) -> None:
    """Rigorous pre-flight validator to ensure test connection cannot touch production.
    Raises ValueError on any ambiguity, forbidden host, or invalid configuration.
    Credentials are NEVER printed in exception messages.
    """
    if not uri or not isinstance(uri, str) or not uri.strip():
        raise ValueError("SECURITY ABORT: Test database URI is missing or empty. Fails closed.")

    clean_uri = uri.strip()

    try:
        parsed = urllib.parse.urlsplit(clean_uri)
    except Exception as parse_err:
        raise ValueError(f"SECURITY ABORT: Test database URI is malformed: {parse_err}")

    if parsed.scheme not in ("mongodb", "mongodb+srv"):
        raise ValueError(
            f"SECURITY ABORT: Invalid scheme '{parsed.scheme}'. Only 'mongodb' or 'mongodb+srv' permitted."
        )

    # Extract hostnames (supporting single-host, multi-host replica sets, and IPv6)
    netloc_clean = parsed.netloc.split("@")[-1]
    hosts = []
    for raw_part in netloc_clean.split(","):
        p = raw_part.strip()
        if not p:
            continue
        if p.startswith("["):
            end_idx = p.find("]")
            if end_idx != -1:
                hosts.append(p[:end_idx+1].lower())
            else:
                hosts.append(p.lower())
        else:
            hosts.append(p.split(":")[0].lower().strip())

    if not hosts:
        raise ValueError("SECURITY ABORT: URI does not contain a valid hostname.")

    approved = list(DEFAULT_APPROVED_HOSTS)
    if allowed_hosts:
        approved.extend([h.lower().strip() for h in allowed_hosts])

    env_extra_allowed = os.environ.get("TEST_MONGO_ALLOWED_HOSTS", "").strip()
    if env_extra_allowed:
        approved.extend([h.lower().strip() for h in env_extra_allowed.split(",") if h.strip()])

    for host in hosts:
        # 1. Denylist: Reject known production clusters
        for known_prod in KNOWN_PRODUCTION_HOSTS:
            if host == known_prod.lower() or host.endswith("." + known_prod.lower()):
                raise ValueError(
                    f"SECURITY ABORT: Hostname '{host}' matches known production Atlas cluster. Rejected."
                )

        # 2. Denylist: Reject forbidden patterns (Atlas, Railway, production strings)
        for pattern in FORBIDDEN_HOST_PATTERNS:
            if re.search(pattern, host):
                raise ValueError(
                    f"SECURITY ABORT: Hostname '{host}' matches forbidden pattern '{pattern}'. Rejected."
                )

        # 3. Allowlist: Host must be in approved allowlist
        if host not in approved:
            raise ValueError(
                f"SECURITY ABORT: Hostname '{host}' is not in the approved test host allowlist {approved}. "
                f"Unknown or ambiguous endpoints fail closed."
            )

    # 4. Database Name Validation
    if not db_name or not isinstance(db_name, str) or not db_name.strip():
        raise ValueError("SECURITY ABORT: Test database name is missing or empty.")

    clean_db = db_name.strip().lower()

    if clean_db in FORBIDDEN_DB_NAMES:
        raise ValueError(
            f"SECURITY ABORT: Database name '{clean_db}' is a protected production or system database."
        )

    if not any(clean_db.startswith(prefix) for prefix in REQUIRED_TEST_DB_PREFIXES):
        raise ValueError(
            f"SECURITY ABORT: Database name '{clean_db}' must start with one of {REQUIRED_TEST_DB_PREFIXES}."
        )
