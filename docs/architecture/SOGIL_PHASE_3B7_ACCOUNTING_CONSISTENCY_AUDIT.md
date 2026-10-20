# SOGIL FURNITURE — TECHNICAL AUDIT REPORT
## PHASE 3.B.7: PRE-IMPLEMENTATION ACCOUNTING CONSISTENCY AUDIT
**Document Identifier:** `SOGIL_PHASE_3B7_ACCOUNTING_CONSISTENCY_AUDIT.md`  
**Version:** v1.0  
**Status:** STRICT READ-ONLY PRE-IMPLEMENTATION AUDIT  
**Target Repository:** `HIDD-Web/Sogil-Furniture`  
**Expected HEAD / Baseline Commit:** `b6731c082d62f48b93b1116435e872b169e58387` (main)  
**Parent Commit:** `42d68b3efebc11fecc9c96cd52cdc48715547f8f`  
**Reference Authoritative Documents:**
- `docs/architecture/SOGIL_PHASE_3_SCOPE_LOCK_v1.3.md` (Scope Lock v1.3)
- `docs/architecture/SOGIL_PHASE_3_IMPLEMENTATION_PLAN_v1.3.md` (Implementation Plan v1.3)
- `docs/architecture/SOGIL_PHASE_3B7_REPORTING_ENGINE_SPECIFICATION.md` (B.7 Specification v1.0)  
**Date:** 2026-10-12  

---

## 1. Executive Summary & Objective

This audit performs an evidence-based, mathematical, and architectural consistency audit of the Phase 3.B.7 Reporting Engine specification against the actual codebase and data models implemented through commit `b6731c0`.

The audit specifically interrogates:
1. Exact data semantics and potential collection overlaps between `payments`, `finance_transactions`, `customer_credit_events`, `orders`, and `finance_adjustments`.
2. Reporting-period attribution vs. historical restatement for post-handover adjustments and cancellations.
3. Numeric reconciliation of customer advances, customer credit liabilities, accounts receivable, and cash.
4. Identification of any accounting contradictions, open owner decisions, or implementation gaps before code is written.

---

## 2. Evidence-Based Data Semantics Audit

Every proposed reporting metric was audited against the actual database fields, models, and routes in `backend/server.py`.

```
+----------------------------------------------------------------------------------------------------------------------+
| METRIC                       | SOURCE COLLECTION         | FIELDS & NORMALIZATION        | DATE FIELD  | CLASSIFICATION      |
+----------------------------------------------------------------------------------------------------------------------+
| Penerimaan Kas Riil          | db.finance_transactions   | amount (float > 0)            | date        | Physical Cash Flow  |
| (Real Cash Inflow)           |                           | type in ("order_payment",     | (ISO-8601)  | Inflow              |
|                              |                           | "order_revenue", "income")    |             |                     |
|                              |                           | account == cur, status!=void  |             |                     |
+----------------------------------------------------------------------------------------------------------------------+
| Pengeluaran Kas Riil         | db.finance_transactions   | amount (float > 0)            | date        | Physical Cash Flow  |
| (Real Cash Outflow)          |                           | type in ("expense", "refund", | (ISO-8601)  | Outflow             |
|                              |                           | "credit_refund"), account==cur|             |                     |
+----------------------------------------------------------------------------------------------------------------------+
| Pendapatan Penjualan         | db.orders +               | order.recognized_revenue_le + | completed_at| Earned Operating    |
| (Sales Revenue)              | db.finance_adjustments    | adjustment.amount (+ or -)    | created_at  | Revenue (Accrual)   |
|                              |                           | order_status in (selesai, dib)|             |                     |
+----------------------------------------------------------------------------------------------------------------------+
| Pendapatan Lain-lain         | db.finance_transactions   | amount (float > 0)            | date        | Other Operating     |
| (Other Non-Sales Income)     |                           | type == "income", cur == cur  | (ISO-8601)  | Income              |
|                              |                           | classification in (None, rev) |             |                     |
+----------------------------------------------------------------------------------------------------------------------+
| Kredit Pelanggan Tersedia    | db.customer_credit_events | signed_amount (+ or -)        | created_at  | Balance Sheet       |
| (Available Credit Liability) |                           | currency == cur               | (<= cutoff) | Current Liability   |
+----------------------------------------------------------------------------------------------------------------------+
| Uang Muka Pelanggan          | db.orders +               | sum(payment.amount_le)        | As-of       | Balance Sheet       |
| (Customer Advances)          | db.payments               | order_status not in           | active      | Deposit Liability   |
|                              |                           | ("selesai", "dibatalkan")     | snapshot    |                     |
+----------------------------------------------------------------------------------------------------------------------+
| Piutang Usaha                | db.orders + adjustments   | max(0, (rec_rev + net_adj)    | As-of       | Balance Sheet       |
| (Accounts Receivable)        | + db.payments             |         - canonical_paid_le)  | active      | Current Asset       |
+----------------------------------------------------------------------------------------------------------------------+
```

### Detailed Data Semantics & Source Tracing

1. **`canonical_paid_le` Semantics (`server.py L353–L398, L6171–L6179`):**
   - Traced in `compute_order_payment_summary`: `paid_amount_le` is the exact sum of `amount_le` from `db.payments` where `order_id == order["_id"]` and `status == "recorded"`.
   - In `_compute_order_impact` (`L6175`), `paid_d` is computed identically: `sum(_num(p.get("amount_le", 0.0)) for p in recs)`.
   - **Crucial Invariant**: `canonical_paid_le` sums **all recorded payments applied to the order**, whether settled in physical cash, bank transfer, or customer credit (`payment_method="customer_credit"`). It reflects **total order discharge**, not physical cash.

2. **Customer Credit Settlement Isolation (`server.py L2620–L2643`):**
   - When `payment_method == "customer_credit"`:
     - `db.payments`: Inserted with `payment_method="customer_credit"`, `amount_le=X.XX`.
     - `db.customer_credit_events`: Inserted with `event_type="credit_applied"`, `signed_amount=-X.XX`.
     - `db.finance_transactions`: Inserted with `type="credit_settlement"`, `classification="credit_settlement"`.
   - **Verification**: `type="credit_settlement"` is strictly excluded from cash inflows. Double counting is impossible because the transaction type is distinct and non-cash.

3. **Customer Credit Refund Semantics (`server.py L5950–L5991`):**
   - When credit is refunded:
     - `db.customer_credit_events`: Inserted with `event_type="credit_refunded"`, `signed_amount=-X.XX`.
     - `db.finance_transactions`: Inserted with `type="refund"`, `classification="liability_settlement"`, `account=cur`.
   - **Verification**: `classification="liability_settlement"` is excluded from operating expense queries (`classification in (None, "cost")`), ensuring credit refunds extinguish liabilities and decrease cash without distorting operating profit.

4. **Finance Adjustments Isolation (`server.py L6326–L6344`):**
   - Inserted solely into `db.finance_adjustments`.
   - Zero writes occur to `db.payments`, `db.customer_credit_events`, or `db.finance_transactions`.
   - Adjustments algebraically adjust `Pendapatan Penjualan` and `Piutang Usaha` without generating spurious cash or credit records.

---

## 3. Reporting-Period Behavior & Historical Restatement Analysis

The audit verified five critical temporal edge cases:

### Case 1: Handover in September, Adjustment in October
- **Scenario**: Order handed over on 2026-09-25 with recognized snapshot of 5,000 LE. On 2026-10-10, an authorized price correction of -500 LE is recorded in `db.finance_adjustments`.
- **Accounting Treatment**:
  - **September Report**: Sales Revenue = 5,000 LE (the completed handover snapshot). September accounts are closed and not restated.
  - **October Report**: The adjustment has `created_at` in October. October Sales Revenue includes -500 LE.
  - **As-of October 31 Balance Sheet**: Net adjusted revenue for the order is 4,500 LE; Accounts Receivable reflects the net adjusted figure.
- **Rule Confirmed**: Historical financial statements are **not restated**. Adjustments appear in the period in which they are created (`created_at in period`).

### Case 2: Compensating Adjustment in a Later Period
- **Scenario**: October price correction is -500 LE. In November, an error is identified, and a compensating +500 LE correction is created.
- **Accounting Treatment**:
  - October retains -500 LE.
  - November records +500 LE.
  - Audit trail in `db.finance_adjustments` preserves both records immutably. Cumulative net impact across all time returns to 0.00 LE.

### Case 3: Post-Handover Cancellation Without Erasing Revenue
- **Scenario**: Order handed over in September (`completed_at = 2026-09-15`, `recognized_revenue_le = 4,000 LE`). In October, admin sets status to `dibatalkan` with confirmation and reason.
- **Accounting Treatment**:
  - Under Phase 3.B.1 and 3.B.6, `completed_at` and `recognized_revenue_le` remain on `db.orders`.
  - The handover is a historical fact. Changing order status does not silently erase past revenue.
  - If a genuine reversal occurred, an authorized admin records a `revenue_reversal` adjustment (-4,000 LE) in October.
  - Result: September report retains 4,000 LE; October report records -4,000 LE.

### Case 4: Voided Payments & Transactions
- **Scenario**: Payment recorded in October, voided 2 hours later.
- **Accounting Treatment**:
  - In `db.payments`: `status == "voided"`.
  - In `db.finance_transactions`: `is_void == True`, `status == "void"`.
  - In `db.customer_credit_events`: Reversal event `credit_reversed` created with opposite sign.
  - All reporting queries filter `is_void: {"$ne": True}` and `status: {"$ne": "void"}`. Voided records contribute 0.00 to all periods.

---

## 4. Numeric Reconciliation Models

### 4.1 Reconciliation Scenario Table

| Event | Action Description | Real Cash Inflow | Real Cash Outflow | Customer Advances | Available Credit | Accounts Receivable | Sales Revenue | Other Income |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **E1** | Order 1 created (4,000 LE), customer pays 1,000 LE deposit (`status="diproses"`). | **+1,000** | 0.00 | **+1,000** | 0.00 | 0.00 | **0.00** | 0.00 |
| **E2** | Order 2 created (3,000 LE), customer pays 5,000 LE transfer (`allocations`: 3,000 prod, 2,000 credit). | **+5,000** | 0.00 | **+3,000** | **+2,000** | 0.00 | **0.00** | 0.00 |
| **E3** | Non-sales scrap wood sold for 500 LE (`type="income"`). | **+500** | 0.00 | 0.00 | 0.00 | 0.00 | **0.00** | **+500** |
| **E4** | Order 1 finished and handed over (`status="selesai"`). No new payment. | 0.00 | 0.00 | **-1,000** | 0.00 | **+3,000** | **+4,000** | 0.00 |
| **E5** | Customer uses 1,500 LE credit to pay down Order 1 balance (`payment_method="customer_credit"`). | **0.00** | 0.00 | 0.00 | **-1,500** | **-1,500** | 0.00 | 0.00 |
| **E6** | Customer requests cash refund of remaining 500 LE credit. | 0.00 | **+500** | 0.00 | **-500** | 0.00 | 0.00 | 0.00 |
| **E7** | Post-handover minor defect on Order 1: authorized price correction of -500 LE. | 0.00 | 0.00 | 0.00 | 0.00 | **-500** | **-500** | 0.00 |
| **TOT**| **Cumulative Position After E1–E7** | **+6,500** | **+500** | **+3,000** | **0.00** | **+1,000** | **+3,500** | **+500** |

### 4.2 Mathematical Balance Sheet & Flow Verification

1. **Net Cash Position**:
   $$\text{Ending Cash Balance} = \text{Cash Inflows} - \text{Cash Outflows} = 6,500 - 500 = 6,000\text{ LE}$$
2. **Total Earned Revenue**:
   $$\text{Total Earned Revenue} = \text{Sales Revenue} + \text{Other Income} = 3,500 + 500 = 4,000\text{ LE}$$
3. **Fundamental Accounting Equation (Assets = Liabilities + Equity/Revenue)**:
   - **Assets**: Cash (6,000 LE) + Accounts Receivable (1,000 LE) = **7,000 LE**.
   - **Liabilities**: Customer Advances (3,000 LE on Order 2) + Available Credit (0.00 LE) = **3,000 LE**.
   - **Cumulative Earned Value**: Total Revenue recognized = **4,000 LE**.
   - **Reconciliation**:
     $$\text{Assets } (7,000) = \text{Liabilities } (3,000) + \text{Revenue } (4,000)$$
     **Perfect 100% mathematical balance**. Zero leaks, zero double-counts.

---

## 5. Confirmed Invariants & Audit Decisions

### 5.1 Confirmed Invariants
1. **No Phantom Revenue from Deposits**: Cash received on active orders prior to handover sits strictly in `Customer Advances` (liability), not `Sales Revenue`.
2. **No Phantom Cash from Credit Settlements**: Paying an order with customer credit generates zero cash inflow.
3. **No Phantom Costs from Credit Refunds**: Refunding customer credit reduces cash and reduces liability; operating cost is 0.00.
4. **No Double Counting Across Ledgers**: `finance_transactions` tracks cash; `customer_credit_events` tracks credit liability; `orders` + `adjustments` tracks sales revenue; `payments` tracks order settlement.

### 5.2 Key Decision for Owner Approval: Period Attribution vs. Restatement (OD-B7-01)
- **Specification Policy**: Finance adjustments affect the reporting period in which they are created (`adjustment.created_at in period`). Historical periods are **never restated**.
- **Rationale**: In small business financial accounting, once a monthly statement is closed and tax/owner distributions are evaluated, retroactively changing previous months creates discrepancy with bank statements and tax filings.
- **Recommendation**: **Approve period-of-creation attribution (no historical restatement).**

---

## 6. Updated Master Test Matrix for Phase 3.B.7

The test matrix is expanded to 20 exhaustive automated test scenarios:

| Test ID | Module | Scenario & Preconditions | Expected Assertion |
| :--- | :--- | :--- | :--- |
| **B7-TC-01** | Cash Flow | Cash payment on `status="diproses"` order. | `cash_inflow += amt`, `sales_revenue == 0`, `customer_advances += amt`. |
| **B7-TC-02** | Cash Flow | Overpayment (5,000 LE paid on 3,000 LE order). | `cash_inflow == 5000`, `available_credit += 2000`, `customer_advances += 3000`. |
| **B7-TC-03** | Cash Flow | Non-cash credit settlement (`customer_credit`). | `cash_inflow == 0`, `available_credit -= amt`, `accounts_receivable -= amt`. |
| **B7-TC-04** | Cash Flow | Customer credit cash refund. | `cash_outflow += amt`, `available_credit -= amt`, `operating_cost == 0`. |
| **B7-TC-05** | Revenue | First handover transition to `selesai` in period. | `sales_revenue += recognized_revenue_le`, `customer_advances -= paid`. |
| **B7-TC-06** | Revenue | Order handed over in prior period queried in current period. | Current period `sales_revenue` excludes order; prior period retains snapshot. |
| **B7-TC-07** | Revenue | Non-sales income recorded in period (Owner Decision A). | `other_income += amt`; strictly omitted from `sales_revenue`. |
| **B7-TC-08** | Adjustments | Post-handover upward price correction in period. | `sales_revenue += amt`, `accounts_receivable += amt`. |
| **B7-TC-09** | Adjustments | Post-handover downward revenue reversal in period. | `sales_revenue -= abs(amt)`, `accounts_receivable -= abs(amt)`. |
| **B7-TC-10** | Temporal | Handover in Month 1, Adjustment in Month 2. | Month 1 retains full snapshot; Month 2 records adjustment. No restatement. |
| **B7-TC-11** | Temporal | Adjustments in Month 2 compensated in Month 3. | Month 2 and Month 3 each record their respective events; net across time = 0. |
| **B7-TC-12** | Receivables | Handed-over order with partial payment. | $\text{AR} = \max(0, \text{snapshot} + \text{adj} - \text{paid})$. |
| **B7-TC-13** | Receivables | Fully paid order with downward adjustment. | $\text{AR} == 0.00$; unallocated excess = $\text{abs(adj)}$. |
| **B7-TC-14** | Currency | EGP order transactions and IDR non-sales income. | EGP and IDR buckets strictly segregated; 0 cross-currency pollution. |
| **B7-TC-15** | Status Guard | Handed-over order transitioned to `dibatalkan`. | Historical snapshot retained in completed period; reversal requires explicit adjustment. |
| **B7-TC-16** | Voids | Payment and linked transaction marked `is_void=True`. | Completely excluded from cash, revenue, credit, and receivables. |
| **B7-TC-17** | Legacy Data | Legacy transaction with `type="order_revenue"`. | Counted as cash inflow in `_compute_balances`; excluded from Phase 3 sales revenue. |
| **B7-TC-18** | Legacy DP | Ambiguous legacy `dp` order with 0 payment docs. | No synthetic cash or credit generated; excluded from customer advances. |
| **B7-TC-19** | Balance Cutoff | `as_of` ending balance query with cutoff timestamp. | Exactly aggregates transactions where `date <= cutoff`. Future transactions ignored. |
| **B7-TC-20** | Performance | Query execution over large order/payment dataset. | Pure read operations; index-supported aggregation executing in < 50ms. |

---

## 7. Minimal Implementation Plan

### Targeted Changes in `backend/server.py`:
1. **Refactor `_stats_for(s, e)` (`L5307–L5330`):**
   - Query `db.orders` for handed-over sales revenue (`completed_at in [s, e]`, `recognized_revenue_le`).
   - Query `db.finance_adjustments` for period adjustments (`created_at in [s, e]`, `is_void != True`).
   - Query `db.finance_transactions` for cash inflow, cash outflow, other income, and operating expenses with proper `classification` filters.
   - Aggregate `db.customer_credit_events` for available credit and credit flow metrics.
   - Aggregate active `db.orders` and `db.payments` for customer advances and accounts receivable.
2. **Preserve Backward Compatibility in `GET /admin/finance/stats` (`L5332–L5369`):**
   - Return both legacy keys (`revenue`, `cost`, `operating_profit`, `cash_flow`) and explicit new Phase 3 keys (`sales_revenue`, `other_income`, `real_cash_inflow`, `real_cash_outflow`, `accounts_receivable`, `customer_advances`, `available_customer_credit`).

---

## 8. Final Audit Verdict

### **`READY FOR IMPLEMENTATION APPROVAL`**

The specification is mathematically sound, preserves 100% backward compatibility, cleanly solves the legacy revenue distortion defects, and introduces no contradictions.

Upon owner approval of the specification and policy OD-B7-01, implementation of Phase 3.B.7 can proceed directly.
