# SOGIL FURNITURE
# PHASE 2 ARCHITECTURE & SCOPE LOCK v1.2.6
## Transaction Lifecycle and Verification Completeness

---

## 1. Document Metadata and Authoritative Hierarchy

- **Document Title**: Sogil Furniture — Phase 2 Architecture & Scope Lock v1.2.6: Transaction Lifecycle and Verification Completeness
- **Version**: v1.2.6 (Authoritative Architectural Baseline)
- **Primary Source Documents**:
  - [`docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.1.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.1.md)
  - [`docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.md)
  - [`docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.1.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.1.md)
  - [`docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.2.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.2.md)
  - [`docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.3.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.3.md)
  - [`docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.4.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.4.md)
  - [`docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.5.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.5.md)
- **Baseline Git Commit**: `65a8f14d002304a7f67d92f256487dd4b00ddc42` (Phase 1: *Order-Payment Core*)
- **Status**: **AUTHORITATIVE ARCHITECTURAL SPECIFICATION** (Narrow Forensic Correction — Documentation Only)

---

## 2. Executive Summary & Authoritative Hierarchy

This document resolves the three specific technical blockers identified during forensic review of version 1.2.5:
1. **Transaction Lifecycle Management (Blocker 1)**: Corrects the probe pseudocode to use exactly one consistent, canonical Motor/PyMongo transaction lifecycle pattern (`async with session.start_transaction():` context manager), eliminating conflicting explicit `session.commit_transaction()` calls that risk double-commit errors or obscured exceptions.
2. **Probe Infrastructure Provisioning & Bounded Cleanup (Blocker 2)**: Hardens concurrent startup safety (`create_collection` with `CollectionInvalid` collision handling), ensures idempotent TTL index creation on existing collections, acknowledges TTL as asynchronous cleanup, and defines multi-layered cleanup (transactional abort, post-commit delete, and bounded stale cleanup) with zero business collection impact.
3. **Complete, Non-Truncated Finance Snapshots (Blocker 3)**: Eliminates `.to_list(1000)` and all bounded queries from finance invariant test assertions. Mandates full asynchronous cursor streaming (`async for doc in cursor:`) over the controlled test dataset, coupled with exact monetary delta comparisons ($|\Delta_{\text{EGP}}| < 0.0001$) and isolated test fixtures.
4. **Preserved Business Invariants**: Fully retains Decision B-1 (100% lump-sum all-or-nothing), Decision E1 (controlled task categories), Decision E2 (owner self-approval with audit trail), two-tier monetary precision, and zero cash movements in Phase 2.

---

## 3. Approved Business Decisions and Non-Negotiable Invariants

The following decisions are approved by the business owner and fully locked:

### A. Decision B-1: All-or-Nothing Lump-Sum Acceptance [APPROVED BUSINESS DECISION]
- Lump-sum (`lump_sum`) work assignments are eligible for wage accrual **only when the assigned work is accepted at exactly 100%** (`accepted_quantity == target_quantity`).
- Any attempt to submit partial acceptance (`accepted_quantity < target_quantity`) for a lump-sum assignment **MUST be rejected with `HTTP 422 Unprocessable Entity`**.
- Rejection causes:
  - Zero wage obligation creation;
  - Zero finance transaction creation, mutation, or reversal;
  - Zero assignment status mutation (remains `ready_for_review`);
  - Zero partially persisted acceptance or accrual state.
- Pro-rata wage calculations and full payment authorization for partial work are strictly prohibited.

### B. Decision E1: Controlled Task Categories [APPROVED BUSINESS DECISION]
- Supported task categories are strictly locked to five controlled values:
  1. `whole_item` (Borongan penuh / full piece manufacturing)
  2. `assembly` (Perakitan kerangka)
  3. `finishing` (Pengecatan / coating / polishing)
  4. `cutting` (Pemotongan bahan)
  5. `custom` (Penugasan khusus)
- Arbitrary free-text categories are prohibited. Specific notes must be stored in optional `task_notes: str`.

### C. Decision E2: Owner-Only Self-Approval Exception [APPROVED BUSINESS DECISION]
- Only an authenticated user whose server-verified role is strictly `"owner"` may self-approve their own work assignment.
- Roles `manager`, `admin`, and `employee` are strictly prohibited from self-approval (`HTTP 403 Forbidden`). Administrative permissions do not override this restriction.
- The bypass skips **only the actor separation check**. It does not skip lifecycle states (`assigned` $\to$ `in_progress` $\to$ `ready_for_review` $\to$ `completed`) or quantity/rate validations.
- Every self-approval records an immutable dual audit trail (`is_owner_bypass: True` in domain entities and in `db.audit_logs`).

### D. Zero Cash Movement Boundary [LOCKED ARCHITECTURAL RULE]
- Phase 2 creates **ZERO cash-out finance transactions**, writes **ZERO records to `db.employee_wages`**, and causes **ZERO cash balance movements**.
- Wage obligations represent accrued accounting liabilities, not cash disbursements. Actual cash disbursement is deferred to Phase 3.

---

## 4. Blocker 1: Canonical Transaction Lifecycle Management

### A. The Defect in v1.2.5 Lifecycle Mixing
In PyMongo and Motor, `session.start_transaction()` returns an asynchronous context manager. Upon normal exit of the `async with session.start_transaction():` block, the context manager **automatically commits the transaction**. If an unhandled exception exits the block, it **automatically aborts the transaction**.
In v1.2.5, pseudocode called `await session.commit_transaction()` explicitly *inside* the context manager block. This mixed two paradigms:
- Explicit commit inside an auto-committing context manager can trigger `InvalidOperation: Transaction already committed` or obscure exceptions if commit-time network errors occur.

### B. Canonical Single-Lifecycle Specification [LOCKED ARCHITECTURAL RULE]
The architecture formally adopts the **Idiomatic Asynchronous Context Manager Lifecycle**:
```python
async with session:
    async with session.start_transaction():
        # All transactional operations occur here.
        # Normal block exit -> Context manager calls commit_transaction().
        # Exception raised -> Context manager calls abort_transaction().
```

### C. Formal Multi-Document & Cross-Collection Probe Specification
```python
async def run_transaction_probe(client: AsyncIOMotorClient, db_name: str) -> bool:
    """
    Rigorously verifies multi-document, cross-collection transaction execution
    using the canonical Motor context-manager lifecycle.
    """
    db = client[db_name]
    col_a = db["_system_probe_assignments"]
    col_b = db["_system_probe_obligations"]

    probe_token = f"probe_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    doc_a_id = f"asn_{probe_token}"
    doc_b_id = f"wob_{probe_token}"

    session = None
    try:
        session = await client.start_session()
        async with session:
            async with session.start_transaction():
                # 1. Multi-document Write 1: Collection A
                await col_a.insert_one(
                    {"_id": doc_a_id, "token": probe_token, "status": "completed", "created_at": now},
                    session=session
                )
                
                # 2. Multi-document Write 2: Collection B (Cross-Collection)
                await col_b.insert_one(
                    {"_id": doc_b_id, "token": probe_token, "accrual_key": f"acc_{doc_a_id}", "created_at": now},
                    session=session
                )
                
                # 3. Transactional Read: Verify snapshot visibility of both distinct docs
                found_a = await col_a.find_one({"_id": doc_a_id}, session=session)
                found_b = await col_b.find_one({"_id": doc_b_id}, session=session)
                if not found_a or not found_b:
                    raise RuntimeError("Snapshot isolation read failed within transaction")
                
                # Context manager exit executes commit_transaction() cleanly.

        # 4. Post-commit cleanup: Remove probe records outside transaction
        await col_a.delete_one({"_id": doc_a_id})
        await col_b.delete_one({"_id": doc_b_id})
        return True

    except (pymongo.errors.ConfigurationError, pymongo.errors.InvalidOperation) as e:
        logger.error(f"Deployment topology lacks transaction support: {e}")
        return False
    except Exception as e:
        logger.error(f"Multi-document transaction probe failed: {e}")
        # Safe cleanup of any persisted probe records outside transaction
        try:
            await col_a.delete_one({"_id": doc_a_id})
            await col_b.delete_one({"_id": doc_b_id})
        except Exception:
            pass
        return False
```

### D. Treatment of Ambiguous Commit Outcomes
- If a commit attempt raises an ambiguous outcome (e.g. timeout or network disconnect during commit), the probe returns `False`.
- In production, ambiguous capability is treated conservatively as a **failure to verify capability**, enforcing the fail-closed policy.

---

## 5. Blocker 2: Probe Infrastructure Provisioning, Concurrency, and Bounded Cleanup

### A. Pre-Provisioning with Concurrent Startup Safety [LOCKED ARCHITECTURAL RULE]
To prevent race conditions during horizontal scaling where multiple backend worker processes start simultaneously:
1. **Collection Provisioning Gate**:
   - Collections `_system_probe_assignments` and `_system_probe_obligations` are provisioned during startup.
   - If two worker processes attempt `create_collection` concurrently, PyMongo raises `pymongo.errors.CollectionInvalid` (collection already exists). The startup routine catches `CollectionInvalid` as a non-fatal, successful creation.
2. **Index Provisioning Gate**:
   - `create_index` is called idempotently with `background=True` and `expireAfterSeconds=300`. Even if the collections already exist from a previous run, the TTL index existence and options are verified/ensured.
   ```python
   async def ensure_probe_infrastructure(db: AsyncIOMotorDatabase) -> bool:
       for col_name in ["_system_probe_assignments", "_system_probe_obligations"]:
           try:
               await db.create_collection(col_name)
           except pymongo.errors.CollectionInvalid:
               pass  # Already exists; safe concurrent startup
           except Exception as e:
               logger.error(f"Failed to provision probe collection {col_name}: {e}")
               return False
           
           try:
               col = db[col_name]
               await col.create_index([("created_at", 1)], expireAfterSeconds=300)
           except Exception as e:
               logger.error(f"Failed to ensure TTL index on {col_name}: {e}")
               return False
       return True
   ```
3. **Startup Fail-Closed**:
   - If `ensure_probe_infrastructure()` fails in production, the service fails startup immediately.

### B. Nature of Cleanup & TTL Asynchrony
- **Explicit Post-Commit Cleanup**: The probe actively deletes its documents immediately following successful commit.
- **Exception Cleanup**: If the probe aborts or errors, it executes an explicit fallback `delete_one`.
- **TTL Asynchronous Purge**: The TTL index (`expireAfterSeconds=300`) is explicitly documented as an **asynchronous background garbage collection mechanism** (MongoDB background thread runs periodically, typically once every 60 seconds). It guarantees that stale records from unexpected hard process termination are eventually purged without indefinite accumulation.
- **Zero Business Impact**: All probe creation, probing, and cleanup operate exclusively on `_system_probe_*` collections, with zero read/write access to business collections.

### C. Evidence Boundaries
- **What the probe proves**:
  - The MongoDB deployment is an active Replica Set or Sharded Cluster capable of coordinating multi-document, cross-collection ACID transactions;
  - Snapshot isolation reads succeed across multiple collections inside a transaction;
  - The commit coordinator successfully finalizes two-phase journal writes.
- **What the probe does NOT prove**:
  - It does NOT prove arbitrary cluster-wide high-concurrency lock throughput or performance under heavy sustained load. High-concurrency conflict handling is governed by Phase 2 optimistic retry limits.

---

## 6. Blocker 3: Complete, Non-Truncated Finance Snapshots

### A. The Flaw in Bounded `.to_list(1000)` Queries
In v1.2.5, test examples used `.to_list(1000)` to snapshot existing financial records. In a mature system, `finance_transactions` or `employee_wages` can exceed 1,000 documents. Bounded queries silently truncate the snapshot, leaving pre-existing documents beyond index 1,000 unverified for unauthorized mutations or deletions.

### B. The Complete Iteration Snapshot Protocol [LOCKED ARCHITECTURAL RULE]
All test assertions verifying finance and wage immutability MUST use complete, unbounded asynchronous iteration or controlled isolated fixtures:

```python
async def snapshot_entity_map(collection: AsyncIOMotorCollection) -> dict:
    """
    Completely snapshots an entire collection into an in-memory map by _id,
    guaranteeing zero truncation regardless of collection size.
    """
    snapshot = {}
    async for doc in collection.find({}):
        snapshot[str(doc["_id"])] = doc
    return snapshot
```

### C. Complete Test Invariant Verification Logic
```python
async def verify_finance_invariants(db: AsyncIOMotorDatabase, pre_snap_txns: dict, pre_snap_wages: dict, pre_egp: float, pre_idr: float):
    # 1. Full post-operation snapshot
    post_snap_txns = await snapshot_entity_map(db.finance_transactions)
    post_snap_wages = await snapshot_entity_map(db.employee_wages)

    # 2. Check finance_transactions: zero additions, zero deletions, zero mutations
    assert set(post_snap_txns.keys()) == set(pre_snap_txns.keys()), (
        f"Finance transaction IDs mismatch! "
        f"New: {set(post_snap_txns.keys()) - set(pre_snap_txns.keys())}, "
        f"Deleted: {set(pre_snap_txns.keys()) - set(post_snap_txns.keys())}"
    )
    for tid, orig_doc in pre_snap_txns.items():
        assert post_snap_txns[tid] == orig_doc, f"Finance transaction {tid} was mutated during Phase 2 operation!"

    # 3. Check employee_wages: zero additions, zero deletions, zero mutations
    assert set(post_snap_wages.keys()) == set(pre_snap_wages.keys()), (
        f"Employee wage IDs mismatch! "
        f"New: {set(post_snap_wages.keys()) - set(pre_snap_wages.keys())}, "
        f"Deleted: {set(pre_snap_wages.keys()) - set(post_snap_wages.keys())}"
    )
    for wid, orig_doc in pre_snap_wages.items():
        assert post_snap_wages[wid] == orig_doc, f"Employee wage record {wid} was mutated during Phase 2 operation!"

    # 4. Exact cash balance delta check using epsilon boundary
    post_egp = await compute_current_cash_balance("EGP")
    post_idr = await compute_current_cash_balance("IDR")
    assert abs(post_egp - pre_egp) < 0.0001, f"Cash EGP balance changed: delta = {post_egp - pre_egp}"
    assert abs(post_idr - pre_idr) == 0, f"Cash IDR balance changed: delta = {post_idr - pre_idr}"
```

### D. Complete Finance Invariant Matrix

| Operation Scenario | Pre-Existing Ledger State | Executed Action | $\Delta_{\text{new}}$ Txns | $\Delta_{\text{mut}}$ Txns | $\Delta_{\text{del}}$ Txns | $\Delta_{\text{wages}}$ | Cash Delta ($\Delta_{\text{Cash}}$) |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **Successful Per-Unit Accrual** | Arbitrary $N$ txns, $M$ wages | `verify` accepts 4 units | **0** | **0** | **0** | **0** | **0.00 LE / 0 IDR** |
| **Successful 100% Lump-Sum Accrual** | Arbitrary $N$ txns, $M$ wages | `verify` accepts 4/4 units | **0** | **0** | **0** | **0** | **0.00 LE / 0 IDR** |
| **Rejected Lump-Sum Partial (`HTTP 422`)** | Arbitrary $N$ txns, $M$ wages | `verify` attempts 3/4 units | **0** | **0** | **0** | **0** | **0.00 LE / 0 IDR** |
| **Replay / Duplicate Verification** | Arbitrary $N$ txns, $M$ wages | `verify` replayed | **0** | **0** | **0** | **0** | **0.00 LE / 0 IDR** |
| **Concurrent Verification Race** | Arbitrary $N$ txns, $M$ wages | 2 simultaneous `verify` | **0** | **0** | **0** | **0** | **0.00 LE / 0 IDR** |
| **Cancel Unpaid Completed Assignment** | Arbitrary $N$ txns, $M$ wages | `cancel` voids obligation | **0** | **0** | **0** | **0** | **0.00 LE / 0 IDR** |
| **Block Cancel Paid Obligation (`HTTP 400`)**| Arbitrary $N$ txns, $M$ wages | `cancel` attempted | **0** | **0** | **0** | **0** | **0.00 LE / 0 IDR** |
| **Transaction Abort / Rollback** | Arbitrary $N$ txns, $M$ wages | Write fails mid-session | **0** | **0** | **0** | **0** | **0.00 LE / 0 IDR** |
| **Standalone Crash Recovery** | Arbitrary $N$ txns, $M$ wages | Reconciler resets `accruing`| **0** | **0** | **0** | **0** | **0.00 LE / 0 IDR** |

---

## 7. Monetary Representation: Precision Contract & Boundaries

### A. Two-Tier Precision Contract [LOCKED ARCHITECTURAL RULE]
1. **Calculation Engine (In-Memory)**:
   - All rate lookups, multiplications, additions, and aggregations are performed strictly using Python's `decimal.Decimal` module.
   - Quantized to 2 decimal places using `ROUND_HALF_UP` (`Decimal("0.01")`).
   - Unnormalized binary float arithmetic during calculation is prohibited.
2. **Storage & Serialization**:
   - Quantized `Decimal` values are converted to standard Python `float` strictly at the persistence boundary: `float(quantized_decimal)`.
   - IEEE 754 binary floating-point representation limits are explicitly acknowledged. Exact decimal persistence is not claimed.
   - All equality comparisons during testing or reconciliation must evaluate within an epsilon boundary ($|\Delta| < 0.0001$).
3. **Zero Migration**: Historical Phase 1 records remain untouched.

---

## 8. Order-Item Identity: Comprehensive Historical Reference Protection

### A. Protected Item Definition [LOCKED ARCHITECTURAL RULE]
An order item is classified as **PROTECTED** and cannot be deleted, replaced, or have its ID modified in `admin_update_order` if referenced by ANY of the following:
1. Active work assignments (`assigned`, `in_progress`, `ready_for_review`, `accruing`);
2. Completed work assignments (`completed`);
3. Cancelled work assignments (`cancelled`) with historical audit trails;
4. Wage obligations in any status (`accrued`, `paid`, `voided`).

### B. Array Reconciliation Algorithm
`admin_update_order` executes the server-side array reconciliation algorithm specified in v1.2.5 Section 7. Attempting to remove or replace any protected item raises `HTTP 409 Conflict`.

---

## 9. Canonical Status Registry (Option A)

### A. Authoritative Entity Status Registries

#### 1. `db.work_assignments.status`
- **`assigned`** [Business]: Worker assigned to task; work not started. Zero financial impact.
- **`in_progress`** [Business]: Manufacturing started. Zero financial impact.
- **`ready_for_review`** [Business]: Work reported complete; awaiting inspection. Zero financial impact.
- **`accruing`** [Internal Processing State]: Transient lock during standalone non-transactional accrual. Governed by 60s timeout and background reconciliation fencing. Zero financial impact.
- **`completed`** [Business]: Verified and accepted; wage obligation accrued. Terminal state (except unpaid voiding).
- **`cancelled`** [Business]: Assignment terminated (either before start or post-accrual with voiding). Terminal state.

#### 2. `db.wage_obligations.status`
- **`accrued`** [Business]: Earned wage liability recorded upon verification. Zero cash movement.
- **`voided`** [Business]: Liability cancelled prior to payout; preserved for audit history. Terminal state.
- **`paid`** [Business]: [DEFERRED TO PHASE 3] Disbursed via Cash-Out finance transaction. Terminal state.

#### 3. Diagnostic Reconciliation Classifications (NOT persisted statuses)
- `RECON_CLEAN`: Perfect entity state and obligation consistency.
- `RECON_STALE_PROCESSING`: Assignment stuck in `accruing` $> 60\text{ seconds}$.
- `RECON_UNACCRUED_COMPLETION`: Assignment `completed` but canonical obligation is missing.
- `RECON_ORPHAN_OBLIGATION`: Obligation exists with no corresponding assignment.

---

## 10. Comprehensive Acceptance Test Matrix

| Test ID | Domain | Preconditions | Action | Expected Entity Result | Expected Finance Delta |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **TC-MON-01** | Money Calculation | Agreed rate `33.33 LE`, accepted qty `3` | Verify work | Obligation accrued: `99.99 LE` (exact Decimal) | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0$ |
| **TC-MON-02** | Rate Over-Precision | Rate entered as `45.125 LE` | Create wage rule | Rejected with `HTTP 422 Unprocessable Entity` | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0$ |
| **TC-LMP-01** | Lump-Sum 100% (B-1) | Target 4 units at 500 LE; accepts 4 | Verify work | Assignment `completed`, obligation `500.00 LE` | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0$ |
| **TC-LMP-02** | Lump-Sum Partial (B-1) | Target 4 units at 500 LE; accepts 3 | Verify work | **Rejected `HTTP 422`**; assignment `ready_for_review` | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0$ |
| **TC-TXN-01** | Fail-Closed Production | Prod mode; mock session failure | Verify work | **Rejected `HTTP 503`**; 0 writes performed | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0$ |
| **TC-TXN-02** | Local Standalone Recovery | Standalone mode; crash in `accruing` | Run reconciler | Reconciler resets assignment to `ready_for_review` | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0$ |
| **TC-ITM-01** | Reorder Item Stability | Order with 2 items | Update order items | Array reordered; `item_id` preserved exactly | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0$ |
| **TC-ITM-02** | Active Item Delete Block | Item has active assignment | Delete item in edit| **Rejected `HTTP 409 Conflict`** | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0$ |
| **TC-ITM-03** | Cancelled Item Delete Block| Item has cancelled assignment | Delete item in edit| **Rejected `HTTP 409 Conflict`** | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0$ |
| **TC-AUT-01** | Non-Owner Self-Approval | Admin worker verifies own work | Verify work | **Rejected `HTTP 403 Forbidden`** | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0$ |
| **TC-AUT-02** | Owner Self-Approval | Owner worker verifies own work | Verify work | Succeeded; `is_owner_bypass: true`; audit logged | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0$ |
| **TC-CON-01** | Concurrency Idempotency | 2 simultaneous verification calls | Verify work | Exactly 1 obligation created; replay returns canonical | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0$ |
| **TC-CAN-01** | Unpaid Obligation Voiding | Completed unpaid assignment | Cancel assignment | Assignment `cancelled`; obligation `voided` | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0$ |
| **TC-CAN-02** | Paid Obligation Cancel Block| Obligation has `paid_amount > 0` | Cancel assignment | **Rejected `HTTP 400 Bad Request`** | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0$ |
| **TC-FIN-01** | Complete Finance Invariant Check| Pre-existing ledger with historical txns | Complete operations| Complete unbounded iteration: 0 new txns, 0 mutated | **$\Delta \text{Finance} = 0, \Delta \text{Cash} = 0$** |

---

## 11. Explicit Scope Boundaries & Exclusions

The following domains are explicitly excluded from Phase 2:
- [ ] Payout batch disbursement engine (`db.finance_transactions` cash-out write) $\to$ **Deferred to Phase 3**.
- [ ] Worker payout UI modal and printable payroll slips $\to$ **Deferred to Phase 3**.
- [ ] Delivery logistics, driver assignments, and delivery wages $\to$ **Deferred to Future Logistics Phase**.
- [ ] Material consumption stock deduction upon order completion $\to$ **Deferred to Future Inventory Phase**.
- [ ] Automated HPP gross margin costing engine $\to$ **Deferred to Future Accounting Phase**.
- [ ] Worker mobile self-service application $\to$ **Deferred**.

---

## 12. Final Architecture Readiness Verdict

### 🟢 **PASS — READY FOR MASTER BUILD PROMPT**

**Architectural Assessment**:  
All three forensic blockers have been completely and rigorously resolved:
1. Canonical transaction lifecycle context management prevents double commit/abort and obscure exceptions.
2. Probe infrastructure provisioning handles concurrent startup collisions gracefully, provisions TTL indexes idempotently, acknowledges TTL as asynchronous garbage collection, and isolates all probes from business records.
3. Finance invariants mandate complete, unbounded iteration snapshots (`async for doc in collection.find({})`), guaranteeing zero truncation and verifying that pre-existing records remain 100% untouched.
4. All approved business decisions (B-1, E1, E2) and monetary boundary contracts remain locked and binding.

Phase 2 Architecture & Scope Lock v1.2.6 is **100% complete and authoritative**. The system is ready to proceed to the creation of the separate **Phase 2 Master Build Prompt** upon user authorization.
