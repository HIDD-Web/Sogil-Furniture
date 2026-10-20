# SOGIL FURNITURE — PHASE 3.C.1
## EDGE-CASE CORRECTION SPECIFICATION (REVISED & HARDENED)

**Document Status:** Specification Final Review (Ready for Owner Implementation Authorization)  
**Author:** AI Technical Specialist & Finance Architecture Pair  
**Baseline HEAD:** `da4baa2fab2523cecca4c4ea9a5714b2e784968e`  
**Target Branch:** `main`  
**Target Code Modification:** `backend/server.py`  
**Target Test Suite:** `backend/tests/test_phase3_edge_cases_reconciliation.py`  

---

## 1. EXECUTIVE SUMMARY & OBJECTIVE

Following the Phase 3.B.1–B.7 implementation (`da4baa2`), the transaction lifecycle audit identified two operational edge cases:

1. **Finding C-01 (High Risk — Unbacked Customer Credit Deficit):**  
   When an overpayment on Order A mints store credit (`credit_minted`), and that credit is subsequently utilized (partially or fully) via Order B (`credit_applied`) or cash withdrawal (`credit_refunded`), voiding the original payment on Order A executes an unconditional reversal (`credit_reversed` with `signed_amount = -minted_amount`). This forces the customer's available credit balance below zero ($< 0.00$), creating a negative liability (an unbacked financial asset deficit) that violates ledger invariants.

2. **Finding C-02 (Medium Risk — General Ledger vs. Order Ledger Desynchronization):**  
   The finance transaction deletion endpoint `DELETE /admin/finance/transactions/{txn_id}` (`finance_delete`) marks transactions as void (`is_void = True, status = "void"`) without evaluating linkage to structured order payments or customer credit operations. Voiding a payment-linked transaction directly from the general ledger suppresses the cash receipt from dashboard metrics while leaving `db.payments.status = "recorded"`, corrupting order payment summaries, accounts receivable, and customer advances.

This revised specification hardens the transaction boundaries, fail-closed guarantees, currency handling, fungible credit semantics, relationship precedence rules, and test matrix.

---

## 2. DETAILED SPECIFICATION: FINDING C-01 (PREVENT NEGATIVE CREDIT AFTER VOID)

### 2.1 Problem Analysis & Execution Flow
In `backend/server.py` L2855–L2953 (`admin_void_order_payment`):
* The endpoint receives `order_id`, `payment_id`, and `PaymentVoidInput`.
* It verifies permissions, order existence, payment existence, and `pmt["status"] != "voided"`.
* Inside `_do_void(session)`:
  1. It updates `db.payments` to `status = "voided"`.
  2. It updates `db.finance_transactions` to `is_void = True, status = "void"`.
  3. It searches `db.customer_credit_events` for `source_payment_id == str(pmt["_id"])` and `event_type in ["credit_minted", "credit_applied"]`.
  4. If a `credit_minted` event is found, it unconditionally calculates `rev_signed = -original_signed` (e.g. $-500.00$) and inserts a `credit_reversed` event.

### 2.2 Fungible Credit Semantics & Mathematical Invariant
* **Fungibility:** Store credit balances in Sogil Furniture are completely fungible by customer and currency. Once credited to a customer account, credits are pooled together regardless of origin (overpayment from Order 1, referral rewards, goodwill credits, etc.). Credit consumption does not preserve coin-level provenance.
* **Invariant:** An overpayment void reverses an unearned liability. If the customer has already spent or withdrawn those credits, the company cannot unilaterally extinguish the liability without creating an unauthorized negative balance:
  $$\text{Balance}_{\text{post-void}}(cid, cur) = \text{Balance}_{\text{current}}(cid, cur) - \text{ReversalAmount} \ge 0.00$$
* If $\text{Balance}_{\text{current}}(cid, cur) < \text{ReversalAmount}$, the void request **must fail closed** with HTTP 409 Conflict.

### 2.3 Source Currency Determination (No Hardcoded Assumptions)
* The credit event currency must be derived directly from the source records:
  ```python
  event_currency = (
      cce.get("currency")
      or pmt.get("currency")
      or order.get("currency")
      or "EGP"
  ).strip().upper()
  ```
* Under no circumstances may `"EGP"` be assumed without checking the source document.

### 2.4 Transactional Boundary & Strict Fail-Closed Execution Order
To guarantee absolute atomicity and prevent partial writes:

1. **Step 1: Check Pre-conditions inside `_do_void(session)`:**
   Before mutating any document (`db.payments` or `db.finance_transactions`), find the associated `credit_minted` event:
   ```python
   cce = await db.customer_credit_events.find_one(
       {"source_payment_id": str(pmt["_id"]), "event_type": "credit_minted"},
       **ins_kw
   )
   ```
2. **Step 2: Acquire Serialization Lock on Customer Document:**
   If a `credit_minted` event exists and customer ID is present:
   ```python
   cust_id_str = str(cce.get("customer_id") or order.get("customer_id") or "").strip()
   if cust_id_str:
       cust_oid = id_query(cust_id_str)
       cust_touch_res = await db.customers.update_one(
           {"_id": cust_oid},
           {"$set": {"last_credit_transaction_at": now_iso}},
           **ins_kw
       )
       if cust_touch_res.matched_count == 0:
           raise HTTPException(
               status_code=400,
               detail="Akun pelanggan tidak ditemukan untuk serialisasi transaksi kredit"
           )
   ```
3. **Step 3: Evaluate In-Transaction Balance Gate:**
   Calculate the customer's real-time credit balance **within the active transaction session**:
   ```python
   in_txn_balance = await get_customer_credit_balance(
       cust_id_str,
       event_currency,
       session=session
   )
   required_reversal_amt = abs(float(cce.get("signed_amount", 0.0)))
   if in_txn_balance < required_reversal_amt:
       raise HTTPException(
           status_code=409,
           detail=(
               f"Konflik saldo: Pembayaran ini menghasilkan saldo kredit sebesar {required_reversal_amt:.2f} {event_currency}, "
               f"namun saldo kredit pelanggan saat ini hanya tersisa {in_txn_balance:.2f} {event_currency}. "
               "Batalkan transaksi penggunaan kredit atau pengembalian dana kredit pelanggan terlebih dahulu "
               "sebelum membatalkan pembayaran ini."
           )
       )
   ```
4. **Step 4: Execute Document Writes (Only after gate passes):**
   * Write `credit_reversed` document to `db.customer_credit_events`.
   * Update `db.payments` status to `"voided"`.
   * Update `db.finance_transactions` `is_void = True, status = "void"`.

### 2.5 Multi-Document Transaction vs. Fallback Policy
* **Production / Replica Set Mode:**  
  The operation executes inside an ACID session (`async with session.start_transaction(): await _do_void(session)`).  
  If the HTTP 409 exception is raised at Step 3, the transaction immediately aborts. WiredTiger snapshots roll back all mutations. Zero documents are modified or inserted.
* **Standalone / Test Fallback Mode:**  
  By placing the balance gate and serialization check **prior to the writes** on `payments` and `finance_transactions`, even in fallback non-transactional test execution, an exception at Step 3 stops execution before any write occurs.
* **Fail-Closed on Unavailable Transactions:**  
  Per `is_standalone_fallback_permitted()`, in production or unknown environment modes, if a multi-document transaction cannot be started, the endpoint fails closed immediately with HTTP 503 Service Unavailable without attempting non-transactional execution.

---

## 3. DETAILED SPECIFICATION: FINDING C-02 (PREVENT DIRECT VOID OF PAYMENT TRANSACTIONS)

### 3.1 Problem Analysis & Execution Flow
In `backend/server.py` L5236–L5258 (`finance_delete` route `DELETE /admin/finance/transactions/{txn_id}`):
* Currently, any transaction document `t` in `db.finance_transactions` can be voided via `void_source = "finance_manual"`.
* When an admin directly deletes a transaction generated by order payments or customer credit refunds:
  - The finance transaction is marked `is_void = True`.
  - The payment document in `db.payments` remains `status = "recorded"`.
  - The credit event in `db.customer_credit_events` remains active.
  - Cash flow decreases on the finance dashboard, while order payment summaries and accounts receivable calculate as if the payment is still valid.

### 3.2 Detection Precedence & Linkage Resolution
To prevent bypassing the official order payment void workflow while preserving legitimate manual finance operations, `finance_delete` must evaluate linkage using the following strict precedence:

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        LINKAGE EVALUATION PIPELINE                      │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Transaction already voided? -> Return 400 Bad Request               │
│ 2. Has direct payment linkage?                                         │
│    - txn.get("payment_id") is present AND non-empty                    │
│    - OR txn.get("related_payment_number") is present AND non-empty     │
│ 3. Has reverse payment linkage?                                        │
│    - db.payments.find_one({"finance_transaction_id": txn_id,           │
│                           "status": {"$ne": "voided"}})                │
│ 4. Has customer credit refund linkage?                                 │
│    - txn.get("classification") == "liability_settlement"               │
│    - OR txn.get("type") in ("credit_settlement", "credit_refund")       │
│    - OR txn.get("related_credit_event_number") is present              │
│ 5. Is legacy order_revenue?                                            │
│    - type == "order_revenue" but NO payment_id and NO matching payment │
│      -> PERMIT VOID (Legacy historical cleanup)                        │
│ 6. Is standalone expense / income / balance_adjustment?                │
│    - -> PERMIT VOID (Standard manual finance operations)               │
└────────────────────────────────────────────────────────────────────────┘
```

### 3.3 Protection Rules & Error Semantics
In `finance_delete`:
1. **Already Voided Guard:**
   ```python
   if t.get("is_void") or t.get("status") == "void":
       raise HTTPException(
           status_code=400,
           detail="Transaksi yang telah dibatalkan tidak dapat dibatalkan kembali"
       )
   ```
2. **Linked Payment Guard:**
   ```python
   is_payment_linked = False
   if t.get("payment_id") or t.get("related_payment_number"):
       is_payment_linked = True
   else:
       # Reverse lookup: check if any active payment points to this transaction
       matching_pmt = await db.payments.find_one({
           "finance_transaction_id": str(t["_id"]),
           "status": "recorded"
       })
       if matching_pmt:
           is_payment_linked = True

   if is_payment_linked:
       order_ref = t.get("related_order_id") or "terkait"
       raise HTTPException(
           status_code=409,
           detail=(
               "Transaksi keuangan ini terhubung langsung dengan pembayaran pesanan resmi. "
               "Pembatalan tidak dapat dilakukan melalui modul keuangan. "
               f"Silakan batalkan pembayaran melalui menu Detail Pesanan (Order ID: {order_ref}) "
               "agar saldo pesanan, alokasi dana, dan pembukuan kas tetap sinkron."
           )
       )
   ```
3. **Linked Credit Refund Guard:**
   ```python
   is_credit_linked = (
       t.get("classification") == "liability_settlement" or
       t.get("type") in ("credit_settlement", "credit_refund") or
       bool(t.get("related_credit_event_number"))
   )
   if is_credit_linked:
       raise HTTPException(
           status_code=409,
           detail=(
               "Transaksi ini terhubung dengan transaksi kredit atau pengembalian saldo kredit pelanggan. "
               "Pembatalan langsung dari modul keuangan dilarang untuk menjaga konsistensi buku besar kredit."
           )
       )
   ```
4. **Preservation of Standalone & Legacy Operations:**
   - Standalone `expense` (material purchases, operational costs, wage payments) $\to$ **Allowed**.
   - Standalone `income` (non-sales income) $\to$ **Allowed**.
   - Standalone `transfer` $\to$ **Allowed**.
   - Legacy `order_revenue` (pre-Phase 1 records without a linked `payment_id` or `db.payments` document) $\to$ **Allowed**, ensuring backward-compatible maintenance.

---

## 4. CONCURRENCY, IDEMPOTENCY & AUDIT REQUIREMENTS

1. **WiredTiger Write Serialization:**
   - Concurrent calls to spend credit while voiding an overpayment will compete for the customer document lock (`db.customers.update_one` with snapshot timestamp).
   - One transaction will acquire the lock; the other will encounter a write-write conflict and retry via PyMongo's transient transaction retry mechanism.
   - Upon retry, the second transaction sees the committed lower balance and fails closed with HTTP 409.
2. **Append-Only Credit Audit Ledger:**
   - No customer credit event documents are ever deleted or mutated.
   - Reversals are recorded as new immutable events (`event_type = "credit_reversed"`, `reverses_event_id = cce["_id"]`, `idempotency_key = f"cce_rev_pmt_{pmt['_id']}"`).
3. **Idempotency on Payment Void:**
   - Repeated void attempts on an already-voided payment return HTTP 400 (`"Pembayaran sudah dibatalkan sebelumnya"`).
   - The unique index on `db.customer_credit_events` (`uniq_cce_idempotency`) ensures that duplicate credit reversals cannot be minted even during network retries.

---

## 5. MASTER TEST MATRIX (16 TEST SCENARIOS)

The dedicated test file `backend/tests/test_phase3_edge_cases_reconciliation.py` will implement 16 comprehensive automated tests:

| Test ID | Method Name | Description & Expected Assertion |
| :--- | :--- | :--- |
| **C1-TC-01** | `test_c1_tc01_void_overpayment_full_credit_balance` | Customer has full minted credit balance. Void succeeds (200 OK), `payments` status='voided', `credit_reversed` inserted, balance reaches 0.00. |
| **C1-TC-02** | `test_c1_tc02_void_overpayment_spent_partial_credit` | Customer minted 1000 LE, spent 400 LE (remaining 600 LE). Void attempted. Rejection 409 Conflict; payment stays recorded, zero events inserted. |
| **C1-TC-03** | `test_c1_tc03_void_overpayment_spent_all_credit_order2` | Customer minted 500 LE, spent 500 LE on Order 2. Void rejected with 409 Conflict; order 1 & 2 balances unaffected. |
| **C1-TC-04** | `test_c1_tc04_void_overpayment_withdrawn_via_cash_refund` | Customer minted 800 LE, refunded 800 LE in cash. Void rejected with 409 Conflict; zero mutations. |
| **C1-TC-05** | `test_c1_tc05_void_overpayment_with_external_credit_topup` | Customer minted 500 LE, spent 300 LE, but received 400 LE from elsewhere (total 600 LE). Void succeeds (200 OK) because fungible balance $\ge 500\text{ LE}$. |
| **C1-TC-06** | `test_c1_tc06_void_credit_applied_restores_balance` | Voiding a payment made with customer credit restores credit (+signed_amount) without requiring credit balance check. |
| **C1-TC-07** | `test_c1_tc07_currency_propagation_idr_overpayment` | An IDR overpayment derives currency from source event and checks IDR balance, verifying strict currency isolation. |
| **C1-TC-08** | `test_c1_tc08_concurrency_race_credit_spend_vs_void` | Simulated concurrent credit application and payment void: customer serialization lock prevents race past balance gate. |
| **C1-TC-09** | `test_c1_tc09_replica_set_abort_on_exception` | Mocked transaction session aborts atomically when 409 is raised; verifies `session.abort_transaction()` called and zero writes committed. |
| **C2-TC-10** | `test_c2_tc10_finance_delete_blocked_on_direct_payment_id` | Transaction with `payment_id` rejected with 409 Conflict and descriptive error message. |
| **C2-TC-11** | `test_c2_tc11_finance_delete_blocked_on_reverse_payment_lookup` | Transaction without `payment_id` field but referenced by `db.payments.finance_transaction_id` rejected with 409 Conflict. |
| **C2-TC-12** | `test_c2_tc12_finance_delete_blocked_on_credit_refund` | Transaction with `classification="liability_settlement"` or credit refund rejected with 409 Conflict. |
| **C2-TC-13** | `test_c2_tc13_finance_delete_permitted_standalone_expense` | Standalone `expense` (wage, supplier payment) voided successfully (200 OK). |
| **C2-TC-14** | `test_c2_tc14_finance_delete_permitted_legacy_order_revenue` | Pre-Phase 1 `order_revenue` without linked payment document voided successfully (200 OK). |
| **C2-TC-15** | `test_c2_tc15_finance_delete_already_voided_returns_400` | Attempting `finance_delete` on already voided transaction returns 400 Bad Request. |
| **C-ALL-16** | `test_c_all16_full_suite_regression_invariants` | Verify full suite compatibility with zero regressions against all 158 prior tests. |

---

## 6. OPEN DECISIONS & SCOPE BOUNDARIES

* **Open Decision OD-C1-01:**  
  *Should an admin be allowed to force-void an overpayment if they explicitly acknowledge creating a customer debt/deficit?*  
  **Architectural Recommendation:** **No.** Permitting negative credit balances introduces uncollectable debt risk without a credit agreement contract. The admin must resolve the downstream credit consumption first (e.g. canceling Order 2 or receiving repayment).
* **Scope Boundary:**  
  Phase 3.C.1 is purely a backend consistency hardening task. Zero changes to frontend API contracts, zero alterations to collection schemas, and zero data migrations are required.

---

## 7. FINAL VERDICT

### **`READY FOR OWNER IMPLEMENTATION APPROVAL`**

* The revised specification provides an airtight, fail-closed blueprint covering transaction boundaries, fungible credit mechanics, relationship precedence, and comprehensive test coverage.
* No application code, frontend code, or existing architecture documents were touched during this review.
