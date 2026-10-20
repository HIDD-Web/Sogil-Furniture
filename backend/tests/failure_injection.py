"""Deterministic Failure-Injection Utilities for Sogil Furniture Adversarial Testing.

SAFETY REQUIREMENTS:
- Opt-in and strictly confined to test executions.
- Zero impact on production request flows.
- Uses explicit context managers and monkeypatching hooks.
- Uses asyncio.Event / asyncio.Barrier for deterministic concurrency coordination without fragile sleeps.
"""

import asyncio
from contextlib import asynccontextmanager, contextmanager
from typing import Optional, Callable, Any
import pymongo
import pymongo.errors


class SimulatedFailureError(Exception):
    """Base exception for deterministic test-injected failures."""
    pass


class SimulatedPreCommitCrashError(SimulatedFailureError):
    """Simulates an immediate process termination or power loss before session.commit_transaction()."""
    pass


class SimulatedTransientTransactionError(pymongo.errors.PyMongoError):
    """Simulates a MongoDB transient transaction conflict (e.g. WriteConflict)."""
    def __init__(self, message="Simulated write conflict during transaction"):
        super().__init__(message, error_labels=["TransientTransactionError"])


class SimulatedUnknownCommitResultError(pymongo.errors.ConnectionFailure):
    """Simulates a lost commit ACK or socket drop during commit_transaction()."""
    def __init__(self, message="Simulated network disconnect during commit_transaction"):
        super().__init__(message, error_labels=["UnknownTransactionCommitResult"])


class SimulatedDuplicateKeyError(pymongo.errors.DuplicateKeyError):
    """Simulates a unique index E11000 collision."""
    def __init__(self, message="E11000 duplicate key error collection: wage_obligations index: uniq_wage_obligation_accrual_event"):
        super().__init__(message, code=11000)


@contextmanager
def inject_pre_commit_crash(session):
    """Intercepts session.commit_transaction() and raises SimulatedPreCommitCrashError."""
    original_commit = session.commit_transaction

    async def _failing_commit():
        raise SimulatedPreCommitCrashError("CRASH: Server crashed immediately before commit_transaction completed")

    session.commit_transaction = _failing_commit
    try:
        yield
    finally:
        session.commit_transaction = original_commit


@contextmanager
def inject_unknown_commit_result(session):
    """Intercepts session.commit_transaction() and raises UnknownTransactionCommitResult."""
    original_commit = session.commit_transaction

    async def _ambiguous_commit():
        # First execute the real commit so the data is actually committed on server
        await original_commit()
        # Then raise the connection failure simulating lost network ACK
        raise SimulatedUnknownCommitResultError(
            "SIMULATED NETWORK DROP: Transaction committed on primary but client socket severed"
        )

    session.commit_transaction = _ambiguous_commit
    try:
        yield
    finally:
        session.commit_transaction = original_commit


@contextmanager
def inject_transient_transaction_error(session):
    """Simulates transient conflict error during commit."""
    original_commit = session.commit_transaction

    async def _transient_commit():
        raise SimulatedTransientTransactionError("SIMULATED WRITE CONFLICT: TransientTransactionError")

    session.commit_transaction = _transient_commit
    try:
        yield
    finally:
        session.commit_transaction = original_commit


class ConcurrencyCoordinator:
    """Provides deterministic rendezvous barriers for concurrent race-condition tests.
    Eliminates fragile time.sleep() calls in test suites.
    """

    def __init__(self, parties: int = 2):
        self.parties = parties
        self.barrier = asyncio.Barrier(parties)
        self.release_event = asyncio.Event()

    async def wait_for_all(self):
        """Wait until all concurrent tasks reach the rendezvous point."""
        await self.barrier.wait()

    def signal_release(self):
        """Signals tasks to proceed after synchronized pre-conditions are verified."""
        self.release_event.set()

    async def wait_for_release(self):
        """Blocks task until explicit release signal is given."""
        await self.release_event.wait()
