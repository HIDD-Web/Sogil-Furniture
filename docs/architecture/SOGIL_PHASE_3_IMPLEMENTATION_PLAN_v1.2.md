# SOGIL FURNITURE — IMPLEMENTATION PLAN
## PHASE 3: CUSTOMER OVERPAYMENT CREDIT, REVENUE ATTRIBUTION & HANDOVER RECOGNITION
**Version:** v1.2  
**Status:** AUTHORITATIVE TECHNICAL IMPLEMENTATION PLAN — STRICT READ-ONLY PLANNING  
**Target Repository:** `HIDD-Web/Sogil-Furniture`  
**Baseline Git Commit:** `656d7960150e0b47d0295c5c736512308c721ee1`  
**Supersedes:** `SOGIL_PHASE_3_IMPLEMENTATION_PLAN_v1.1.md` and `SOGIL_PHASE_3_IMPLEMENTATION_PLAN_v1.0.md`  
**Reference Document:** `docs/architecture/SOGIL_PHASE_3_SCOPE_LOCK_v1.2.md`  
**Date:** 2026-10-10  

---

## 1. Executive Summary

This document specifies the sequenced engineering implementation for Phase 3, translating all business rules, accounting invariants, data structures, backend safeguards, and testing protocols into an actionable engineering plan.

### 1.1 Core System Capabilities
1. **Handover-Based Revenue Recognition**: Sales revenue recognized upon order status transitioning to `selesai`, snapshot immutably at the recognized order value (`order.recognized_revenue_le`).
2. **Immutable Snapshot Protection**: Subsequent price changes on mutable order fields do not silently alter recognized historical revenue.
3. **Backend-Enforced Safeguards on Handover Cancellation**: Strict confirmation, mandatory reason, elevated role checks, and immutable audit logs when moving from `selesai` to `dibatalkan`.
4. **Clean Economic Metric Separation**:
   - Primary: *Penerimaan Kas Riil*, *Pendapatan Penjualan*, *Kredit Pelanggan Tersedia*.
   - Secondary: *Uang Muka Pelanggan*, *Piutang Usaha*, *Kredit Digunakan*, *Kredit Dikembalikan*.
5. **Signed Event-Sourced Customer Credit**: Managed in `db.customer_credit_events` with ACID multi-document transaction boundaries.
6. **Legacy Compatibility**: Full backward compatibility for `type="order_revenue"` in cash reporting without historical data mutation.

---

## 2. Authoritative Data Model & Schemas

### 2.1 Collection: `customer_credit_events`
```json
{
  "_id": "ObjectId",
  "event_id": "cce_b8a92f01",
  "customer_id": "cust_607f1f77bcf86cd799439011",
  "currency": "EGP",
  "event_type": "credit_minted | credit_applied | credit_refunded | credit_reversed",
  "signed_amount": 2000.00,
  "source_type": "overpayment | goodwill | cancellation_refund | correction",
  "source_order_id": "ord_607f1f77bcf86cd799439012",
  "source_payment_id": "pmt_607f1f77bcf86cd799439013",
  "target_order_id": null,
  "reverses_event_id": null,
  "idempotency_key": "cce-idem-uuid-001",
  "notes": "Alokasi kelebihan transfer pada pesanan ORD-202610-001",
  "created_by_id": "admin_607f1f77bcf86cd799439010",
  "created_by_name": "Finance Admin",
  "created_at": "2026-10-10T14:30:00Z"
}
```
**Signed Amount Rules**:
- `credit_minted`: Positive (`signed_amount > 0`).
- `credit_applied`: Negative (`signed_amount < 0`).
- `credit_refunded`: Negative (`signed_amount < 0`).
- `credit_reversed`: Opposite sign of `reverses_event_id`.

**Indexes**:
- `{"customer_id": 1, "currency": 1, "created_at": 1}`
- `{"idempotency_key": 1}` (Unique, sparse)
- `{"source_payment_id": 1}` (Sparse)

### 2.2 Order Document Extensions (`db.orders`)
Added upon first transition to status `"selesai"`:
```json
{
  "completed_at": "2026-10-10T15:00:00Z",
  "completed_by_id": "admin_oid",
  "completed_by_name": "Finance Admin",
  "recognized_revenue_le": 3500.00,
  "status_history": [
    {
      "from_status": "siap",
      "to_status": "selesai",
      "changed_at": "2026-10-10T15:00:00Z",
      "changed_by_id": "admin_oid",
      "changed_by_name": "Finance Admin",
      "reason": null
    }
  ]
}
```

### 2.3 Collection: `finance_adjustments`
Created for explicit price corrections or formal product returns after handover:
```json
{
  "_id": "ObjectId",
  "adjustment_id": "adj_8f7b2c",
  "order_id": "order_oid",
  "type": "revenue_reversal | price_correction | bad_debt_writeoff",
  "currency": "EGP",
  "amount": -500.00,
  "reason": "Retur meja makan cacat produksi setelah serah terima",
  "idempotency_key": "adj-idem-token-123",
  "created_by_id": "owner_oid",
  "created_by_name": "Owner",
  "created_at": "2026-10-10T16:00:00Z"
}
```

---

## 3. Financial Calculation Formulas & Reporting Engine

### 3.1 Primary Dashboard Metrics (`_stats_for`, `_compute_balances`)
1. **Penerimaan Kas Riil (Real Cash Inflow)**:
   $$\text{Cash Inflow} = \sum_{\substack{\text{finance\_txns in period} \\ \text{is\_void} \neq \text{True}}} \left( \begin{cases} \text{amount} & \text{if } \text{type} \in [\text{"order\_payment"}, \text{"order\_revenue"}, \text{"income"}] \\ 0 & \text{otherwise} \end{cases} \right)$$
2. **Pendapatan Penjualan (Earned Sales Revenue)**:
   $$\text{Earned Revenue} = \sum_{\substack{\text{orders with } \text{completed\_at in period} \\ \text{status} = \text{"selesai"}}} \text{order.recognized\_revenue\_le} + \sum_{\substack{\text{finance\_txns in period} \\ \text{type} = \text{"income"}}} \text{amount} + \sum_{\substack{\text{adjustments in period}}} \text{amount}$$
3. **Kredit Pelanggan Tersedia (Available Customer Credit Liability)**:
   $$\text{Available Credit} = \sum_{\text{customer\_credit\_events}} \text{signed\_amount}$$

### 3.2 Secondary Breakdown Metrics
4. **Uang Muka Pelanggan (Customer Advances)**:
   $$\text{Customer Advances} = \sum_{\text{active orders with } \text{status} \neq \text{"selesai"} \land \text{status} \neq \text{"dibatalkan"}} \text{canonical\_paid\_le}$$
5. **Piutang Usaha (Accounts Receivable)**:
   $$\text{Receivables} = \sum_{\text{orders with } \text{status} = \text{"selesai"}} \max(0, \text{order.total\_le} - \text{canonical\_paid\_le})$$
6. **Kredit Digunakan (Credit Applied)**:
   $$\text{Credit Applied} = \left| \sum_{\substack{\text{credit\_events in period} \\ \text{event\_type} = \text{"credit\_applied"}}} \text{signed\_amount} \right|$$
7. **Kredit Dikembalikan (Customer Credit Refunded)**:
   $$\text{Credit Refunded} = \left| \sum_{\substack{\text{credit\_events in period} \\ \text{event\_type} = \text{"credit\_refunded"}}} \text{signed\_amount} \right|$$

---

## 4. Implementation Workstreams (Phased Roadmap)

### Workstream 3.B: Backend Architecture & Financial Invariants
- **Step 3.B.1**: Collections and indexes initialization (`db.customer_credit_events`, `db.finance_adjustments`).
- **Step 3.B.2**: Overpayment split and credit minting in `create_order_payment` ([server.py line 2400](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/backend/server.py#L2400)).
- **Step 3.B.3**: Non-cash credit settlement (`payment_method="customer_credit"`) within PyMongo multi-document ACID transaction.
- **Step 3.B.4**: Customer credit refund route `POST /admin/customers/{id}/credit-refund`.
- **Step 3.B.5**: Order status handover logic in `admin_update_order` ([server.py line 1998](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/backend/server.py#L1998)):
  - First transition to `selesai`: stamp `completed_at`, record `recognized_revenue_le`, append `status_history`.
  - Safeguard on `selesai` $\rightarrow$ `dibatalkan`: require `confirm_handover_cancellation`, mandatory reason, role check.
- **Step 3.B.6**: Explicit finance adjustment route `POST /admin/finance/adjustments`.
- **Step 3.B.7**: Reporting engine updates (`_stats_for`, `_compute_balances`) with primary and secondary metric breakdowns.

### Workstream 3.C: Automated Tests & Verification
- Implement and execute the comprehensive 40-scenario master test suite.

### Workstream 3.D: Frontend Dashboards & Admin UI
- Add primary KPI cards and secondary collapsible breakdown to `AdminFinance.jsx`.
- Add customer credit balance badge to `AdminCustomers.jsx`.
- Add credit settlement payment option to `AdminOrderDetail.jsx`.
- Add post-handover cancellation confirmation modal with reason prompt.

### Workstream 3.E: Independent Audit & Quality Gate
- Strict read-only verification of all changed lines against Phase 3 invariants.

### Workstream 3.F: Controlled Production Deployment
- Authorized commit, push, monitored Railway deployment, and runtime transaction verification.

---

## 5. Master Test Matrix (40 Comprehensive Scenarios)

| ID | Scenario | Preconditions | Action | Persisted Database Effects | Financial & Reporting Effects | Expected API Behavior |
| :---: | :--- | :--- | :--- | :--- | :--- | :--- |
| **TC-01** | Fully Paid Handover | Order 1,000 LE, paid 1,000 LE, `siap` | Status updated to `selesai` | `completed_at`, `recognized_revenue_le=1000`, `status_history` appended | Cash: 0, Rev: +1,000 LE, Advance: -1,000, Rec: 0 | HTTP 200; order clean |
| **TC-02** | Partially Paid Handover | Order 1,000 LE, paid 400 LE, `siap` | Status updated to `selesai` | `completed_at`, `recognized_revenue_le=1000`, `status_history` appended | Cash: 0, Rev: +1,000 LE, Advance: -400, Rec: +600 LE | HTTP 200; receivable tracked |
| **TC-03** | Unpaid Handover | Order 1,000 LE, paid 0 LE, `siap` | Status updated to `selesai` | `completed_at`, `recognized_revenue_le=1000`, `status_history` appended | Cash: 0, Rev: +1,000 LE, Advance: 0, Rec: +1,000 LE | HTTP 200; valid receivable |
| **TC-04** | Overpayment Before Handover | Order 1,000 LE, `diproses` | Customer pays 1,500 LE cash | `pmt` inserted, `cce` minted (+500), `ft` (1,500 cash) | Cash: +1,500, Rev: 0, Credit: +500, Advance: +1,000 | HTTP 200; credit available |
| **TC-05** | Advance Before Handover | Order 2,000 LE, `diproses` | Customer pays 500 LE DP cash | `pmt` inserted, `ft` (500 cash) | Cash: +500, Rev: 0, Credit: 0, Advance: +500 | HTTP 200; status `dp` |
| **TC-06** | Credit Applied to Order | Cust credit 500 LE, Order 500 LE | Pay order using `customer_credit` | `cce` applied (-500), `ft` (credit_settlement 500) | Cash: **0**, Rev: 0, Credit: -500 (bal 0), Advance: +500 | HTTP 200; zero cash inflow |
| **TC-07** | Customer Credit Refund | Cust credit 500 LE | Refund 500 LE cash | `cce` refunded (-500), `ft` (refund 500) | Cash: -500, Rev: 0, Credit: -500 (bal 0), Cost: 0 | HTTP 200; liability settled |
| **TC-08** | Legacy order_revenue Cash | Legacy `order_revenue` 2,000 LE | Call `_compute_balances()` | None (read query) | Cash Balance includes 2,000 LE; Rev unchanged | Balance includes legacy cash |
| **TC-09** | Duplicate Payment Request | Payment sent with `idempotency_key` | Retry same payload | Zero duplicate rows in `pmt`, `ft`, `cce` | Zero duplicate financial values | HTTP 200; returns existing |
| **TC-10** | Duplicate Handover Request | Order already `selesai` with snapshot | Retry status `selesai` with idem-key | Zero duplicate snapshot or history rows | Revenue recognized exactly once | HTTP 200; idempotent |
| **TC-11** | Repeated Selesai Update | Order `selesai` | Admin patches admin note / info | `updated_at` updated; `completed_at` untouched | Revenue unchanged | HTTP 200; snapshot immutable |
| **TC-12** | Order Total Edit Post-Handover | Order `selesai` (`recognized_rev=1000`) | Admin edits delivery fee (+200 LE) | `total_le=1200`, `recognized_revenue_le=1000` | Rev remains 1,000 LE; Receivable increases to 200 LE | HTTP 200; snapshot intact |
| **TC-13** | Explicit Post-Handover Correction | Goods partially returned | Formal `finance_adjustments` (-300 LE) | `adjustment` document inserted | Rev adjusted net to 700 LE; audit logged | HTTP 200; auditable contra rev |
| **TC-14** | Cancel Before Handover | Order `diproses`, paid 1,000 LE | Change status to `dibatalkan` | `order_status="dibatalkan"`, history logged | Rev: 0, Advance: -1,000, Credit/Refund: +1,000 | HTTP 200; standard cancel |
| **TC-15** | Post-Handover Cancel Unconfirmed | Order `selesai` | Patch status to `dibatalkan` (no confirm) | Zero database mutations | Zero financial changes | HTTP 400; missing confirmation |
| **TC-16** | Post-Handover Cancel No Reason | Order `selesai` | Patch `dibatalkan` (confirm=True, reason="")| Zero database mutations | Zero financial changes | HTTP 400; missing reason |
| **TC-17** | Post-Handover Cancel Authorized | Order `selesai`, owner role | Patch `dibatalkan` (confirm=True, valid reason)| Status `dibatalkan`, history logged with reason | `completed_at` & snapshot preserved; Rev not erased | HTTP 200; audit logged |
| **TC-18** | Post-Handover Cancel Unauthorized | Order `selesai`, staff role (no finance) | Patch `dibatalkan` (confirm=True, valid reason)| Zero database mutations | Zero financial changes | HTTP 403; forbidden |
| **TC-19** | Explicit Reversal After Handover | Order `selesai` cancelled | Create formal `revenue_reversal` adjustment | Adjustment inserted with full amount | Revenue reversed via contra entry | HTTP 200; clean reversal |
| **TC-20** | Duplicate Reversal Request | Reversal adjustment with idem-key | Retry reversal request | Zero duplicate adjustment rows | Zero duplicate reversal | HTTP 200; idempotent |
| **TC-21** | Credit Event Reversal | Overpayment credit minted (+500) | Admin voids originating payment | `cce` reversed (-500) referencing mint event | Credit balance returns to 0 LE | HTTP 200; linked reversal |
| **TC-22** | Legacy DP Unknown Paid | Historical `dp` order, 0 payments | Call `compute_order_payment_summary` | None (read query) | `paid_amount_le=None`, no synthetic credit minted | Flagged `legacy_dp_unknown` |
| **TC-23** | Legacy Selesai With Reliable Evidence | Pre-cutoff `selesai`, valid date `2026-08-01` | Query stats for August 2026 | None | Recognized in August period | Correct historical attribution |
| **TC-24** | Legacy Selesai No Evidence | Pre-cutoff `selesai`, unknown date | Query stats for post-cutoff period | None | Excluded from post-cutoff revenue | Zero fabricated revenue |
| **TC-25** | Pre-Cutoff Order Handed Over Post | Created pre-cutoff, delivered post | Status updated to `selesai` post-cutoff | `completed_at` stamped with current timestamp | Recognized in current active period | HTTP 200; clean cutoff |
| **TC-26** | Cross-Currency Payment & Snapshot | 357,000 IDR paid on 1,000 LE order | Payment recorded with rate 357 | `pmt` stored with rate snapshot, `ft` in IDR | Cash: +357,000 IDR, LE tracked accurately | HTTP 200; currency isolated |
| **TC-27** | Void Payment Exclusion | Valid cash payment recorded | Admin voids payment with reason | Payment & txn marked `is_void=True` | Excluded from cash balance and advances | HTTP 200; voided safely |
| **TC-28** | Fail-Closed Transaction Setup | Production mode, replica set fails | Attempt payment creation | Zero database mutations | Zero financial changes | HTTP 503; fail-closed |
| **TC-29** | Write Failure Abort | Credit insert fails mid-transaction | Error raised in PyMongo session | Complete ACID rollback | Zero orphaned payment or finance rows | HTTP 500; zero leaks |
| **TC-30** | Dashboard Reconciliation | 10 mixed orders, credit, payments | Call `/admin/finance/stats` | None | Cash $\neq$ Rev $\neq$ Credit; fully balanced | Balanced financial metrics |
| **TC-31** | Advances Excluded from Credit | Order `diproses`, paid 1,000 LE | Query customer credit endpoint | None | Customer credit = 0 LE; Advance = 1,000 LE | Clean separation |
| **TC-32** | No Synthetic Cash for Credit | 500 LE credit applied to Order B | Query cash flow in period | None | Physical cash flow = 0.00 | Zero cash inflation |
| **TC-33** | No Fabricated Legacy Credit | Legacy overpaid order pre-cutoff | Query customer credit | None | Available credit = 0 LE (unless authorized) | No automatic backfill |
| **TC-34** | Period Attribution Handover Date | Paid in Jan; Handover in Feb | Query stats Jan and Feb | None | Jan: +Cash, 0 Rev. Feb: 0 Cash, +Rev. | Proper GAAP timing |
| **TC-35** | Audit Actor & Timestamp Integrity | Handover performed by Admin X | Verify `order` document fields | `completed_by_id`, `completed_by_name`, `completed_at` | Fully auditable actor trail | Exact audit trail |
| **TC-36** | Concurrent Handover Protection | 2 concurrent requests set `selesai` | Handover update executed simultaneously | Exactly one writes `completed_at`; other is no-op | Revenue counted exactly once | Idempotent concurrency |
| **TC-37** | Concurrent Cancellation Safeguard | 2 concurrent post-handover cancels | Cancellation executed simultaneously | History logged idempotently | Zero duplicate reversal adjustments | Safe concurrency |
| **TC-38** | Immutable Snapshot After Adjustment | Adjustment (-200) applied post-handover| Query order document | `recognized_revenue_le` remains original value | Historical fact unchanged; net is computed | Audit preservation |
| **TC-39** | Finance Adjustment Auth | Staff without finance creates adjustment | Call `POST /admin/finance/adjustments` | Zero database mutations | Zero financial changes | HTTP 403; forbidden |
| **TC-40** | Historical Immutability Guarantee | Existing database before Phase 3 | Start application & run test suite | Zero pre-existing documents mutated | Complete data integrity | Baseline verified |

---

## 6. Historical Data Safety & Migration Strategy

1. **Zero Automated Rewriting**:
   Existing documents in `db.orders`, `db.payments`, and `db.finance_transactions` are treated as immutable read-only records.
2. **Explicit Cutoff Gate**:
   `PHASE_3_ACTIVATION_CUTOFF` determines whether modern split rules and handover snapshots apply.
3. **Rollback Strategy**:
   All new schema additions are additive. If code is reverted to baseline `656d796`, core order viewing and legacy payment processing continue operating without schema friction.
