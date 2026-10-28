# PHASE WAGE RECOVERY 08.1.1 — CORRECTIVE AUDIT: PIASTRE ALLOCATION & WAGE POLICY SAFETY
**Tanggal:** 2026-10-28
**Sistem:** Sogil Furniture (`HIDD-Web/Sogil-Furniture`)
**Lingkungan:** Local Verification Workspace (Branch: `main`, Base Commit: `9bd1adab4e7a9a7303917ee573f9053bbfce123b`)
**Status Audit:** PASSED / SAFE FOR STAGE 08.2 TRANSITION

---

## 1. PREFLIGHT & INTEGRITAS REPOSITORY
- **Branch Aktif:** `main`
- **Git HEAD:** `9bd1adab4e7a9a7303917ee573f9053bbfce123b`
- **Status Working Tree:** Bersih dari perubahan tak terduga, hanya memuat penambahan fitur Phase 08.1 dan perbaikan audit korektif Phase 08.1.1.
- **Git Remote Synchronization:** Up to date dengan `origin/main`. Tidak ada commit atau push yang dilakukan dalam fase ini.

---

## 2. AUDIT PENERIMA KOSONG (EMPTY RECIPIENTS AUDIT)
- **Problem Statement:** Pada `calculate_delivery_helper_wage_allocations` dan serah terima stop pengiriman (`record_delivery_stop_handover_core`), jika nominal upah bernilai positif tetapi daftar pekerja/helper kosong (`helpers = []`), sistem sebelumnya mengembalikan daftar kosong `[]` tanpa error. Hal ini berisiko mencatat pengeluaran upah pada trip tetapi kewajiban pekerja (`wage_obligations`) tidak terbentuk sama sekali (ghost wage).
- **Perbaikan Implementasi:**
  1. `distribute_wage_piastres(total_wage_le, recipients)`:
     - Jika `total_wage_le > 0` dan `not recipients` (baik `[]` maupun `None`), fungsi kini secara eksplisit melempar `ValueError("Daftar penerima upah tidak boleh kosong jika nominal upah bernilai positif")`.
     - Jika `total_wage_le == 0.0` dan daftar penerima kosong atau `None`, fungsi mengembalikan `[]`.
     - Jika `total_wage_le == 0.0` dan terdapat penerima, fungsi mengembalikan daftar alokasi dengan nominal 0 piastre (0.0 LE).
  2. `calculate_delivery_helper_wage_allocations(total_wage_le, helpers, allow_empty=False)`:
     - Ditambahkan parameter eksplisit `allow_empty: bool = False`.
     - Alur simulator preview (`admin_preview_delivery_wage_allocation`) meneruskan `allow_empty=True` agar formulir admin yang belum memilih helper dapat menampilkan preview kosong tanpa crash HTTP 500.
     - Alur operasional handover tidak menggunakan `allow_empty=True`, sehingga secara ketat memicu `ValueError` jika helper kosong.
  3. `record_delivery_stop_handover_core`:
     - Menambahkan validasi Fail-Closed sebelum eksekusi handover:
       `if not helpers and total_wage > 0: raise HTTPException(422, detail="Trip pengiriman tidak memiliki helper terdaftar untuk menerima alokasi upah pengantaran.")`
     - Pemanggilan alokasi upah dibungkus blok `try...except ValueError` yang menerjemahkan error alokasi menjadi respons HTTP 422.
     - Terbukti bahwa order status tidak berubah, trip stop outcome tidak berubah menjadi `delivered`, dan 0 dokumen `wage_obligations` dicatat.

---

## 3. AUDIT PRESISI MATA UANG & PEMBULATAN (CURRENCY PRECISION AUDIT)
- **Mata Uang & Unit Terkecil:** Egyptian Pound (EGP / LE) dengan unit pembukuan integer terkecil 1 Piastre (0.01 EGP).
- **Aturan Pembulatan (Rounding Policy):** `ROUND_HALF_UP` eksplisit pada level 2 desimal melalui modul `Decimal`.
  - Contoh uji batas:
    - `50.125 LE` dibulatkan naik menjadi `50.13 LE` (`5013 piastres`).
    - `50.124 LE` dibulatkan turun menjadi `50.12 LE` (`5012 piastres`).
    - `100.33333333333333 LE` dibulatkan menjadi `100.33 LE` (`10033 piastres`).
- **Zero Money Drift Invariant:**
  - `total_piastres = int(Decimal(str(total_wage_le)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)`
  - Pembagian integer: `base_share = total_piastres // n`, `remainder = total_piastres % n`.
  - Sisa integer piastre dialokasikan secara deterministik ke `r` penerima pertama.
  - Jumlah total alokasi terbukti identik: `sum(a["amount_piastres"]) == total_piastres` (selisih = 0 piastre pada semua kombinasi nominal dan jumlah pekerja).
- **Validasi Nilai Non-Numeric / Negatif:**
  - `None`, `NaN`, `Infinity`, `float('inf')`, dan string non-angka ditolak tegas dengan `ValueError`.
  - Nilai negatif ditolak tegas dengan `ValueError("Nominal upah tidak boleh bernilai negatif")`.

---

## 4. AUDIT BATAS MULTI-BUYER (MULTI-BUYER LIMIT AUDIT)
- **Harmonisasi Batas Maksimal:** Diselaraskan secara ketat maksimal 5 pembeli (`1 <= max_buyers <= 5`) pada seluruh lapisan:
  1. **Pydantic Model:** `MaterialPurchaseWagePolicyInput.max_buyers: int = Field(5, ge=1, le=5)`.
  2. **Backend Logic & Getter:** `get_active_material_purchase_wage_policy` melakukan pemotongan batas `min(5, max(1, int(val.get("max_buyers", 5))))`.
  3. **Backend API Endpoint:** `admin_update_wage_policy_endpoint("material_purchase")` menolak `payload.max_buyers < 1 or payload.max_buyers > 5` dengan HTTP 422.
  4. **Frontend Form & Validasi:** `AdminWageSettings.jsx` memvalidasi input `maxBuyers < 1 || maxBuyers > 5` dan membatasi kontrol HTML `<Input type="number" min="1" max="5" />`.
- **Hasil Uji:** Nilai `max_buyers = 6` ditolak dengan HTTP 422; nilai `max_buyers = 0` ditolak dengan HTTP 422; nilai `max_buyers = 1` dan `max_buyers = 5` diterima dengan status HTTP 200.

---

## 5. AUDIT KOMPATIBILITAS KEBIJAKAN PENGANTARAN & DETERMINASI 50 / 100 / 500 LE
- **Asal Usul Angka 50 / 100 / 500 LE:**
  - Nilai 50.0 LE (Tarif Dasar), 100.0 LE (Batas Nominal Tidak Wajar), dan 500.0 LE (Batas Keras / Hard Cap) adalah **Code Fallback Defaults** pada fungsi `get_active_delivery_wage_policy` di `backend/server.py`.
  - Jika dokumen `key: "delivery_wage_policy"` di koleksi `db.settings` belum dibuat oleh Owner, fungsi mengembalikan nilai default in-code tersebut dengan flag `is_configured: False`.
  - Ketika Owner memperbarui kebijakan melalui endpoint lama (`PUT /api/admin/delivery-wage-policy`) maupun endpoint terpadu baru (`PUT /api/admin/wage-policies/delivery`), nilai baru disimpan ke `db.settings` pada key yang sama (`delivery_wage_policy`), dan selanjutnya dikembalikan dengan `is_configured: True`.
- **Sinkronisasi Dua Arah (Bidirectional Parity):**
  - Endpoint lama membaca dan menulis ke koleksi serta dokumen yang sama persis dengan endpoint baru.
  - Payload respons endpoint lama kini dilengkapi dengan field `"enabled": True` dan `"is_configured": True` untuk kompatibilitas penuh.
  - Hak akses konsisten: pembacaan memerlukan izin `access_finance`, pembaruan memerlukan role `owner`.

---

## 6. AUDIT IMMUTABILITAS & INTEGRITAS HISTORIS
- **Immutabilitas Kewajiban Upah Historis:**
  - Dokumen kewajiban upah pekerja pada koleksi `wage_obligations` mencatat `amount_le` dan `amount_piastres` secara permanen saat serah terima/approval terjadi.
  - Perubahan kebijakan pada `db.settings` tidak pernah memicu pembaruan retroaktif atau mutasi pada `wage_obligations` yang telah dicatat sebelumnya.
  - Terverifikasi melalui automated test: data kewajiban upah bernilai 50.0 LE tidak mengalami mutasi ketika kebijakan pengantaran diubah menjadi 65.0 LE lalu 70.0 LE.

---

## 7. HASIL PENGUJIAN REGRESI LENGKAP
1. **Test Suite Phase 08.1 & 08.1.1 (`backend/tests/test_phase08_1_core_wage_settings.py`):**
   - 40 test case: **40 PASSED** (100%), durasi: 1.15s.
2. **Total Backend Wage & Pending Payments Suites (8 test suites):**
   - `test_material_purchase_wages.py`
   - `test_pending_payments_api.py`
   - `test_phase08_1_core_wage_settings.py`
   - `test_phase1_financial_currency_and_wages.py`
   - `test_phase2_work_assignments_wages.py`
   - `test_phase3_f_3_wage_settlement.py`
   - `test_phase3_f_4_2_delivery_wages.py`
   - `test_tiered_delivery_wage_policy.py`
   - Hasil: **204 PASSED**, 0 failed, 10 deprecation warnings.
3. **Frontend Test Suite (7 suites, `CI=true npm test`):**
   - Hasil: **120 PASSED**, 0 failed across 7 test suites.
4. **Frontend Production Build (`npm run build`):**
   - Hasil: **SUCCESS** (Compiled with existing react-hooks warnings, 0 syntax/runtime build errors).
5. **Git Whitespace & Integrity Check (`git diff --check`):**
   - Hasil: **Clean** (Exit code 0, tidak ada trailing whitespace).

---

## 8. DAFTAR FILE TERKAIT
1. `backend/server.py` (Utilitas `distribute_wage_piastres`, `calculate_delivery_helper_wage_allocations`, fail-closed handover, endpoint `/admin/wage-policies`, harmonisasi `max_buyers <= 5`).
2. `backend/tests/test_phase08_1_core_wage_settings.py` (40 unit dan integration test mencakup pembulatan piastre, empty recipient rejection, multi-buyer limit, bidirectional sync, dan immutability).
3. `frontend/src/pages/admin/AdminWageSettings.jsx` (Formulir Pengaturan Upah 4 kategori, harmonisasi input `max_buyers` 1-5).
4. `frontend/src/__tests__/AdminWageSettings.test.js` (Pengujian UI unit setting upah).
5. `frontend/src/pages/admin/AdminDeliveryWageSettings.jsx` (Komponen lama dengan banner migrasi).
6. `frontend/src/pages/admin/AdminLayout.jsx` & `frontend/src/App.js` (Integrasi navigasi menu Pengaturan Upah).
7. `frontend/src/__tests__/AdminLayout.test.js` (Pengujian menu layout).
8. `docs/operations/phase_wage_recovery_08_1_core_wage_settings_and_piastre_allocation.md` (Dokumentasi Phase 08.1).
9. `docs/operations/phase_wage_recovery_08_1_1_corrective_audit.md` (Dokumen audit ini).

---

## 9. STATUS WORKING TREE & SAFETY CONFIRMATION
- **Tidak Ada Mutasi Database Production:** Seluruh pengujian dijalankan pada mock dan memory database lokal.
- **Tidak Ada Deployment:** Tidak ada push ke branch remote, tidak ada deployment Railway maupun Cloudflare Pages.
- **Tidak Ada Auto-Commit:** Perubahan tersimpan rapi pada working tree lokal menunggu instruksi commit resmi.
- **Kesiapan Fase Berikutnya:** Sistem inti pengaturan upah dan alokasi piastre telah terbukti aman, presisi, dan siap dijadikan pondasi untuk Phase 08.2 (Multi-Worker Production Wage Flow).
