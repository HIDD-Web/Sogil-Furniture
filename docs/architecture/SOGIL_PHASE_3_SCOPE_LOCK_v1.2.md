# SOGIL FURNITURE — ARCHITECTURE SCOPE LOCK
## PHASE 3: CUSTOMER OVERPAYMENT CREDIT, REVENUE ATTRIBUTION & HANDOVER RECOGNITION
**Version:** v1.2  
**Status:** AUTHORITATIVE FINAL SPECIFICATION LOCK — AWAITING OWNER AUTHORIZATION FOR PHASE 3.B  
**Target Repository:** `HIDD-Web/Sogil-Furniture`  
**Baseline Git Commit:** `656d7960150e0b47d0295c5c736512308c721ee1`  
**Supersedes:** `SOGIL_PHASE_3_SCOPE_LOCK_v1.1.md` and `SOGIL_PHASE_3_SCOPE_LOCK_v1.0.md`  
**Date:** 2026-10-10  

---

## 1. Executive Summary & Authoritative Principles

Phase 3 establishes accounting correctness, financial auditability, and data integrity for **Customer Overpayments**, **Customer Advances**, **Available Customer Credit**, **Accounts Receivable**, and **Handover-Based Revenue Recognition** across the Sogil Furniture platform.

### 1.1 Authoritative Business Invariants Locked by Owner
1. **Unchanged Order Status Lifecycle**:
   - `Siap Dikirim/Ambil` (`siap`): Factory production is completed; the custom furniture item is ready for delivery or pickup, but has **not** yet been handed over to or received by the customer.
   - `Selesai` (`selesai`): The product has **actually been handed over** to or received by the customer.
   - *No new order status* and *no duplicate handover confirmation buttons* will be introduced. Customer handover is represented exclusively by the existing transition to status `selesai`.
2. **Handover-Based Revenue Recognition & Immutable Snapshot**:
   - Sales revenue is recognized **exclusively upon actual handover** (transition to `selesai`), backed by immutable audit evidence.
   - Revenue recognized upon handover equals the **full recognized sale value** of the order snapshot at the moment of handover (`order.recognized_revenue_le`), **not** capped by the cash amount collected.
   - Payments received before handover are treated as **Uang Muka Pelanggan** (Customer Advances / Deposit Liability), **never** recognized sales revenue.
   - At the first valid handover, an immutable snapshot (`recognized_revenue_le`, `completed_at`, `completed_by_id`, `completed_by_name`) is persisted on `db.orders`. Subsequent edits to `order.total_le` or line items do **NOT** silently rewrite historical recognized revenue.
3. **Backend-Enforced Safeguards on Cancellation After Handover**:
   - Changing an order that has reached `selesai` to `dibatalkan` is strictly protected:
     - Requires explicit confirmation flag (`confirm_handover_cancellation: True`).
     - Requires a mandatory non-empty cancellation reason (`cancellation_reason`).
     - Requires elevated role permissions (`owner` or admin with `access_finance`).
     - Records the acting user's identity and timestamp in `status_history`.
     - Preserves the original `completed_at` and `recognized_revenue_le` historical audit trail.
     - Does **NOT** silently erase recognized revenue.
     - Any genuine financial reversal or product return requires an explicit, auditable **Finance Adjustment** entry (`db.finance_adjustments`), preventing duplicate adjustments.
4. **Strict Separation of Economic Concepts**:
   - **Penerimaan Kas Riil (Actual Cash / Bank Receipts)**: Real fiat currency physically received into cash registers or bank accounts.
   - **Pendapatan Penjualan (Earned Sales Revenue)**: Total recognized sales value upon actual customer handover (`selesai`).
   - **Uang Muka Pelanggan (Customer Advances / Unearned Deposits)**: Payments received and allocated to unfulfilled orders (`order_status != "selesai"`). Held as unearned revenue liability.
   - **Kredit Pelanggan Tersedia (Available Customer Credit Liability)**: Unallocated, free customer credit (from overpayments or approved credits) held as a general balance sheet liability, available for future orders or cash refund.
   - **Piutang Usaha (Outstanding Customer Receivables)**: Delivered products (`selesai`) where recognized sale value exceeds collected payments.
   - **Kredit Digunakan (Credit Applied)**: Non-cash internal balance settlement against order obligations.
   - **Kredit Dikembalikan (Customer Credit Refunded)**: Actual cash outflows returning customer credit liability without inflating operating expenses.
5. **Historical Immutability & Backward Compatibility**:
   - Existing historical orders, payments, and `finance_transactions` must **not** be rewritten or backfilled automatically. Legacy records with `type="order_revenue"` continue to be counted as valid cash receipts.
   - Phase 3 rules apply strictly after an explicit activation cutoff (`PHASE_3_ACTIVATION_CUTOFF`).
6. **Canonical Payment & Transaction Integrity**:
   - `db.payments` remains the single canonical source of truth for order payments.
   - Payment idempotency, ACID multi-document transaction safety with fail-closed behavior, currency isolation (EGP vs. IDR), and complete audit trails are strictly preserved.

---

## 2. Analysis of Existing Architecture & Core Discrepancies

### 2.1 Current Overpayment & Premature Revenue Recognition Defect
In `backend/server.py` ([L2404–L2425](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/backend/server.py#L2404-L2425)), order payment creation unconditionally inserts into `db.finance_transactions`:
```python
"type": "order_revenue",
"category": "Penjualan",
"amount": conv["primary_amount"] # Full cash received, including excess
```
In `_stats_for(s, e)` ([L4918–L4941](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/backend/server.py#L4918-L4941)):
```python
if typ == "order_revenue":
    res[cur]["revenue"] += amt
```
**Two major accounting distortions exist**:
1. **Premature Revenue Recognition**: Cash received on unfulfilled orders (`diproses`, `siap`) is immediately added to `revenue`, violating handover-based recognition.
2. **Revenue Overstatement by Overpayment**: If a customer pays `5,000 LE` on a `3,000 LE` order, `revenue` increases by `5,000 LE`, overstating sales revenue and profit by the `2,000 LE` customer deposit.

### 2.2 Legacy Cash Reporting Dependency
Historically, `db.finance_transactions` used `type="order_revenue"` to represent **actual physical cash receipts from orders**.
- In `_compute_balances()` ([L4683](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/backend/server.py#L4683)), cash balances sum `typ in ("income", "order_revenue")`.
- In `AdminFinance.jsx` ([L133, L145](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/frontend/src/pages/admin/AdminFinance.jsx#L133)), transaction filters and editing modal treat `type="order_revenue"` as order income.
- **Invariant**: Historical transactions with `type="order_revenue"` must continue to be counted as valid physical cash receipts so historical cash and bank balances remain 100% accurate without rewriting historical documents.

---

## 3. Authoritative Architectural Design Specifications

### 3.1 Revenue Recognition on Handover & Immutable Value Snapshot
1. **Recognition Trigger**:
   - Sales revenue is recognized when `order_status` transitions to `"selesai"` for the first time.
   - At this moment, the server atomically records:
     - `completed_at`: ISO-8601 UTC timestamp of first handover.
     - `completed_by_id`, `completed_by_name`: Admin identity recording the handover.
     - `recognized_revenue_le`: Float snapshot of `order.total_le` at that exact moment.
     - Appends entry to `order.status_history`:
       ```json
       {
         "from_status": "siap",
         "to_status": "selesai",
         "changed_at": "2026-10-10T14:30:00Z",
         "changed_by_id": "admin_oid",
         "changed_by_name": "Finance Admin",
         "reason": null
       }
       ```
2. **Immutability of Recognized Value**:
   - If an admin subsequently edits `order.total_le` (e.g. changing delivery fee or line items), `order.total_le` updates for billing/receivable purposes, but `order.recognized_revenue_le` remains untouched.
   - Any legitimate post-handover revenue adjustment requires an explicit **Finance Adjustment** entry.
3. **Period Attribution**:
   - Recognized sales revenue is attributed to the period matching `completed_at`, completely decoupled from when payments were collected.
4. **Receivables Calculation**:
   - For an order with status `"selesai"`:
     $$\text{Piutang Usaha} = \max(0, \text{order.total\_le} - \text{canonical\_paid\_le})$$

### 3.2 Post-Handover Status Protection (`selesai` $\rightarrow$ `dibatalkan`)
If an admin attempts to change `order_status` from `selesai` to `dibatalkan`:
1. **Backend Validation Rules**:
   - Must provide `confirm_handover_cancellation: True` in payload.
   - Must provide non-empty `cancellation_reason` (min 5 characters).
   - Admin must have `role == "owner"` or `permissions.access_finance == True`.
   - If missing, backend rejects with HTTP 400 (`"Pembatalan pesanan yang telah selesai memerlukan konfirmasi eksplisit dan alasan pembatalan."`) or HTTP 403.
2. **Audit & Non-Erasure**:
   - Appends cancellation transition to `order.status_history` with actor, timestamp, and reason.
   - `completed_at` and `recognized_revenue_le` are **preserved** as historical facts.
   - Does **not** automatically delete or zero out recognized revenue in historical period reports.
3. **Explicit Financial Reversal / Return**:
   - If the goods were physically returned and revenue must be reversed, an explicit adjustment is created via `POST /admin/finance/adjustments`:
     - Creates `db.finance_adjustments` record (`type="revenue_reversal"`, `amount=-X.XX`).
     - Links to `order_id` with `idempotency_key`.

### 3.3 Customer Advances vs. Available Customer Credit
- **Uang Muka Pelanggan (Customer Advances)**:
  - Canonical payments tied to an order whose `order_status != "selesai"`.
  - Allocated to `product` or `shipping`.
  - Held as an unearned deposit liability. It is locked to that specific order and cannot be applied elsewhere or refunded as unallocated credit unless the order is formally cancelled.
- **Kredit Pelanggan Tersedia (Available Customer Credit)**:
  - Freely spendable customer liability minted from overpayment excess (allocations to `unallocated_credit`) or approved goodwill credits.
  - Tracked in `db.customer_credit_events`.
  - Can be applied to settle any order for that customer or refunded in cash.
- **Strict Isolation**: No dollar amount is ever counted in both categories simultaneously.

### 3.4 Customer Credit Settlement (Non-Cash Movement)
When an order balance is settled using customer credit:
- Payload specifies `payment_method = "customer_credit"`.
- Backend verifies customer owns sufficient `available_credit` via ACID transaction.
- **Persisted Documents**:
  1. `db.payments`: Created with `payment_method="customer_credit"`, `amount_le=X.XX`.
  2. `db.customer_credit_events`: Created with `event_type="credit_applied"`, `signed_amount=-X.XX`.
  3. `db.finance_transactions`: Internal non-cash entry (`type="credit_settlement"`, `account="CUSTOMER_CREDIT"`).
- **Physical Cash Inflow**: **0.00** (Zero physical cash movement).

### 3.5 Customer Credit Refund Accounting
When unallocated customer credit is returned to the customer:
- `POST /admin/customers/{id}/credit-refund`:
  - Validates `amount <= available_credit`.
  - Atomically creates `db.customer_credit_events` (`event_type="credit_refunded"`, `signed_amount=-X.XX`).
  - Creates `db.finance_transactions`:
    - `type="refund"` (or `credit_refund`)
    - `classification="liability_settlement"`
    - `amount=X.XX`, `account="EGP"` (or `"IDR"`)
  - **Financial Result**: Cash outflow decreases physical cash/bank balance; customer credit liability decreases; **Operating expenses / costs are unaffected**.

### 3.6 Signed, Event-Sourced Credit Ledger Model (`db.customer_credit_events`)
- **Balance Invariant**:
  $$\text{Available Credit} = \sum_{\text{events}} \text{signed\_amount}$$
- **Event Signs & Types**:
  - `credit_minted`: `signed_amount > 0`. (Minted from overpayment or goodwill).
  - `credit_applied`: `signed_amount < 0`. (Consumed on order payment).
  - `credit_refunded`: `signed_amount < 0`. (Returned in cash).
  - `credit_reversed`: Signed opposite of original event.
    - Reversing mint (+500): `signed_amount = -500`, references `reverses_event_id`.
    - Reversing application (-300): `signed_amount = +300`, references `reverses_event_id`.
- Reversal prevents duplicate execution via unique idempotency key and state tracking.

### 3.7 Historical Activation Cutoff (`PHASE_3_ACTIVATION_CUTOFF`)
- Defined as an immutable ISO timestamp in configuration (e.g. `2026-10-15T00:00:00Z`).
- **Operational Rules**:
  1. **New Orders / Payments Post-Cutoff**: Full Phase 3 rules (overpayments split, revenue on handover snapshot).
  2. **Pre-Cutoff Orders Handed Over Post-Cutoff**: When status changes to `selesai` after cutoff, `completed_at` is stamped at that exact moment. Revenue is recognized in the post-cutoff period.
  3. **Pre-Cutoff Orders Already "Selesai"**:
     - *With reliable completion timestamp*: Retain existing historical date.
     - *Without reliable timestamp*: Left as legacy; excluded from post-cutoff revenue reports. No fabricated timestamps are generated.
  4. **Ambiguous Legacy DP Orders**:
     - Orders with `payment_status="dp"` and zero recorded payments remain flagged `legacy_dp_unknown=True`. No synthetic payments or credits are generated.

---

## 4. Financial Dashboard Metrics & Reconciliation Architecture

The Finance Dashboard (`AdminFinance.jsx`) maintains the **three primary cards** and exposes **secondary breakdown metrics**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PRIMARY DASHBOARD METRICS                         │
├──────────────────────────┬──────────────────────────┬───────────────────────┤
│   Penerimaan Kas Riil    │   Pendapatan Penjualan   │ Kredit Pelanggan      │
│   (Real Cash Inflow)     │   (Earned Sales Revenue) │ Tersedia (Liability)  │
└──────────────────────────┴──────────────────────────┴───────────────────────┘
┌─────────────────────────────────────────────────────────────────────────────┐
│                           SECONDARY BREAKDOWN METRICS                       │
├──────────────────────────┬──────────────────────────┬───────────────────────┤
│   Uang Muka Pelanggan    │   Piutang Usaha          │ Kredit Digunakan &    │
│   (Customer Advances)    │   (Accounts Receivable)  │ Kredit Dikembalikan   │
└──────────────────────────┴──────────────────────────┴───────────────────────┘
```

### 4.1 Metric Formulas & Sources of Truth

| Metric | Source of Truth | Inclusion / Calculation Formula |
| :--- | :--- | :--- |
| **Penerimaan Kas Riil** | `db.finance_transactions` | $\sum \text{amount}$ where `type` $\in$ `["order_payment", "order_revenue", "income"]`, `account` $\in$ `["EGP", "IDR"]`, and `is_void != True`. *(Decoupled from order status).* |
| **Pendapatan Penjualan** | `db.orders` + `db.finance_transactions` | $\sum \text{recognized\_revenue\_le}$ for orders with `completed_at` in period + $\sum \text{amount}$ for `finance_transactions` with `type="income"` in period. |
| **Kredit Pelanggan Tersedia** | `db.customer_credit_events` | $\sum \text{signed\_amount}$ across all active credit events for given currency. |
| **Uang Muka Pelanggan** | `db.orders` + `db.payments` | $\sum \text{canonical\_paid\_le}$ across active orders with `order_status != "selesai"` and `order_status != "dibatalkan"`. |
| **Piutang Usaha** | `db.orders` | $\sum \max(0, \text{order.total\_le} - \text{canonical\_paid\_le})$ across orders with `order_status == "selesai"`. |
| **Kredit Digunakan** | `db.customer_credit_events` | $|\sum \text{signed\_amount}|$ where `event_type == "credit_applied"` in period. |
| **Kredit Dikembalikan** | `db.customer_credit_events` | $|\sum \text{signed\_amount}|$ where `event_type == "credit_refunded"` in period. |

---

## 5. Strategic Approvals & Readiness

All owner directives have been fully integrated:
1. Cancellation after handover requires backend authorization, explicit confirmation, mandatory reason, and audit logging.
2. Revenue is recognized at handover, snapshot immutably, and decoupled from cash.
3. Dashboard separates the three primary metrics from advances, receivables, and settlements.
4. Historical legacy cash and orders remain completely preserved.

**Status**: Scope Lock v1.2 is finalized and locked. Ready for owner authorization.
