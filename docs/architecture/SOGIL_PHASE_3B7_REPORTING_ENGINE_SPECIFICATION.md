# SOGIL FURNITURE — TECHNICAL SPECIFICATION & ARCHITECTURE AUDIT
## PHASE 3.B.7: REPORTING ENGINE & METRIC RECONCILIATION
**Document Identifier:** `SOGIL_PHASE_3B7_REPORTING_ENGINE_SPECIFICATION.md`  
**Version:** v1.0  
**Status:** SPECIFICATION AUDIT & DESIGN — STRICT READ-ONLY AUDIT  
**Baseline Commit:** `b6731c082d62f48b93b1116435e872b169e58387` (HEAD -> main)  
**Parent Commit:** `42d68b3efebc11fecc9c96cd52cdc48715547f8f`  
**Reference Authoritative Documents:**  
- `docs/architecture/SOGIL_PHASE_3_SCOPE_LOCK_v1.3.md` (Scope Lock v1.3)
- `docs/architecture/SOGIL_PHASE_3_IMPLEMENTATION_PLAN_v1.3.md` (Implementation Plan v1.3)  
**Date:** 2026-10-12  

---

## 1. Executive Summary & Purpose

Phase 3.B.7 is the central financial reporting and metric reconciliation layer of Sogil Furniture. 
With the completion of:
- **Phase 3.B.1**: Handover-based revenue recognition and immutable order snapshots (`completed_at`, `recognized_revenue_le`).
- **Phase 3.B.2**: Real payment allocation and overpayment customer credit minting (`db.customer_credit_events`).
- **Phase 3.B.3**: Non-cash customer credit order settlements (`payment_method="customer_credit"`).
- **Phase 3.B.4**: Customer credit cash refunds (`POST /admin/customers/{id}/credit-refund`).
- **Phase 3.B.6**: Explicit post-handover finance adjustments (`db.finance_adjustments`).

The backend reporting engine—chiefly `_stats_for(s, e)`, `_compute_balances(as_of)`, `GET /admin/finance/stats`, and `GET /admin/finance/statistics`—must be upgraded to eliminate legacy distortions and faithfully compute real cash receipts, earned sales revenue, other non-sales income, accounts receivable, and customer credit liabilities.

This document establishes the exact accounting formulas, source collections, query boundaries, normalization rules, and test scenarios required to implement Phase 3.B.7 safely without corrupting historical data or silently mixing currencies.

---

## 2. Current Architecture & Production Discrepancy Analysis

### 2.1 Current Implementation State in `backend/server.py`

#### A. `_stats_for(s, e)` (`L5307–L5330`)
```python
async def _stats_for(s, e):
    q = {"is_void": {"$ne": True}, "status": {"$ne": "void"}}
    if s or e:
        q["date"] = {}
        if s:
            q["date"]["$gte"] = s
        if e:
            q["date"]["$lte"] = e
    res = {"IDR": {"revenue": 0.0, "cost": 0.0}, "EGP": {"revenue": 0.0, "cost": 0.0}}
    async for t in db.finance_transactions.find(q):
        cur = t.get("currency", "EGP"); typ = t.get("type"); amt = _num(t.get("amount")); cls = t.get("classification")
        if cur not in res:
            continue
        if typ == "order_revenue":
            res[cur]["revenue"] += amt
        elif typ == "income" and cls in (None, "revenue"):
            res[cur]["revenue"] += amt
        elif typ == "expense" and cls in (None, "cost"):
            res[cur]["cost"] += amt
    for cur in res:
        r = res[cur]
        r["operating_profit"] = r["revenue"] - r["cost"]
        r["cash_flow"] = r["revenue"] - r["cost"]
    return res
```

#### B. `_compute_balances(as_of)` (`L5065–L5084`)
```python
async def _compute_balances(as_of: Optional[str] = None):
    bal = {"IDR": 0.0, "EGP": 0.0}
    q = {"is_void": {"$ne": True}, "status": {"$ne": "void"}}
    if as_of:
        q["date"] = {"$lte": as_of}
    async for t in db.finance_transactions.find(q):
        typ = t.get("type"); cur = t.get("currency", "EGP"); amt = _num(t.get("amount"))
        if typ in ("income", "order_revenue"):
            bal[t.get("account", cur)] = bal.get(t.get("account", cur), 0) + amt
        elif typ in ("expense", "refund", "credit_refund"):
            bal[t.get("account", cur)] = bal.get(t.get("account", cur), 0) - amt
        elif typ == "transfer":
            bal[t.get("from_account", "IDR")] = bal.get(t.get("from_account", "IDR"), 0) - _num(t.get("from_amount"))
            bal[t.get("to_account", "EGP")] = bal.get(t.get("to_account", "EGP"), 0) + _num(t.get("to_amount"))
        elif typ == "balance_adjustment":
            bal[t.get("account", cur)] = bal.get(t.get("account", cur), 0) + _num(t.get("amount"))
    for k in bal:
        bal[k] = round(bal[k], 2)
    return bal
```

#### C. `finance_statistics` (`L6988–L7116`)
In `GET /admin/finance/statistics`, `type == "order_revenue"` is mapped directly to `typ = "income"; cls = "revenue"`, and groups are summarized solely from `db.finance_transactions`.

### 2.2 Discrepancies and Audit Findings

1. **Defect D1 — Premature Revenue Recognition in `_stats_for`**:
   - `_stats_for` currently derives `res[cur]["revenue"]` from `db.finance_transactions` where `typ == "order_revenue"` or `typ == "income"`.
   - In production, when an order is created and a deposit payment is received while the order is in status `diproses` or `siap`, a `finance_transaction` with `type="order_revenue"` is recorded.
   - Result: Revenue is counted immediately upon payment receipt instead of upon handover (`completed_at` on `db.orders`).

2. **Defect D2 — Inflation of Revenue by Overpayments**:
   - When a customer overpays (e.g. 5,000 LE on a 3,000 LE order), the payment cash transaction records 5,000 LE.
   - Currently, `_stats_for` adds 5,000 LE to `revenue`, overstating sales revenue by 2,000 LE. Under Phase 3, that 2,000 LE is an unallocated customer credit liability, not revenue.

3. **Defect D3 — Non-Sales Income Blended into Revenue (Violation of Owner Decision A)**:
   - Arbitrary income transactions (`type="income"`) are lumped directly into `revenue` alongside order revenue.
   - Owner Decision A strictly requires *Pendapatan Penjualan* (Sales Revenue) to be isolated from *Pendapatan Lain-lain* (Other Income).

4. **Defect D4 — Missing Finance Adjustments in Revenue Aggregation**:
   - Post-handover adjustments recorded in `db.finance_adjustments` (Phase 3.B.6) do not generate `db.finance_transactions`.
   - Because `_stats_for` only reads `db.finance_transactions`, legitimate post-handover price corrections, partial returns, and revenue reversals are completely ignored by dashboard revenue reporting.

5. **Defect D5 — Missing Balance Sheet Liabilities and Receivables**:
   - The current stats payload returns only `revenue`, `cost`, `operating_profit`, `cash_flow`, and ending cash balances.
   - Metrics mandated by Scope Lock v1.3—namely *Kredit Pelanggan Tersedia* (Customer Credit Liability), *Uang Muka Pelanggan* (Customer Advances), and *Piutang Usaha* (Accounts Receivable)—are not computed or exposed.

6. **Defect D6 — Conflation of Cash Flow and Revenue**:
   - Line 5329 sets `r["cash_flow"] = r["revenue"] - r["cost"]`.
   - Real net cash flow is actual cash inflow minus actual cash outflow, which includes refunds, customer advances, and balance adjustments, completely independent of when furniture is handed over.

---

## 3. Authoritative Accounting Invariants & Principles

### Invariant 1: Cash Receipts vs. Earned Revenue Separation
- **Penerimaan Kas Riil (Real Cash Inflow)**: Actual physical money entering business accounts (`account == cur`) during the period. It counts all cash payments (`order_payment`, legacy `order_revenue`, and non-sales `income`), regardless of whether the furniture has been manufactured or delivered.
- **Pendapatan Penjualan (Earned Sales Revenue)**: Earned solely upon physical handover of furniture (`completed_at in period`) snapshot at `order.recognized_revenue_le`, plus authorized `db.finance_adjustments` in the period. Pre-handover deposits are deposit liabilities, not revenue.

### Invariant 2: Pure Sales Revenue Metric (Owner Decision A)
- *Pendapatan Penjualan* includes **only** furniture sales revenue.
- Non-sales income (`type="income"`) is reported separately under *Pendapatan Lain-lain*.
- $\text{Total Pendapatan} = \text{Pendapatan Penjualan} + \text{Pendapatan Lain-lain}$.

### Invariant 3: Customer Credit Non-Cash Settlements (Zero Cash Inflow)
- When an order balance is paid using customer credit (`payment_method="customer_credit"`), `db.finance_transactions` has `type="credit_settlement"`, `classification="credit_settlement"`.
- This transaction represents an internal balance sheet offset (Liability $\downarrow$, Accounts Receivable $\downarrow$).
- **Cash Inflow = 0.00 LE**. Cash reports must strictly exclude `credit_settlement`.

### Invariant 4: Customer Credit Refund Classification
- Refunding customer credit (`POST /admin/customers/{id}/credit-refund`) creates a cash transaction (`type="refund"`, `classification="liability_settlement"`, `account=cur`).
- This is a physical cash outflow (Liability $\downarrow$, Cash $\downarrow$).
- **Cost / Expense Invariant**: A credit refund is **not** an operating cost or expense. Operating costs and COGS are unchanged. It affects cash balance and cash flow, but not operating profit.

### Invariant 5: Finance Adjustments Isolation (Owner Decision B6-OD-01)
- `db.finance_adjustments` records price corrections, revenue reversals, and return allowances.
- They **do not** write to `db.payments`, `db.customer_credit_events`, or `db.finance_transactions`.
- Adjustments are applied to *Pendapatan Penjualan* and *Piutang Usaha*, but produce **zero direct cash inflow or outflow**.

### Invariant 6: Accounts Receivable Non-Negativity Floor
- Receivables for handed-over orders:
  $$\text{Piutang Usaha} = \sum_{\text{handed over}} \max(0, (\text{recognized\_revenue\_le} + \text{net\_adjustments}) - \text{canonical\_paid\_le})$$
- Receivables can never be negative. If `canonical_paid_le > (recognized_revenue_le + net_adjustments)`, the excess is captured as *Kredit Pelanggan Tersedia* or *Unallocated Excess*, never negative accounts receivable.

### Invariant 7: Strict Currency Isolation
- Currencies `EGP` and `IDR` are strictly segregated into independent buckets (`res["EGP"]`, `res["IDR"]`).
- No metric is ever cross-summed without explicit, documented currency conversion rates.

### Invariant 8: Backward Compatibility & Historical Cutoff
- Historical transactions with `type="order_revenue"` continue to be recognized as valid cash receipts so historical cash balances remain 100% stable without database mutation.
- Historical orders without valid handover timestamps are treated as legacy orders and not falsely included in post-cutoff revenue batches.

---

## 4. Precise Metric Formulas & Source Collections

### 4.1 Primary Metrics (Per Currency Bucket $cur \in \{\text{EGP}, \text{IDR}\}$)

#### 1. Penerimaan Kas Riil (Real Cash Inflow)
- **Classification**: Cash Flow Inflow
- **Source Collection**: `db.finance_transactions`
- **Period Filter**: `date >= s` and `date <= e` (inclusive)
- **Status Filter**: `is_void != True` and `status != "void"`
- **Account / Currency Filter**: `account == cur` (fallback to `currency == cur` if `account` is null)
- **Transaction Types Included**:
  - `type == "order_payment"`
  - `type == "order_revenue"` (Legacy order payment cash receipt)
  - `type == "income"` where `classification in (None, "revenue")`
  - `type == "transfer"` where `to_account == cur` (Gross cash arriving into this account)
  - `type == "balance_adjustment"` where `amount > 0` and `account == cur`
- **Explicit Exclusions**:
  - `type == "credit_settlement"` (Non-cash settlement; strictly excluded)
  - Transactions where `is_void == True` or `status == "void"`
- **Formula**:
  $$\text{Cash Inflow}(cur) = \sum_{t \in \text{valid txns}} \text{amount}$$

#### 2. Pengeluaran Kas Riil (Real Cash Outflow)
- **Classification**: Cash Flow Outflow
- **Source Collection**: `db.finance_transactions`
- **Period Filter**: `date in period`
- **Status Filter**: `is_void != True` and `status != "void"`
- **Account / Currency Filter**: `account == cur` (or `from_account == cur` for transfers)
- **Transaction Types Included**:
  - `type == "expense"` where `classification in (None, "cost")`
  - `type in ("refund", "credit_refund")`
  - `type == "transfer"` where `from_account == cur`
  - `type == "balance_adjustment"` where `amount < 0` (absolute value)
- **Formula**:
  $$\text{Cash Outflow}(cur) = \sum_{t \in \text{valid outflow txns}} |\text{amount}|$$

#### 3. Arus Kas Bersih (Net Cash Flow)
- **Formula**:
  $$\text{Net Cash Flow}(cur) = \text{Cash Inflow}(cur) - \text{Cash Outflow}(cur)$$

#### 4. Pendapatan Penjualan (Earned Sales Revenue — Owner Decision A)
- **Classification**: Earned Operating Revenue (Accrual basis)
- **Source Collections**: `db.orders` + `db.finance_adjustments`
- **Currency**: `EGP` (Furniture sales orders are priced and recognized in Egyptian Pounds LE)
- **Order Criteria**:
  - Order has `completed_at` valid ISO timestamp where `completed_at >= s` and `completed_at <= e`.
  - Order has valid numeric `recognized_revenue_le >= 0`.
  - `order_status in ["selesai", "dibatalkan"]` (Recognized upon handover; cancellation requires explicit adjustment to reverse).
- **Adjustment Criteria**:
  - `db.finance_adjustments` where `created_at >= s` and `created_at <= e`.
  - `is_void != True`.
  - `currency == "EGP"`.
- **Formula**:
  $$\text{Pendapatan Penjualan} = \sum_{\substack{\text{orders with} \\ \text{completed\_at in period}}} \text{recognized\_revenue\_le} + \sum_{\substack{\text{adjustments with} \\ \text{created\_at in period}}} \text{amount}$$
- **Strict Exclusion**: Arbitrary `finance_transactions` with `type="income"` or `type="order_revenue"` must **NOT** be added to this metric.

#### 5. Pendapatan Lain-lain (Other Non-Sales Income)
- **Classification**: Other Operating Income
- **Source Collection**: `db.finance_transactions`
- **Period Filter**: `date in period`
- **Criteria**:
  - `type == "income"`
  - `classification in (None, "revenue")`
  - `currency == cur`
  - `is_void != True`
- **Formula**:
  $$\text{Pendapatan Lain-lain}(cur) = \sum_{t \in \text{income txns}} \text{amount}$$

#### 6. Total Pendapatan Operasi (Total Revenue)
- **Formula**:
  $$\text{Total Revenue}(cur) = \begin{cases} \text{Pendapatan Penjualan} + \text{Pendapatan Lain-lain}(cur) & \text{if } cur == \text{"EGP"} \\ \text{Pendapatan Lain-lain}(cur) & \text{if } cur == \text{"IDR"} \end{cases}$$

#### 7. Biaya Operasional (Operating Expenses)
- **Classification**: Operating Expense
- **Source Collection**: `db.finance_transactions`
- **Period Filter**: `date in period`
- **Criteria**:
  - `type == "expense"`
  - `classification in (None, "cost")`
  - `account == cur`
  - `is_void != True`
- **Strict Exclusion**: `classification == "liability_settlement"` (e.g. credit refund) and `type in ("refund", "credit_refund")` must **NOT** be added to operating costs.

#### 8. Laba Operasi (Operating Profit)
- **Formula**:
  $$\text{Operating Profit}(cur) = \text{Total Revenue}(cur) - \text{Biaya Operasional}(cur)$$

### 4.2 Secondary Balance Sheet & Working Capital Metrics

#### 9. Kredit Pelanggan Tersedia (Available Customer Credit Liability)
- **Classification**: Current Liability (As-of metric / point in time)
- **Source Collection**: `db.customer_credit_events`
- **Filter**: All active events for `currency == cur` as of the period cutoff (`created_at <= cutoff`).
- **Formula**:
  $$\text{Kredit Pelanggan Tersedia}(cur) = \sum_{\substack{\text{events with} \\ \text{created\_at} \le \text{cutoff}}} \text{signed\_amount}$$
- **Invariant**: Computed via the canonical helper `get_customer_credit_balance(cid, cur)` or aggregate `$sum: "$signed_amount"` over all customers.

#### 10. Uang Muka Pelanggan (Customer Advances / Deposit Liability)
- **Classification**: Current Liability (Unearned revenue)
- **Source Collections**: `db.orders` + `db.payments`
- **Criteria**:
  - Active orders where `order_status not in ["selesai", "dibatalkan"]`.
  - Sum of canonical payments allocated to each order (`canonical_paid_le`).
- **Formula**:
  $$\text{Uang Muka Pelanggan} = \sum_{\substack{\text{orders with} \\ \text{status} \notin [\text{"selesai"}, \text{"dibatalkan"}]}} \text{canonical\_paid\_le}$$

#### 11. Piutang Usaha (Accounts Receivable)
- **Classification**: Current Asset (As-of metric)
- **Source Collections**: `db.orders` + `db.finance_adjustments` + `db.payments`
- **Criteria**:
  - Handed-over orders (`completed_at is not None` and `order_status in ["selesai", "dibatalkan"]`).
  - Net recognized value = `recognized_revenue_le + cumulative_adjustments_le`.
  - Total payments recorded on order = `canonical_paid_le`.
- **Formula**:
  $$\text{Piutang Usaha} = \sum_{\text{handed over orders}} \max(0, (\text{recognized\_revenue\_le} + \text{cumulative\_adjustments\_le}) - \text{canonical\_paid\_le})$$

#### 12. Kredit Digunakan (Credit Consumed in Period)
- **Classification**: Contra-Liability Flow (Flow metric)
- **Source Collection**: `db.customer_credit_events`
- **Criteria**:
  - `event_type == "credit_applied"`
  - `currency == cur`
  - `created_at in period`
- **Formula**:
  $$\text{Kredit Digunakan}(cur) = \left| \sum \text{signed\_amount} \right|$$

#### 13. Kredit Dikembalikan (Credit Refunded in Period)
- **Classification**: Liability Settlement Flow (Flow metric)
- **Source Collection**: `db.customer_credit_events`
- **Criteria**:
  - `event_type == "credit_refunded"`
  - `currency == cur`
  - `created_at in period`
- **Formula**:
  $$\text{Kredit Dikembalikan}(cur) = \left| \sum \text{signed\_amount} \right|$$

---

## 5. Duplicate Counting Prevention Matrix

| Potential Overlap Area | Risk of Double Counting | Authoritative Prevention Rule |
| :--- | :--- | :--- |
| **Order Payment vs. Allocation** | Double counting cash receipts if both `payments` and `finance_transactions` are summed. | Cash receipt reports **only** read `db.finance_transactions`. `db.payments` is used strictly for order-level settlement tracking, never cash totals. |
| **Cash Payment vs. Customer Credit Settlement** | Treating credit settlement as new cash income. | Credit settlement creates `finance_transaction` with `type="credit_settlement"`, which is **strictly excluded** from Cash Inflow. |
| **Credit Minting vs. Sales Revenue** | Overpayment minted into credit counted as revenue. | Handover revenue is based on `order.recognized_revenue_le`, not payments. Minted credit in `db.customer_credit_events` is never aggregated into revenue. |
| **Credit Refund vs. Operating Cost** | Refund of unallocated credit counted as business expense. | Credit refund is created with `classification="liability_settlement"` and `type="refund"`. Expense queries filter `classification in (None, "cost")`, preventing cost distortion. |
| **Handover Snapshot vs. Finance Adjustment** | Double counting adjustments if order total is modified directly. | Scope Lock v1.3 / B6-OD-01 strictly freezes order total after handover (`HTTP 409`). Adjustments live only in `db.finance_adjustments` and are added algebraically once. |
| **Post-Handover Cancellation vs. Revenue** | Deleting past revenue upon order cancellation. | Revenue snapshot remains tied to historical `completed_at`. Reversals require explicit `db.finance_adjustments` entries, preserving audit trails. |
| **Legacy `order_revenue` vs. Phase 3 `order_payment`** | Breaking historical cash balances or double-counting legacy receipts. | Legacy `order_revenue` is counted as cash receipt in cash metrics, but excluded from Phase 3 sales revenue metric. |

---

## 6. Proposed Endpoint Contracts & Response Models

### 6.1 Upgraded `GET /admin/finance/stats` Response Contract

```json
{
  "period": "this_month",
  "range": {
    "start": "2026-10-01T00:00:00Z",
    "end": "2026-10-31T23:59:59Z"
  },
  "current": {
    "EGP": {
      "real_cash_inflow": 45000.00,
      "real_cash_outflow": 28000.00,
      "cash_flow": 17000.00,
      "sales_revenue": 52000.00,
      "other_income": 1500.00,
      "total_revenue": 53500.00,
      "operating_cost": 28000.00,
      "operating_profit": 25500.00,
      "available_customer_credit": 4500.00,
      "customer_advances": 12000.00,
      "accounts_receivable": 8500.00,
      "credit_applied": 3000.00,
      "credit_refunded": 1000.00,
      "legacy_revenue": 53500.00
    },
    "IDR": {
      "real_cash_inflow": 15000000.00,
      "real_cash_outflow": 8000000.00,
      "cash_flow": 7000000.00,
      "sales_revenue": 0.00,
      "other_income": 2000000.00,
      "total_revenue": 2000000.00,
      "operating_cost": 8000000.00,
      "operating_profit": -6000000.00,
      "available_customer_credit": 0.00,
      "customer_advances": 0.00,
      "accounts_receivable": 0.00,
      "credit_applied": 0.00,
      "credit_refunded": 0.00,
      "legacy_revenue": 2000000.00
    }
  },
  "comparison": {
    "EGP": {
      "sales_revenue": 14.2,
      "operating_cost": -5.1,
      "operating_profit": 28.6,
      "real_cash_inflow": 8.5
    },
    "IDR": {
      "sales_revenue": null,
      "operating_cost": 12.0,
      "operating_profit": null,
      "real_cash_inflow": 5.0
    }
  },
  "balances": {
    "EGP": 124500.00,
    "IDR": 48200000.00
  }
}
```

*Note on Backward Compatibility:* The keys `revenue`, `cost`, `operating_profit`, and `cash_flow` should be preserved in the response dictionary to avoid breaking existing frontend builds before Workstream 3.D is deployed. `revenue` can alias `sales_revenue + other_income` or `sales_revenue` during the transition.

---

## 7. Comprehensive Master Test Matrix for Phase 3.B.7

| Test ID | Category | Scenario Description | Expected Outcome |
| :--- | :--- | :--- | :--- |
| **B7-TC-01** | Cash Flow | Cash payment on unhanded-over order (`status="diproses"`). | Cash Inflow increases by payment amount; Sales Revenue = 0.00; Customer Advances increases. |
| **B7-TC-02** | Cash Flow | Overpayment (e.g. 5,000 LE paid on 3,000 LE order; 2,000 LE minted as credit). | Cash Inflow = 5,000 LE; Available Credit increases by 2,000 LE; Sales Revenue = 0.00. |
| **B7-TC-03** | Cash Flow | Settlement using customer credit (`payment_method="customer_credit"`). | Cash Inflow = 0.00 LE; Available Credit decreases; Accounts Receivable decreases. |
| **B7-TC-04** | Cash Flow | Customer credit cash refund (`POST /admin/customers/{id}/credit-refund`). | Cash Outflow increases; Available Credit decreases; Operating Cost = 0.00. |
| **B7-TC-05** | Revenue Recognition | Order completed within period (`order_status="selesai"`). | Sales Revenue increases by `order.recognized_revenue_le`; Customer Advances released. |
| **B7-TC-06** | Revenue Recognition | Order completed in prior period, queried in current period. | Current period Sales Revenue does NOT include order; prior period retains snapshot. |
| **B7-TC-07** | Owner Decision A | Arbitrary non-sales `income` recorded in period. | Included in *Pendapatan Lain-lain*; strictly excluded from *Pendapatan Penjualan*. |
| **B7-TC-08** | Adjustments | Upward price correction adjustment in period. | Sales Revenue increases by correction amount; Receivables increases. |
| **B7-TC-09** | Adjustments | Downward revenue reversal adjustment in period. | Sales Revenue decreases by reversal amount; Receivables decreases. |
| **B7-TC-10** | Balance Sheet | Accounts Receivable on handed-over order with partial payment. | $\text{Receivables} = \max(0, \text{snapshot} + \text{adj} - \text{paid})$. Non-negative. |
| **B7-TC-11** | Balance Sheet | Accounts Receivable on fully paid order with downward adjustment. | Excess payment turns into unallocated excess; Receivables remains exactly 0.00 LE. |
| **B7-TC-12** | Currency Isolation | IDR non-sales income and EGP order revenue recorded simultaneously. | EGP metrics contain only EGP amounts; IDR metrics contain only IDR amounts. No cross-summing. |
| **B7-TC-13** | Status Safeguard | Handed-over order changed to `dibatalkan` with valid reason. | Historical `recognized_revenue_le` preserved in completed period; not silently removed. |
| **B7-TC-14** | Voids & Reversals | Voided payment transaction (`is_void=True`). | Completely excluded from Cash Inflow, Cash Outflow, and Accounts Receivable calculations. |
| **B7-TC-15** | Legacy Data | Legacy order with `type="order_revenue"` in historical database. | Counted as Cash Inflow in `_compute_balances()`; excluded from Phase 3 handover sales revenue. |
| **B7-TC-16** | Legacy DP Order | Ambiguous legacy `dp` order with 0 payment docs. | No synthetic cash or credit generated; ignored by customer credit ledger. |
| **B7-TC-17** | As-Of Balance | Ending balance query with period cutoff date `e`. | Balances aggregate exactly transactions where `date <= e`. Future transactions ignored. |
| **B7-TC-18** | Replay & Idempotency | Replayed queries under high frequency. | Pure deterministic read query; zero side-effects on database state. |

---

## 8. Gaps, Risks, and Open Design Decisions

### 8.1 Decision D-01: Definition of Legacy `revenue` Field in API Response
- **Issue:** Frontend component `AdminFinance.jsx` currently consumes `stats.current[cur].revenue` and expects it to be a single number.
- **Option 1 (Recommended):** Set `current[cur].revenue = sales_revenue + other_income` for backward compatibility, and introduce explicit new fields `sales_revenue` (*Pendapatan Penjualan*), `other_income` (*Pendapatan Lain-lain*), `real_cash_inflow` (*Penerimaan Kas Riil*), and `customer_credit_liability`.
- **Option 2:** Set `current[cur].revenue = sales_revenue` (pure sales revenue), and update frontend simultaneously in Workstream 3.D.
- **Recommendation:** Implement Option 1 in the backend so existing dashboards do not break if visited before the frontend PR is merged.

### 8.2 Decision D-02: Aggregation Strategy for Balance Sheet Metrics (Scale vs. Real-Time)
- **Issue:** Computing *Piutang Usaha* and *Uang Muka Pelanggan* across all active orders involves querying `db.orders` and associated `db.payments`.
- **Analysis:** For Sogil Furniture's operational volume (hundreds to low thousands of active custom furniture orders), an indexed MongoDB aggregation pipeline or lean `find({"order_status": ...})` executes in < 30ms.
- **Recommendation:** Use direct indexed MongoDB aggregation queries in `_stats_for()` without introducing complex cached read-models or background worker daemons.

### 8.3 Risk R-01: Orders Handed Over Before Phase 3 Activation Cutoff
- **Issue:** Orders completed months ago without a reliable `completed_at` timestamp.
- **Mitigation:** The query for `completed_at in period` naturally excludes legacy orders lacking a valid timestamp, ensuring historical periods are never retroactively polluted.

---

## 9. Minimal Implementation Plan & Workstream Boundaries

### Phase 3.B.7 Scope Boundary
Phase 3.B.7 is strictly backend reporting logic:
- Modify `_stats_for(s, e)` in `backend/server.py`.
- Enhance `GET /admin/finance/stats` to expose the new metrics.
- Update `_compute_balances(as_of)` if needed to guarantee exact transaction-type isolation.
- Add dedicated test suite `backend/tests/test_phase3_reporting_engine.py`.
- **Strictly Excluded**:
  - No frontend edits (Workstream 3.D).
  - No schema migrations.
  - No changes to payment creation, credit settlement, or adjustment endpoints.
  - No database mutations.

---

## 10. Audit Verdict

### **`READY FOR OWNER APPROVAL`**

The specification is fully aligned with Scope Lock v1.3, respects all five approved owner decisions from Phase 3.B.6, preserves backward compatibility with legacy cash tracking, and establishes rigorous multi-collection accounting formulas without ambiguity.

Upon explicit owner authorization, implementation of Workstream 3.B.7 can proceed immediately.
