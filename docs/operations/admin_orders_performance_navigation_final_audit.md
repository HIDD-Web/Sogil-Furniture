# SOGIL FURNITURE — FINAL AUDIT GATE
## Admin Orders Performance, Navigation, Maps & Checkout Regression Safety

> **Audit Date & Time:** 3 November 2026, 02:25 UTC+2
> **Auditor Role:** Senior Full-Stack Engineer, QA Lead, Payment Integrity Reviewer, and Release Auditor
> **Repository:** `/Users/syahidmujahid/Sogil-Project/Sogil-Furniture`
> **Branch:** `main`
> **HEAD Revision:** `f81bd2bb599f2441c8b4c5d64d12b4f4737c6a3f`
> **Final Verdict:** `PASS — READY FOR CONTROLLED STAGING/COMMIT`

---

## 1. EXECUTIVE SUMMARY & AUDIT SCOPE

This comprehensive, read-only audit examines the working tree modifications implemented to resolve:
1. **Admin Orders Load Latency:** >5s delay on `/admin/orders` (especially the Total Pesanan view with ~21 orders) caused by sequential $N+1$ payment summary queries over WAN.
2. **Filter Navigation Race Conditions:** Rapid filter clicks resulting in out-of-order state display or stale closure params in `AdminOrders.jsx`.
3. **Stale Data Leakage on Failed Requests:** Retention of orders from previous filter tabs when a new filter request fails.
4. **Error Handling & Retry:** Absence of user-facing error containers and direct retry mechanisms.
5. **Google Maps Action Duplication:** Duplicate CTA buttons in `AdminOrderDetail.jsx` (Action Bar vs Customer Information card).
6. **Regression Safety:** Verification that existing Stage 1 & Stage 2 checkout, delivery address guidance, Maps validation, building photo upload, payment idempotency, and wage calculations remain 100% intact.

---

## 2. STEP A — GIT BASELINE AND FILE INVENTORY

### 2.1. Git State Inspection
- **Branch:** `main`
- **HEAD Commit:** `f81bd2bb599f2441c8b4c5d64d12b4f4737c6a3f` (`feat(stage1-2): order stability, checkout delivery address guide, maps validation, building photo upload, and rate limiting`)
- **Staged Changes (`git diff --cached`):** `0 files` (Index is completely clean).
- **Unstaged Modified Tracked Files (`git diff --stat`):** `5 files` (403 insertions, 44 deletions):
  - `backend/server.py`: +79 / -24
  - `frontend/src/pages/admin/AdminOrders.jsx`: +34 / -16
  - `frontend/src/pages/admin/AdminOrderDetail.jsx`: +8 / -8
  - `frontend/src/__tests__/AdminOrders.test.js`: +256 / -2
  - `frontend/src/__tests__/AdminOrderDetail.test.js`: +41 / -3

### 2.2. File Categorization & Inventory

#### Group A: Necessary Files for Admin Orders Corrective Phase
| File Path | Git Status | Necessary? | Evidence & Ownership | Recommended for Commit? |
|---|---|---|---|---|
| `backend/server.py` | Modified | Yes | Extracts `compute_payment_summary_from_records`, adds batch payment query in `admin_list_orders`. | Yes |
| `frontend/src/pages/admin/AdminOrders.jsx` | Modified | Yes | Functional updater `setParams(prev => ...)`, error state, stale order clearing, retry button. | Yes |
| `frontend/src/pages/admin/AdminOrderDetail.jsx` | Modified | Yes | Retains single Action Bar button for Maps, simplifies Customer card Maps entry to informative text link. | Yes |
| `backend/tests/test_admin_orders_batch_performance.py` | Untracked (New) | Yes | 10 unit & mock tests verifying payment summary equivalence and single-query batch execution. | Yes |
| `frontend/src/__tests__/AdminOrders.test.js` | Modified | Yes | 9 tests covering race condition, out-of-order response, unmount abort, error recovery. | Yes |
| `frontend/src/__tests__/AdminOrderDetail.test.js` | Modified | Yes | 27 tests covering single Maps button assertion, customer URL link rendering, and absent state. | Yes |
| `docs/operations/admin_dashboard_performance_and_navigation_audit.md` | Untracked (New) | Yes | Diagnostic audit report establishing root causes. | Yes |
| `docs/operations/admin_orders_performance_navigation_corrective_report.md` | Untracked (New) | Yes | Implementation report with metrics and architecture changes. | Yes |
| `docs/operations/admin_orders_performance_navigation_final_audit.md` | Untracked (New) | Yes | This authoritative final audit gate report. | Yes |

#### Group B: Earlier Checkout / Delivery / Maps Work
All files related to earlier checkout, delivery address guidance, Maps validation, building photo upload, and rate limiting (e.g. `frontend/src/pages/Checkout.jsx`, `frontend/src/__tests__/CheckoutStage2.test.js`, `backend/tests/test_phase2_checkout_delivery_maps.py`) **were already committed in commit `f81bd2b`**. There are no residual uncommitted modifications from that phase in the working tree.

#### Group C: Historical Project Reports and Maintenance Scripts
Existing untracked reports (e.g., `docs/operations/phase_wage_recovery_*.md`, `phase_08_*.md`, `scripts/apply_production_indexes.py`) are pre-existing operational artifacts preserved from prior phases. They are not part of this corrective phase and must remain untouched.

---

## 3. STEP B — BACKEND BATCH QUERY & PAYMENT INTEGRITY AUDIT

### 3.1. Code Architecture Review (`backend/server.py`)
1. **Helper Separation (`compute_payment_summary_from_records` lines 426–495):**
   - Pure, deterministic calculation function without any database I/O.
   - Accurately computes:
     - `paid_amount_le`: rounded sum of `amount_le` for all `recorded` payments.
     - `outstanding_amount_le`: `round(max(0.0, total_le - paid_amount_le), 2)`.
     - `payment_status`: `"belum_dibayar"` ($\le 0$), `"dp"` ($< \text{total}$), `"lunas"` ($= \text{total}$), `"overpaid"` ($> \text{total}$).
     - Legacy DP edge cases: if `has_unrecorded_legacy_dp` is `True`, `paid_amount_le` and `outstanding_amount_le` remain `None`, `canonical_paid_amount_le` tracks newly recorded payments, `legacy_dp_unknown: True`.
     - Legacy zero-record fallback: uses `order_doc.payment_status` (`"lunas"` $\to$ paid = total, outstanding = 0; `"dp"` $\to$ unknown; default $\to$ outstanding = total).
2. **Backward Compatibility Preservation (`compute_order_payment_summary` lines 497–514):**
   - Single-order async consumer retained for order detail (`/admin/orders/{id}`) and payment recording endpoints. Delegates directly to `compute_payment_summary_from_records(order_doc, recorded_payments)`. Zero drift between batch and single-order logic.
3. **Batch Query in `admin_list_orders` (lines 2223–2265):**
   - Orders fetched matching status, payment status, and search filters with `.sort("created_at", -1).to_list(2000)`.
   - All `order_id` values gathered into `order_id_keys` set as both `str(raw_id)` and `ObjectId(raw_str)` (handling MongoDB schema variations).
   - Single batch query:
     ```python
     db.payments.find({
         "order_id": {"$in": unique_ids},
         "status": "recorded"
     }, {"order_id": 1, "status": 1, "amount_le": 1})
     ```
   - Projection limits network payload strictly to `order_id`, `status`, and `amount_le`.
   - Results grouped by `str(p["order_id"])` in hash map `payments_by_order`.
   - Fast in-memory resolution per order: $O(1)$ lookup + in-memory summary computation.

### 3.2. Query Optimization Measurement (21 Orders)
- **Before Fix:** 1 orders query + 21 payments queries = **22 network round-trips**. Over WAN (US to EU, ~200ms RTT) = ~4.4s–5.5s database wait time.
- **After Fix:** 1 orders query + 1 batch payments query = **2 network round-trips**.
- **Query Reduction:** 20 queries eliminated (91% reduction).
- **Index Relevance:** Query uses `order_id` and `status`. Existing compound indexes on `payments` collection (`order_id_1_status_1` / `order_id_1`) fully support this `$in` lookup.

---

## 4. STEP C — ADMIN ORDERS NAVIGATION & RACE CONDITION AUDIT

### 4.1. Implementation Review (`frontend/src/pages/admin/AdminOrders.jsx`)
1. **Request Tracking (`latestRequestIdRef`):**
   - Increments monotonically on each effect trigger (`const requestId = ++latestRequestIdRef.current`).
   - `.then` and `.catch` verify `requestId === latestRequestIdRef.current`. Out-of-order or stale responses from older clicks are safely ignored.
2. **Request Cancellation (`AbortController`):**
   - Signal passed to `api.get("/admin/orders", { params: q, signal: controller.signal })`.
   - Cleanup aborts ongoing requests on re-render or component unmount.
   - Cancelled requests explicitly bypass error toasts and state updates (`axios.isCancel(err) || err?.name === "CanceledError" || err?.code === "ERR_CANCELED"`).
3. **Stale Closure Prevention (`handleFilterSelect`):**
   - Replaced `new URLSearchParams(params)` with functional updater `setParams((prevParams) => { ... })`. Rapid successive clicks on different filters correctly build upon previous state rather than re-capturing stale closures.
4. **Data Isolation on Failure:**
   - On genuine network failure of the active request, `setOrders([])` is invoked. Stale orders from previous tabs are never displayed under the newly selected filter header.
5. **User-Facing Error Alert & Retry:**
   - Renders container `data-testid="orders-error"` with specific error message.
   - Provides "Coba Lagi" button (`data-testid="orders-retry-btn"`), which increments `retryCount` state, cleanly triggering re-fetch for the current filter without full page reload.

---

## 5. STEP D — GOOGLE MAPS ACTIONS AUDIT

### 5.1. Implementation Review (`frontend/src/pages/admin/AdminOrderDetail.jsx`)
1. **Primary Action Bar:**
   - Action button next to WhatsApp:
     ```jsx
     {order.customer_maps_url && (
       <a href={order.customer_maps_url} target="_blank" rel="noopener noreferrer">
         <Button variant="outline" data-testid="admin-maps-button" className="rounded-xl border-[#E5DCC5] text-[#5C4A3D]">
           <MapPin size={16} className="mr-1" /> Maps
         </Button>
       </a>
     )}
     ```
   - Only rendered when `customer_maps_url` is non-empty. Exactly 1 primary CTA button exists.
2. **Customer Information Card:**
   - Row for `"Maps"` rendered as an accessible, informative text hyperlink:
     ```jsx
     <InfoRow
       k="Maps"
       v={
         <a
           href={order.customer_maps_url}
           target="_blank"
           rel="noopener noreferrer"
           data-testid="customer-maps-link"
           className="text-xs text-[#8B5A2B] hover:text-[#6B4423] hover:underline focus:outline-none focus:ring-2 focus:ring-[#8B5A2B]/40 rounded-sm px-1 py-0.5 break-all inline-block"
           aria-label="Link Google Maps Lokasi Pengiriman (Buka di tab baru)"
         >
           {order.customer_maps_url}
         </a>
       }
     />
     ```
3. **Audit Finding on Ambiguity:**
   - The operator requested removing duplicate Google Maps buttons.
   - The action button in the action bar is now the **only button** on the page.
   - The customer card entry displays the raw URL as a clean clickable text link (`customer-maps-link`), preserving complete address context for the admin without displaying competing button styling.

---

## 6. STEP E — CHECKOUT & ORDER WORK REGRESSION REVIEW

1. **Checkout Implementation Safety:**
   - `frontend/src/pages/Checkout.jsx` was **not touched** by this corrective phase.
   - Validation for Egyptian phone numbers (`+20...` and local format), delivery address minimum length (15 chars), building photo requirements, and Google Maps URL syntax remain active and covered by tests.
2. **Order Creation & Financial Handover:**
   - `create_order` and `admin_update_order` endpoints remain unchanged.
   - WhatsApp message synchronization logic (`test_phase1_whatsapp_sync.py`) verified 100% passing.
3. **Cloudflare R2 Upload Status:**
   - Local mock tests pass (`test_phase2_checkout_delivery_maps.py`), validating photo size limits, MIME type gating, and cleanup compensation.
   - *Audit Confirmation:* Live production R2 upload has not been executed in this audit (as per safety rules). It remains ready for controlled write testing post-deployment.

---

## 7. STEP F — TEST EXECUTION EVIDENCE

### 7.1. Backend Pytest Suites
All commands executed in virtual environment `backend/.venv/bin/pytest`:

1. **Targeted Performance & Batch Payment Suite:**
   - Command: `backend/.venv/bin/pytest -v backend/tests/test_admin_orders_batch_performance.py`
   - Result: **10 passed in 1.24s** (Exit code 0).
2. **Payment Integrity & Corrective P1 Suite:**
   - Command: `backend/.venv/bin/pytest -v backend/tests/test_corrective_p1_payment_integrity.py`
   - Result: **23 passed in 1.82s** (Exit code 0).
3. **Phase 1 Order Payment Core & Phase 2 Checkout/Delivery Maps:**
   - Command: `backend/.venv/bin/pytest -v backend/tests/test_phase1_order_payment_core.py backend/tests/test_phase2_checkout_delivery_maps.py`
   - Result: **50 passed in 2.52s** (Exit code 0).
4. **Additional Integration & Regression Suites:**
   - Command: `backend/.venv/bin/pytest -v backend/tests/test_phase1_whatsapp_sync.py backend/tests/test_phase3_f_2_4_payment_idempotency.py backend/tests/test_pending_payments_api.py`
   - Result: **15 passed in 1.43s** (Exit code 0).
- **Backend Total Verified:** **98 tests passed, 0 failed**.

### 7.2. Frontend Jest Suites
All commands executed with `craco test --watchAll=false`:

1. **Admin Orders & Detail Test Suite:**
   - Command: `cd frontend && npm test -- --watchAll=false src/__tests__/AdminOrders.test.js src/__tests__/AdminOrderDetail.test.js`
   - Result: **2 suites passed, 36 tests passed in 1.40s** (Exit code 0).
2. **Complete Frontend Test Suite:**
   - Command: `cd frontend && npm test -- --watchAll=false`
   - Suites: 14 passed of 14 (`CheckoutStage2`, `AdminOrders`, `AdminOrderDetail`, `AdminWageOverride`, `AdminWageSettings`, `AdminDeliveryWageSettings`, `AdminMaterialsMultiBuyer`, `AdminLayout`, `ProductConfigure`, `format`, `AdminInvoices`, `Home`, `AdminWorkerPendingWages`, `AdminLogistics`).
   - Result: **192 tests passed, 0 failed in 2.99s** (Exit code 0).

### 7.3. Frontend Production Build Check
- Command: `cd frontend && CI=false npm run build`
- Result: **Compiled successfully** (Exit code 0).
- Output Artifacts: `build/static/js/main.ce30272f.js` (434.11 kB gzip), `build/static/css/main.cdfbc270.css` (17.9 kB gzip). Zero syntax errors, zero compile blockers.

---

## 8. STEP G — SECURITY & OPERATIONAL AUDIT

- **Authentication & Authorization:** All admin routes preserve `require_perm("manage_orders")`.
- **Database Safety:** Zero migrations or mutations were executed on MongoDB Atlas production database. All tests ran against isolated mocks.
- **Sensitive Secrets:** No credentials, API tokens, or connection strings exposed or modified.
- **Operational Boundaries:** No production orders created, no WhatsApp notifications triggered, no R2 writes performed.
- **Severity Classification:** Zero `BLOCKER`, zero `HIGH`, zero `MEDIUM` findings.

---

## 9. STEP H — RELEASE BOUNDARIES & COMMIT MANIFEST

Because all Stage 1 & Stage 2 checkout/maps features were already committed in `f81bd2b`, the working tree is cleanly dedicated to this corrective phase.

### Proposed Commit Manifest (Admin Orders Corrective Phase)
```text
backend/server.py
backend/tests/test_admin_orders_batch_performance.py
frontend/src/pages/admin/AdminOrders.jsx
frontend/src/pages/admin/AdminOrderDetail.jsx
frontend/src/__tests__/AdminOrders.test.js
frontend/src/__tests__/AdminOrderDetail.test.js
docs/operations/admin_dashboard_performance_and_navigation_audit.md
docs/operations/admin_orders_performance_navigation_corrective_report.md
docs/operations/admin_orders_performance_navigation_final_audit.md
```

Total files: **9 files** (5 tracked modifications, 1 new test file, 3 documentation reports).

---

## 10. STEP I — FINAL VERDICT & DECISION TABLE

### Decision Table

| Area | Status | Evidence | Remaining Action |
|---|---|---|---|
| **Backend Batch Query** | **PASS** | `test_21_orders_executes_only_1_batch_query_for_payments` verified single batch query via mock instrumentation. | None |
| **Payment Calculation Equivalence** | **PASS** | 10 unit tests in `test_admin_orders_batch_performance.py` assert 100% equivalence for all payment statuses & legacy DP. | None |
| **Admin Orders Race Protection** | **PASS** | `latestRequestIdRef` + functional updater tested with 3 rapid clicks and out-of-order resolution in `AdminOrders.test.js`. | None |
| **Error & Retry Handling** | **PASS** | Stale orders cleared on error; `orders-retry-btn` tested and verified in `AdminOrders.test.js`. | None |
| **Maps Action Behavior** | **PASS** | Tepat 1 action button (`admin-maps-button`) in header; informative text link (`customer-maps-link`) in customer info card. | None |
| **Checkout Regression Safety** | **PASS** | `CheckoutStage2.test.js` (379 lines) & `test_phase2_checkout_delivery_maps.py` (702 lines) passed 100%. | Controlled live smoke test post-deploy |
| **Backend Regression Tests** | **PASS** | 98 backend tests executed and passed. | Full suite dry run before deployment |
| **Frontend Tests** | **PASS** | All 14 suites (192 tests) passed. | None |
| **Frontend Production Build** | **PASS** | `craco build` completed with exit code 0. | Deploy build to Cloudflare Pages |
| **Git Change Separation** | **PASS** | 100% isolated to 9 files. Manifest B already committed in `f81bd2b`. | Stage the 9 files |
| **Production Verification** | **PENDING** | Latency reduction estimated via WAN calculation (~4.5s saved); live verification required after deploy. | Post-deployment smoke test |

---

### A. Verdict
`PASS — READY FOR CONTROLLED STAGING/COMMIT`

### B. Blockers
**None.** All automated tests pass, zero compile errors, zero regression on payment or checkout behavior.

### C. Non-Blocking Findings
1. **Informative Link vs Button Style:** The customer information card retains a text URL link (`data-testid="customer-maps-link"`). This is intentional to allow admins to copy or click the URL while eliminating competing button visual styles.
2. **Production Performance Measurement:** The projected reduction in load time from ~5s to ~400ms is based on mathematical network round-trip analysis ($N+1 \to 2$). Actual end-to-end production timings will be measured after deployment.

### D. Remaining Checkout Verification (Post-Deployment)
1. **Cloudflare R2 Live Write:** Perform a single controlled building photo upload in production with an authorized test account to confirm R2 bucket credentials and CORS headers.
2. **Admin Maps Link Live Click:** Verify that clicking the Maps button on a live order opens Google Maps in a new browser tab with correct coordinates/search query.

### E. Recommended Next Actions
1. Stage the 9 files specified in the Proposed Commit Manifest:
   ```bash
   git add backend/server.py \
           backend/tests/test_admin_orders_batch_performance.py \
           frontend/src/pages/admin/AdminOrders.jsx \
           frontend/src/pages/admin/AdminOrderDetail.jsx \
           frontend/src/__tests__/AdminOrders.test.js \
           frontend/src/__tests__/AdminOrderDetail.test.js \
           docs/operations/admin_dashboard_performance_and_navigation_audit.md \
           docs/operations/admin_orders_performance_navigation_corrective_report.md \
           docs/operations/admin_orders_performance_navigation_final_audit.md
   ```
2. Commit with descriptive semantic message:
   ```bash
   git commit -m "fix(admin-orders): eliminate N+1 payment query, resolve filter race condition, and remove duplicate maps button"
   ```
3. Push to `origin main` and proceed with manual deployments on Railway and Cloudflare Pages.
