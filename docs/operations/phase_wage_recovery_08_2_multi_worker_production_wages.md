# PHASE WAGE RECOVERY 08.2 — MULTI-WORKER PRODUCTION WAGE FLOW
**Tanggal:** 2026-10-28
**Sistem:** Sogil Furniture (`HIDD-Web/Sogil-Furniture`)
**Lingkungan:** Local Verification Workspace (Branch: `main`, Base Commit: `9bd1adab4e7a9a7303917ee573f9053bbfce123b`)
**Status Implementasi & Verifikasi Lokal:** **PASS (READY FOR REVIEW & OPERATIONAL VERIFICATION)**

---

## 1. RINGKASAN EKSEKUTIF

Phase 08.2 mengimplementasikan alur penugasan kerja produksi multi-pekerja (*Multi-Worker Production Wage Flow*) pada sistem Sogil Furniture. Fitur ini memungkinkan 1 hingga 5 pekerja (pengrajin/tukang) ditugaskan secara bersama-sama dalam satu penugasan kerja per item pesanan, dengan perlindungan alokasi unit pesanan, pembagian upah presisi integer piastre (0.01 EGP) tanpa selisih (*zero money drift*), pencegahan duplikasi kewajiban upah, mekanisme pembatalan aman dengan pelepasan kapasitas unit, validasi kebijakan upah produksi (*Fail-Closed*), serta kompatibilitas penuh terhadap model penugasan tunggal warisan (*legacy single-worker assignment*).

---

## 2. PREFLIGHT & INTEGRITAS REPOSITORY

- **Branch Aktif:** `main`
- **Git HEAD:** `9bd1adab4e7a9a7303917ee573f9053bbfce123b`
- **Status Working Tree:** Bersih dari modifikasi liar; memuat perubahan Phase 08.1/08.1.1 serta perubahan terarah Phase 08.2.
- **Git Remote Synchronization:** Sinkron dengan `origin/main`. Tidak ada commit atau push yang dilakukan ke remote repository.
- **Batasan Operasional:** Tidak ada deployment ke Railway atau Cloudflare Pages, tidak ada mutasi ke database production.

---

## 3. PERUBAHAN ARSITEKTUR & FILE

### File yang Dimodifikasi:
1. `backend/server.py`:
   - Penambahan skema input `WorkAssignmentCreateInput` mendukung `worker_ids: Optional[List[str]] = None`, `worker_id` dan `agreed_rate_le` bersifat opsional, dan `pricing_basis` default `"per_unit"`.
   - Modifikasi `admin_create_work_assignment`:
     - Validasi jumlah pekerja: 1 hingga 5 pekerja, penolakan pekerja duplikat dalam satu penugasan.
     - Validasi status pekerja aktif di `db.admins` (role `worker` / `employee`, status aktif).
     - Validasi kapasitas unit: menjamin `total_active_assigned_quantity + target_qty <= ordered_quantity` per item pesanan dan kategori tahapan kerja (`task_category`). Menolak penugasan yang melebihi kapasitas dengan HTTP 422.
     - Penolakan duplikasi penugasan aktif untuk pekerja yang sama pada item dan kategori yang sama.
     - Resolusi tarif upah dari `production_wage_policy` aktif di `db.settings`. Memeriksa batas kewajaran (`unusual_rate_threshold_le`), batas atas keras (`max_wage_per_unit_le`), serta mensyaratkan role `owner` dan alasan minimal 3 karakter untuk manual override. Gagal-aman (*fail-closed* HTTP 422) jika kebijakan tidak terkonfigurasi.
     - Kompatibilitas mundur: jika `worker_id` tunggal dan `agreed_rate_le` dikirimkan secara langsung, penugasan single-worker warisan tetap didukung.
   - Modifikasi `admin_get_order_assignments`:
     - Mengisi array `workers` lengkap dan menyatukan string nama multi-pekerja pada field `worker_name` untuk antarmuka klien lama.
   - Modifikasi `admin_verify_work_assignment`:
     - Verifikasi idempotensi penugasan: memeriksa semua dokumen `wage_obligations` tertaut.
     - Dual-custody enforcement: jika admin yang memverifikasi ada di dalam daftar pekerja penugasan, proses ditolak kecuali memiliki role `owner`.
     - Distribusi piastre terbagi: menggunakan `distribute_wage_piastres(total_wage_le, raw_workers)` untuk membagi upah secara adil dengan total presisi integer tanpa kebocoran uang.
     - Pembuatan dokumen `wage_obligations`: membuat satu kewajiban upah per pekerja dengan `accrual_event_key` unik (`acc_{aid_str}_{wid}` untuk multi-worker atau `acc_{aid_str}` untuk penugasan tunggal).
     - Menyimpan `wage_obligation_numbers` dan `total_wage_recorded_le` pada penugasan.
   - Modifikasi `admin_cancel_work_assignment`:
     - Memeriksa apakah kewajiban upah tertaut sudah pernah dibayar (status `paid` atau `partially_paid`). Jika sudah, pembatalan ditolak tegas dengan HTTP 400.
     - Membatalkan kewajiban upah yang masih berstatus `accrued` (`status: "voided"`).
     - Menandai penugasan sebagai `cancelled`, yang secara otomatis membebaskan kapasitas unit kembali ke kuantitas pesanan.
2. `frontend/src/pages/admin/AdminOrderDetail.jsx`:
   - Memuat kebijakan upah produksi aktif melalui endpoint `/admin/wage-policies/production`.
   - Mengembangkan modal penugasan (*Assign Modal*):
     - Pilihan multi-pekerja (1 hingga 5 pekerja) dengan checkbox interaktif dan counter `(X / 5 Terpilih)`.
     - Ringkasan kapasitas unit: menampilkan kuantitas dipesan, telah ditugaskan, dan sisa tersedia.
     - Peringatan kapasitas terlampaui serta menonaktifkan tombol submit jika kuantitas melebihi kapasitas atau sisa kapasitas 0.
     - Banner peringatan jika `production_wage_policy` belum terkonfigurasi / nonaktif.
     - Estimasi upah total dan pembagian upah per pekerja secara langsung (*real-time preview*).
     - Kartu penugasan menampilkan lencana multi-pekerja `{asn.workers.length} Pekerja` dan daftar nama pekerja.
3. `frontend/src/__tests__/AdminOrderDetail.test.js`:
   - Memperbarui pengujian mock order detail untuk mencakup skenario multi-worker, perhitungan kapasitas, dan penugasan.
4. `backend/tests/test_phase08_2_multi_worker_production_wages.py`:
   - Penambahan 22 test case otomatis independen yang memverifikasi secara mendalam seluruh skenario F.1 hingga F.22.

---

## 4. MODEL PENUGASAN KERJA (WORK ASSIGNMENT DATA MODEL)

### Model Warisan (Legacy Single-Worker):
```json
{
  "_id": ObjectId("..."),
  "order_id": "ord_1001",
  "order_item_id": "itm_01",
  "worker_id": "usr_01",
  "worker_name": "Ahmad",
  "task_category": "whole_item",
  "target_quantity": 2,
  "pricing_basis": "per_unit",
  "agreed_rate_le": 50.0,
  "status": "assigned",
  "wage_obligation_number": "WOB-20261028-0001"
}
```

### Model Baru (Multi-Worker Phase 08.2):
```json
{
  "_id": ObjectId("..."),
  "order_id": "ord_1001",
  "order_item_id": "itm_01",
  "worker_ids": ["usr_01", "usr_02"],
  "workers": [
    {"worker_id": "usr_01", "worker_name": "Ahmad", "role": "employee"},
    {"worker_id": "usr_02", "worker_name": "Budi", "role": "employee"}
  ],
  "worker_id": "usr_01",
  "worker_name": "Ahmad, Budi",
  "task_category": "whole_item",
  "target_quantity": 2,
  "pricing_basis": "per_unit",
  "agreed_rate_le": 50.0,
  "total_assignment_wage_le": 100.0,
  "status": "assigned",
  "rate_source": "policy",
  "rate_policy_snapshot": {
    "policy_key": "production_wage_policy",
    "rate_le": 50.0,
    "max_wage_per_unit_le": 200.0,
    "unusual_rate_threshold_le": 100.0,
    "is_override": false
  },
  "wage_obligation_numbers": ["WOB-20261028-0001", "WOB-20261028-0002"],
  "wage_obligation_number": "WOB-20261028-0001",
  "total_wage_recorded_le": 100.0
}
```

---

## 5. MEKANISME KONTROL & INTEGRITAS FINANSIAL

### A. Pencegahan Over-Allocation Kapasitas Unit
- Unit kapasitas dilacak secara ketat per item pesanan dan kategori tahapan pekerjaan (`task_category`).
- Rumus validasi kapasitas aktif:
  $$\text{Total Active Assigned Qty} = \sum_{\text{active status}} \text{target\_quantity}$$
  $$\text{Total Active Assigned Qty} + \text{Target Qty} \le \text{Ordered Quantity}$$
  Status aktif yang dihitung: `assigned`, `in_progress`, `ready_for_review`, `accruing`, `completed`.
- Jika penugasan berstatus `cancelled`, kapasitas unit penugasan tersebut tidak lagi dihitung, sehingga otomatis kembali menjadi sisa unit tersedia.
- Jika kuantitas target melebihi sisa kapasitas, sistem melempar `HTTPException(422)` dengan rincian unit yang akurat.

### B. Pencegahan Duplikasi Kewajiban Upah
- Idempotensi ganda:
  1. Pemeriksaan awal sebelum akrual pada `admin_verify_work_assignment` memeriksa dokumen `wage_obligations` yang memiliki `work_assignment_id`. Jika sudah ada, sistem mengembalikan data tersimpan tanpa membuat dokumen baru.
  2. Kunci akrual unik: Setiap kewajiban upah memiliki `accrual_event_key`:
     - Multi-worker: `acc_{assignment_id}_{worker_id}`
     - Single-worker legacy: `acc_{assignment_id}`
  3. Kunci idempotensi unik: `wob_assignment_{assignment_id}_{worker_id}`.
  4. Indeks unik MongoDB pada `accrual_event_key` dan `idempotency_key` menjamin bahwa *race conditions* pada level database akan gagal secara konsisten dengan `DuplicateKeyError` dan ditangani secara rekonsiliatif.

### C. Pembatalan Penugasan & Histori Keuangan
- Jika penugasan dibatalkan:
  - Pemeriksaan saldo kewajiban: Jika kewajiban upah terkait memiliki `paid_amount_le > 0` atau berstatus `paid` / `partially_paid`, pembatalan ditolak tegas (`HTTP 400`).
  - Jika kewajiban upah masih berstatus `accrued`, statusnya diubah menjadi `voided`. Dokumen kewajiban tidak dihapus fisik (*soft-void*), sehingga audit trail historis tetap utuh dan nomor urut `WOB` tidak hilang.
  - Status penugasan menjadi `cancelled`, melepaskan unit yang sebelumnya terikat.

### D. Perhitungan Piastre Tanpa Selisih (Zero Money Drift)
- Perhitungan upah total:
  $$\text{Total Wage LE} = \text{Agreed Rate LE} \times \text{Accepted Quantity}$$
- Menggunakan `distribute_wage_piastres(total_wage_le, raw_workers)`:
  - Dikonversi ke integer piastre melalui `ROUND_HALF_UP`:
    $$\text{Total Piastres} = \operatorname{round}(\text{Total Wage LE} \times 100)$$
  - Nilai dasar per pekerja: `base = Total Piastres // n`
  - Sisa piastre: `remainder = Total Piastres % n`
  - Sisa $r$ piastre dibagikan secara adil masing-masing 1 piastre ke $r$ pekerja pertama.
  - Jumlah total pembagian identik 100% dengan total kewajiban perusahaan.

---

## 6. DETAIL KEBIJAKAN PRODUKSI (PRODUCTION WAGE POLICY)

Dokumen kebijakan produksi dikelola pada `db.settings` dengan `key: "production_wage_policy"`:
```json
{
  "key": "production_wage_policy",
  "category": "production",
  "enabled": true,
  "pricing_basis": "per_unit",
  "rates": {
    "cutting": 30.0,
    "assembly": 40.0,
    "finishing": 35.0,
    "whole_item": 50.0
  },
  "default_rate_le": 50.0,
  "unusual_rate_threshold_le": 100.0,
  "max_wage_per_unit_le": 200.0,
  "max_workers_per_assignment": 5,
  "is_configured": true
}
```
- **Fail-Closed:** Jika dokumen kebijakan tidak ada atau `enabled: false`, penugasan baru pada alur Phase 08.2 menolak eksekusi dengan HTTP 422: *"Kebijakan upah produksi belum dikonfigurasi atau dinonaktifkan."*
- **Hard Cap:** Tarif penugasan tidak boleh melebihi `max_wage_per_unit_le` (HTTP 422).
- **Manual Override:** Jika tarif berbeda dari tarif kebijakan, memerlukan role `owner` dan pencatatan `rate_override_reason` minimal 3 karakter.

---

## 7. HASIL PENGUJIAN REGRESI LENGKAP

1. **Test Suite Khusus Phase 08.2 (`backend/tests/test_phase08_2_multi_worker_production_wages.py`):**
   - Command: `./backend/.venv/bin/pytest backend/tests/test_phase08_2_multi_worker_production_wages.py -v`
   - Hasil: **22 passed, 0 failed** (100%), durasi: 1.11s.
   - Skenario yang diuji mencakup F.1 hingga F.22:
     - F.01: Penugasan 1 pekerja tunggal.
     - F.02: Penugasan 2 pekerja bersama.
     - F.03: Penugasan 5 pekerja bersama.
     - F.04: Penolakan penugasan 6 pekerja (batas maksimal 5).
     - F.05: Penolakan penugasan pekerja duplikat.
     - F.06: Penolakan pekerja yang tidak ditemukan atau tidak aktif.
     - F.07: Perhitungan upah total dari tarif dan kuantitas unit.
     - F.08: Pembagian integer piastre tanpa selisih (zero money drift).
     - F.09: Satu order item 2 unit, 2 penugasan terpisah masing-masing 1 unit.
     - F.10: Penolakan kuantitas penugasan melebihi sisa kuantitas pesanan.
     - F.11: Dua pekerja bersama-sama mengerjakan 2 unit.
     - F.12: Pembatalan penugasan melepaskan kuantitas kembali ke kuantitas tersedia.
     - F.13: Pembatalan penugasan mempertahankan histori kewajiban (status `voided`).
     - F.14: Penyelesaian penugasan menghasilkan kewajiban upah presisi dengan snapshot tarif.
     - F.15: Pemanggilan ulang verifikasi bersifat idempoten tanpa duplikasi kewajiban.
     - F.16: Dual-custody: Penolakan verifikasi diri sendiri oleh non-owner.
     - F.17: Kebijakan produksi yang belum dikonfigurasi gagal-aman (*fail-closed* HTTP 422).
     - F.18: Perubahan kebijakan produksi di masa depan tidak mengubah kewajiban historis.
     - F.19: Manual override tarif memerlukan role `owner` dan alasan minimal 3 karakter.
     - F.20: Penolakan tarif melebihi batas atas keras (*hard cap*).
     - F.21: Konsistensi pelunasan parsial dan penuh kewajiban upah produksi.
     - F.22: Pembatalan pelunasan (*void settlement*) memulihkan kewajiban ke status `accrued`.

2. **Seluruh Suite Regresi Backend Upah & Pending Payments (9 test suites):**
   - Command:
     ```bash
     ./backend/.venv/bin/pytest \
     backend/tests/test_phase08_2_multi_worker_production_wages.py \
     backend/tests/test_phase08_1_core_wage_settings.py \
     backend/tests/test_phase2_work_assignments_wages.py \
     backend/tests/test_material_purchase_wages.py \
     backend/tests/test_pending_payments_api.py \
     backend/tests/test_phase1_financial_currency_and_wages.py \
     backend/tests/test_phase3_f_3_wage_settlement.py \
     backend/tests/test_phase3_f_4_2_delivery_wages.py \
     backend/tests/test_tiered_delivery_wage_policy.py -v
     ```
   - Hasil: **226 passed, 0 failed**, 10 deprecation warnings, durasi: 2.09s.

3. **Frontend Test Suite (7 test suites, 121 tests):**
   - Command: `cd frontend && CI=true npm test -- --watchAll=false`
   - Hasil: **121 passed, 0 failed across 7 test suites**, durasi: 3.59s.

4. **Frontend Production Build:**
   - Command: `cd frontend && npm run build`
   - Hasil: **SUCCESS** (Compiled cleanly, File size gzip: 420.43 kB main bundle).

5. **Pemeriksaan Whitespace & Git Diff:**
   - Command: `git diff --check`
   - Hasil: **Clean (Exit code 0, tidak ada trailing whitespace atau conflict marker)**.

---

## 8. PERLINDUNGAN KEAMANAN & BATASAN OPERASIONAL

- **Zero Commit / Push:** Tidak ada commit atau push ke `origin/main`.
- **Zero Deployment:** Tidak ada build atau deploy trigger ke Railway atau Cloudflare Pages.
- **Zero Production Database Mutation:** Tidak ada koneksi, manipulasi dokumen, pembuatan data palsu, atau pembaruan langsung pada MongoDB Atlas production.
- **Scope Discipline:** Fitur Phase 08.3 (multi-buyer material), Phase 08.4 (admin wage accrual), Phase 08.5 (rekonsiliasi 13 order lama), Phase 10 (general pending expenses), dan Phase 11 (supplier debt) tetap tertutup dan tidak dimasukkan ke dalam pekerjaan ini.
