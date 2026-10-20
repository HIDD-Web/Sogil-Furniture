# SOGIL FURNITURE — IMPLEMENTATION PLAN
## PHASE 3: CUSTOMER OVERPAYMENT CREDIT & REVENUE ATTRIBUTION
**Version:** v1.0  
**Status:** DRAFT SPECIFICATION & WORKSTREAM PLAN — STRICT READ-ONLY PLANNING  
**Target Repository:** `HIDD-Web/Sogil-Furniture`  
**Baseline Git Commit:** `656d7960150e0b47d0295c5c736512308c721ee1`  
**Date:** 2026-10-10  

---

## 1. Executive Summary

Phase 3 establishes financial correctness, auditability, and data integrity for **Customer Overpayments** and **Revenue Recognition** across the Sogil Furniture platform.

### Authoritative Business Invariants Locked by Business Owner:
1. **Unchanged Order-Status Workflow**:
   - `Siap Dikirim/Ambil` (`siap`): Production completed, product ready for delivery/pickup, but **NOT** yet handed over.
   - `Selesai` (`selesai`): Product has actually been handed over to or received by the customer.
   - No additional handover status or duplicate confirmation buttons will be introduced.
2. **Handover-Based Revenue Recognition**:
   - Sales revenue is recognized **exclusively upon actual handover** (represented by the existing transition to order status `Selesai`).
   - Customer payments, down payments, production completions, and `siap` transitions do **NOT** independently recognize sales revenue.
3. **Distinct Financial Concepts**:
   - **Penerimaan Kas Riil**: Actual money received through physical cash or bank transfer channels.
   - **Pendapatan Penjualan**: Revenue recognized from products actually handed over to customers (`order_status == "selesai"`).
   - **Kredit Pelanggan Tersedia**: Unspent customer deposits held as balance-sheet liabilities available for future orders or refund.
4. **Auditable Customer Credit Ledger**:
   - Overpayments and credits are managed via an immutable event-sourcing ledger (`db.customer_credit_events`), avoiding untraceable mutable balances.
5. **Historical Immutability**:
   - Existing historical transactions, payments, and orders remain unchanged. Phase 3 applies strictly to new transactions after an approved activation cutoff.

---

## 2. Verified Current Architecture & Source Evidence

### 2.1 Current Payment & Finance Data Flow
1. **Payment Submission**: `POST /admin/orders/{order_id}/payments` ([server.py line 2300](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/backend/server.py#L2300)).
2. **Persistence**:
   - Inserts into `db.finance_transactions`:
     ```python
     "type": "order_revenue",
     "category": "Penjualan",
     "amount": conv["primary_amount"] # Full cash received
     ```
   - Inserts into `db.payments`: `amount_le`, allocations (`product`, `shipping`, `unallocated_credit`).
3. **Defect**: In `_stats_for(s, e)` ([server.py lines 4918–4941](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/backend/server.py#L4918-L4941)), revenue is computed as:
   `if typ == "order_revenue": res[cur]["revenue"] += amt`
   This conflates physical cash inflow with recognized sales revenue and treats overpayment credit as earned sales revenue.

### 2.2 Order Completion & Handover Flow
1. **Status Update Route**: `PATCH /admin/orders/{order_id}` ([server.py lines 1998–2124](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/backend/server.py#L1998-L2124)).
2. **Current Audit Evidence**:
   - Calls `audit_fields(admin)` which sets `"updated_at"`, `"updated_by_id"`, `"updated_by_name"`.
   - **Gap Identified**: There is currently **no durable status transition history collection** or dedicated `"completed_at"` / `"handed_over_at"` timestamp on `db.orders`. If an order is edited repeatedly after becoming `selesai`, `"updated_at"` is overwritten.
   - **Compatible Improvement Planned**: When `order_status` transitions to `selesai`, atomically persist:
     - `completed_at`: Immutable timestamp of first transition to `selesai`.
     - `completed_by_id` / `completed_by_name`: Admin who performed the handover.
     - Append to an embedded `status_history` array on the order document: `[{"status": "selesai", "changed_at": now, "changed_by_name": admin_name}]`.

### 2.3 Customer Credit Capabilities
- **Verification Result**: **Zero customer credit infrastructure exists**.
- There is no `db.customer_credits` collection, no credit wallet on `db.customers`, and no payment method `"customer_credit"`. Excess payment is stored only as descriptive text inside `pmt.allocations`.

---

## 3. Proposed Target Architecture

```
[Customer Payment: 5,000 LE on 3,000 LE Order]
        │
        ├──> Physical Cash Ledger (db.finance_transactions):
        │      • Entry 1: 5,000 LE (type="order_payment", account="EGP")
        │      • Increases: "Penerimaan Kas Riil" (Cash Balance)
        │
        ├──> Customer Credit Ledger (db.customer_credit_events):
        │      • Event: "credit_minted" (+2,000 LE, status="available")
        │      • Increases: "Kredit Pelanggan Tersedia" (Liability)
        │
        └──> Revenue Recognition (On Handover / Selesai):
               • While order is diproses / siap: Recognized Revenue = 0 LE
               • When order transitions to "selesai": Recognized Revenue = 3,000 LE
               • Increases: "Pendapatan Penjualan"
```

### 3.1 Applying Credit to Subsequent Orders
- Customer places Order #2 Total: `2,000 LE`.
- Admin records payment with `payment_method = "customer_credit"`:
  - `db.customer_credit_events`: `event_type="credit_applied"`, `amount_le=-2000.0`.
  - `db.payments`: `amount_le=2000.0`, `payment_method="customer_credit"`.
  - `db.finance_transactions`: Non-cash internal contra entry (`type="credit_settlement"`), ensuring **ZERO duplicate physical cash movement** while enabling revenue recognition when Order #2 reaches `selesai`.

---

## 4. Financial Formulas

1. **Penerimaan Kas Riil (Real Cash Inflow)**:
   $$\text{Cash Inflow} = \sum \text{finance\_transactions}(\text{type} \in [\text{"order\_payment"}, \text{"income"}], \text{is\_void} \neq \text{True})$$
2. **Pendapatan Penjualan (Recognized Sales Revenue)**:
   $$\text{Recognized Revenue} = \sum_{\text{orders with } \text{status} = \text{"selesai"}} \min(\text{order.total\_le}, \text{canonical\_paid\_le})$$
   *(Or derived from fulfilled order settlement transactions, excluding unallocated customer deposits).*
3. **Kredit Pelanggan Tersedia (Available Customer Credit Liability)**:
   $$\text{Available Credit} = \sum \text{customer\_credit\_events}(\text{type} = \text{"credit\_minted"}) - \sum (\text{applied} + \text{refunded} + \text{reversed})$$
4. **Order Balance (Outstanding Receivable)**:
   $$\text{Outstanding Balance} = \max(0, \text{order.total\_le} - \text{canonical\_paid\_le})$$

---

## 5. Scope-Lock Reconciliation & Owner Policy Alignment

### Conflict in Previous Draft Scope Lock (`SOGIL_PHASE_3_SCOPE_LOCK_v1.0.md`):
- Section 3 of the draft scope lock proposed Option 1: recognizing revenue at payment time up to `order.total_le`.
- **Owner Resolution**: The owner has formally locked **Handover-Based Revenue Recognition** (`order_status == "selesai"`).
- **Resolution Plan**: `SOGIL_PHASE_3_SCOPE_LOCK_v1.0.md` will be cleanly superseded by `v1.1` in Phase 3.B to align 100% with handover-based recognition upon owner approval.

---

## 6. Implementation Workstreams

### Workstream 3.B: Backend Architecture & Financial Invariants
- **Scope**:
  1. `db.customer_credit_events` schema and indexes.
  2. Overpayment split logic in `admin_create_order_payment` (cash receipt vs credit minting).
  3. `payment_method="customer_credit"` implementation with multi-document ACID transaction.
  4. Handover revenue recognition trigger in `admin_update_order` on transition to `selesai`.
  5. Status history array and immutable `completed_at` timestamping.
  6. Credit refund endpoint (`POST /admin/customers/{id}/credit-refund`).
  7. Payment void reversal rules (blocking void if minted credit was already spent).
  8. `_stats_for()` and `_compute_balances()` reporting updates.
- **Dependencies**: Baseline `656d796`.
- **Risks**: Ensuring zero regression in Phase 1 canonical payments and Phase 2 wage calculations.

### Workstream 3.C: Automated Tests & Regression Coverage
- **Scope**: Comprehensive test suite covering all 33 scenarios in Section 7.
- **Dependencies**: Workstream 3.B.
- **Target**: Zero test failures across Phase 1, Phase 2, and Phase 3 suites.

### Workstream 3.D: Frontend Finance Dashboard & Admin UI
- **Scope**:
  1. Display three distinct cards on `AdminFinance.jsx`: *Penerimaan Kas Riil*, *Pendapatan Penjualan*, *Kredit Pelanggan Tersedia*.
  2. Customer credit balance badge and history table in `AdminCustomers.jsx`.
  3. "Gunakan Kredit Pelanggan" option in payment modal of `AdminOrderDetail.jsx`.
- **Dependencies**: Workstream 3.B APIs.

### Workstream 3.E: Independent Correctness & Security Review
- **Scope**: Read-only source audit of all Phase 3 modifications against financial invariants.

### Workstream 3.F: Controlled Release & Post-Deployment Verification
- **Scope**: Controlled local commit, verified push, Railway deployment monitoring, and startup probe verification.

---

## 7. Master Test Matrix (33 Scenarios)

| ID | Scenario | Initial State | Operation | Expected Outcome |
| :---: | :--- | :--- | :--- | :--- |
| **TC-01** | Exact Payment | Order total 1,000 LE | Customer pays 1,000 LE cash | Cash: +1,000 LE, Rev: 0 LE (order not selesai), Credit: 0 LE, Out: 0 LE |
| **TC-02** | Underpayment | Order total 1,000 LE | Customer pays 400 LE cash | Cash: +400 LE, Rev: 0 LE, Credit: 0 LE, Out: 600 LE |
| **TC-03** | Down Payment (DP) | Order total 2,000 LE | Customer pays 500 LE DP | Cash: +500 LE, Rev: 0 LE, Credit: 0 LE, Status: dp |
| **TC-04** | Overpayment Simple | Order total 1,000 LE | Customer pays 1,500 LE cash | Cash: +1,500 LE, Rev: 0 LE, Credit: +500 LE, Out: 0 LE |
| **TC-05** | Overpayment with Shipping | Order 1,000 LE + 100 LE ongkir | Customer pays 1,500 LE cash | Alloc: prod 1,000, ship 100, credit 400. Cash: +1,500 LE, Credit: +400 LE |
| **TC-06** | Credit Application (Full) | Cust has 500 LE credit | Settle Order #2 total 500 LE via credit | Cash: 0 LE, Credit: -500 LE (bal 0), Order #2 paid in full |
| **TC-07** | Credit Application (Partial) | Cust has 500 LE credit | Apply 300 LE credit on Order #2 (1,000 LE) | Cash: 0 LE, Credit: -300 LE (bal 200), Order #2 Out: 700 LE |
| **TC-08** | Multi-Order Credit Spend | Cust has 1,000 LE credit | Apply 600 LE to Ord A, 400 LE to Ord B | Credit balance becomes exactly 0 LE; both orders credited |
| **TC-09** | Insufficient Credit | Cust has 200 LE credit | Attempt to apply 300 LE credit | Rejected HTTP 422; zero mutations; balance remains 200 LE |
| **TC-10** | Concurrent Credit Spend | Cust has 500 LE credit | Two concurrent requests spend 500 LE | Exactly one succeeds; other fails with HTTP 409/422 (no double spend) |
| **TC-11** | Duplicate Payment Submission | Payment submitted with Idem-Key | Client retries same request | Returns existing payment; zero duplicate credit or cash writes |
| **TC-12** | Duplicate Credit Application | Credit applied with Idem-Key | Client retries credit application | Returns existing allocation; zero duplicate credit deductions |
| **TC-13** | Credit Refund Full | Cust has 500 LE credit | Admin refunds 500 LE via cash | Cash: -500 LE (expense), Credit: -500 LE (bal 0 LE), Rev: 0 LE |
| **TC-14** | Credit Refund Partial | Cust has 500 LE credit | Admin refunds 200 LE | Cash: -200 LE (expense), Credit: -200 LE (bal 300 LE) |
| **TC-15** | Duplicate Refund Request | Refund submitted with Idem-Key | Client retries refund request | Returns existing refund; zero duplicate cash outflow |
| **TC-16** | Credit Event Reversal | Admin manually corrects credit | Reversal event created | Immutable reversal event logged; balance adjusted; audit trail intact |
| **TC-17** | Cancel Order Before Handover | Order diproses, paid 1,000 LE | Order cancelled (`dibatalkan`) | Revenue recognized: 0 LE; paid cash convertible to credit/refund |
| **TC-18** | Cancel Order After Selesai | Order selesai, rev 1,000 LE | Order status changed to `dibatalkan` | Rev reversed cleanly via adjusting entry; audit log recorded |
| **TC-19** | Transition to "Siap" | Order diproses, paid 1,000 LE | Order status changed to `siap` | Revenue remains 0 LE (handover not occurred yet) |
| **TC-20** | Transition to "Selesai" | Order siap, paid 1,000 LE | Order status changed to `selesai` | Revenue recognized: exactly 1,000 LE; `completed_at` persisted |
| **TC-21** | Repeated "Selesai" Update | Order already selesai | Admin patches order note/status selesai | Revenue recognized exactly once (idempotent; no duplicate revenue) |
| **TC-22** | Status Reversal from Selesai | Order selesai, rev recognized | Status reverted to `diproses` | Revenue derecognized cleanly; audit history records reversal |
| **TC-23** | Revenue Recog Idempotency | Order selesai with 2 payments | Stats endpoint recomputed multiple times | Revenue matches order value exactly; zero duplication |
| **TC-24** | EGP Cash Payment | Raw amount 1,000 EGP | Cash EGP payment recorded | Currency EGP; primary account EGP; counterpart N/A |
| **TC-25** | IDR Transfer Snapshot | Raw amount 1,000 LE, rate 357 | Transfer IDR payment recorded | Primary IDR 357,000; snapshot rate 357 stored; EGP 1,000 tracked |
| **TC-26** | Legacy Order Without Payments | Order legacy lunas, 0 payments | Summary computed | Flagged `is_legacy_derived=True`; revenue recognized on selesai |
| **TC-27** | Historical Order Uncertain DP | Legacy DP order, 0 payments | Summary computed | Flagged `legacy_dp_unknown=True`; outstanding None; no fake credit |
| **TC-28** | Void Unspent Overpayment | Payment created +500 LE credit | Admin voids payment | Payment voided, finance voided, credit event voided (bal 0 LE) |
| **TC-29** | Void Spent Overpayment Guard | Payment created +500 LE credit | Credit spent on Ord B; admin voids | Rejected HTTP 409 (credit already consumed); preserves integrity |
| **TC-30** | Transaction Startup Failure | Production mode (`APP_ENV=prod`) | PyMongo `start_session` fails | Fails closed HTTP 503; zero writes to payments, finance, or credit |
| **TC-31** | Transaction Mid-Write Failure | Insert finance succeeds, credit fails | Database error on credit insert | Entire transaction aborts; zero orphaned finance or payment rows |
| **TC-32** | Dashboard Reconciliation | 10 mixed orders, overpayments, credit | Call `/admin/finance/stats` | Cash Inflow $\neq$ Revenue; Credit Liability matches ledger balance |
| **TC-33** | Zero Duplicate Economic Value | Customer pays 1,000 LE; spent on 2 ords | Flow completed | Cash received: 1,000 LE; total revenue across 2 ords: 1,000 LE |

---

## 8. Historical Data & Deployment Safety Plan

1. **Strict Immutability**:
   Existing orders and transactions will **not** be modified or rewritten.
2. **Phase 3 Cutoff Date (`PHASE_3_ACTIVATION_DATE`)**:
   - Payments recorded after the activation date generate split cash/credit transactions.
   - Historical payments recorded before the activation date are read-only and maintain their historical accounting representation.
3. **Future Optional Historical Reconciliation (Separate Phase)**:
   Any potential backfill of unallocated credits on pre-Phase-3 orders will require an independent dry-run audit report and explicit owner authorization.

---

## 9. Rollback and Recovery Strategy

- **Backend Flag / Fallback**: Phase 3 features are architected additively. If rolled back to baseline `656d796`, existing payments and orders continue functioning normally because canonical `db.payments` structures remain backward-compatible.
- **Data Integrity**: All credit operations run within ACID multi-document transactions with fail-closed gates.

---

## 10. Summary of Authoritative Decisions & Next Step

All core business requirements have been verified and locked.
- **Status**: The Implementation Plan [`docs/architecture/SOGIL_PHASE_3_IMPLEMENTATION_PLAN_v1.0.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/architecture/SOGIL_PHASE_3_IMPLEMENTATION_PLAN_v1.0.md) is complete and ready for owner review.
- **Next Step**: Await owner authorization to proceed to **Phase 3.B (Backend Architecture & Financial Invariants Implementation)**.
