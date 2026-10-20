# SOGIL FURNITURE — IMPLEMENTATION PLAN
## PHASE 3: CUSTOMER OVERPAYMENT CREDIT & REVENUE ATTRIBUTION
**Version:** v1.1  
**Status:** DRAFT SPECIFICATION & WORKSTREAM PLAN (CORRECTED) — STRICT READ-ONLY PLANNING  
**Target Repository:** `HIDD-Web/Sogil-Furniture`  
**Baseline Git Commit:** `656d7960150e0b47d0295c5c736512308c721ee1`  
**Supersedes:** `SOGIL_PHASE_3_IMPLEMENTATION_PLAN_v1.0.md`  
**Reference Document:** `docs/architecture/SOGIL_PHASE_3_SCOPE_LOCK_v1.1.md`  
**Date:** 2026-10-10  

---

## 1. Executive Summary & Design Core

Phase 3 establishes accounting correctness, financial auditability, and data integrity for **Customer Overpayments**, **Customer Advances**, **Available Credit**, and **Handover-Based Revenue Recognition** across the Sogil Furniture platform.

### Authoritative Business Invariants Locked by Owner:
1. **Unchanged Order Status Lifecycle**:
   - `Siap Dikirim/Ambil` (`siap`): Production completed, product ready for delivery/pickup, but **NOT** yet handed over to or received by the customer.
   - `Selesai` (`selesai`): Product has actually been handed over to or received by the customer.
   - No additional status or duplicate handover confirmation buttons will be introduced.
2. **Handover-Based Revenue Recognition**:
   - Sales revenue is recognized **exclusively upon actual handover** (represented by the existing transition to order status `Selesai`).
   - Revenue recognized upon handover equals the **full recognized sale value** (`order.total_le`), even if the order was only partially paid or unpaid at the moment of delivery.
   - Payments received before handover are treated as **Uang Muka Pelanggan** (Customer Advances / Deposit Liability), **NOT** recognized revenue.
3. **Distinct Financial Concepts**:
   - **Penerimaan Kas Riil**: Real fiat money received into physical cash or bank accounts.
   - **Pendapatan Penjualan**: Earned sales revenue recognized when goods are handed over (`order_status == "selesai"`).
   - **Uang Muka Pelanggan**: Customer deposits tied to unfulfilled orders (`order_status != "selesai"`).
   - **Kredit Pelanggan Tersedia**: Unallocated, freely available customer credit balance (from overpayments or approved credits) held as a liability.
   - **Piutang Usaha**: Outstanding order balance on completed orders (`selesai`).
4. **Historical Immutability & Safe Cutoff**:
   - Existing historical orders, payments, and `finance_transactions` must not be rewritten. Legacy records with `type="order_revenue"` continue to be counted as valid cash receipts.
   - Phase 3 rules apply strictly after an approved activation cutoff (`PHASE_3_ACTIVATION_CUTOFF`).
5. **Signed Event-Sourced Credit Ledger**:
   - Customer credits are managed via an immutable event ledger (`db.customer_credit_events`) with strict signed accounting and source event references.

---

## 2. Technical Architecture & Integration Points

### 2.1 Backend Data Structures & Collections

#### Collection: `db.customer_credit_events`
```json
{
  "_id": "ObjectId",
  "event_id": "cce_unique_str",
  "customer_id": "cust_oid",
  "currency": "EGP | IDR",
  "event_type": "credit_minted | credit_applied | credit_refunded | credit_reversed",
  "signed_amount": 2000.00,
  "source_order_id": "order_oid_optional",
  "source_payment_id": "pmt_oid_optional",
  "target_order_id": "order_oid_optional",
  "reverses_event_id": "cce_parent_event_id_optional",
  "idempotency_key": "unique_client_token",
  "notes": "Alasan / keterangan audit",
  "created_by_id": "admin_oid",
  "created_by_name": "Finance Admin",
  "created_at": "ISO-8601"
}
```
**Signed Amount Rules**:
- `credit_minted`: `> 0` (Increases liability)
- `credit_applied`: `< 0` (Decreases liability, settles order)
- `credit_refunded`: `< 0` (Decreases liability, cash outflow)
- `credit_reversed`:
  - If reversing a `credit_minted` (+X): `signed_amount = -X`
  - If reversing a `credit_applied` (-X): `signed_amount = +X`

**Indexes Required**:
- `customer_id` + `currency` + `created_at` (Compound index for running balance)
- `source_payment_id` (Sparse index)
- `idempotency_key` (Unique sparse index)

#### Audit Fields on `db.orders`:
- `completed_at`: Immutable timestamp of the first transition to `selesai`.
- `completed_by_id`, `completed_by_name`: Admin who recorded the handover.
- `status_history`: Array of transition events:
  ```json
  [
    {
      "from_status": "diproses",
      "to_status": "siap",
      "changed_at": "2026-10-10T10:00:00Z",
      "changed_by_name": "Admin A"
    },
    {
      "from_status": "siap",
      "to_status": "selesai",
      "changed_at": "2026-10-10T14:30:00Z",
      "changed_by_name": "Admin B"
    }
  ]
  ```

---

## 3. Financial Calculation Formulas & Reporting Engine

### 3.1 Real Cash Inflow & Outflow (`_compute_balances`, `_stats_for`)
- **Real Cash Inflow**:
  $$\text{Cash Inflow} = \sum \text{finance\_transactions}(\text{type} \in [\text{"order\_payment"}, \text{"order\_revenue"}, \text{"income"}], \text{is\_void} \neq \text{True})$$
  *(Preserves 100% backward compatibility with legacy `order_revenue` records).*
- **Real Cash Outflow**:
  $$\text{Cash Outflow} = \sum \text{finance\_transactions}(\text{type} \in [\text{"expense"}, \text{"refund"}, \text{"credit\_refund"}], \text{is\_void} \neq \text{True})$$
  *(Credit refunds decrease cash balance, but are tagged with `classification="liability_settlement"`, ensuring they do **NOT** inflate operational expenses/costs).*

### 3.2 Earned Sales Revenue
- **Period Recognized Revenue**:
  $$\text{Recognized Revenue} = \sum_{\substack{\text{orders with } \text{status} = \text{"selesai"} \\ \text{completed\_at in } [s, e]}} \text{order.total\_le} + \sum_{\substack{\text{finance\_txns } \text{type} = \text{"income"} \\ \text{date in } [s, e]}} \text{amount}$$
- **Revenue Invariant**:
  - Independent of whether the order was paid 0%, 50%, or 100% at delivery.
  - Independent of physical cash receipt timing.

### 3.3 Customer Advances (Uang Muka)
- Total cash collected for orders that are still unfulfilled:
  $$\text{Customer Advances} = \sum_{\text{order\_status} \neq \text{"selesai"}} \text{canonical\_paid\_le}$$

### 3.4 Available Customer Credit Liability
- Freely available customer credit derived from the ledger:
  $$\text{Available Credit} = \sum_{\text{events}} \text{signed\_amount}$$

### 3.5 Accounts Receivable (Piutang Usaha)
- Outstanding receivables on delivered orders:
  $$\text{Receivables} = \sum_{\text{order\_status} = \text{"selesai"}} \max(0, \text{order.total\_le} - \text{canonical\_paid\_le})$$

---

## 4. Implementation Workstreams

- **Workstream 3.B: Backend Architecture & Financial Invariants**
  - Collection `db.customer_credit_events` setup and indexes.
  - Payment creation: split cash vs credit minting; support `payment_method="customer_credit"`.
  - Credit refund endpoint: `POST /admin/customers/{id}/credit-refund` with liability classification.
  - Order status handover handling: atomic `completed_at` and `status_history` append.
  - Reversal and void safeguards: ACID transactions, non-negative balance checks.
  - Updated `_stats_for` and `_compute_balances` reporting.
- **Workstream 3.C: Automated Tests & Verification**
  - Implementation and execution of the revised 40-scenario test matrix.
- **Workstream 3.D: Frontend UI & Dashboards**
  - Financial dashboard metrics in `AdminFinance.jsx`.
  - Customer credit display in `AdminCustomers.jsx`.
  - Customer credit settlement option in `AdminOrderDetail.jsx`.
- **Workstream 3.E: Independent Audit & Pre-Commit Review**
  - Strict read-only audit of code changes against architectural invariants.
- **Workstream 3.F: Push & Monitored Deployment**
  - Authorized Git push, Railway deployment observation, and startup probe verification.

---

## 5. Master Test Matrix (Revised — 40 Scenarios)

The test matrix includes all core flows, edge cases, legacy backwards-compatibility, and the 16 mandatory design correction scenarios.

| ID | Category | Initial State | Operation | Cash Movement | Recognized Revenue | Customer Credit | Customer Advances | Receivables | Audit / Persistence Result |
| :---: | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **TC-01** | Standard Flow | Order total 1,000 LE, status `diproses` | Customer pays 1,000 LE cash | +1,000 LE | 0 LE | 0 LE | 1,000 LE | 0 LE | Payment recorded; txn `order_payment` |
| **TC-02** | Partial Payment | Order total 1,000 LE, status `diproses` | Customer pays 400 LE cash | +400 LE | 0 LE | 0 LE | 400 LE | 600 LE (unearned) | Status `dp`; canonical paid 400 LE |
| **TC-03** | Overpayment Split | Order total 1,000 LE, status `diproses` | Customer pays 1,500 LE cash | +1,500 LE | 0 LE | +500 LE | 1,000 LE | 0 LE | `credit_minted` (+500 LE); advance 1,000 LE |
| **TC-04** | Handover Partial Pay | Order total 1,000 LE, paid 400 LE, status `siap` | Transition status to `selesai` | 0 LE | +1,000 LE | 0 LE | 0 LE (-400 LE) | +600 LE (actual) | `completed_at` persisted; revenue = 1,000 LE |
| **TC-05** | Handover Zero Pay | Order total 1,000 LE, paid 0 LE, status `siap` | Transition status to `selesai` | 0 LE | +1,000 LE | 0 LE | 0 LE | +1,000 LE (actual) | `completed_at` persisted; valid receivable 1,000 LE |
| **TC-06** | Legacy Cash Count | Legacy txn `type="order_revenue"`, 2,000 LE | Calculate cash balances in `_compute_balances` | +2,000 LE | Unchanged | 0 LE | 0 LE | 0 LE | Legacy `order_revenue` counted as physical cash |
| **TC-07** | Credit Refund Accounting | Customer has 500 LE available credit | Admin refunds 500 LE via cash | -500 LE | 0 LE | -500 LE (bal 0 LE) | 0 LE | 0 LE | Txn `type="refund"`, `classification="liability_settlement"`; operating cost unaffected |
| **TC-08** | Credit Settlement | Customer has 500 LE credit, Order #2 (500 LE) | Pay Order #2 with `customer_credit` | **0 LE** | 0 LE (order `diproses`) | -500 LE (bal 0 LE) | +500 LE | 0 LE | Txn `type="credit_settlement"`; zero cash inflow; Order #2 paid |
| **TC-09** | Advance vs Credit | Order #1 total 1,000 LE, paid 1,000 LE (`diproses`) | Query customer available credit | 0 LE | 0 LE | **0 LE** | 1,000 LE | 0 LE | Allocated deposit is Advance, NOT available credit |
| **TC-10** | Repeated Selesai Update | Order already `selesai`, `completed_at` set | Admin updates admin note or resaves `selesai` | 0 LE | Exactly 1,000 LE (no change) | 0 LE | 0 LE | Unchanged | `completed_at` immutable; zero duplicate revenue |
| **TC-11** | Erroneous Status Change | Order `selesai` with `completed_at`, rev recognized | Admin reverts status to `diproses` | 0 LE | Preserved / Flagged | 0 LE | 0 LE | Unchanged | Transition logged in `status_history`; revenue not silently deleted |
| **TC-12** | Explicit Rev Correction | Order `selesai` cancelled/returned by owner | Owner issues formal return adjustment | 0 LE | -1,000 LE (contra) | 0 LE | 0 LE | 0 LE | Auditable contra adjustment logged in `finance_adjustments` |
| **TC-13** | Pre-Cutoff Order Handover | Order created pre-cutoff (1,000 LE, paid 1,000) | Transitioned to `selesai` after cutoff | 0 LE | +1,000 LE (current period) | 0 LE | -1,000 LE | 0 LE | `completed_at` stamped now; revenue recognized post-cutoff |
| **TC-14** | Pre-Cutoff Historical | Order marked `selesai` 6 months ago, no timestamp | Compute current period stats | 0 LE | 0 LE (not in period) | 0 LE | 0 LE | 0 LE | Historical order not backfilled; historical stats undisturbed |
| **TC-15** | Duplicate Refund Request | Refund submitted with `idempotency_key` | Client retries same request | 0 LE extra | 0 LE | 0 LE extra | 0 LE | 0 LE | Second request returns existing refund; no duplicate payout |
| **TC-16** | Credit-Mint Reversal | Overpayment minted +500 LE credit in error | Admin voids originating payment | 0 LE (txn voided) | 0 LE | -500 LE (`credit_reversed`) | 0 LE | 0 LE | Event `credit_reversed` logged referencing source mint event |
| **TC-17** | Credit-Apply Reversal | Credit applied (-300 LE) on order; order cancelled | Order cancelled before production | 0 LE | 0 LE | +300 LE (`credit_reversed`) | -300 LE | 0 LE | Event `credit_reversed` restores customer available credit |
| **TC-18** | Currency Isolation | Customer has 500 EGP credit and 0 IDR credit | Attempt to pay 500 IDR using credit | 0 LE | 0 LE | 500 EGP unchanged | 0 LE | 0 LE | Rejected HTTP 422: Currency mismatch; EGP credit cannot settle IDR |
| **TC-19** | Old vs New Txn Reconcil | Mix of legacy `order_revenue` & new `order_payment` | Run finance stats query | Total = Old + New | Independent metrics | Valid | Valid | Valid | Balance equals sum of legacy and modern cash flows |
| **TC-20** | Insufficient Credit | Customer has 200 LE credit | Attempt to apply 300 LE credit | 0 LE | 0 LE | 200 LE unchanged | 0 LE | 0 LE | Rejected HTTP 422; transaction rolled back |
| **TC-21** | Concurrent Credit Spend | Customer has 500 LE credit | 2 simultaneous requests spend 500 LE | 0 LE | 0 LE | Exactly 0 LE | +500 LE | 0 LE | One succeeds, one rejected; no double spending |
| **TC-22** | Duplicate Payment Retries | Payment submitted with `idempotency_key` | Client network timeout & resend | 0 LE extra | 0 LE | 0 LE extra | 0 LE | 0 LE | Returns existing payment; zero duplicate ledger entries |
| **TC-23** | Transition to "Siap" | Order `diproses`, paid 1,000 LE | Status changed to `siap` | 0 LE | **0 LE** | 0 LE | 1,000 LE | 0 LE | Handover not occurred; revenue remains 0 LE |
| **TC-24** | Void Spent Credit Guard | Overpayment +500 LE credit; credit spent on Ord #2 | Admin attempts to void initial payment | 0 LE | 0 LE | Unchanged | Unchanged | Unchanged | Rejected HTTP 409; cannot void payment whose credit is already consumed |
| **TC-25** | ACID Fail-Closed Test | Payment creation fails mid-transaction | Error during credit event write | 0 LE | 0 LE | 0 LE | 0 LE | 0 LE | Entire transaction aborts; zero orphaned finance or payment rows |
| **TC-26** | EGP Cash Flow Isolation | Customer pays 1,000 EGP cash | Recorded on EGP account | +1,000 EGP | 0 LE | 0 LE | 1,000 EGP | 0 LE | EGP account balance increases; IDR balance unchanged |
| **TC-27** | IDR Transfer Snapshot | Customer pays 357,000 IDR (rate 357 = 1,000 LE) | Recorded on IDR account | +357,000 IDR | 0 LE | 0 LE | 1,000 LE | 0 LE | IDR cash increases; order tracked in LE snapshot |
| **TC-28** | Partial Credit + Cash | Order total 1,000 LE; Cust has 400 LE credit | Pays 400 LE credit + 600 LE cash | +600 LE cash | 0 LE | -400 LE (bal 0 LE) | 1,000 LE | 0 LE | Order fully paid; cash inflow only 600 LE |
| **TC-29** | Credit Refund Partial | Customer has 500 LE credit | Admin refunds 200 LE cash | -200 LE | 0 LE | -200 LE (bal 300 LE) | 0 LE | 0 LE | Cash leaves register; remaining credit is 300 LE |
| **TC-30** | Historical Legacy DP Order | Order legacy with `payment_status="dp"`, 0 txns | Summary computed | 0 LE | 0 LE | 0 LE | Unknown | Unknown | Flagged `legacy_dp_unknown=True`; no fake credit minted |
| **TC-31** | Cancel Unfulfilled Order | Order `diproses`, customer paid 1,000 LE advance | Order cancelled (`dibatalkan`) | 0 LE | 0 LE | +1,000 LE (if transferred) | 0 LE (-1,000) | 0 LE | Advance converted to available customer credit or refunded |
| **TC-32** | Handover Overpaid Order | Order 1,000 LE, customer paid 1,500 LE | Order status changed to `selesai` | 0 LE | +1,000 LE | 500 LE unchanged | 0 LE (-1,000) | 0 LE | Revenue is exactly order value (1,000 LE); credit remains 500 LE |
| **TC-33** | Multiple Partial Payments | Order 2,000 LE; pays 500, then 800 LE | Both recorded during production | +1,300 LE | 0 LE | 0 LE | 1,300 LE | 700 LE | Advance accumulates to 1,300 LE; revenue recognized at handover |
| **TC-34** | Date-Range Stats Attribution | Payment in Jan; Handover (`selesai`) in Feb | Query stats for Feb | Jan: +1,000 Cash, Feb: 0 Cash | Jan: 0 Rev, Feb: +1,000 Rev | 0 LE | Jan: +1,000, Feb: 0 | 0 LE | Cash attributed to Jan; Revenue attributed to Feb |
| **TC-35** | Credit Ledger Balance Query | Mint +500, Apply -200, Mint +100, Refund -150 | Query credit balance endpoint | Net cash flows | 0 LE | 250 LE | 0 LE | 0 LE | Signed ledger sums to exactly 250 LE |
| **TC-36** | Void Credit Application | Payment via credit voided (before handover) | Void credit payment | 0 LE | 0 LE | +Amount (restored) | -Amount | +Amount | Credit restored to customer; order balance re-opened |
| **TC-37** | Zero Amount Payment Guard | Admin attempts payment with amount = 0 | Validation check | 0 LE | 0 LE | 0 LE | 0 LE | 0 LE | Rejected HTTP 400; no records created |
| **TC-38** | Negative Amount Guard | Admin attempts payment with amount < 0 | Validation check | 0 LE | 0 LE | 0 LE | 0 LE | 0 LE | Rejected HTTP 400; negative payments disallowed |
| **TC-39** | Goodwill Credit Mint | Admin grants 100 LE credit compensation | Direct credit minting event | 0 LE | 0 LE | +100 LE | 0 LE | 0 LE | Minted with `source_type="goodwill"`; zero cash movement |
| **TC-40** | Total Economic Reconciliation | Customer deposits 1,000 LE; spent across 2 orders | Full flow completed | Cash = 1,000 LE | Rev = 1,000 LE | Bal = 0 LE | Bal = 0 LE | Bal = 0 LE | Zero economic duplication; perfect reconciliation |

---

## 6. Historical Migration & Deployment Safeguards

1. **Zero Retroactive Mutation**:
   Historical documents in `db.orders`, `db.payments`, and `db.finance_transactions` will remain completely unmutated.
2. **Explicit Activation Cutoff**:
   - `PHASE_3_ACTIVATION_CUTOFF` configured in backend settings.
   - Payments created after this cutoff execute Phase 3 split logic.
   - Order handovers after this cutoff stamp `completed_at` and trigger Phase 3 revenue recognition.
3. **Rollback Safety**:
   - Schema additions (`db.customer_credit_events`, `order.completed_at`, `order.status_history`) are strictly additive.
   - If backend is rolled back to baseline `656d796`, existing endpoints continue operating without schema corruption.
