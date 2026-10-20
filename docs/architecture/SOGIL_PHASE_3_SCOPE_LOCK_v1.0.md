# SOGIL FURNITURE — ARCHITECTURE SCOPE LOCK
## PHASE 3: CUSTOMER OVERPAYMENT CREDIT & REVENUE ATTRIBUTION
**Version:** v1.0  
**Status:** DRAFT SPECIFICATION — AWAITING OWNER APPROVAL  
**Target Repository:** `HIDD-Web/Sogil-Furniture`  
**Baseline Git Commit:** `656d7960150e0b47d0295c5c736512308c721ee1`  
**Date:** 2026-10-10  

---

## 1. Executive Summary & Scope

### 1.1 Objective
Phase 3 formalizes the accounting, financial reporting, and operational handling of **Customer Overpayments** and **Revenue Recognition** within Sogil Furniture. It resolves the confirmed limitation where customer overpayment excess (allocated to `unallocated_credit`) was aggregated into period gross sales revenue inside `_stats_for()`, conflating physical cash receipts with earned sales revenue.

### 1.2 Core Architectural Principles
1. **Separation of Economic Realities**:
   - **Cash Inflow (Penerimaan Kas Riil)**: Physical cash received into bank/cash accounts.
   - **Earned Sales Revenue (Pendapatan Penjualan)**: Recognized sales value when fulfillment criteria are satisfied.
   - **Customer Credit Liability (Kredit Pelanggan Tersedia / Titipan Pelanggan)**: Unearned customer deposits held as a balance sheet liability.
2. **Auditable Customer Credit Ledger**: Customer credits are tracked via an immutable event-sourcing ledger collection (`db.customer_credit_events`), guaranteeing that available credit is derived or reconciled from verifiable events.
3. **No Revenue Inflation**: Applying customer credit to subsequent orders recognizes earned sales revenue on that order without recording duplicate bank cash inflow.
4. **Strict Historical Compatibility**: Existing historical orders, payments, and finance transactions remain completely immutable. Phase 3 rules apply strictly to new transactions recorded after the Phase 3 activation date (`as_of_phase3_date`).

### 1.3 Explicit Non-Goals
- **No Retroactive Rewriting**: No automated mutation or retroactive re-categorization of existing historical `finance_transactions`.
- **No Cryptocurrency or Multi-tier Loyalty Conversions**: Phase 3 manages real fiat currency credits (`EGP` and `IDR`). Points/loyalty systems remain isolated in `db.point_transactions`.

---

## 2. Current Architecture & Confirmed Defect Analysis

### 2.1 Confirmed Accounting Discrepancy
In `backend/server.py` ([lines 2404–2425](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/backend/server.py#L2404-L2425)), order payment creation unconditionally inserts a document into `db.finance_transactions` with:
```python
"type": "order_revenue",
"category": "Penjualan",
"amount": conv["primary_amount"] # Full cash received, including excess
```
In `_stats_for(s, e)` ([lines 4918–4941](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/backend/server.py#L4918-L4941)):
```python
if typ == "order_revenue":
    res[cur]["revenue"] += amt
```
**Example Discrepancy**:
- Order Total: `3,000 LE`.
- Customer Cash Received: `5,000 LE`.
- Excess Payment: `2,000 LE` (stored in `pmt_doc.allocations` as `target_type="unallocated_credit"`).
- **Result in Reports**: `revenue` increases by `5,000 LE`, overstating earned sales revenue and operating profit by `2,000 LE`. Furthermore, there is no mechanism for the customer to spend this `2,000 LE` on a future order.

### 2.2 Fulfillment vs. Revenue Recognition Ambiguity
In the existing codebase, an order passes through fulfillment stages:
`pesanan_masuk` $\rightarrow$ `dikonfirmasi` $\rightarrow$ `diproses` $\rightarrow$ `siap` $\rightarrow$ `selesai` (or `dibatalkan`).
Previously, recording cash automatically generated `order_revenue` regardless of whether the custom furniture was merely an initial deposit or actually manufactured and delivered. Phase 3 establishes explicit revenue recognition rules.

---

## 3. Phase 3 Accounting Model & Lifecycle

### 3.1 Financial Definitions & Ledgers

| Metric Name (Dashboard) | Accounting Classification | Definition / Source |
| :--- | :--- | :--- |
| **Penerimaan Kas Riil** | Cash Inflow (Cash Flow Statement) | Sum of physical cash & transfer receipts recorded in `db.finance_transactions` (`type in ("order_revenue", "customer_deposit", "income")`). |
| **Pendapatan Penjualan** | Earned Sales Revenue (Income Statement) | Recognized sales value of fulfilled orders or allocated order portions, net of discounts and excluding unallocated customer deposits. |
| **Kredit Pelanggan Tersedia** | Current Liability (Balance Sheet) | Total active, unconsumed, un-refunded customer deposits held by Sogil Furniture across all customers. |
| **Kredit Diterapkan** | Internal Settlement (Contra-Liability) | Customer credit applied toward order balances; recognizes revenue without physical cash inflow. |

### 3.2 Complete Lifecycle Scenarios (Worked Examples in EGP)

#### Scenario A: Overpayment on Order #1
- Order #1 Total: `3,000 LE`.
- Customer pays: `5,000 LE` Cash.
- **Ledger Entries Created (Atomic Multi-Document Transaction)**:
  1. `db.payments`:
     - `amount_le`: `5,000.0`
     - Allocations: `product` = 3,000 LE, `unallocated_credit` = 2,000 LE.
  2. `db.finance_transactions`:
     - Entry 1 (Cash Inflow - Revenue Portion): `3,000 LE`, `type="order_revenue"`, `category="Penjualan"`, `account="EGP"`.
     - Entry 2 (Cash Inflow - Deposit Portion): `2,000 LE`, `type="customer_deposit"`, `category="Titipan Pelanggan"`, `account="EGP"`.
  3. `db.customer_credit_events`:
     - `event_type`: `"credit_minted"`
     - `customer_id`: `cust_123`
     - `amount_le`: `2,000.0`
     - `source_order_id`: `ord_001`
     - `source_payment_id`: `pmt_001`
     - `status`: `"available"`
- **Financial Balances After Scenario A**:
  - Cash Account (EGP): `+5,000 LE` (Real cash in register).
  - Earned Sales Revenue: `+3,000 LE` (Attributed to Order #1).
  - Customer Credit Liability: `+2,000 LE` (Owed to `cust_123`).

#### Scenario B: Applying Credit to Order #2
- Customer places Order #2 Total: `2,500 LE`.
- Customer uses available `2,000 LE` credit + pays `500 LE` cash.
- **Ledger Entries Created**:
  1. Payment 1 (Credit Application):
     - `payment_method`: `"customer_credit"`
     - `amount_le`: `2,000.0 LE`
     - `allocations`: `[{"target_type": "product", "amount_le": 2000.0}]`
     - `db.customer_credit_events`:
       - `event_type`: `"credit_applied"`
       - `amount_le`: `-2,000.0`
       - `target_order_id`: `ord_002`
     - `db.finance_transactions`:
       - `amount`: `2,000 LE`, `type="credit_settlement"`, `category="Penjualan (Kredit)"`, `account="CUSTOMER_CREDIT"` (Non-cash internal settlement; recognized as earned revenue, zero physical cash movement).
  2. Payment 2 (Cash Payment):
     - `payment_method`: `"cash"`
     - `amount_le`: `500.0 LE`
     - `db.finance_transactions`: `amount`: `500 LE`, `type="order_revenue"`, `account="EGP"`.
- **Financial Balances After Scenario B**:
  - Cash Inflow: `+500 LE` (Only physical cash received).
  - Earned Sales Revenue: `+2,500 LE` (Order #2 recognized in full).
  - Customer Credit Liability: `0 LE` (Credit fully consumed).

#### Scenario C: Refunding Customer Credit
- Customer has `2,000 LE` credit and requests bank/cash refund.
- Admin performs refund:
  - `db.customer_credit_events`: `event_type="credit_refunded"`, `amount_le=-2000.0`.
  - `db.finance_transactions`:
    - `amount`: `2,000 LE`
    - `type`: `"expense"`
    - `category`: `"Pengembalian Deposit Pelanggan"`
    - `account`: `"EGP"`
- **Financial Balances After Scenario C**:
  - Cash Inflow: `-2,000 LE` (Cash leaves register).
  - Earned Sales Revenue: `0 LE` (Unchanged).
  - Customer Credit Liability: `0 LE` (Extinguished).

#### Scenario D: Voiding an Overpayment
- Originating payment `pmt_001` (from Scenario A) is voided before credit is spent.
- **Pre-condition Guard**: `credit_event` must still have status `"available"` (unspent). If credit has already been applied to Order #2, voiding `pmt_001` is **REJECTED** with HTTP 409 until Order #2 payment is unlinked.
- Inside single ACID transaction:
  - `db.payments`: `status="voided"`.
  - `db.finance_transactions`: both `order_revenue` and `customer_deposit` marked `is_void=True`.
  - `db.customer_credit_events`: `event_type="credit_reversed"`, `status="voided"`.

---

## 4. Data Models & Schemas

### 4.1 Collection: `customer_credit_events`
```json
{
  "_id": "ObjectId",
  "event_id": "cce_uuid12",
  "event_number": "CCE-202610-0001",
  "customer_id": "cust_oid",
  "event_type": "credit_minted | credit_applied | credit_refunded | credit_reversed",
  "amount_le": 2000.00,
  "currency": "EGP",
  "source_order_id": "order_oid",
  "source_payment_id": "pmt_oid",
  "target_order_id": "optional_order_oid",
  "target_payment_id": "optional_pmt_oid",
  "status": "available | consumed | refunded | voided",
  "remaining_amount_le": 2000.00,
  "idempotency_key": "unique_client_token",
  "created_by_id": "admin_oid",
  "created_by_name": "Finance Admin",
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601"
}
```

### 4.2 Indexes Required
- `customer_id` + `status` + `created_at` (Compound query for available balance).
- `source_payment_id` (Unique sparse index for minting events).
- `idempotency_key` (Unique sparse index).

---

## 5. API Contracts & Endpoints

### 5.1 Customer Credit Query
- `GET /admin/customers/{customer_id}/credit-balance`
  - *Response*:
    ```json
    {
      "customer_id": "607f1f77bcf86cd799439011",
      "available_credit_le": 2000.0,
      "pending_credit_le": 0.0,
      "total_minted_le": 5000.0,
      "total_consumed_le": 3000.0,
      "events": [...]
    }
    ```

### 5.2 Apply Credit to Order
- `POST /admin/orders/{order_id}/payments`
  - Payload supports `payment_method: "customer_credit"`.
  - Validates `customer_id` owns sufficient `available_credit_le`.
  - Deducts credit within the transaction.

### 5.3 Credit Refund
- `POST /admin/customers/{customer_id}/credit-refund`
  - *Payload*:
    ```json
    {
      "amount_le": 1000.0,
      "refund_method": "cash | transfer",
      "reason": "Permintaan pengembalian kelebihan transfer",
      "idempotency_key": "ref-12345"
    }
    ```

---

## 6. Financial Reporting Engine Updates (`_stats_for`)

In `backend/server.py`:
- `res[cur]["cash_inflow"]`: Sums `order_revenue` + `customer_deposit` + `income`.
- `res[cur]["revenue"]`: Sums `order_revenue` + `credit_settlement` + standard `income`.
- `res[cur]["credit_liability"]`: Sums active unspent credit.
- `res[cur]["operating_profit"]`: `revenue - cost`.
- `res[cur]["net_cash_flow"]`: `cash_inflow - cash_outflow`.

---

## 7. Acceptance Criteria for Phase 3 Implementation

1. **AC-01 (Normal Exact Payment)**: 1,000 LE payment on 1,000 LE order records 1,000 LE cash, 1,000 LE revenue, 0 LE credit.
2. **AC-02 (Overpayment Split)**: 1,500 LE payment on 1,000 LE order records 1,500 LE cash, 1,000 LE revenue, 500 LE customer credit.
3. **AC-03 (Credit Reuse)**: Applying 500 LE credit to Order #2 records 500 LE revenue, 0 LE duplicate cash, balance becomes 0 LE.
4. **AC-04 (No Negative Credit)**: Attempting to spend 600 LE credit when only 500 LE is available is rejected with HTTP 422.
5. **AC-05 (Concurrent Double-Spend Guard)**: Concurrent requests attempting to consume the same credit balance fail safely via optimistic locking or unique event indexing.
6. **AC-06 (Credit Refund)**: Refunding credit generates an `expense` cash outflow transaction and extinguishes credit balance.
7. **AC-07 (Voiding Originating Overpayment)**: Voiding unspent overpayment cleanly voids the payment, finance transactions, and credit event.
8. **AC-08 (Void Guard on Spent Credit)**: Voiding an overpayment whose credit has already been consumed is rejected with HTTP 409.
9. **AC-09 (Fail-Closed Transaction Safety)**: Any mid-write failure rolls back completely without standalone fallback in production.
10. **AC-10 (Historical Immutability)**: Historical orders created before Phase 3 activation maintain existing calculations.

---

## 8. Strategic Decisions Requiring Explicit Owner Approval

Prior to proceeding with implementation:
1. **Revenue Recognition Event Policy**:
   - *Option 1 (Payment-Time Match)*: Earned revenue is recognized when payment is applied, capped strictly at `order.total_le` (excess goes to deposit).
   - *Option 2 (Fulfillment-Time Recognition)*: All payments are held in deposit until order status reaches `siap` or `selesai`.
   *(Technical recommendation: Option 1 is standard for custom make-to-order manufacturing with upfront non-refundable deposits).*
2. **Dashboard Metric Labeling**:
   Confirm whether the three distinct cards on `AdminFinance.jsx` should be labeled:
   - `Penerimaan Kas Riil (Cash Flow)`
   - `Pendapatan Penjualan (Earned Revenue)`
   - `Kredit Pelanggan Tersedia (Customer Deposit Liability)`
3. **Approval to Proceed**:
   Does the owner approve this Scope Lock specification to proceed to Phase 3 implementation planning?
