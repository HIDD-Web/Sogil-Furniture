# SOGIL FURNITURE — ARCHITECTURE SCOPE LOCK
## PHASE 3: CUSTOMER OVERPAYMENT CREDIT & REVENUE ATTRIBUTION
**Version:** v1.1  
**Status:** DRAFT SPECIFICATION (CORRECTED — REVENUE, CASH & LEDGER INVARIANTS) — AWAITING OWNER APPROVAL  
**Target Repository:** `HIDD-Web/Sogil-Furniture`  
**Baseline Git Commit:** `656d7960150e0b47d0295c5c736512308c721ee1`  
**Supersedes:** `SOGIL_PHASE_3_SCOPE_LOCK_v1.0.md`  
**Date:** 2026-10-10  

---

## 1. Executive Summary & Authoritative Principles

Phase 3 formalizes the accounting, financial reporting, and operational handling of **Customer Overpayments**, **Customer Advances**, **Available Customer Credit**, and **Handover-Based Revenue Recognition** within Sogil Furniture.

### 1.1 Authoritative Business Invariants Locked by Owner
1. **Unchanged Order Status Lifecycle**:
   - `Siap Dikirim/Ambil` (`siap`): Factory production is completed; the custom furniture item is ready for delivery or pickup, but has **not** yet been handed over to or received by the customer.
   - `Selesai` (`selesai`): The product has **actually been handed over** to or received by the customer.
   - *No new status* and *no duplicate handover confirmation buttons* will be introduced. Handover is represented by the existing transition to status `selesai`.
2. **Handover-Based Revenue Recognition**:
   - Sales revenue is recognized **exclusively upon actual handover** (transition to `selesai`), backed by adequate audit evidence.
   - Customer payments, down payments, production progress, and transition to `siap` do **NOT** recognize sales revenue.
   - Revenue earned on handover is based on the **full recognized sale value** of the order (`order.total_le`), **not** capped by the cash amount collected.
3. **Strict Separation of Economic Realities**:
   - **Penerimaan Kas Riil (Actual Cash / Bank Receipts)**: Real fiat currency physically received into cash registers or bank accounts.
   - **Pendapatan Penjualan (Earned Sales Revenue)**: Total recognized sales value upon actual customer handover (`selesai`).
   - **Uang Muka Pelanggan (Customer Advances / Unfulfilled Deposits)**: Payments received and allocated to unfulfilled orders (`order_status != "selesai"`). Held as unearned revenue liability.
   - **Kredit Pelanggan Tersedia (Available Customer Credit Liability)**: Unallocated, free customer credit (from overpayments or approved credits) held as a general balance sheet liability, available for future orders or cash refund.
   - **Piutang Usaha (Outstanding Customer Receivables)**: Delivered products (`selesai`) where order total exceeds collected payments.
   - **Pengembalian Dana (Refunds & Reversals)**: Cash outflows or auditable ledger reversals returning liability.
4. **Historical Data Immutability**:
   - Existing historical orders, payments, and `finance_transactions` must **not** be rewritten or backfilled automatically. Phase 3 rules apply strictly after an explicit activation cutoff date.
5. **Canonical Payment & Transaction Integrity**:
   - Payment idempotency, ACID multi-document transaction safety with fail-closed behavior, currency isolation (EGP vs. IDR), and complete audit trails are strictly preserved.

---

## 2. Analysis of Existing Architecture & Core Discrepancies

### 2.1 Current Overpayment & Revenue Distortion
In `backend/server.py` ([L2404–L2425](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/backend/server.py#L2404-L2425)), order payment creation unconditionally inserts into `db.finance_transactions`:
```python
"type": "order_revenue",
"category": "Penjualan",
"amount": conv["primary_amount"] # Full cash received, including overpayment excess
```
In `_stats_for(s, e)` ([L4918–L4941](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/backend/server.py#L4918-L4941)):
```python
if typ == "order_revenue":
    res[cur]["revenue"] += amt
```
**Two major accounting defects occur**:
1. **Revenue Recognized Prematurely**: Cash received on unfulfilled orders (`diproses`, `siap`) is immediately added to `revenue`, violating handover-based recognition.
2. **Revenue Overstated by Excess Deposit**: If customer pays `5,000 LE` on a `3,000 LE` order, `revenue` increases by `5,000 LE`, overstating sales revenue and profit by the `2,000 LE` customer deposit.

### 2.2 Legacy Cash Reporting Dependency
Historically, `db.finance_transactions` used `type="order_revenue"` to represent **actual physical cash receipts from orders**.
- In `_compute_balances()` ([L4683](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/backend/server.py#L4683)), cash balances sum `typ in ("income", "order_revenue")`.
- In `AdminFinance.jsx` ([L133, L145](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/frontend/src/pages/admin/AdminFinance.jsx#L133)), transaction filters and editing modal treat `type="order_revenue"` as order income.
- **Critical Requirement**: Any new transaction model must remain backward-compatible with historical `order_revenue` records so historical bank and cash calculations remain 100% accurate without data migrations.

---

## 3. Required Architectural Design Corrections

### 3.1 Correction A: Revenue Recognition Model
- **Handover Rule**: When an order transitions to `order_status == "selesai"`, revenue is recognized at the **recognized sale value** (`order.total_le`), regardless of whether the order is fully paid, partially paid, or unpaid.
- **Reporting Period Attribution**:
  - Revenue is attributed to the financial period matching the **Handover Event Date** (`order.completed_at`), **not** the payment dates and not the order creation date.
- **Outstanding Receivables Tracking**:
  - If `order.total_le > paid_amount_le`, the difference is recognized as `Piutang Usaha` (Accounts Receivable).
  - Formula: $\text{Receivable} = \max(0, \text{order.total\_le} - \text{canonical\_paid\_le})$.
- **No Double-Counting**: Re-calculating stats, patching order notes, or updating unrelated fields does not re-trigger revenue recognition. Recognition is derived idempotently from the order's immutable handover timestamp and total value.

### 3.2 Correction B: Legacy Cash & Bank Balance Reporting
To preserve historical cash balances without touching existing records:
- **Cash Inflow Invariant**:
  $$\text{Real Cash Inflow} = \sum \text{finance\_transactions}(\text{type} \in [\text{"order_revenue"}, \text{"order_payment"}, \text{"income"}], \text{is\_void} \neq \text{True})$$
- Historical transactions with `type="order_revenue"` continue to be treated as valid physical cash receipts.
- New post-activation cash receipts will use `type="order_payment"` (or continue using `type="order_revenue"` with explicit `cash_flow: true` classification and split deposit accounting).
- **Zero Cash Disruption**: `_compute_balances()` will include `order_payment` and `order_revenue`, ensuring seamless continuity.

### 3.3 Correction C: Refund Accounting
Refunding unallocated customer credit is **NOT an operating expense**:
- It is a **balance sheet settlement**: Cash/Bank decreases, and Customer Credit Liability decreases.
- **PERSISTED RECORDS**:
  1. `db.customer_credit_events`: `event_type="credit_refunded"`, `amount_le=-X.XX`.
  2. `db.finance_transactions`:
     - `type="refund"` (or `type="credit_refund"`)
     - `classification="liability_settlement"` (explicitly excluded from operating costs/expenses)
     - `amount=X.XX`, `account="EGP"` (or `"IDR"`)
     - Physical cash leaves the account.
- **Idempotency & Guard**: Requires `idempotency_key` and verifies `available_credit >= refund_amount`.

### 3.4 Correction D: Credit Settlement vs. Actual Cash Payment
When a customer settles an order balance using available customer credit:
- **Payment Method**: `payment_method="customer_credit"`.
- **Cash Movement**: **0 LE** (Zero physical cash inflow).
- **Persisted Records**:
  1. `db.payments`: Created with `payment_method="customer_credit"`, `amount_le=X.XX`.
  2. `db.customer_credit_events`: Created with `event_type="credit_applied"`, `amount_le=-X.XX`, referencing `target_order_id`.
  3. `db.finance_transactions`: Internal non-cash contra entry (`type="credit_settlement"`, `account="CUSTOMER_CREDIT"`). Excluded from physical cash inflow calculations.
- **Handover Outcome**: When the order reaches `selesai`, revenue of `order.total_le` is recognized. The credit settlement already fulfilled the customer obligation without duplicate cash recording.

### 3.5 Correction E: Customer Advances vs. Available Credit
We strictly distinguish:
1. **Uang Muka Pelanggan (Customer Advances)**:
   - Cash received and allocated to `product` or `shipping` for an order whose `order_status != "selesai"`.
   - Cannot be spent on other orders or refunded as unallocated credit unless an explicit order cancellation/credit transfer is performed.
2. **Kredit Pelanggan Tersedia (Available Customer Credit)**:
   - Cash received in excess of order total (allocated to `unallocated_credit`), or credits minted via goodwill/refunds.
   - Available to be applied to any order or refunded in cash.
3. **Pendapatan Penjualan (Earned Revenue)**:
   - Only recognized upon handover (`selesai`).
4. **Piutang Usaha (Accounts Receivable)**:
   - For `selesai` orders: $\max(0, \text{total\_le} - \text{paid\_le})$.

### 3.6 Correction F: Handover Audit and Revenue Reversals
- **Audit Fields on `db.orders`**:
  - `completed_at`: Immutable timestamp of first transition to `selesai`.
  - `completed_by_id`, `completed_by_name`: Admin user performing handover.
  - `status_history`: Embedded array logging every status change with timestamp, previous status, next status, and actor.
- **Accidental Status Reversion vs. Real Cancellation**:
  - If an admin erroneously changes status from `selesai` back to `diproses`, this is recorded in `status_history`.
  - **Financial Principle**: Do not silently erase revenue history.
  - If a genuine cancellation occurs after delivery, an explicit **Return / Cancellation Event** (`db.finance_adjustments` or `status="dibatalkan"` with cancellation audit) must be recorded, creating an auditable contra-revenue adjustment entry.
  - Repeated saves of `selesai` never duplicate revenue (governed by idempotent `completed_at` and order ID uniqueness).

### 3.7 Correction G: Historical Activation Cutoff
- **Phase 3 Activation Timestamp**: `PHASE_3_ACTIVATION_CUTOFF` (ISO timestamp).
- **Rule 1 (Historical Orders Completed Before Cutoff)**:
  - If an order was marked `selesai` before the cutoff and lacks `completed_at`, it remains legacy. Revenue in historical stats can be derived from existing transaction records or order date. No historical records are rewritten.
- **Rule 2 (Pre-Cutoff Orders Handed Over After Cutoff)**:
  - When a pre-existing order transitions to `selesai` *after* the cutoff, `completed_at` is stamped with the actual transition time. Revenue is recognized in the post-cutoff period.
- **Rule 3 (New Payments on Existing Orders)**:
  - Subject to Phase 3 rules (overpayments split into available credit).
- **Rule 4 (No Silent Policies)**:
  - Any historical order with ambiguous legacy DP status is flagged `legacy_dp_unknown=True` and excluded from automated credit minting.

### 3.8 Correction H: Signed, Auditable Credit Ledger Model
`db.customer_credit_events` uses an immutable, event-sourced signed ledger:
- **Balance Calculation**:
  $$\text{Available Credit} = \sum_{\text{events}} \text{signed\_amount\_le}$$
- **Event Types & Signs**:
  - `credit_minted`: Positive (`+amount_le`). Minted from overpayment or admin grant.
  - `credit_applied`: Negative (`-amount_le`). Applied to settle an order.
  - `credit_refunded`: Negative (`-amount_le`). Returned to customer via cash/bank.
  - `credit_reversed`: Signed opposite of the target event. Specifically references `source_event_id`.
    - E.g., Reversing a `credit_minted` (+500) creates `credit_reversed` (-500) with `reverses_event_id`.
    - E.g., Reversing a `credit_applied` (-300) due to order cancellation creates `credit_reversed` (+300) with `reverses_event_id`.
- **Integrity Constraints**:
  - Unique sparse `idempotency_key`.
  - Atomically verified non-negative balance constraint within MongoDB ACID transactions.

---

## 4. Financial Metric Formulas & Dashboard Architecture

| Metric | Accounting Type | Calculation Formula |
| :--- | :--- | :--- |
| **Penerimaan Kas Riil** | Cash Flow (Inflow) | $\sum \text{finance\_transactions}(\text{type} \in [\text{"order_payment"}, \text{"order_revenue"}, \text{"income"}], \text{valid})$ |
| **Pengeluaran Kas Riil** | Cash Flow (Outflow) | $\sum \text{finance\_transactions}(\text{type} \in [\text{"expense"}, \text{"refund"}, \text{"credit_refund"}], \text{valid})$ |
| **Pendapatan Penjualan** | Earned Sales Revenue | $\sum_{\text{orders with completed\_at in period}} \text{order.total\_le} + \sum \text{finance\_transactions}(\text{type}="income", \text{valid})$ |
| **Uang Muka Pelanggan** | Current Liability | $\sum_{\text{orders with status} \neq \text{"selesai"}} \text{canonical\_paid\_le}$ |
| **Kredit Pelanggan Tersedia**| Current Liability | $\sum \text{customer\_credit\_events.signed\_amount\_le}$ |
| **Piutang Usaha** | Current Asset | $\sum_{\text{orders with status} = \text{"selesai"}} \max(0, \text{order.total\_le} - \text{canonical\_paid\_le})$ |

---

## 5. Strategic Approvals Required from Owner

1. **Explicit Cancellation / Revenue Adjustment Approval Workflow**:
   - Confirm whether reversing an order from `selesai` to `dibatalkan` requires a dedicated owner/finance authorization prompt in the admin UI.
2. **Dashboard Card Presentation**:
   - Confirm whether the Finance Dashboard should display 3 primary KPI cards (*Penerimaan Kas*, *Pendapatan Penjualan*, *Kredit Pelanggan Tersedia*) with expandable sub-breakdowns for *Uang Muka* and *Piutang*.
