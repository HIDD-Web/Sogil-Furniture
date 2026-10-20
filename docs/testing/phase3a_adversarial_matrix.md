# SOGIL FURNITURE — PHASE 3A ADVERSARIAL ACCEPTANCE MATRIX (TX-01 THROUGH TX-16)
**Target: Unified Finance & Wage Management System**
**Specification Baseline: Phase 2X Recovery & Atomicity Model Reconciliation**

---

## 1. Overview & Architectural Principles

This document encodes the formal Acceptance Test Matrix for Phase 3A of the Sogil Furniture Web Application (`HIDD-Web/Sogil-Furniture`). It defines the exact preconditions, failure injection points, concurrency barriers, expected database states, and pass/fail criteria for scenarios **TX-01 through TX-16**.

### Authoritative Architecture Foundations (Locked from Phase 2X):
1. **Model A Atomicity:** All related multi-document mutations for batch claim, verification, settlement, and recovery execute inside a **single MongoDB replica-set ACID transaction**. The multi-stage saga (Model B) is strictly rejected.
2. **Dual-Custody Enforcement:** A worker cannot verify their own assignment (`admin_id != worker_id`), except via an explicit Owner/CEO bypass that generates an immutable audit record in `db.audit_logs`.
3. **Financial Arithmetic:** All wage obligations and settlements calculate monetary amounts using `Decimal` arithmetic with `ROUND_HALF_UP` to 2 decimal places.
4. **Settlement Bounds:** Cumulative allocations across settlements must never exceed the obligation total: `paid_amount_le <= total_amount_le`.
5. **Realized Ledger Atomicity:** Cash disbursements in `db.finance_transactions` commit in the identical transaction boundary as `db.wage_settlements`.
6. **Immutable Historical Records:** Obligations with status `paid` and associated cash ledgers cannot be overwritten, deleted, or converted to tombstones.
7. **Fail-Closed on `voided` State:** Recovery encountering an obligation in status `voided` must fail closed and quarantine the assignment group (`status: "quarantined"`) for Owner manual review.
8. **Generation-Based Fencing:** Stale recovery workers or supervisors are fenced via monotonic `recovery_generation` and `claim_generation` checks.
9. **Transactional Outbox:** Outbox events in `db.outbox_events` are inserted inside the same database transaction as domain mutations, guaranteeing at-least-once delivery with consumer deduplication.

---

## 2. Adversarial Matrix Specification: TX-01 through TX-16

```
+=======================================================================================================================+
|                                        ADVERSARIAL TEST MATRIX (TX-01 TO TX-16)                                       |
+=======+=============================================================+=======================+=========================+
| ID    | Critical Invariant / Coverage Area                          | Test Mode             | Isolation Requirement   |
+=======+=============================================================+=======================+=========================+
| TX-01 | Successful atomic recovery & obligation accrual (Model A)   | Integration / Unit    | Disposable Replica Set  |
| TX-02 | Failure before transaction commit (WiredTiger auto-rollback)| Integration           | Disposable Replica Set  |
| TX-03 | Mid-transaction exception & multi-document consistency      | Integration           | Disposable Replica Set  |
| TX-04 | Ambiguous commit result (UnknownTransactionCommitResult)    | Integration / Driver  | Disposable Replica Set  |
| TX-05 | Commit retry & reconciliation without duplicate liabilities | Integration / Driver  | Disposable Replica Set  |
| TX-06 | Tombstone handling when accrual_event_key already exists    | Integration / Unit    | Disposable Replica Set  |
| TX-07 | Unique-index collision (uniq_wage_obligation_accrual_event) | Integration           | Disposable Replica Set  |
| TX-08 | Preservation of paid obligations & immutable cash ledger    | Integration / Unit    | Disposable Replica Set  |
| TX-09 | Voided obligation fail-closed quarantine                    | Integration / Unit    | Disposable Replica Set  |
| TX-10 | Recovery generation fencing against stale worker            | Integration / Unit    | Disposable Replica Set  |
| TX-11 | Concurrent recovery collision & optimistic lock             | Integration / Concurr | Disposable Replica Set  |
| TX-12 | Concurrent wage settlement / competing allocation race      | Integration / Concurr | Disposable Replica Set  |
| TX-13 | Partial settlement boundary & prevention of overpayment     | Integration / Unit    | Disposable Replica Set  |
| TX-14 | Batch fission counter/array sync (atomic $set invariant)   | Integration / Unit    | Disposable Replica Set  |
| TX-15 | Dual-custody enforcement & Owner/CEO bypass audit log       | Unit / Integration    | Synthetic Mock / RS     |
| TX-16 | Transactional outbox atomicity, crash recovery & dedup      | Integration / Unit    | Disposable Replica Set  |
+=======+=============================================================+=======================+=========================+
```

---

### TX-01: Successful Atomic Recovery & Obligation Accrual (Model A Happy Path)
- **Invariant:** When recovery or assignment completion executes within a single replica-set transaction, all related entity states (`item_instances`, `assignment_groups`, `work_assignments`, `wage_obligations`) transition atomically from initial staging to finalized completion.
- **Initial State:** Parent group `G1` has `recovery_lock` set to current worker, `target_instance_ids: ["INST-1"]`, `instance_count: 1`. Instance `INST-1` has `active_assignment_group_id: "G1"`. Child group `G2` and assignment `A2` staged.
- **Failure Injection Point:** None.
- **Expected Outcome:** HTTP 200 OK.
- **Expected Final State:**
  - `item_instances`: `active_assignment_group_id: "G2"`, `claim_generation: gen + 1`.
  - `assignment_groups`: Parent `G1` has `instance_count: 0`, `target_instance_ids: []`. Child `G2` has `status: "completed"`.
  - `work_assignments`: `A2` has `status: "completed"`.
  - `wage_obligations`: 1 document created with status `"accrued"`, matching calculated total.
  - `db.outbox_events`: 1 event created with status `"pending"`.
- **Pass/Fail Criteria:** All mutations visible via majority read; zero uncommitted or orphan records.

---

### TX-02: Failure Before Transaction Commit (Pre-Commit Crash Atomicity)
- **Invariant:** A crash or server termination occurring immediately before `session.commit_transaction()` must result in WiredTiger rolling back 100% of mutations.
- **Initial State:** Parent group `G1` active with 2 instances (`["INST-1", "INST-2"]`).
- **Failure Injection Point:** Python exception or simulated process kill immediately after mutating `item_instances` and `assignment_groups`, before `commit_transaction()`.
- **Expected Outcome:** Transaction aborts cleanly.
- **Expected Final State:**
  - `item_instances`: `active_assignment_group_id` remains `"G1"`; claim generations unaltered.
  - `assignment_groups`: `instance_count` remains 2; `target_instance_ids` remains `["INST-1", "INST-2"]`.
  - `wage_obligations`: Zero documents created.
  - `db.outbox_events`: Zero documents created.
- **Pass/Fail Criteria:** Strict byte-for-byte baseline restoration; zero partial state persisted.

---

### TX-03: Mid-Transaction Exception & Multi-Document Consistency
- **Invariant:** If any intermediate write inside the transaction raises a validation error, duplicate key error, or document-not-found error, the entire transaction is rolled back.
- **Initial State:** Assignment `A1` in `status: "ready_for_review"`.
- **Failure Injection Point:** Inject failure during `wage_obligations.insert_one` (e.g. schema validation or invalid numerical rate).
- **Expected Outcome:** HTTP 422 / 500 error; transaction aborts.
- **Expected Final State:**
  - `work_assignments`: `A1` remains in `status: "ready_for_review"` (does NOT become `"completed"`).
  - `wage_obligations`: No record inserted.
- **Pass/Fail Criteria:** Zero partial state where assignment is completed without an accrued obligation.

---

### TX-04: Ambiguous Commit Result (`UnknownTransactionCommitResult`)
- **Invariant:** When `commit_transaction()` raises an exception with error label `"UnknownTransactionCommitResult"` (e.g., socket timeout), the client/recovery worker must not assume transaction aborted; it must retry commit or query the primary with `read_concern="majority"`.
- **Initial State:** Fission or verification ready to commit.
- **Failure Injection Point:** Mock/inject network disconnection on commit call raising `pymongo.errors.ConnectionFailure("socket timeout", error_labels=["UnknownTransactionCommitResult"])`.
- **Expected Outcome:** Recovery handler catches `UnknownTransactionCommitResult`, retries commit or inspects primary replica set state using idempotency key.
- **Expected Final State:** Exactly one set of committed documents; no duplicate obligation created.
- **Pass/Fail Criteria:** Handled deterministically without throwing uncaught 500 or generating duplicate transactions.

---

### TX-05: Commit Retry & Reconciliation Without Duplicate Financial Records
- **Invariant:** When a client retries an operation whose commit succeeded on the server but whose network ACK was lost, the retry returns HTTP 200 with the existing document if payload hash matches, and HTTP 409 if payload diverges.
- **Initial State:** Assignment verified; obligation `WOB-001` exists with `accrual_event_key: "KEY-1"`, `payload_hash: H1`.
- **Failure Injection Point:** Client resends verification request with same `accrual_event_key: "KEY-1"`.
- **Expected Outcome:**
  - Subcase A (Matching Payload H1): HTTP 200 OK, returning existing obligation `WOB-001`.
  - Subcase B (Conflicting Payload H2): HTTP 409 Conflict ("Payload mismatch for idempotency key").
- **Expected Final State:** `db.wage_obligations` still contains exactly one document `WOB-001`.
- **Pass/Fail Criteria:** Zero duplicate obligations created; payload divergence strictly blocked.

---

### TX-06: Tombstone Handling When `accrual_event_key` Already Exists
- **Invariant:** If an obligation already exists with `accrual_event_key`, a rollback must NOT attempt an `insert_one` tombstone (which would crash on `uniq_wage_obligation_accrual_event`). It must perform an in-place status transition or verify key is poisoned.
- **Initial State:** Obligation `WOB-001` exists with `accrual_event_key: "KEY-ROLLBACK"`, status `"accruing"`.
- **Failure Injection Point:** Rollback worker triggers tombstone creation.
- **Expected Outcome:** In-place update transitions `status` to `"tombstone_aborted"`, `amount_le: 0.0`.
- **Expected Final State:** Document has `status: "tombstone_aborted"`. No duplicate key exception raised.
- **Pass/Fail Criteria:** Key is poisoned; subsequent verification requests with this key fail closed.

---

### TX-07: Unique-Index Collision & Safe Recovery
- **Invariant:** The unique index `uniq_wage_obligation_accrual_event` must strictly prevent two concurrent transactions from creating duplicate obligations for the same assignment.
- **Initial State:** Clean database with index `uniq_wage_obligation_accrual_event` enabled.
- **Failure Injection Point:** Two concurrent coroutines attempt to insert distinct obligations sharing identical `accrual_event_key`.
- **Expected Outcome:** One transaction succeeds; second transaction receives `DuplicateKeyError (E11000)` and rolls back cleanly.
- **Expected Final State:** Exactly 1 obligation in database.
- **Pass/Fail Criteria:** Total count of obligations matching key == 1.

---

### TX-08: Preservation of Paid Obligations & Immutable Cash Ledger
- **Invariant:** Obligations with status `paid` or `partially_paid` with realized cash outflows in `finance_transactions` must never be rolled back, cancelled, or overwritten by recovery.
- **Initial State:** Obligation `WOB-PAID` has `status: "paid"`, `paid_amount_le: 500.0`. Linked `finance_transactions` record `FT-001` exists.
- **Failure Injection Point:** Recovery worker or rogue admin attempts rollback or cancellation on `WOB-PAID`.
- **Expected Outcome:** Rejection with HTTP 400 Bad Request; group quarantined if attempted via recovery.
- **Expected Final State:** `WOB-PAID` remains `paid`; `FT-001` remains valid and un-mutated.
- **Pass/Fail Criteria:** Zero modification to settled obligations or cash ledger.

---

### TX-09: Voided Obligation Fail-Closed Quarantine
- **Invariant:** If a recovery worker inspects an assignment group whose associated wage obligation has `status: "voided"` (from administrative cancellation), automated recovery must fail closed and quarantine the group.
- **Initial State:** Assignment group `G-VOID` under recovery; linked obligation has `status: "voided"`.
- **Failure Injection Point:** Automated recovery scanner processes `G-VOID`.
- **Expected Outcome:** Recovery aborts automated repair-forward; updates `assignment_groups.status = "quarantined"`, emits audit warning.
- **Expected Final State:** Group `G-VOID` has `status: "quarantined"`, `quarantine_reason: "Encountered voided obligation without explicit re-assignment directive"`.
- **Pass/Fail Criteria:** No automated repair-forward; Owner alert recorded.

---

### TX-10: Recovery-Generation Fencing Against Stale Worker
- **Invariant:** A delayed recovery worker attempting to commit with an outdated `recovery_generation` must be rejected when a newer worker has taken over the lease.
- **Initial State:** Worker 1 holds lease at `recovery_generation: 1`. Lease expires. Worker 2 takes over and sets `recovery_generation: 2`.
- **Failure Injection Point:** Worker 1 wakes up and attempts conditional update using `recovery_generation: 1`.
- **Expected Outcome:** Worker 1 update matches 0 documents; transaction aborts.
- **Expected Final State:** Database state reflects Worker 2's mutations only.
- **Pass/Fail Criteria:** Zero writes permitted from Worker 1 after lease takeover.

---

### TX-11: Two Concurrent Recovery Attempts for Same Assignment Group
- **Invariant:** Concurrent recovery attempts competing for the same assignment group lock must be serialized via atomic conditional write (`recovery_lock == None`).
- **Initial State:** Group `G-RACE` requires recovery.
- **Failure Injection Point:** Worker A and Worker B simultaneously attempt to acquire recovery lock.
- **Expected Outcome:** Exactly one worker acquires lock (HTTP 200); competing worker receives HTTP 409 Conflict.
- **Expected Final State:** Exactly one recovery worker processes the group.
- **Pass/Fail Criteria:** Zero duplicate processing or split-brain assignments.

---

### TX-12: Concurrent Wage Settlement or Competing Allocation Race
- **Invariant:** When two concurrent settlement requests attempt to allocate payouts against the same obligation, optimistic locking on `paid_amount_le` must serialize them and prevent overpayment.
- **Initial State:** Obligation `WOB-RACE` has `total_amount_le: 1000.0`, `paid_amount_le: 0.0`.
- **Failure Injection Point:** Admin 1 and Admin 2 concurrently submit settlement of 600.0 each (total 1200.0 > 1000.0).
- **Expected Outcome:** First transaction commits (`paid_amount_le` becomes 600.0). Second transaction fails optimistic lock check (`paid_amount_le == 0.0` matches 0 docs) and raises HTTP 409 Conflict.
- **Expected Final State:** `paid_amount_le: 600.0`, `status: "partially_paid"`.
- **Pass/Fail Criteria:** Total allocated amount never exceeds 1000.0.

---

### TX-13: Partial Settlement Boundary & Prevention of Overpayment
- **Invariant:** A settlement allocation specifying an amount greater than the remaining unpaid balance (`total_amount_le - paid_amount_le`) must be rejected during pre-validation.
- **Initial State:** Obligation `WOB-BOUND` has `total_amount_le: 500.0`, `paid_amount_le: 400.0` (remaining 100.0).
- **Failure Injection Point:** Payout requested for 150.0.
- **Expected Outcome:** HTTP 422 Unprocessable Entity / 400 Bad Request ("Allocation exceeds unpaid balance").
- **Expected Final State:** `WOB-BOUND` remains unchanged at `paid_amount_le: 400.0`.
- **Pass/Fail Criteria:** Zero over-allocation allowed under any circumstance.

---

### TX-14: Batch Fission Counter/Array Sync (Atomic `$set` Invariant)
- **Invariant:** Repair-forward on parent group must update `target_instance_ids` and `instance_count` using synchronized `$set`, proving the instance was present and preventing counter desync on duplicate array entries.
- **Initial State:** Parent group `G-SYNC` has `target_instance_ids: ["A", "B"]`, `instance_count: 2`.
- **Failure Injection Point:** Subcase 1: Normal fission of "A". Subcase 2: Corrupted array with duplicate `["A", "A"]` or mismatched count `instance_count == 5`.
- **Expected Outcome:**
  - Subcase 1: Synchronized update removes "A" and sets count to 1 atomically.
  - Subcase 2: Pre-condition check detects array corruption, aborts transaction, marks group `"quarantined"`.
- **Expected Final State:** `instance_count == len(target_instance_ids)` in all persistent states.
- **Pass/Fail Criteria:** Counter and array length never diverge.

---

### TX-15: Dual-Custody Enforcement & Owner/CEO Bypass Audit Log
- **Invariant:** Verification where `admin_id == worker_id` must be rejected with HTTP 403 Forbidden, unless `admin.role == "owner"`, which sets `is_owner_bypass: True` and writes an audit log.
- **Initial State:** Assignment `A-SELF` assigned to worker "W-123".
- **Failure Injection Point:**
  - Subcase A: Admin "W-123" (role: "foreman") attempts verification.
  - Subcase B: Admin "W-123" (role: "owner") attempts verification.
- **Expected Outcome:**
  - Subcase A: HTTP 403 Forbidden ("Pemisahan tugas: Penugasan tidak dapat diverifikasi oleh pekerja yang sama").
  - Subcase B: HTTP 200 OK, `obligation.is_owner_bypass: True`.
- **Expected Final State:** In Subcase B, `is_owner_bypass` is true in `wage_obligations`.
- **Pass/Fail Criteria:** Self-verification by non-owner strictly blocked.

---

### TX-16: Transactional Outbox Atomicity, Crash Recovery & Deduplication
- **Invariant:** Outbox records in `db.outbox_events` must commit atomically with domain mutations. Relays provide at-least-once delivery with consumer deduplication.
- **Initial State:** Empty outbox collection.
- **Failure Injection Point:**
  - Subcase A: Transaction aborts before commit -> Outbox event must NOT exist.
  - Subcase B: Transaction commits, relay crashes after delivery before ack -> Outbox event retried; consumer deduplicates using `event_id`.
- **Expected Outcome:**
  - Subcase A: Outbox collection count == 0.
  - Subcase B: Consumer receives duplicate event with identical `event_id`, recognizes duplicate, ignores secondary side effect.
- **Expected Final State:** All committed domain events eventually reach `status: "dispatched"`.
- **Pass/Fail Criteria:** Zero lost events; zero duplicate downstream business side effects.

---

## 3. Test Execution & Isolation Requirements Summary

| Test ID | Execution Mode | Safe Without External Replica Set? | Status in Phase 3A-1 |
| :--- | :--- | :--- | :--- |
| **TX-01** | Real Replica Set | No (requires ACID transaction) | **BLOCKED BY ENVIRONMENT** |
| **TX-02** | Real Replica Set | No (requires WiredTiger abort) | **BLOCKED BY ENVIRONMENT** |
| **TX-03** | Real Replica Set | No (requires ACID transaction) | **BLOCKED BY ENVIRONMENT** |
| **TX-04** | Real Replica Set | No (requires Motor session commit) | **BLOCKED BY ENVIRONMENT** |
| **TX-05** | Real Replica Set / Mock | Yes (Unit payload hash logic) | **IMPLEMENTED & PASSING (Unit)** |
| **TX-06** | Real Replica Set / Mock | Yes (Unit status transition logic)| **IMPLEMENTED & PASSING (Unit)** |
| **TX-07** | Real Replica Set | No (requires MongoDB unique index)| **BLOCKED BY ENVIRONMENT** |
| **TX-08** | Real Replica Set / Mock | Yes (Unit immutable guard logic) | **IMPLEMENTED & PASSING (Unit)** |
| **TX-09** | Real Replica Set / Mock | Yes (Unit fail-closed logic) | **IMPLEMENTED & PASSING (Unit)** |
| **TX-10** | Real Replica Set / Mock | Yes (Unit fencing generation) | **IMPLEMENTED & PASSING (Unit)** |
| **TX-11** | Real Replica Set | No (requires atomic concurrency) | **BLOCKED BY ENVIRONMENT** |
| **TX-12** | Real Replica Set | No (requires multi-doc tx lock) | **BLOCKED BY ENVIRONMENT** |
| **TX-13** | Real Replica Set / Mock | Yes (Unit settlement bounds) | **IMPLEMENTED & PASSING (Unit)** |
| **TX-14** | Real Replica Set / Mock | Yes (Unit array/count sync) | **IMPLEMENTED & PASSING (Unit)** |
| **TX-15** | Synthetic Mock / Server | Yes (Unit dual-custody check) | **IMPLEMENTED & PASSING (Unit)** |
| **TX-16** | Real Replica Set / Mock | Yes (Unit outbox schema & dedup) | **IMPLEMENTED & PASSING (Unit)** |
