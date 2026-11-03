# SOGIL FURNITURE — ADMIN ORDERS PERFORMANCE & NAVIGATION CORRECTIVE REPORT

> **Dokumen Operasional:** `docs/operations/admin_orders_performance_navigation_corrective_report.md`
> **Tanggal Pelaksanaan:** 3 November 2026
> **Status Verifikasi:** PASSED (Siap untuk deployment terkontrol)
> **Git Base Commit:** `f81bd2bb599f2441c8b4c5d64d12b4f4737c6a3f` (Branch: `main`)

---

## 1. RINGKASAN EKSEKUTIF

Fase perbaikan ini menangani 3 masalah performa dan navigasi yang dilaporkan operator pada halaman Admin Orders:
1. **Performa Pemuatan Lambat (>5 detik pada tab Total Pesanan):**
   - **Akar Masalah:** Pola sekuensial $N+1$ query di endpoint `GET /api/admin/orders`. Untuk setiap pesanan dalam daftar (mis. 21 pesanan), fungsi `compute_order_payment_summary` mengeksekusi `await db.payments.find` secara individu. Di lingkungan cloud (backend Railway di US West ke MongoDB Atlas di AWS Frankfurt), latensi round-trip jaringan WAN berkisar 180–220ms per kueri, terakumulasi menjadi ~4,5–5,5 detik pemblokiran I/O sekuensial.
   - **Solusi Terpasang:** Logika komputasi pembayaran diekstraksi ke helper murni in-memory `compute_payment_summary_from_records(order_doc, recorded_payments)`. Endpoint `admin_list_orders` mengumpulkan seluruh `order_id` (baik representasi string maupun `ObjectId`), lalu menjalankan **satu batch query tunggal** menggunakan operator `$in` dengan projection hemat bandwidth `{"order_id": 1, "status": 1, "amount_le": 1}`. Kompleksitas kueri berkurang dari $N+1$ (22 kueri) menjadi $O(1)$ (2 kueri: 1 orders + 1 batch payments). Single-order helper `compute_order_payment_summary` tetap dipertahankan penuh untuk kompatibilitas backward rute lain.
2. **Race Condition & Potensi Data Usang pada Perpindahan Filter:**
   - **Akar Masalah:** Navigasi filter di `AdminOrders.jsx` sebelumnya membaca snapshot lama `params` melalui `new URLSearchParams(params)` alih-alih functional updater, sehingga klik cepat berurutan berpotensi menimpa state query URL dengan closure basi. Selain itu, bila request filter aktif gagal (misal koneksi terputus), state `orders` lama dari filter sebelumnya tidak dibersihkan, membiarkan data kategori lain tetap terpampang di bawah tab baru.
   - **Solusi Terpasang:** `handleFilterSelect` kini menggunakan functional updater `setParams((prevParams) => { ... })`. Saat request aktif mengalami kegagalan non-abort, state `orders` dikosongkan (`setOrders([])`), error ditampilkan secara transparan via alert kontainer `data-testid="orders-error"`, dan tombol retry `data-testid="orders-retry-btn"` disediakan untuk recovery instan tanpa refresh halaman.
3. **Duplikasi Tombol Google Maps pada Detail Pesanan:**
   - **Akar Masalah:** Pada `AdminOrderDetail.jsx`, tombol aksi berlabel `"Maps"` berada di baris aksi utama bersanding dengan WhatsApp dan Salin Ringkasan. Namun, di kartu informasi Customer di bawahnya, baris "Maps" juga merender elemen interaktif bergaya tombol aksi lengkap dengan ikon, menciptakan redundant CTA di halaman yang sama.
   - **Solusi Terpasang:** Tombol aksi utama di baris atas tetap dipertahankan tunggal (`data-testid="admin-maps-button"` berdampingan dengan WhatsApp). Pada kartu Informasi Customer, baris data "Maps" diubah menjadi link teks URL yang informatif (`data-testid="customer-maps-link"`, `break-all`) dengan atribut aksesibilitas, tanpa membingungkan operator dengan tombol aksi ganda.

---

## 2. AUDIT PERUBAHAN FILE

### 2.1. Backend (`backend/server.py`)
- **Fungsi Baru:** `compute_payment_summary_from_records(order_doc: dict, recorded_payments: list) -> dict` (baris 426–495).
  - Menghitung secara deterministik in-memory: `total_paid_le`, `effective_paid_le`, `balance_le`, `calculated_payment_status`, dan `payment_reconciliation`.
  - Sepenuhnya murni tanpa I/O database.
- **Fungsi Kompatibilitas:** `compute_order_payment_summary(order_doc: dict, session=None) -> dict` (baris 497–514).
  - Melakukan fetch single order payments, lalu memanggil `compute_payment_summary_from_records`. Tetap kompatibel 100% untuk endpoint detail dan update status pembayaran.
- **Optimasi Endpoint:** `admin_list_orders` (baris 2215–2265).
  - Mengambil daftar order dari `db.orders`.
  - Menghimpun seluruh representasi `ObjectId` dan `str` dari ID pesanan ke dalam `set`.
  - Menjalankan 1 batch kueri `db.payments.find({"order_id": {"$in": unique_ids}, "status": "recorded"}, {"order_id": 1, "status": 1, "amount_le": 1})`.
  - Mengelompokkan pembayaran berdasarkan ID pesanan dalam dictionary in-memory `payments_by_order`.
  - Menghitung ringkasan pembayaran per order secara instan in-memory.

### 2.2. Frontend Orders (`frontend/src/pages/admin/AdminOrders.jsx`)
- **Functional URL Update:** Mengganti `const next = new URLSearchParams(params)` dengan `setParams((prevParams) => { const next = new URLSearchParams(prevParams); ... return next; })`.
- **Error State & Stale Data Clearing:** Menambahkan state `error` dan `retryCount`. Ketika request aktif gagal, `setOrders([])` dipanggil untuk mencegah kebocoran data kategori sebelumnya.
- **User-Facing Error Alert & Retry:** Merender kontainer alert ramah pengguna dengan tombol "Coba Lagi" (`data-testid="orders-retry-btn"`).

### 2.3. Frontend Order Detail (`frontend/src/pages/admin/AdminOrderDetail.jsx`)
- **Single Maps CTA Action:** Mempertahankan 1 tombol aksi utama di header berdampingan dengan Telepon dan WhatsApp (`data-testid="admin-maps-button"`).
- **Clean Customer Info Link:** Mengubah tampilan baris alamat/maps pada kartu Customer Info menjadi link URL teks terformat rapi (`data-testid="customer-maps-link"`), mencegah duplikasi visual dan layout shift.

---

## 3. HASIL VERIFIKASI PENGUJIAN

### 3.1. Pengujian Unit & Mock Backend
- **Test Suite Baru:** [test_admin_orders_batch_performance.py](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/backend/tests/test_admin_orders_batch_performance.py)
  - Memvalidasi 10 kasus uji: kesesuaian 100% hasil perhitungan batch vs individual, verifikasi kueri database tepat 1 kali untuk 21 order (bukan 21 kali), penanganan ID campuran (`ObjectId` vs string), order kosong, order tanpa pembayaran, order dengan multi-termin pembayaran, dan toleransi legacy DP.
- **Hasil:**
  ```text
  backend/tests/test_admin_orders_batch_performance.py::test_compute_payment_summary_from_records_no_payments PASSED
  backend/tests/test_admin_orders_batch_performance.py::test_compute_payment_summary_from_records_with_payments PASSED
  backend/tests/test_admin_orders_batch_performance.py::test_compute_payment_summary_from_records_legacy_dp PASSED
  backend/tests/test_admin_orders_batch_performance.py::test_batch_vs_single_compute_strict_equivalence PASSED
  backend/tests/test_admin_orders_batch_performance.py::test_admin_list_orders_executes_single_batch_query_not_n_plus_one PASSED
  backend/tests/test_admin_orders_batch_performance.py::test_admin_list_orders_empty_list PASSED
  backend/tests/test_admin_orders_batch_performance.py::test_admin_list_orders_matches_both_objectid_and_str_order_ids PASSED
  backend/tests/test_admin_orders_batch_performance.py::test_admin_list_orders_payment_status_filter_preserved PASSED
  backend/tests/test_admin_orders_batch_performance.py::test_admin_list_orders_search_filter_preserved PASSED
  backend/tests/test_admin_orders_batch_performance.py::test_compute_order_payment_summary_backward_compatibility PASSED
  ============================== 10 passed in 1.24s ==============================
  ```
- **Regression Suite Backend Terkait:**
  - `test_corrective_p1_payment_integrity.py`: 23 passed.
  - `test_phase1_order_payment_core.py`: 25 passed.
  - `test_phase2_checkout_delivery_maps.py`: 25 passed.
  - Total: **83 backend tests passed** tanpa kegagalan.

### 3.2. Pengujian Frontend
- **Test Suite Diperbarui:**
  - [AdminOrders.test.js](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/frontend/src/__tests__/AdminOrders.test.js) (9 tes): Memvalidasi pencegahan race condition, abort cleanup saat unmount, functional `setParams` pada klik cepat, penanganan out-of-order response, pembersihan data basi saat error, serta recovery tombol retry.
  - [AdminOrderDetail.test.js](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/frontend/src/__tests__/AdminOrderDetail.test.js) (27 tes): Memvalidasi eksistensi tepat 1 tombol aksi Maps di header, text link Maps di info customer, dan ketiadaan tombol saat URL Maps kosong.
- **Hasil:**
  ```text
  PASS src/__tests__/AdminOrders.test.js
  PASS src/__tests__/AdminOrderDetail.test.js
  Test Suites: 2 passed, 2 total
  Tests:       36 passed, 36 total
  ```
- **Seluruh Suite Frontend (Full Suite):**
  - **14 test suites passed**, **192 tests passed** (100% green).

### 3.3. Build Produksi Frontend (`craco build`)
- Perintah: `cd frontend && CI=false npm run build`
- Hasil:
  ```text
  Compiled with warnings (unrelated missing hook dependency warnings).
  File sizes after gzip:
    434.11 kB (+143 B)  build/static/js/main.ce30272f.js
    17.9 kB (+11 B)     build/static/css/main.cdfbc270.css
  The build folder is ready to be deployed.
  ```
- Status: **BUILD SUCCESSFUL (Exit Code 0)**.

---

## 4. ESTIMASI DAMPAK PERFORMA

| Metrik | Sebelum Perbaikan | Setelah Perbaikan | Penghematan / Peningkatan |
|---|---|---|---|
| Kueri Database per Pemuatan (21 Order) | 1 orders + 21 payments ($N+1$) = **22 kueri** | 1 orders + 1 batch payments = **2 kueri** | **Pengurangan 91% round-trip I/O** |
| Estimasi Durasi Backend I/O (WAN ~200ms) | $22 \times 200\text{ ms} \approx 4.400 - 5.500\text{ ms}$ | $2 \times 200\text{ ms} \approx 400 - 500\text{ ms}$ | **~10x lebih cepat (hemat ~4,5 detik)** |
| Responsivitas Navigasi Filter | Terbuka risiko race condition / data usang | Terproteksi: `latestRequestIdRef`, functional updater, & error-clearing | **Deterministik & Kebal Out-of-Order** |
| Tampilan Tombol Google Maps | 2 tombol interaktif bertabrakan fungsi visual | 1 Action Button di Action Bar + 1 URL text link di Kartu Data | **Bersih, konsisten, dan mudah dipahami** |

---

## 5. REKOMENDASI DEPLOYMENT

Perbaikan saat ini tersimpan di working tree lokal secara bersih tanpa efek samping ke database production maupun repositori remote.
Langkah yang disarankan untuk operator berikutnya:
1. Stage dan commit perubahan yang relevan:
   - `backend/server.py`
   - `frontend/src/pages/admin/AdminOrders.jsx`
   - `frontend/src/pages/admin/AdminOrderDetail.jsx`
   - `backend/tests/test_admin_orders_batch_performance.py`
   - `frontend/src/__tests__/AdminOrders.test.js`
   - `frontend/src/__tests__/AdminOrderDetail.test.js`
   - `docs/operations/admin_orders_performance_navigation_corrective_report.md`
2. Push ke branch `main`.
3. Jalankan deployment terkontrol ke Railway (backend) dan Cloudflare Pages (frontend).
