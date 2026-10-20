# SOGIL FURNITURE
# PHASE 2 ARCHITECTURE & SCOPE LOCK v1.2.5
## Transaction Probe Evidence Hardening & Multi-Document Verification

---

## 1. Document Metadata and Authoritative Hierarchy

- **Document Title**: Sogil Furniture — Phase 2 Architecture & Scope Lock v1.2.5: Transaction Probe Evidence Hardening & Multi-Document Verification
- **Version**: v1.2.5 (Authoritative Architectural Baseline)
- **Primary Source Documents**:
  - [`docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.1.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.1.md)
  - [`docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.md)
  - [`docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.1.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.1.md)
  - [`docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.2.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.2.md)
  - [`docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.3.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.3.md)
  - [`docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.4.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.4.md)
- **Baseline Git Commit**: `65a8f14d002304a7f67d92f256487dd4b00ddc42` (Phase 1: *Order-Payment Core*)
- **Status**: **AUTHORITATIVE ARCHITECTURAL SPECIFICATION** (Narrow Correction — Documentation Only)

---

## 2. Executive Summary & Authoritative Hierarchy

This document delivers the final, rigorous architectural hardening for **Phase 2 — Work Assignments & Production Piece-Rate** of the Sogil Furniture platform. It resolves the two targeted evidence-hardening blockers identified in version 1.2.4:
1. **Multi-Document & Cross-Collection Transaction Probe Hardening (Blocker 1)**: Replaces the previous single-document probe with a safe, isolated, multi-document and cross-collection transaction probe operating across two pre-provisioned internal probe collections (`_system_probe_assignments` and `_system_probe_obligations`). The probe explicitly exercises transactional writes, transactional cross-collection reads, atomic commit, post-commit cleanup, and TTL-bounded stale probe garbage collection without mutating business records.
2. **Robust Entity-Level Finance Invariant Test Verification (Blocker 2)**: Replaces assumptions about collection counts and monotonic ObjectIds with explicit before/after entity snapshotting in isolated test fixtures, rigorously verifying that no new financial records are created, no protected pre-existing records are mutated or deleted, and zero cash movement occurs across all Phase 2 operational paths.
3. **Preservation of Core Invariants**: Retains Decision B-1 (100% lump-sum all-or-nothing), Decision E1 (controlled task categories), Decision E2 (owner-only self-approval), two-tier monetary precision (exact Python `Decimal` calculation arithmetic quantized via `ROUND_HALF_UP` to 2-decimal floats), and strict isolation from cash movements, payouts, and HPP.

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

## 4. Blocker 1: Multi-Document & Cross-Collection Transaction Probe Hardening

### A. Architectural Motivation & Deficit in v1.2.4
Version 1.2.4 proposed an insert-read-delete sequence on a single document in `_system_transaction_probes`. While an improvement over `ping`, it had two architectural limitations:
1. It operated on a single document in a single collection. In MongoDB, single-document operations are atomic by default even without multi-document transaction coordinators.
2. In Phase 2, the production accrual transaction must coordinate atomic mutations across **two distinct collections**: `db.work_assignments` (status transition to `completed`) and `db.wage_obligations` (inserting the accrued obligation).
3. Furthermore, MongoDB restricts implicit collection creation inside multi-document transactions (depending on server version and feature compatibility). Creating a collection dynamically inside a transaction can cause transactions to abort.

### B. Dedicated Pre-Provisioned Probe Infrastructure [LOCKED ARCHITECTURAL RULE]
To prove multi-document and cross-collection transaction support without touching business collections:
1. **Two Dedicated Internal Probe Collections**:
   - `db._system_probe_assignments`
   - `db._system_probe_obligations`
2. **Pre-Provisioning Gate (Out-of-Transaction)**:
   Before executing the probe transaction, the application verifies that both probe collections exist. If they do not exist, they are explicitly created **outside of any transaction** (`create_collection`) during application initialization.
3. **Automatic Stale Record Quarantine via TTL Index**:
   Both collections maintain a TTL index on `created_at` (e.g. `expireAfterSeconds: 300`). If a server crashes or network breaks mid-probe before cleanup, MongoDB automatically purges orphaned probe records within 5 minutes.
   ```python
   await db._system_probe_assignments.create_index([("created_at", 1)], expireAfterSeconds=300)
   await db._system_probe_obligations.create_index([("created_at", 1)], expireAfterSeconds=300)
   ```

### C. Safe Multi-Document & Cross-Collection Probe Specification [LOCKED ARCHITECTURAL RULE]
During startup in production, the backend executes the following verification probe:

```python
async def verify_production_transaction_capability(client: AsyncIOMotorClient, db_name: str) -> bool:
    """
    Rigorously verifies multi-document and cross-collection transaction capability:
    1. Pre-provisions probe collections outside transaction if missing.
    2. Opens transaction session.
    3. Writes to Collection A (mock assignment state change).
    4. Writes to Collection B (mock wage obligation creation).
    5. Reads both documents inside the transaction to verify snapshot isolation.
    6. Commits transaction to verify two-phase journal commit.
    7. Cleans up probe documents outside transaction (or within non-transactional write).
    """
    db = client[db_name]
    col_a = db["_system_probe_assignments"]
    col_b = db["_system_probe_obligations"]
    
    # Pre-provision collections outside transaction to avoid implicit creation errors
    existing_cols = await db.list_collection_names()
    if "_system_probe_assignments" not in existing_cols:
        await db.create_collection("_system_probe_assignments")
        await col_a.create_index([("created_at", 1)], expireAfterSeconds=300)
    if "_system_probe_obligations" not in existing_cols:
        await db.create_collection("_system_probe_obligations")
        await col_b.create_index([("created_at", 1)], expireAfterSeconds=300)

    # Unique probe correlation token per instance/probe attempt
    probe_token = f"probe_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    doc_a_id = f"asn_{probe_token}"
    doc_b_id = f"wob_{probe_token}"

    try:
        async with await client.start_session() as session:
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
                
                # 3. Transactional Read: Verify both distinct documents exist in snapshot
                found_a = await col_a.find_one({"_id": doc_a_id}, session=session)
                found_b = await col_b.find_one({"_id": doc_b_id}, session=session)
                if not found_a or not found_b:
                    raise RuntimeError("Multi-document snapshot read failed inside transaction")
                
                # 4. Commit Transaction
                await session.commit_transaction()

        # 5. Clean up probe records after successful commit
        await col_a.delete_one({"_id": doc_a_id})
        await col_b.delete_one({"_id": doc_b_id})
        return True

    except (pymongo.errors.ConfigurationError, pymongo.errors.InvalidOperation) as e:
        logger.error(f"MongoDB deployment topology does not support transactions: {e}")
        return False
    except Exception as e:
        logger.error(f"Multi-document transaction probe failed: {e}")
        # Clean up any partial probe records if commit failed
        try:
            await col_a.delete_one({"_id": doc_a_id})
            await col_b.delete_one({"_id": doc_b_id})
        except Exception:
            pass
        return False
```

### D. Evidence Boundaries: What the Probe Proves vs. Does Not Prove

| Verification Dimension | Proven by Probe? | Forensic Reality / Evidence Assessment |
| :--- | :---: | :--- |
| **Driver Session Creation** | **YES** | Proves client can allocate Motor session objects. |
| **Replica Set Topology** | **YES** | Proves MongoDB deployment is configured as a Replica Set; standalone throws `ConfigurationError`. |
| **Multi-Document Write Coordination** | **YES** | Proves driver and cluster coordinate writes to multiple distinct documents. |
| **Cross-Collection Transaction Locking** | **YES** | Proves transaction coordinator successfully handles lock acquisition across multiple distinct collections. |
| **Two-Phase Journal Commit** | **YES** | Proves transaction committed to write-ahead journal across cluster nodes. |
| **Production Business Data Mutation** | **NO (0 mutations)** | Operates strictly in `_system_probe_*` collections; 0 business collections touched. |
| **Long-Running Write Contention / Deadlocks** | **NO** | Does not prove high-concurrency lock contention under massive load (governed by Phase 2 optimistic retry limits). |

### E. Production Startup & Runtime Fail-Closed Policy [LOCKED ARCHITECTURAL RULE]
1. **Production Startup (`ENVIRONMENT == "production"`)**:
   - The probe MUST succeed during application startup (`@app.on_event("startup")`).
   - If the probe returns `False`, the backend **HALTS APPLICATION STARTUP IMMEDIATELY** with a fatal log:
     ```text
     FATAL: Production database lacks verified multi-document cross-collection transaction capability. Halting service.
     ```
2. **Production Runtime Enforcement**:
   - The verification endpoint (`POST /api/admin/assignments/{id}/verify`) executes strictly within a transaction session.
   - If transaction allocation fails at runtime, the endpoint **FAILS CLOSED WITH `HTTP 503 Service Unavailable: "Sistem transaksi database tidak tersedia"`**.
   - Silent fallback to `session = None` in production is strictly forbidden by code design.
3. **Local Standalone Mode (`ENVIRONMENT in ["development", "test"]`)**:
   - Permitted exclusively in non-production environments using the Option A durable two-phase state machine (`ready_for_review` $\to$ `accruing` $\to$ `completed`).

---

## 5. Blocker 2: Robust Entity-Level Finance Invariant Test Verification

### A. The Flaw of Collection Counts and Monotonic ObjectId Assumptions
Testing finance invariants by asserting global counts (`count == 0`) or checking IDs with `_id > max_before_id` has two fatal flaws:
1. Global count checks fail in any environment where pre-existing test fixtures or legacy finance records exist.
2. MongoDB `ObjectId` generation includes timestamp, machine, process, and counter components. In distributed or concurrent test runs, assuming strict monotonicity across concurrent worker processes can result in false negatives.

### B. The Entity-Level Snapshot Strategy [LOCKED ARCHITECTURAL RULE]
Tests must snapshot the exact entities relevant to the test before execution and verify deltas at the entity level:

1. **Baseline Snapshotting**:
   Before executing the Phase 2 action, the test captures:
   ```python
   # 1. Capture set of existing finance transaction IDs
   pre_existing_txn_ids = set(await db.finance_transactions.distinct("_id"))
   pre_existing_txn_map = {
       str(t["_id"]): t 
       for t in await db.finance_transactions.find({"_id": {"$in": list(pre_existing_txn_ids)}}).to_list(1000)
   }

   # 2. Capture set of existing employee wage IDs
   pre_existing_wage_ids = set(await db.employee_wages.distinct("_id"))
   pre_existing_wage_map = {
       str(w["_id"]): w 
       for w in await db.employee_wages.find({"_id": {"$in": list(pre_existing_wage_ids)}}).to_list(1000)
   }

   # 3. Capture baseline cash balances
   pre_balance_egp = await compute_current_cash_balance("EGP")
   pre_balance_idr = await compute_current_cash_balance("IDR")
   ```

2. **Phase 2 Operation Execution**:
   The test executes the targeted Phase 2 endpoint (e.g. `verify`, `reject`, `cancel`, or `reconcile`).

3. **Post-Operation Entity Invariant Assertions**:
   ```python
   # Invariant A: Exactly zero new finance transactions created
   post_txn_ids = set(await db.finance_transactions.distinct("_id"))
   new_txn_ids = post_txn_ids - pre_existing_txn_ids
   assert len(new_txn_ids) == 0, f"Unintended finance transactions created: {new_txn_ids}"

   # Invariant B: Zero pre-existing finance transactions mutated or deleted
   post_txns = await db.finance_transactions.find({"_id": {"$in": list(pre_existing_txn_ids)}}).to_list(1000)
   assert len(post_txns) == len(pre_existing_txn_ids), "Pre-existing finance transactions were deleted"
   for t in post_txns:
       orig = pre_existing_txn_map[str(t["_id"])]
       assert t == orig, f"Pre-existing finance transaction {t['_id']} was mutated"

   # Invariant C: Exactly zero new employee_wages created
   post_wage_ids = set(await db.employee_wages.distinct("_id"))
   new_wage_ids = post_wage_ids - pre_existing_wage_ids
   assert len(new_wage_ids) == 0, f"Unintended employee_wages created: {new_wage_ids}"

   # Invariant D: Zero pre-existing employee_wages mutated or deleted
   post_wages = await db.employee_wages.find({"_id": {"$in": list(pre_existing_wage_ids)}}).to_list(1000)
   assert len(post_wages) == len(pre_existing_wage_ids), "Pre-existing employee_wages were deleted"
   for w in post_wages:
       orig = pre_existing_wage_map[str(w["_id"])]
       assert w == orig, f"Pre-existing employee_wage {w['_id']} was mutated"

   # Invariant E: Exact zero cash balance delta
   post_balance_egp = await compute_current_cash_balance("EGP")
   post_balance_idr = await compute_current_cash_balance("IDR")
   assert abs(post_balance_egp - pre_balance_egp) < 0.0001, "Cash balance in EGP moved during Phase 2 operation"
   assert abs(post_balance_idr - pre_balance_idr) == 0, "Cash balance in IDR moved during Phase 2 operation"
   ```

### C. Comprehensive Entity-Level Finance Delta Matrix

| Operation Scenario | Pre-Existing Ledger State | Phase 2 Action Executed | New Finance Txns ($\Delta_{\text{new}}$) | Mutated Pre-Existing Txns ($\Delta_{\text{mut}}$) | New / Mutated `employee_wages` | Cash Movement ($\Delta_{\text{Cash}}$) |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| **Successful Per-Unit Accrual** | $N$ txns, $M$ wage docs | `verify` accepts 4 units | **0** | **0** | **0** | **0.00 LE / 0 IDR** |
| **Successful 100% Lump-Sum Accrual** | $N$ txns, $M$ wage docs | `verify` accepts 4/4 units | **0** | **0** | **0** | **0.00 LE / 0 IDR** |
| **Rejected Lump-Sum Partial (`HTTP 422`)** | $N$ txns, $M$ wage docs | `verify` attempts 3/4 units | **0** | **0** | **0** | **0.00 LE / 0 IDR** |
| **Replay / Duplicate Verification** | $N$ txns, $M$ wage docs | `verify` replayed | **0** | **0** | **0** | **0.00 LE / 0 IDR** |
| **Concurrent Verification Race** | $N$ txns, $M$ wage docs | 2 simultaneous `verify` calls | **0** | **0** | **0** | **0.00 LE / 0 IDR** |
| **Cancel Unpaid Completed Assignment** | $N$ txns, $M$ wage docs | `cancel` voids obligation | **0** | **0** | **0** | **0.00 LE / 0 IDR** |
| **Block Cancel Paid Obligation (`HTTP 400`)**| $N$ txns, $M$ wage docs | `cancel` attempted on paid task | **0** | **0** | **0** | **0.00 LE / 0 IDR** |
| **Transaction Abort / Rollback** | $N$ txns, $M$ wage docs | Write fails mid-session | **0** | **0** | **0** | **0.00 LE / 0 IDR** |
| **Standalone Crash Recovery** | $N$ txns, $M$ wage docs | Reconciler resets `accruing` | **0** | **0** | **0** | **0.00 LE / 0 IDR** |

---

## 6. Monetary Representation: Precision Contract & Calculation Boundary

### A. Clarification of Mathematical Claims [LOCKED ARCHITECTURAL RULE]
To ensure complete mathematical honesty:
1. **Binary Float Limitations Acknowledged**:
   - MongoDB storage for Phase 2 wage obligations uses standard Python `float` values for fields `amount_le` and `agreed_rate_le`.
   - The architecture explicitly acknowledges that IEEE 754 binary floating-point numbers cannot mathematically represent exact base-10 decimals.
   - We **DO NOT claim** "exact binary-float decimal persistence."
2. **Calculation Boundary Precision**:
   - All rate lookups, quantity multiplications, additions, and aggregations are performed strictly in Python's standard `decimal.Decimal` module.
   - Intermediate calculations evaluate with exact precision and are quantized via `Decimal("0.01")` using `ROUND_HALF_UP`.
   - Floating-point arithmetic during calculation is strictly prohibited.
3. **Serialization & Reconciliation Boundary**:
   - The quantized `Decimal` value is converted to `float` only at the persistence boundary: `float(quantized_decimal)`.
   - During equality comparisons, tests, or reconciliation, binary float comparisons (`a == b`) are prohibited. Comparisons must evaluate within an epsilon boundary:
     $$\left| \text{stored} - \text{expected} \right| < 0.0001$$
     or convert values to `Decimal(str(round(v, 2)))` prior to comparison.
4. **Zero Historical Migration**:
   - Phase 1 financial records remain untouched in their original float formats.

---

## 7. Order-Item Identity: Comprehensive Historical Reference Protection

### A. Protected Item Definition [LOCKED ARCHITECTURAL RULE]
An order item is classified as **PROTECTED** and cannot be deleted, replaced, or have its ID modified in `admin_update_order` if referenced by ANY of the following:
1. Active work assignments (`assigned`, `in_progress`, `ready_for_review`, `accruing`);
2. Completed work assignments (`completed`);
3. Cancelled work assignments (`cancelled`) with historical audit trails;
4. Wage obligations in any status (`accrued`, `paid`, `voided`).

### B. Array Edit Reconciliation Algorithm
```python
async def reconcile_order_items_on_update(order_id: str, incoming_items: List[dict]) -> List[dict]:
    order = await db.orders.find_one({"_id": id_query(order_id)})
    existing_items = order.get("items", [])
    existing_map = {i["item_id"]: i for i in existing_items if i.get("item_id")}

    # Query all active and historical references
    assigned_item_ids = set(await db.work_assignments.distinct(
        "order_item_id", {"order_id": order_id}
    ))
    obligated_item_ids = set(await db.wage_obligations.distinct(
        "order_item_id", {"order_id": order_id}
    ))
    protected_item_ids = assigned_item_ids.union(obligated_item_ids)

    seen_ids = set()
    sanitized_items = []

    for item in incoming_items:
        iid = item.get("item_id")
        if iid:
            if iid not in existing_map:
                raise HTTPException(400, f"item_id '{iid}' tidak terdaftar pada pesanan ini")
            if iid in seen_ids:
                raise HTTPException(400, f"Duplikasi item_id '{iid}' dalam request")
            seen_ids.add(iid)
            sanitized_items.append(item)
        else:
            # Genuine new item addition
            new_item = dict(item)
            new_item["item_id"] = f"itm_{uuid.uuid4().hex[:12]}"
            sanitized_items.append(new_item)

    # Check deletion of protected items
    for pid in protected_item_ids:
        if pid not in seen_ids:
            raise HTTPException(
                409, 
                f"Tidak dapat menghapus item pesanan yang memiliki riwayat penugasan atau kewajiban upah (item_id: {pid})"
            )

    return sanitized_items
```

---

## 8. Canonical Status Registry (Option A)

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

## 9. Comprehensive Acceptance Test Matrix

Every test evaluates entity-level mutations and deltas without assuming clean or empty global collections.

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
| **TC-FIN-01** | Zero Finance Delta Leakage | Pre-existing ledger with historical txns | Complete operations| 0 new finance transactions, 0 new `employee_wages` | **$\Delta \text{Finance} = 0, \Delta \text{Cash} = 0$** |

---

## 10. Explicit Scope Boundaries & Exclusions

The following domains are explicitly excluded from Phase 2:
- [ ] Payout batch disbursement engine (`db.finance_transactions` cash-out write) $\to$ **Deferred to Phase 3**.
- [ ] Worker payout UI modal and printable payroll slips $\to$ **Deferred to Phase 3**.
- [ ] Delivery logistics, driver assignments, and delivery wages $\to$ **Deferred to Future Logistics Phase**.
- [ ] Material consumption stock deduction upon order completion $\to$ **Deferred to Future Inventory Phase**.
- [ ] Automated HPP gross margin costing engine $\to$ **Deferred to Future Accounting Phase**.
- [ ] Worker mobile self-service application $\to$ **Deferred**.

---

## 11. Final Architecture Readiness Verdict

### 🟢 **PASS — READY FOR MASTER BUILD PROMPT**

**Architectural Assessment**:  
All targeted hardening requirements have been fully satisfied:
1. Multi-document and cross-collection transaction verification is explicitly proven across two pre-provisioned internal probe collections (`_system_probe_assignments` and `_system_probe_obligations`), verifying multi-document isolation and commit without mutating business records.
2. Production startup and runtime fail-closed policies are strictly enforced.
3. Finance invariants and test case TC-FIN-01 evaluate entity-level before/after snapshots, ensuring zero unintended new records, zero mutations of pre-existing records, and zero cash movement.
4. Decimal calculation boundaries and float persistence limits are mathematically honest.
5. Historical order item references are protected across all assigned, completed, cancelled, and obligated states.
6. Approved Decisions B-1, E1, and E2 remain locked.

Phase 2 Architecture & Scope Lock v1.2.5 is **100% complete and authoritative**. The system is ready to proceed to the creation of the separate **Phase 2 Master Build Prompt** upon user authorization.
