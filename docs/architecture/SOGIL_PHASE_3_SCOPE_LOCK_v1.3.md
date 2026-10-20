# SOGIL FURNITURE — ARCHITECTURE SCOPE LOCK
## PHASE 3: CUSTOMER OVERPAYMENT CREDIT, REVENUE ATTRIBUTION & HANDOVER RECOGNITION
**Version:** v1.3  
**Status:** AUTHORITATIVE FINAL SPECIFICATION LOCK — AWAITING OWNER AUTHORIZATION FOR PHASE 3.B  
**Target Repository:** `HIDD-Web/Sogil-Furniture`  
**Baseline Git Commit:** `656d7960150e0b47d0295c5c736512308c721ee1`  
**Supersedes:** `SOGIL_PHASE_3_SCOPE_LOCK_v1.2.md`, `SOGIL_PHASE_3_SCOPE_LOCK_v1.1.md`, and `SOGIL_PHASE_3_SCOPE_LOCK_v1.0.md`  
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
   - At the first valid handover, an immutable snapshot (`recognized_revenue_le`, `completed_at`, `completed_by_id`, `completed_by_name`) is persisted on `db.orders`.

3. **Owner Decision B — Strict Rejection of Direct Price Edits After Handover**:
   - Once an order has reached `selesai` and its handover revenue snapshot is established, direct modifications to order-content or financial fields that alter sale value (`total_le`, `subtotal_le`, `delivery_fee_le`, `discount_le`, `items`) are **strictly rejected** by the backend (HTTP 409 Conflict).
   - The original handover snapshot remains permanently immutable.
   - Any legitimate post-handover price corrections, partial returns, or allowances must use an explicit, authorized, auditable **Finance Adjustment** (`db.finance_adjustments`).

4. **Owner Decision A — Separation of Sales Revenue from Non-Sales Income**:
   - The primary dashboard metric **Pendapatan Penjualan** represents **strictly** earned sales revenue from handed-over furniture orders (and authorized revenue adjustments).
   - Arbitrary non-sales income (`type="income"`) must **NOT** be included in *Pendapatan Penjualan*.
   - Non-sales income is reported separately under **Pendapatan Lain-lain** (Other Income).
   - Overall revenue can be summarized as **Total Pendapatan** = $\text{Pendapatan Penjualan} + \text{Pendapatan Lain-lain}$.

5. **Backend-Enforced Safeguards on Cancellation After Handover**:
   - Changing an order that has reached `selesai` to `dibatalkan` requires:
     - Explicit confirmation flag: `confirm_handover_cancellation: True`.
     - Mandatory non-empty cancellation reason: `cancellation_reason` (min 5 characters).
     - Elevated permissions: `role == "owner"` or `permissions.access_finance == True`.
   - The backend records the acting user and timestamp in `order.status_history`.
   - The original `completed_at` and `recognized_revenue_le` are **preserved** as immutable historical facts. Revenue recognized at handover is **not** silently deleted when order status changes.
   - Any genuine financial return or reversal requires an explicit, auditable **Finance Adjustment**.

6. **Accounts Receivable Linked to Immutable Recognized Sale Value**:
   - For handed-over orders (`status == "selesai"`), Accounts Receivable (*Piutang Usaha*) is derived from the immutable recognized sale value plus authorized net adjustments, minus canonical payments and non-cash settlements allocated to the order:
     $$\text{Piutang Usaha} = \max(0, (\text{recognized\_revenue\_le} + \text{net\_adjustments}) - \text{canonical\_paid\_le})$$
   - Receivables never become negative. Excess collections are captured as *Kredit Pelanggan Tersedia*.

7. **Strict Currency Isolation (EGP & IDR)**:
   - Cash transactions use `EGP`; bank/transfer transactions use `IDR`.
   - Raw amounts in different currencies are **never** summed directly without an explicit currency bucket or documented snapshot rate.
   - Financial dashboard reports expose metrics with strict per-currency segregation (`res["EGP"]` and `res["IDR"]`).

8. **Historical Immutability & Backward Compatibility**:
   - Existing historical orders, payments, and `finance_transactions` must **not** be rewritten or backfilled automatically.
   - Legacy records with `type="order_revenue"` continue to be counted as valid actual cash receipts in `_compute_balances()`.
   - Phase 3 rules apply strictly after an explicit activation cutoff (`PHASE_3_ACTIVATION_CUTOFF`).

---

## 2. Analysis of Existing Architecture & Core Discrepancies

### 2.1 Current Production Defect
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
**Consequences**:
1. **Premature Revenue Recognition**: Cash received for unfulfilled custom orders (`diproses`, `siap`) is recognized immediately as revenue.
2. **Revenue Distortion by Overpayments**: Overpayments (e.g. 5,000 LE paid on a 3,000 LE order) inflate sales revenue by the 2,000 LE customer deposit.

### 2.2 Legacy Cash Reporting Dependency
Historically, `db.finance_transactions` used `type="order_revenue"` to represent **actual physical cash receipts**.
- In `_compute_balances()` ([L4683](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/backend/server.py#L4683)), cash balances sum `typ in ("income", "order_revenue")`.
- `AdminFinance.jsx` ([L133, L145](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/frontend/src/pages/admin/AdminFinance.jsx#L133)) treats `type="order_revenue"` as order income.
- **Invariant**: Historical transactions with `type="order_revenue"` must continue to be counted as valid cash receipts so historical cash and bank balances remain 100% accurate without data migrations.

---

## 3. Authoritative Architectural Design Specifications

### 3.1 Revenue Recognition on Handover & Immutable Value Snapshot
1. **Recognition Trigger**:
   - Sales revenue is recognized when `order_status` transitions to `"selesai"` for the first time.
   - At this moment, the server atomically records on `db.orders`:
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
2. **Immutability & Direct Edit Rejection (Owner Decision B)**:
   - If an order has `completed_at` set (or status is `selesai`), any attempt in `PATCH /admin/orders/{id}` to modify `total_le`, `subtotal_le`, `delivery_fee_le`, `discount_le`, or `items` is **REJECTED** with HTTP 409 Conflict:
     `"Pesanan yang telah selesai tidak dapat diubah nilainya secara langsung. Gunakan penyesuaian keuangan resmi (Finance Adjustment)."`
   - Retries or patches to non-financial fields (e.g. `admin_note`) do **not** re-trigger revenue recognition or overwrite `completed_at` / `recognized_revenue_le`.

### 3.2 Post-Handover Status Safeguards (`selesai` $\rightarrow$ `dibatalkan`)
If an admin attempts to change `order_status` from `selesai` to `dibatalkan`:
1. **Backend Validation Rules**:
   - Must provide `confirm_handover_cancellation: True` in payload.
   - Must provide non-empty `cancellation_reason` (min 5 characters).
   - Admin must have `role == "owner"` or `permissions.access_finance == True`.
   - If missing, backend rejects with HTTP 400 or HTTP 403.
2. **Audit & Non-Erasure (Finding M03 Resolution)**:
   - Appends cancellation transition to `order.status_history`.
   - `completed_at` and `recognized_revenue_le` remain preserved on the order document.
   - Recognized revenue from the handover period is **NOT** silently deleted or retroactively removed from prior financial reports.
3. **Explicit Financial Reversal / Return**:
   - If products were returned or revenue must be reversed, an authorized admin records an explicit entry in `db.finance_adjustments` (`type="revenue_reversal"`, `amount=-X.XX`).

### 3.3 Customer Advances vs. Available Customer Credit
- **Uang Muka Pelanggan (Customer Advances)**:
  - Cash received and allocated to an order whose `order_status != "selesai"` and `order_status != "dibatalkan"`.
  - Locked to that specific order as an unearned deposit liability. It cannot be spent on other orders or refunded as unallocated credit unless the order is cancelled.
- **Kredit Pelanggan Tersedia (Available Customer Credit)**:
  - Unallocated customer credit minted from overpayment excess (`allocations` to `unallocated_credit`) or approved goodwill credits.
  - Tracked in `db.customer_credit_events`.
  - Freely spendable on future orders or refundable in cash.
- **Strict Isolation**: No currency amount is ever counted as both an advance and available credit simultaneously.

### 3.4 Non-Cash Customer Credit Settlement
When an order balance is settled using customer credit:
- `payment_method = "customer_credit"`.
- Backend verifies customer owns sufficient `available_credit` via ACID multi-document transaction.
- **Persisted Documents**:
  1. `db.payments`: Created with `payment_method="customer_credit"`, `amount_le=X.XX`.
  2. `db.customer_credit_events`: Created with `event_type="credit_applied"`, `signed_amount=-X.XX`.
  3. `db.finance_transactions`: Internal non-cash contra entry (`type="credit_settlement"`, `account="CUSTOMER_CREDIT"`).
- **Physical Cash Inflow**: **0.00** (Zero physical cash movement).

### 3.5 Customer Credit Refund Accounting
When unallocated customer credit is refunded:
- `POST /admin/customers/{id}/credit-refund`:
  - Validates `amount <= available_credit`.
  - Creates `db.customer_credit_events` (`event_type="credit_refunded"`, `signed_amount=-X.XX`).
  - Creates `db.finance_transactions`:
    - `type="refund"` (or `credit_refund`)
    - `classification="liability_settlement"`
    - `amount=X.XX`, `account="EGP"` (or `"IDR"`)
  - **Financial Result**: Cash outflow decreases physical cash/bank balance; customer credit liability decreases; **Operating expenses / costs are unaffected**.

### 3.6 Signed, Event-Sourced Credit Ledger Model (`db.customer_credit_events`)
- **Balance Invariant**:
  $$\text{Available Credit}(cur) = \sum_{\substack{\text{events in } cur}} \text{signed\_amount}$$
- **Event Signs & Types**:
  - `credit_minted`: `signed_amount > 0`. (Minted from overpayment or goodwill).
  - `credit_applied`: `signed_amount < 0`. (Consumed on order payment).
  - `credit_refunded`: `signed_amount < 0`. (Returned in cash).
  - `credit_reversed`: Signed opposite of original event (`reverses_event_id`).
    - Reversing mint (+500): `signed_amount = -500`.
    - Reversing application (-300): `signed_amount = +300`.
- Reversals require a valid `reverses_event_id`, unique `idempotency_key`, and atomicity.

### 3.7 Historical Activation Cutoff (`PHASE_3_ACTIVATION_CUTOFF`)
- Defined as an immutable ISO timestamp in configuration (e.g. `2026-10-15T00:00:00Z`).
- **Operational Rules**:
  1. **New Orders / Payments Post-Cutoff**: Full Phase 3 rules apply.
  2. **Pre-Cutoff Orders Handed Over Post-Cutoff**: When status changes to `selesai` post-cutoff, `completed_at` is stamped at that exact moment. Revenue is recognized in the post-cutoff period.
  3. **Pre-Cutoff Orders Already "Selesai"**:
     - *With reliable completion timestamp*: Retain existing historical date.
     - *Without reliable timestamp*: Left as legacy; excluded from post-cutoff revenue reports. No fabricated timestamps are generated.
  4. **Ambiguous Legacy DP Orders**:
     - Orders with `payment_status="dp"` and zero recorded payments remain flagged `legacy_dp_unknown=True`. No synthetic payments or credits are generated.

---

## 4. Financial Dashboard Metrics & Reconciliation Architecture

The Finance Dashboard (`AdminFinance.jsx`) maintains the **three primary cards** and exposes **secondary breakdown metrics**, with strict currency segregation:

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
│   Pendapatan Lain-lain   │   Uang Muka Pelanggan    │ Piutang Usaha         │
│   (Other Income)         │   (Customer Advances)    │ (Accounts Receivable) │
├──────────────────────────┴──────────────────────────┴───────────────────────┤
│   Kredit Digunakan & Kredit Dikembalikan (Credit Consumption & Refunds)     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.1 Metric Formulas & Sources of Truth (Per Currency Bucket $cur \in \{\text{EGP}, \text{IDR}\}$)

| Metric | Accounting Classification | Source of Truth | Inclusion / Calculation Formula |
| :--- | :--- | :--- | :--- |
| **Penerimaan Kas Riil** | Cash Flow (Inflow) | `db.finance_transactions` | $\sum \text{amount}$ where `type` $\in$ `["order_payment", "order_revenue", "income"]`, `account == cur`, and `is_void != True`. *(Decoupled from order status; includes legacy `order_revenue`).* |
| **Pendapatan Penjualan** | Earned Sales Revenue | `db.orders` + `db.finance_adjustments` | $\sum \text{recognized\_revenue\_le}$ for orders with `completed_at in period` (in EGP) + $\sum \text{amount}$ for order-related `finance_adjustments` in period. *(Owner Decision A: Excludes non-sales income).* |
| **Pendapatan Lain-lain** | Other Operating Income | `db.finance_transactions` | $\sum \text{amount}$ where `type == "income"`, `classification in ["revenue", None]`, and `date in period`. |
| **Kredit Pelanggan Tersedia** | Current Liability | `db.customer_credit_events` | $\sum \text{signed\_amount}$ across all active credit events for given currency $cur$. |
| **Uang Muka Pelanggan** | Current Liability | `db.orders` + `db.payments` | $\sum \text{canonical\_paid\_le}$ across active orders with `order_status != "selesai"` and `order_status != "dibatalkan"`. |
| **Piutang Usaha** | Current Asset | `db.orders` + `db.finance_adjustments` + `db.payments` | $\sum_{\text{handed over}} \max(0, (\text{recognized\_revenue\_le} + \text{net\_adjustments}) - \text{canonical\_paid\_le})$. *(Finding H02 Resolution).* |
| **Kredit Digunakan** | Contra-Liability Flow | `db.customer_credit_events` | $|\sum \text{signed\_amount}|$ where `event_type == "credit_applied"` in period. |
| **Kredit Dikembalikan** | Liability Extinguishment | `db.customer_credit_events` | $|\sum \text{signed\_amount}|$ where `event_type == "credit_refunded"` in period. |

---

## 5. Strategic Approvals & Readiness

All owner directives and audit findings from Phase 3.A.3 have been fully incorporated:
1. **Finding H01 / Owner Decision A**: Non-sales income is cleanly excluded from *Pendapatan Penjualan* and reported separately as *Pendapatan Lain-lain*.
2. **Finding H02 / Owner Decision B**: Direct price edits after handover are strictly blocked (HTTP 409). Receivables are formulated using the immutable recognized revenue snapshot plus authorized adjustments.
3. **Finding M01**: Pydantic schema extension requirements for handover cancellation safeguards are explicitly mandated.
4. **Finding M02**: Strict per-currency segregation is enforced across all reporting formulas.
5. **Finding M03**: Revenue reporting is permanently tied to durable handover snapshots and explicit adjustments, immune to mutable order status toggles.

**Status**: Scope Lock v1.3 is finalized, locked, and ready for owner authorization.
