# SOGIL FURNITURE — ARCHITECTURE SPECIFICATION AUDIT REPORT
## PHASE 3.A.3: INDEPENDENT CONSISTENCY AUDIT REPORT
**Audit Date:** 2026-10-10  
**Target Repository:** `HIDD-Web/Sogil-Furniture` (`/Users/syahidmujahid/Sogil-Project/Sogil-Furniture`)  
**Production Git Baseline:** Commit `656d7960150e0b47d0295c5c736512308c721ee1`  
**Audit Execution Mode:** **STRICT READ-ONLY AUDIT** (No files modified, zero database mutations, no commits/pushes/deploys)  

---

## 1. Executive Summary

This independent consistency audit evaluated the Phase 3 financial architecture specifications across versions v1.0, v1.1, v1.2, the Phase 3.A.2 final audit report, and relevant production backend source code (`backend/server.py`).

The objective is to determine whether the specifications provide a mathematically rigorous, internally consistent, backward-compatible, and technically actionable blueprint for Phase 3.B implementation.

### Key Audit Conclusions:
1. **Core Accounting Model is Substantively Sound**: The foundational separation of **Penerimaan Kas Riil** (real cash receipts), **Pendapatan Penjualan** (handover-based earned revenue), and **Kredit Pelanggan Tersedia** (event-sourced liability ledger) directly addresses the overpayment revenue distortion defect in production.
2. **Material Ambiguities and Contradictions Identified**:
   - **Contradiction on "Income" in Pendapatan Penjualan**: Scope Lock v1.2 defines `Pendapatan Penjualan` strictly as earned sales revenue from handed-over orders, yet the reporting formula in both Scope Lock v1.2 (L204) and Implementation Plan v1.2 (L110) appends non-sales `income` transactions ($\sum \text{finance\_transactions}(\text{type}="income")$) to this metric without separating them or labeling it as total gross revenue.
   - **Order Model Schema Gap for Post-Handover Cancellation**: Scope Lock v1.2 (L110) mandates `confirm_handover_cancellation` and `cancellation_reason` on `PATCH /admin/orders/{id}`, but the Pydantic schema `OrderStatusUpdate` in `backend/server.py` (L287) does not currently declare these fields, and the Implementation Plan v1.2 omitted explicit Pydantic schema extension steps for `OrderStatusUpdate`.
   - **Revenue Snapshot Immutability vs. Receivables Formula Discrepancy**: Scope Lock v1.2 states that `recognized_revenue_le` is snapshot at handover and never changes even if `order.total_le` is edited. However, the receivables formula in Scope Lock v1.2 (L207) and Implementation Plan v1.2 (L118) is written as $\max(0, \text{order.total\_le} - \text{canonical\_paid\_le})$ rather than $\max(0, \text{order.recognized\_revenue\_le} - \text{canonical\_paid\_le})$, creating an inconsistency if price changes occur post-handover.
   - **Cross-Currency Formula Mixing**: Scope Lock v1.2 table formulas sum `amount` across `account in ["EGP", "IDR"]` directly into `Penerimaan Kas Riil` without reiterating that IDR and EGP must remain strictly segregated into distinct currency buckets (`res["EGP"]["cash_inflow"]` and `res["IDR"]["cash_inflow"]`), as implemented in `backend/server.py` (`_stats_for`).
3. **Final Verdict**: **CONDITIONALLY READY — OWNER DECISIONS REQUIRED & CORRECTIONS NOTED**. (Implementation Phase 3.B must remain on hold until the owner approves the clarifications specified in Section 11).

---

## 2. Documents Under Review & Repository Verification

### 2.1 Audited Documents
1. `docs/architecture/SOGIL_PHASE_3_SCOPE_LOCK_v1.2.md` (Authoritative Scope Lock v1.2)
2. `docs/architecture/SOGIL_PHASE_3_IMPLEMENTATION_PLAN_v1.2.md` (Authoritative Implementation Plan v1.2)
3. `docs/architecture/SOGIL_PHASE_3A2_FINAL_SPEC_AUDIT.md` (Phase 3.A.2 Audit Deliverable)
4. Historical comparisons: `SOGIL_PHASE_3_SCOPE_LOCK_v1.1.md`, `SOGIL_PHASE_3_IMPLEMENTATION_PLAN_v1.1.md`, `SOGIL_PHASE_3_SCOPE_LOCK_v1.0.md`, `SOGIL_PHASE_3_IMPLEMENTATION_PLAN_v1.0.md`.
5. Codebase references: `backend/server.py` (`admin_create_order_payment`, `admin_update_order`, `admin_void_order_payment`, `_stats_for`, `_compute_balances`).

### 2.2 Working Tree Verification Before Audit
- Git status clean for tracked files matching baseline commit `656d7960150e0b47d0295c5c736512308c721ee1`.
- SHA-256 Checksums of existing Phase 3 documents before audit:
  - `docs/architecture/SOGIL_PHASE_3_SCOPE_LOCK_v1.2.md`: `ae33e53d6f1d287546c5cfc93b54387bc319200dbf9558180cc0d315d6ee1746`
  - `docs/architecture/SOGIL_PHASE_3_IMPLEMENTATION_PLAN_v1.2.md`: `3d5d34cc8880902478e19b4a4d5447fb3e5392f9f85437379927117945428538`
  - `docs/architecture/SOGIL_PHASE_3A2_FINAL_SPEC_AUDIT.md`: `e0871dba7c23f6ad9cd46b23923450522d396cd1c3b8ec2cae04b9ffd78090e4`

---

## 3. Findings Grouped by Severity

### CRITICAL FINDINGS (0 Found)
*No critical defects that would cause catastrophic database corruption or irreversible loss were found.*

---

### HIGH FINDINGS (2 Found)

#### [FINDING-H01] Non-Sales "Income" Conflation in "Pendapatan Penjualan" Metric
- **Classification**: DEFECT / CONTRADICTION
- **Affected Documents**:
  - `SOGIL_PHASE_3_SCOPE_LOCK_v1.2.md` (Section 4.1, line 204)
  - `SOGIL_PHASE_3_IMPLEMENTATION_PLAN_v1.2.md` (Section 3.1, line 110)
- **Evidence**:
  The metric title approved by the owner is **Pendapatan Penjualan** (Sales Revenue).
  In Scope Lock v1.2 (L204) and Implementation Plan v1.2 (L110), the formula is given as:
  $$\text{Pendapatan Penjualan} = \sum_{\substack{\text{orders completed}}} \text{recognized\_revenue\_le} + \sum_{\substack{\text{finance\_txns} \\ \text{type} = \text{"income"}}} \text{amount} + \sum \text{adjustments}$$
- **Explanation**:
  `finance_transactions` with `type="income"` represent miscellaneous non-sales income (e.g. scrap wood sales, rental income, interest, or owner capital injection classified as income). Adding miscellaneous non-sales `income` directly into a KPI titled *Pendapatan Penjualan* contradicts the core business rule to separate sales revenue earned on handover from general income.
- **Concrete Impact**:
  If a business records 50,000 LE from scrap material sales (`type="income"`), the dashboard shows 50,000 LE under *Pendapatan Penjualan*, misrepresenting furniture sales volume.
- **Required Resolution**:
  Separate the metrics into:
  1. `Pendapatan Penjualan (Sales Revenue)`: Derived exclusively from handed-over orders (`order.recognized_revenue_le`) $\pm$ order-related `finance_adjustments`.
  2. `Pendapatan Lain-lain (Other Income)`: $\sum \text{finance\_transactions}(\text{type}="income")$.
  3. `Total Pendapatan (Total Revenue)`: $\text{Pendapatan Penjualan} + \text{Pendapatan Lain-lain}$.
- **Owner Decision Required**: Yes. (Decision Question 1 in Section 11).

---

#### [FINDING-H02] Receivables Calculation Formula Uses Mutable `order.total_le` Instead of Snapshot
- **Classification**: DEFECT / INCONSISTENCY
- **Affected Documents**:
  - `SOGIL_PHASE_3_SCOPE_LOCK_v1.2.md` (Section 3.1, L105; Section 4.1, L207)
  - `SOGIL_PHASE_3_IMPLEMENTATION_PLAN_v1.2.md` (Section 3.2, L118)
- **Evidence**:
  Scope Lock v1.2 states:
  $$\text{Piutang Usaha} = \sum_{\text{status} = \text{"selesai"}} \max(0, \text{order.total\_le} - \text{canonical\_paid\_le})$$
  However, Section 1.1 (Rule 2) and Section 3.1 (L98) explicitly state that `recognized_revenue_le` is the immutable snapshot of sale value at handover, and subsequent edits to `order.total_le` must not silently rewrite recognized financial value.
- **Explanation**:
  If an order is delivered with total 1,000 LE and paid 400 LE, recognized revenue is 1,000 LE, paid is 400 LE, and receivable is 600 LE.
  If an admin later edits `order.total_le` to 1,200 LE:
  - If receivable is computed from `order.total_le`, receivable becomes $1,200 - 400 = 800$ LE.
  - Recognized revenue remains snapshot at 1,000 LE.
  - Now, $\text{Revenue (1,000)} \neq \text{Paid (400)} + \text{Receivable (800)}$, breaking the accounting identity $\text{Recognized Revenue} = \text{Cash Collected} + \text{Receivable}$.
- **Required Resolution**:
  The receivables formula for handed-over orders must reference the immutable recognized revenue plus any explicit authorized price adjustments:
  $$\text{Piutang Usaha} = \max(0, (\text{order.recognized\_revenue\_le} + \text{net\_adjustments}) - \text{canonical\_paid\_le})$$
  Post-handover edits to `order.total_le` directly on the order document must be blocked unless accompanied by an authorized `finance_adjustment`.

---

### MEDIUM FINDINGS (3 Found)

#### [FINDING-M01] Missing Pydantic Schema Extension for Handover Cancellation Safeguards
- **Classification**: EXISTING-CODE COMPATIBILITY RISK / IMPLEMENTATION GAP
- **Affected Documents & Code**:
  - `SOGIL_PHASE_3_SCOPE_LOCK_v1.2.md` (Section 3.2, L108–L113)
  - `backend/server.py` (`OrderStatusUpdate` class, lines 287–296)
- **Evidence**:
  Scope Lock v1.2 requires `confirm_handover_cancellation: bool` and `cancellation_reason: str` in the payload to `PATCH /admin/orders/{id}` when cancelling an order that reached `selesai`.
  In `backend/server.py`:
  ```python
  class OrderStatusUpdate(BaseModel):
      order_status: Optional[str] = None
      payment_status: Optional[str] = None
      payment_method: Optional[str] = None
      admin_note: Optional[str] = None
      subtotal_le: Optional[float] = None
      delivery_fee_le: Optional[float] = None
      discount_le: Optional[float] = None
      total_le: Optional[float] = None
      items: Optional[List[dict]] = None
  ```
- **Explanation**:
  Because `OrderStatusUpdate` does not declare `confirm_handover_cancellation` or `cancellation_reason`, FastAPI / Pydantic would strip or ignore these fields if extra fields are ignored, or fail validation if strict mode is enabled.
- **Required Resolution**:
  Workstream 3.B.5 in Implementation Plan v1.2 must explicitly specify extending `OrderStatusUpdate` with:
  ```python
  confirm_handover_cancellation: Optional[bool] = False
  cancellation_reason: Optional[str] = None
  ```

---

#### [FINDING-M02] Cross-Currency Summation Notation in Dashboard Table
- **Classification**: AMBIGUOUS SPECIFICATION
- **Affected Documents**:
  - `SOGIL_PHASE_3_SCOPE_LOCK_v1.2.md` (Section 4.1, L203)
- **Evidence**:
  The table entry for *Penerimaan Kas Riil* states:
  $\sum \text{amount}$ where `type in ["order_payment", "order_revenue", "income"]` and `account in ["EGP", "IDR"]`.
- **Explanation**:
  Adding raw EGP amounts and IDR amounts together directly produces nonsensical sums (e.g. 1,000 EGP + 357,000 IDR $\neq$ 358,000). While the existing codebase `_stats_for()` correctly segments results by currency (`res["IDR"]` and `res["EGP"]`), the mathematical table in the specification must explicitly specify per-currency isolation ($res[cur]$) to avoid any implementation regression.
- **Required Resolution**:
  Clarify formula notation to explicitly state:
  $$\text{Cash Inflow}(cur) = \sum_{\substack{\text{txns in currency } cur}} \text{amount}$$

---

#### [FINDING-M03] Ambiguity in Date Filter for Order Revenue Attribution
- **Classification**: AMBIGUOUS SPECIFICATION
- **Affected Documents**:
  - `SOGIL_PHASE_3_IMPLEMENTATION_PLAN_v1.2.md` (Section 3.1, L110)
- **Evidence**:
  $$\text{Earned Revenue} = \sum_{\substack{\text{orders with } \text{completed\_at in period} \\ \text{status} = \text{"selesai"}}} \text{order.recognized\_revenue\_le}$$
- **Explanation**:
  If an order was handed over in January (`completed_at = "2026-01-15T10:00:00Z"`), but in February an admin cancels the order (`order_status = "dibatalkan"` with reason):
  - When finance reports for January are re-run, if the query requires `status == "selesai"`, this order is now excluded because `status == "dibatalkan"`.
  - Consequently, January's historical recognized revenue would drop retroactively, violating the invariant: *"Do not silently erase recognized revenue merely because current order status changes"*.
- **Required Resolution**:
  Revenue query must filter by orders that have `completed_at` in the period, and exclude only orders where an explicit `finance_adjustment` of type `revenue_reversal` exists in that period, rather than filtering on `current order_status == "selesai"`.

---

### LOW FINDINGS (1 Found)

#### [FINDING-L01] Test Case TC-11 API Behavior Description
- **Classification**: MINOR SPECIFICATION OMISSION
- **Affected Documents**:
  - `SOGIL_PHASE_3_IMPLEMENTATION_PLAN_v1.2.md` (Test Matrix TC-11, line 170)
- **Evidence**:
  TC-11 states: *"Admin patches admin note / info; updated_at updated; completed_at untouched"*.
  API response description notes `HTTP 200; snapshot immutable`, but does not explicitly assert that `recognized_revenue_le` is returned in the API order summary.
- **Required Resolution**:
  Add explicit assertion that `clean(order)["recognized_revenue_le"]` is returned unchanged.

---

## 4. Numerical Reconciliation Examples

To verify mathematical consistency, the 8 required cases were evaluated in memory against the proposed models:

| Case | Scenario Details | Cash Receipt ($\Delta$ Cash) | Recognized Revenue ($\Delta$ Rev) | Customer Advances | Customer Credit | Accounts Receivable | Notes / Balance Sheet Integrity |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **A** | 1,000 LE order paid in full before handover (`diproses`) | +1,000 LE | **0 LE** | +1,000 LE | 0 LE | 0 LE | Cash received; unearned advance liability; revenue deferred. |
| **B** | 1,000 LE order receives 300 LE advance (`diproses`) | +300 LE | **0 LE** | +300 LE | 0 LE | 0 LE (unearned) | Advance liability = 300 LE; remaining 700 LE is unbilled contract. |
| **C** | Case B order handed over (`selesai`) with 300 LE paid | 0 LE | **+1,000 LE** | **-300 LE (bal 0)**| 0 LE | **+700 LE** | Advance converts to revenue; unpaid portion recognized as Receivable. $\text{Rev}(1000) = \text{Cash}(300) + \text{Rec}(700)$. |
| **D** | 1,000 LE order receives 1,200 LE before handover (`diproses`) | +1,200 LE | **0 LE** | +1,000 LE | **+200 LE** | 0 LE | Cash = +1,200 LE; Advance = 1,000 LE; Available Credit = 200 LE. No revenue recognized. |
| **E** | Customer has 500 LE credit; applies 200 LE to Order #2 | **0 LE** | **0 LE** | +200 LE | **-200 LE (bal 300)**| 0 LE | Non-cash settlement. Cash movement = 0. Credit liability decreases; Order #2 advance increases. |
| **F** | 200 LE customer credit refund issued | **-200 LE** | **0 LE** | 0 LE | **-200 LE (bal 0)** | 0 LE | Real cash outflow (-200 LE); liability settled (-200 LE). Operating costs unaffected. |
| **G** | Order handed over (snapshot 1,000 LE); total_le edited to 1,200 LE | 0 LE | **1,000 LE (intact)**| 0 LE | 0 LE | **See Finding H02** | Snapshot guarantees revenue remains 1,000 LE. Receivables formula must use snapshot + adjustment. |
| **H** | Handed-over order cancelled without financial return | 0 LE | **1,000 LE (intact)**| 0 LE | 0 LE | Retained / In Dispute | `completed_at` & snapshot preserved. Revenue not erased. Financial reversal requires explicit adjustment. |

**Audit Conclusion on Numerical Cases**:
The core accounting model reconciles cleanly without double counting. Cash, Advances, Available Credit, and Revenue remain strictly partitioned.

---

## 5. Traceability & Quality Gate Analysis

| Audit Area | Scope Lock v1.2 | Implementation Plan v1.2 | Test Matrix v1.2 | Audit Evaluation |
| :--- | :--- | :--- | :--- | :--- |
| **Cash Inflow Invariant** | Sec 1.1, Sec 4.1 | Sec 1.1, Sec 3.1 | TC-01, TC-08, TC-19, TC-26 | **PASS** (Legacy `order_revenue` preserved) |
| **Handover Recognition** | Sec 1.1, Sec 3.1 | Sec 1.1, Sec 3.1 | TC-01, TC-02, TC-03, TC-34 | **PASS** (Handover-based; snapshot recorded) |
| **Non-Sales Income Scope** | Sec 4.1 | Sec 3.1 | TC-30 | **HIGH DEFECT (Finding H01)** |
| **Receivables Formula** | Sec 3.1, Sec 4.1 | Sec 3.2 | TC-02, TC-03, TC-12 | **HIGH DEFECT (Finding H02)** |
| **Post-Handover Cancel Gate** | Sec 1.1, Sec 3.2 | Sec 4 (3.B.5) | TC-15, TC-16, TC-17, TC-18 | **MEDIUM RISK (Finding M01)** |
| **Credit Ledger Event Sourcing**| Sec 3.6 | Sec 2.1 | TC-04, TC-06, TC-07, TC-21 | **PASS** (Signed ledger model intact) |
| **Currency Isolation (EGP/IDR)**| Sec 1.1, Sec 4.1 | Sec 2.1, Sec 3.1 | TC-18, TC-26, TC-27 | **MEDIUM RISK (Finding M02)** |
| **Activation Cutoff Safety** | Sec 3.7 | Sec 6 | TC-22, TC-23, TC-24, TC-25 | **PASS** (No synthetic backfill) |

---

## 6. Required Document Corrections (Listed for Future Update; NOT APPLIED)

1. **Correction to Scope Lock v1.2 & Implementation Plan v1.2 (Finding H01)**:
   - Disentangle non-sales `income` from *Pendapatan Penjualan*. Define `Pendapatan Penjualan` exclusively as sales revenue from handed-over orders, and expose `Total Pendapatan` as the sum of sales revenue and other income.
2. **Correction to Receivables Formula (Finding H02)**:
   - Change the receivables formula to:
     $$\text{Piutang Usaha} = \sum_{\text{handed over orders}} \max(0, (\text{order.recognized\_revenue\_le} + \text{net\_adjustments}) - \text{canonical\_paid\_le})$$
3. **Correction to Implementation Plan v1.2 (Finding M01)**:
   - Update Step 3.B.5 to declare `confirm_handover_cancellation: Optional[bool]` and `cancellation_reason: Optional[str]` on Pydantic class `OrderStatusUpdate`.
4. **Correction to Scope Lock v1.2 (Finding M02)**:
   - Clarify per-currency isolation notation in the dashboard formula table.
5. **Correction to Implementation Plan v1.2 (Finding M03)**:
   - Clarify date filter query for handed-over revenue reporting when orders have status changes.

---

## 7. Explicit Owner Decisions Required

Before proceeding to Phase 3.B implementation, the owner must decide:

1. **Scope of "Pendapatan Penjualan" Dashboard Card**:
   - *Option A (Pure Sales Revenue)*: The card *Pendapatan Penjualan* displays **only** sales revenue from delivered furniture orders. Miscellaneous non-sales income (`type="income"`) is displayed in a separate secondary metric (*Pendapatan Lain-lain*).
   - *Option B (Consolidated Operating Revenue)*: The card is renamed to *Total Pendapatan Operasional* (or similar) to clearly indicate that it includes both furniture sales and other miscellaneous operating income.
   *(Technical recommendation: Option A preserves the purest accounting meaning of Pendapatan Penjualan).*

2. **Blocking Direct Price Edits on Handed-Over Orders**:
   - Should `PATCH /admin/orders/{id}` strictly **reject** price changes (`subtotal_le`, `total_le`, `delivery_fee_le`, `items`) once an order has reached `selesai`, requiring all post-handover financial adjustments to go exclusively through `POST /admin/finance/adjustments`?
   *(Technical recommendation: Yes. Blocking direct edits prevents divergence between billing records and recognized revenue).*

---

## 8. Final Readiness Verdict

### **VERDICT: CONDITIONALLY READY — OWNER DECISIONS REQUIRED**

**Justification**:
- The architecture is fundamentally sound, robustly conceived, and successfully eliminates the overpayment distortion defect.
- There are **zero CRITICAL findings** (no risk of data loss, double spending, or historical data corruption).
- Two **HIGH findings** (non-sales income conflation in metric naming and receivables formula linkage to snapshot) and two **MEDIUM implementation gaps** have been surfaced.
- Once the owner resolves the two explicit questions in Section 7, the corrections can be cleanly incorporated into a finalized Scope Lock & Implementation Plan v1.3, unlocking Phase 3.B authorization.

**Phase 3.B Implementation remains strictly ON HOLD.** Zero application code or test files were modified during this audit.
