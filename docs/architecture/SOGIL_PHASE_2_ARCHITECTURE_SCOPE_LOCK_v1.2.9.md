# SOGIL FURNITURE
# PHASE 2 ARCHITECTURE & SCOPE LOCK v1.2.9
## Explicit Currency Allowlist and Monetary Input Validation

---

## 1. Document Metadata and Authoritative Hierarchy

- **Document Title**: Sogil Furniture — Phase 2 Architecture & Scope Lock v1.2.9: Explicit Currency Allowlist and Monetary Input Validation
- **Version**: v1.2.9 (Authoritative Architectural Baseline)
- **Primary Source Documents**:
  - [`docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.1.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.1.md)
  - [`docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.md)
  - [`docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.1.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.1.md)
  - [`docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.2.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.2.md)
  - [`docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.3.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.3.md)
  - [`docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.4.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.4.md)
  - [`docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.5.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.5.md)
  - [`docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.6.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.6.md)
  - [`docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.7.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.7.md)
  - [`docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.8.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/architecture/SOGIL_PHASE_2_ARCHITECTURE_SCOPE_LOCK_v1.2.8.md)
- **Baseline Git Commit**: `65a8f14d002304a7f67d92f256487dd4b00ddc42` (Phase 1: *Order-Payment Core*)
- **Status**: **AUTHORITATIVE ARCHITECTURAL SPECIFICATION** (Narrow Forensic Correction — Documentation Only)

---

## 2. Executive Summary & Authoritative Hierarchy

This document resolves the specific currency validation finding identified during forensic review of version 1.2.8:
1. **Elimination of Silent IDR Fallback**: In v1.2.8, `normalize_cash_balance()` used an implicit else branch (`prec = Decimal("0.01") if currency.upper() == "EGP" else Decimal("1")`), which silently treated any unknown, misspelled, or unsupported currency string (e.g., `"EUR"`, `"USD"`, `"EGG"`) as IDR.
2. **Explicit Currency Allowlist Enforcement**: Version 1.2.9 defines an immutable, explicit currency allowlist mapping:
   - `"EGP"` $\longrightarrow \text{Decimal}("0.01")$
   - `"IDR"` $\longrightarrow \text{Decimal}("1")$
   Any unsupported, missing, or misspelled currency code is rejected immediately with an explicit error (`ValueError` / `HTTP 422 Unprocessable Entity`), completely preventing silent fallback behavior.
3. **Preservation of the Precision Pipeline**: Retains the two-path canonical Decimal quantization pipeline established in v1.2.8 (existing `Decimal` preserved; `float`/string converted directly via `Decimal(str(val))` without Python `round()` ties-to-even preprocessing; quantized using `ROUND_HALF_UP`).
4. **Preservation of All Locked Decisions**: Fully preserves Decision B-1 (100% lump-sum all-or-nothing), Decision E1 (controlled task categories), Decision E2 (owner-only self-approval with audit trail), three-collection complete snapshotting (`finance_transactions`, `employee_wages`, `payments`), fail-closed production transactions, and zero cash movements in Phase 2.

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
- Phase 2 creates **ZERO cash-out finance transactions**, writes **ZERO records to `db.employee_wages`**, creates **ZERO records in `db.payments`**, and causes **ZERO cash balance movements**.
- Wage obligations represent accrued accounting liabilities, not cash disbursements. Actual cash disbursement is deferred to Phase 3.

---

## 4. Explicit Currency Allowlist and Input Validation Contract

### A. Forensic Analysis of the Finding
In v1.2.8 Section 4.B, `normalize_cash_balance()` determined the quantization precision via:
```python
prec = Decimal("0.01") if currency.upper() == "EGP" else Decimal("1")
```
This logic created an unsafe fallback: if a caller provided an invalid currency (e.g. `"USD"`, `"EUR"`, `"EGP_TYPO"`, or `""`), the ternary expression defaulted silently to `Decimal("1")` (IDR precision). This violated the architectural requirement that currency handling must be strictly fail-closed.

### B. Explicit Currency Allowlist Specification [LOCKED ARCHITECTURAL RULE]
1. **Canonical Supported Currencies**:
   Only two currencies are valid in the Sogil Furniture system:
   - **EGP** (Egyptian Pound): Canonical precision is `Decimal("0.01")` (piastres / cents).
   - **IDR** (Indonesian Rupiah): Canonical precision is `Decimal("1")` (whole rupiah).
2. **Input Normalization & Validation**:
   - The currency input string is stripped of leading/trailing whitespace and converted to uppercase: `cur = (currency or "").strip().upper()`.
   - If `cur` is not in the explicit allowlist `{"EGP", "IDR"}`, the function **immediately raises `ValueError`** (or `HTTP 422 Unprocessable Entity` at the API boundary).
   - Silent defaulting to any currency is strictly prohibited.
3. **Canonical Normalization Implementation**:
   ```python
   from decimal import Decimal, ROUND_HALF_UP

   SUPPORTED_CURRENCY_PRECISIONS = {
       "EGP": Decimal("0.01"),
       "IDR": Decimal("1"),
   }

   def normalize_cash_balance(val, currency: str) -> Decimal:
       """
       Normalizes a cash balance value into canonical Decimal representation
       using strictly ROUND_HALF_UP commercial rounding and explicit currency validation.
       Rejects any unsupported, missing, or misspelled currency code.
       """
       if not currency or not isinstance(currency, str):
           raise ValueError(f"Currency code must be a non-empty string, received: {currency!r}")
       
       cur_code = currency.strip().upper()
       if cur_code not in SUPPORTED_CURRENCY_PRECISIONS:
           raise ValueError(
               f"Unsupported currency code: {currency!r}. "
               f"Allowed currencies: {list(SUPPORTED_CURRENCY_PRECISIONS.keys())}"
           )
       
       prec = SUPPORTED_CURRENCY_PRECISIONS[cur_code]

       # Path 1: Source is already Decimal
       if isinstance(val, Decimal):
           return val.quantize(prec, rounding=ROUND_HALF_UP)
       
       # Path 2: Source is float or numeric string
       # Convert directly via str() without Python round()
       d_val = Decimal(str(val))
       return d_val.quantize(prec, rounding=ROUND_HALF_UP)
   ```

### C. Acceptance Verification Cases

| Test Case | Currency Input | Value Input | Expected Result / Precision | Behavior Verified |
| :--- | :---: | :---: | :---: | :--- |
| **AC-CUR-01** | `"EGP"` / `"egp"` | `140.55` | `Decimal("140.55")` (`Decimal("0.01")`) | Selects exact EGP minor unit precision. |
| **AC-CUR-02** | `"IDR"` / `"idr"` | `2500000.4` | `Decimal("2500000")` (`Decimal("1")`) | Selects exact IDR whole unit precision. |
| **AC-CUR-03** | `"EUR"` / `"USD"` | `100.00` | **`ValueError` raised** (`HTTP 422`) | Rejects unsupported international currency. |
| **AC-CUR-04** | `"EGG"` / `"IDRR"` | `50.00` | **`ValueError` raised** (`HTTP 422`) | Rejects misspelled currency code. |
| **AC-CUR-05** | `""` / `None` | `50.00` | **`ValueError` raised** (`HTTP 422`) | Rejects empty or null currency. |
| **AC-CUR-06** | `"EGP"` movement | $\Delta = 0.01$ | $\delta = \text{Decimal}("0.01") > 0.0001$ | $0.01\text{ LE}$ movement is immediately detected and fails assertion. |
| **AC-CUR-07** | `"IDR"` movement | $\Delta = 1$ | $\delta = \text{Decimal}("1") > 0.0001$ | $1\text{ IDR}$ movement is immediately detected and fails assertion. |

---

## 5. Three-Collection Complete Snapshot Protocol

All test assertions verifying financial immutability snapshot `db.finance_transactions`, `db.employee_wages`, and `db.payments` using unbounded asynchronous cursor iteration (`async for doc in collection.find({})`), guaranteeing zero truncation:

```python
async def snapshot_entity_map(collection: AsyncIOMotorCollection) -> dict:
    """
    Completely snapshots an entire collection into an in-memory map by string _id,
    guaranteeing zero truncation regardless of collection size.
    """
    snapshot = {}
    async for doc in collection.find({}):
        snapshot[str(doc["_id"])] = doc
    return snapshot

async def verify_finance_invariants(
    db: AsyncIOMotorDatabase,
    pre_snap_txns: dict,
    pre_snap_wages: dict,
    pre_snap_payments: dict,
    pre_egp_balance,
    pre_idr_balance
):
    """
    Verifies that zero unintended financial records were created, mutated, or deleted
    across all three protected collections: finance_transactions, employee_wages, payments.
    Verifies that cash balances in EGP and IDR remained strictly unchanged.
    """
    # 1. Unbounded post-operation snapshots
    post_snap_txns = await snapshot_entity_map(db.finance_transactions)
    post_snap_wages = await snapshot_entity_map(db.employee_wages)
    post_snap_payments = await snapshot_entity_map(db.payments)

    # 2. Invariant A: db.finance_transactions (Zero additions, zero deletions, zero mutations)
    assert set(post_snap_txns.keys()) == set(pre_snap_txns.keys()), (
        f"Finance transaction IDs mismatch! "
        f"New: {set(post_snap_txns.keys()) - set(pre_snap_txns.keys())}, "
        f"Deleted: {set(pre_snap_txns.keys()) - set(post_snap_txns.keys())}"
    )
    for tid, orig_doc in pre_snap_txns.items():
        assert post_snap_txns[tid] == orig_doc, f"Finance transaction {tid} was mutated during Phase 2 operation!"

    # 3. Invariant B: db.employee_wages (Zero additions, zero deletions, zero mutations)
    assert set(post_snap_wages.keys()) == set(pre_snap_wages.keys()), (
        f"Employee wage IDs mismatch! "
        f"New: {set(post_snap_wages.keys()) - set(pre_snap_wages.keys())}, "
        f"Deleted: {set(pre_snap_wages.keys()) - set(post_snap_wages.keys())}"
    )
    for wid, orig_doc in pre_snap_wages.items():
        assert post_snap_wages[wid] == orig_doc, f"Employee wage record {wid} was mutated during Phase 2 operation!"

    # 4. Invariant C: db.payments (Zero additions, zero deletions, zero mutations)
    assert set(post_snap_payments.keys()) == set(pre_snap_payments.keys()), (
        f"Payment IDs mismatch! "
        f"New: {set(post_snap_payments.keys()) - set(pre_snap_payments.keys())}, "
        f"Deleted: {set(pre_snap_payments.keys()) - set(post_snap_payments.keys())}"
    )
    for pid, orig_doc in pre_snap_payments.items():
        assert post_snap_payments[pid] == orig_doc, f"Payment document {pid} was mutated during Phase 2 operation!"

    # 5. Invariant D: Normalized Decimal Cash Delta Comparison with Explicit Allowlist
    post_egp_norm = normalize_cash_balance(await compute_current_cash_balance("EGP"), "EGP")
    pre_egp_norm = normalize_cash_balance(pre_egp_balance, "EGP")
    delta_egp = abs(post_egp_norm - pre_egp_norm)

    post_idr_norm = normalize_cash_balance(await compute_current_cash_balance("IDR"), "IDR")
    pre_idr_norm = normalize_cash_balance(pre_idr_balance, "IDR")
    delta_idr = abs(post_idr_norm - pre_idr_norm)

    assert delta_egp < Decimal("0.0001"), f"Cash balance in EGP moved during Phase 2 operation! Delta: {delta_egp}"
    assert delta_idr < Decimal("0.0001"), f"Cash balance in IDR moved during Phase 2 operation! Delta: {delta_idr}"
```

---

## 6. Comprehensive Finance & Payment Invariant Delta Matrix

| Operation Scenario | Pre-Existing Ledger State | Executed Action | $\Delta_{\text{new}}$ Txns | $\Delta_{\text{mut}}$ Txns | $\Delta_{\text{del}}$ Txns | $\Delta$ Wages | $\Delta$ Payments | $\Delta_{\text{Cash}}$ (EGP & IDR) |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Successful Per-Unit Accrual** | Arbitrary $N$ txns, $M$ wages, $P$ payments | `verify` accepts 4 units | **0** | **0** | **0** | **0** | **0** | **0.00 LE / 0 IDR** |
| **Successful 100% Lump-Sum Accrual** | Arbitrary $N$ txns, $M$ wages, $P$ payments | `verify` accepts 4/4 units | **0** | **0** | **0** | **0** | **0** | **0.00 LE / 0 IDR** |
| **Rejected Lump-Sum Partial (`HTTP 422`)** | Arbitrary $N$ txns, $M$ wages, $P$ payments | `verify` attempts 3/4 units | **0** | **0** | **0** | **0** | **0** | **0.00 LE / 0 IDR** |
| **Replay / Duplicate Verification** | Arbitrary $N$ txns, $M$ wages, $P$ payments | `verify` replayed | **0** | **0** | **0** | **0** | **0** | **0.00 LE / 0 IDR** |
| **Concurrent Verification Race** | Arbitrary $N$ txns, $M$ wages, $P$ payments | 2 simultaneous `verify` | **0** | **0** | **0** | **0** | **0** | **0.00 LE / 0 IDR** |
| **Cancel Unpaid Completed Assignment** | Arbitrary $N$ txns, $M$ wages, $P$ payments | `cancel` voids obligation | **0** | **0** | **0** | **0** | **0** | **0.00 LE / 0 IDR** |
| **Block Cancel Paid Obligation (`HTTP 400`)**| Arbitrary $N$ txns, $M$ wages, $P$ payments | `cancel` attempted | **0** | **0** | **0** | **0** | **0** | **0.00 LE / 0 IDR** |
| **Transaction Abort / Rollback** | Arbitrary $N$ txns, $M$ wages, $P$ payments | Write fails mid-session | **0** | **0** | **0** | **0** | **0** | **0.00 LE / 0 IDR** |
| **Standalone Crash Recovery** | Arbitrary $N$ txns, $M$ wages, $P$ payments | Reconciler resets `accruing`| **0** | **0** | **0** | **0** | **0** | **0.00 LE / 0 IDR** |

---

## 7. Canonical Transaction Lifecycle & Infrastructure Hardening (Preserved)

### A. Context Manager Lifecycle Pattern [LOCKED ARCHITECTURAL RULE]
All multi-document transaction operations (both probe and production verification) use strictly the Motor asynchronous context manager:
```python
session = await client.start_session()
async with session:
    async with session.start_transaction():
        # Transactional operations executed with session=session
        # Clean block exit -> commit_transaction() called automatically
        # Exception raised -> abort_transaction() called automatically
```
Explicit `commit_transaction()` inside the context manager is strictly prohibited to avoid double-commit conflicts.

### B. Pre-Provisioning with Concurrent Startup Safety [LOCKED ARCHITECTURAL RULE]
Probe collections `_system_probe_assignments` and `_system_probe_obligations` are pre-provisioned during boot outside transactions. Concurrent startup races are handled safely by catching `pymongo.errors.CollectionInvalid`. TTL indexes (`background=True`, `expireAfterSeconds=300`) are verified idempotently.

---

## 8. Monetary Representation: Precision Contract & Boundaries (Preserved)

### A. Two-Tier Precision Contract [LOCKED ARCHITECTURAL RULE]
1. **Calculation Engine (In-Memory)**:
   - All rate lookups, multiplications, additions, and aggregations use Python's `decimal.Decimal` module.
   - Quantized to 2 decimal places using `ROUND_HALF_UP` (`Decimal("0.01")`).
   - Unnormalized binary float arithmetic during calculation is prohibited.
2. **Storage & Serialization**:
   - Quantized `Decimal` values are converted to standard Python `float` strictly at the persistence boundary: `float(quantized_decimal)`.
   - IEEE 754 binary floating-point representation limits are explicitly acknowledged. Exact decimal persistence is not claimed.
   - Comparisons during testing evaluate after canonical normalization within the epsilon boundary ($|\Delta| < 0.0001$).
3. **Zero Migration**: Historical Phase 1 records remain untouched.

---

## 9. Order-Item Identity: Comprehensive Historical Reference Protection (Preserved)

An order item is classified as **PROTECTED** and cannot be deleted, replaced, or have its ID modified in `admin_update_order` if referenced by ANY of the following:
1. Active work assignments (`assigned`, `in_progress`, `ready_for_review`, `accruing`);
2. Completed work assignments (`completed`);
3. Cancelled work assignments (`cancelled`) with historical audit trails;
4. Wage obligations in any status (`accrued`, `paid`, `voided`).

Attempting to delete or replace a protected item raises `HTTP 409 Conflict`.

---

## 10. Canonical Status Registry (Option A Preserved)

1. **`db.work_assignments.status`**:
   - `assigned` (Business)
   - `in_progress` (Business)
   - `ready_for_review` (Business)
   - `accruing` (Internal Processing State; 60s timeout & reconciliation fencing)
   - `completed` (Business; terminal)
   - `cancelled` (Business; terminal)
2. **`db.wage_obligations.status`**:
   - `accrued` (Business)
   - `voided` (Business; terminal)
   - `paid` (Business; Phase 3 deferred; terminal)
3. **Diagnostic Reconciliation Classifications** (Audit findings only):
   - `RECON_CLEAN`, `RECON_STALE_PROCESSING`, `RECON_UNACCRUED_COMPLETION`, `RECON_ORPHAN_OBLIGATION`.

---

## 11. Comprehensive Acceptance Test Matrix

| Test ID | Domain | Preconditions | Action | Expected Entity Result | Expected Finance / Payment Delta |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **TC-MON-01** | Money Calculation | Agreed rate `33.33 LE`, accepted qty `3` | Verify work | Obligation accrued: `99.99 LE` (exact Decimal) | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0, \Delta \text{Pay} = 0$ |
| **TC-MON-02** | Rate Over-Precision | Rate entered as `45.125 LE` | Create wage rule | Rejected with `HTTP 422 Unprocessable Entity` | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0, \Delta \text{Pay} = 0$ |
| **TC-CUR-01** | Currency Allowlist (EGP/IDR) | Input `"EGP"` and `"IDR"` | Normalize balance | Precision `0.01` and `1` selected cleanly | N/A |
| **TC-CUR-02** | Currency Allowlist (Reject) | Input `"EUR"`, `"USD"`, `"EGG"`, `""` | Normalize balance | **Rejected with `ValueError` (`HTTP 422`)** | N/A |
| **TC-LMP-01** | Lump-Sum 100% (B-1) | Target 4 units at 500 LE; accepts 4 | Verify work | Assignment `completed`, obligation `500.00 LE` | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0, \Delta \text{Pay} = 0$ |
| **TC-LMP-02** | Lump-Sum Partial (B-1) | Target 4 units at 500 LE; accepts 3 | Verify work | **Rejected `HTTP 422`**; assignment `ready_for_review` | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0, \Delta \text{Pay} = 0$ |
| **TC-TXN-01** | Fail-Closed Production | Prod mode; mock session failure | Verify work | **Rejected `HTTP 503`**; 0 writes performed | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0, \Delta \text{Pay} = 0$ |
| **TC-TXN-02** | Local Standalone Recovery | Standalone mode; crash in `accruing` | Run reconciler | Reconciler resets assignment to `ready_for_review` | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0, \Delta \text{Pay} = 0$ |
| **TC-ITM-01** | Reorder Item Stability | Order with 2 items | Update order items | Array reordered; `item_id` preserved exactly | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0, \Delta \text{Pay} = 0$ |
| **TC-ITM-02** | Active Item Delete Block | Item has active assignment | Delete item in edit| **Rejected `HTTP 409 Conflict`** | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0, \Delta \text{Pay} = 0$ |
| **TC-ITM-03** | Cancelled Item Delete Block| Item has cancelled assignment | Delete item in edit| **Rejected `HTTP 409 Conflict`** | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0, \Delta \text{Pay} = 0$ |
| **TC-AUT-01** | Non-Owner Self-Approval | Admin worker verifies own work | Verify work | **Rejected `HTTP 403 Forbidden`** | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0, \Delta \text{Pay} = 0$ |
| **TC-AUT-02** | Owner Self-Approval | Owner worker verifies own work | Verify work | Succeeded; `is_owner_bypass: true`; audit logged | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0, \Delta \text{Pay} = 0$ |
| **TC-CON-01** | Concurrency Idempotency | 2 simultaneous verification calls | Verify work | Exactly 1 obligation created; replay returns canonical | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0, \Delta \text{Pay} = 0$ |
| **TC-CAN-01** | Unpaid Obligation Voiding | Completed unpaid assignment | Cancel assignment | Assignment `cancelled`; obligation `voided` | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0, \Delta \text{Pay} = 0$ |
| **TC-CAN-02** | Paid Obligation Cancel Block| Obligation has `paid_amount > 0` | Cancel assignment | **Rejected `HTTP 400 Bad Request`** | $\Delta \text{Cash} = 0, \Delta \text{Finance} = 0, \Delta \text{Pay} = 0$ |
| **TC-FIN-01** | Complete 3-Collection Invariant Check| Pre-existing ledger (txns, wages, payments) | Complete operations| Unbounded snapshot: 0 new, 0 mutated, 0 deleted | **$\Delta \text{Finance} = 0, \Delta \text{Pay} = 0, \Delta \text{Cash} = 0$** |

---

## 12. Explicit Scope Boundaries & Exclusions

The following domains are explicitly excluded from Phase 2:
- [ ] Payout batch disbursement engine (`db.finance_transactions` cash-out write) $\to$ **Deferred to Phase 3**.
- [ ] Worker payout UI modal and printable payroll slips $\to$ **Deferred to Phase 3**.
- [ ] Delivery logistics, driver assignments, and delivery wages $\to$ **Deferred to Future Logistics Phase**.
- [ ] Material consumption stock deduction upon order completion $\to$ **Deferred to Future Inventory Phase**.
- [ ] Automated HPP gross margin costing engine $\to$ **Deferred to Future Accounting Phase**.
- [ ] Worker mobile self-service application $\to$ **Deferred**.

---

## 13. Final Architecture Readiness Verdict

### 🟢 **PASS — READY FOR MASTER BUILD PROMPT**

**Architectural Assessment**:  
All forensic currency validation requirements have been completely and rigorously resolved:
1. `normalize_cash_balance()` strictly enforces an immutable currency allowlist (`SUPPORTED_CURRENCY_PRECISIONS = {"EGP": Decimal("0.01"), "IDR": Decimal("1")}`). Any unsupported or misspelled currency is rejected with `ValueError` / `HTTP 422`.
2. Silent defaulting to IDR has been completely eliminated.
3. The two-tier Decimal quantization pipeline (`ROUND_HALF_UP`) and detectability of real cash movements ($0.01\text{ LE}$ and $1\text{ IDR}$) remain mathematically proven.
4. Complete 3-collection unbounded snapshotting (`finance_transactions`, `employee_wages`, `payments`) and all locked business decisions (B-1, E1, E2) remain binding.

Phase 2 Architecture & Scope Lock v1.2.9 is **100% complete and authoritative**. The system is ready to proceed to the creation of the separate **Phase 2 Master Build Prompt** upon user authorization.
