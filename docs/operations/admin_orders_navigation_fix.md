# SOGIL FURNITURE — ADMIN ORDERS NAVIGATION FIX REPORT

**Repository:** `HIDD-Web/Sogil-Furniture` (`/Users/syahidmujahid/Sogil-Project/Sogil-Furniture`)  
**Branch:** `main`  
**Baseline Commit:** `9f979712dc5aeb04b602119b9facd4056b364bb1`  
**Execution Date:** November 3, 2026  
**Engineer:** Senior Full-Stack Engineer  

---

## 1. Masalah yang Diselesaikan (Problem Statement)

Sebelum perbaikan ini, pengguna (admin) yang sedang memfilter daftar pesanan berdasarkan status tertentu (misalnya status `"siap"` / *Siap Diambil/Dikirim*, `"proses"`, `"menunggu_pembayaran"`, dll.) atau sedang melakukan pencarian kata kunci tertentu (misalnya query `"SOGIL-001"`):
1. Ketika mengklik salah satu baris pesanan atau kartu pesanan untuk membuka halaman **Admin Order Detail** (`/admin/orders/:orderId`),
2. Kemudian menekan tombol **"Kembali"** pada halaman detail tersebut,
3. Halaman daftar pesanan kembali ke kondisi *default*: tab filter tereset ke **"Semua"** (`status=all`) dan kata kunci pencarian hilang.

Hal ini mengganggu efisiensi kerja admin yang sedang memproses batch pesanan pada status tertentu, karena admin harus memilih ulang tab filter dan mengetik ulang kata kunci pencarian setiap kali selesai memeriksa satu pesanan.

---

## 2. Solusi & Detail Implementasi (Phase B)

Implementasi dilakukan secara murni pada lapisan antarmuka pengguna (*frontend*) tanpa memodifikasi backend atau skema basis data, menggunakan fitur native React Router DOM (`useLocation` dan `navigate state`).

### A. Modifikasi pada `frontend/src/pages/admin/AdminOrders.jsx`
1. **Sinkronisasi Parameter Pencarian dengan URL:**
   - Parameter `q` dari query string URL dibaca saat inisialisasi state: `searchParams.get("q") || ""`.
   - Fungsi `handleSearchSubmit` dan `handleSearchClear` disinkronkan untuk memperbarui query string URL secara reaktif.
2. **Penyimpanan URL Asal (`backUrl`):**
   - Dihitung URL lengkap dengan query parameter aktif:
     ```javascript
     const queryString = searchParams.toString();
     const backUrl = queryString ? `/admin/orders?${queryString}` : "/admin/orders";
     ```
   - URL ini mencakup parameter `status` (misal `?status=siap`), parameter `q` (misal `&q=Budi`), serta filter lainnya.
3. **Penerusan State Navigasi:**
   - Saat admin mengklik kartu pesanan (tampilan *mobile*) atau baris tabel pesanan (tampilan *desktop*), router memanggil:
     ```javascript
     navigate(`/admin/orders/${order.order_id}`, { state: { from: backUrl } });
     ```

### B. Modifikasi pada `frontend/src/pages/admin/AdminOrderDetail.jsx`
1. **Penerimaan State Asal (`location.state`):**
   - Menggunakan hook `useLocation`:
     ```javascript
     const location = useLocation();
     const backTarget = location?.state?.from || "/admin/orders";
     ```
2. **Navigasi Terarah & Fallback Aman:**
   - Tombol utama **"Kembali"** di bagian header bernavigasi ke `backTarget`.
   - Tombol "Kembali" pada tampilan *error / not found* bernavigasi ke `backTarget`.
   - Aksi pengalihan setelah penghapusan pesanan (*post-delete*) bernavigasi ke `backTarget`.
   - Jika halaman dibuka langsung melalui tautan URL baru atau bookmark tanpa riwayat state (`location.state` bernilai `null` atau `undefined`), navigasi otomatis *fallback* ke `"/admin/orders"`.

---

## 3. Bukti Pengujian & Regresi (Phase C)

### A. Unit & Integration Test Navigasi
Dibuat berkas pengujian baru: `frontend/src/__tests__/AdminOrdersNavigation.test.js` yang menguji 10 skenario navigasi:
1. Navigasi kembali dari detail mempertahankan tab filter `all`.
2. Navigasi kembali dari detail mempertahankan tab filter `menunggu_pembayaran`.
3. Navigasi kembali dari detail mempertahankan tab filter `menunggu_verifikasi`.
4. Navigasi kembali dari detail mempertahankan tab filter `proses`.
5. Navigasi kembali dari detail mempertahankan tab filter `siap`.
6. Navigasi kembali dari detail mempertahankan tab filter `selesai`.
7. Navigasi kembali dari detail mempertahankan tab filter `dibatalkan`.
8. Navigasi kembali mempertahankan kombinasi filter status dan kata kunci pencarian (`?status=siap&q=Sogil`).
9. Akses langsung (*direct access*) ke URL detail tanpa state bernavigasi kembali ke default `"/admin/orders"`.
10. Tampilan error pada detail pesanan menggunakan `backTarget` yang sesuai.

### B. Hasil Pengujian Keseluruhan
1. **Frontend Test Suite:**
   - Perintah: `cd frontend && CI=true npm test -- --passWithNoTests`
   - Hasil: **15 passed, 15 total test suites (202 passed, 202 total tests)**.
2. **Frontend Production Build:**
   - Perintah: `cd frontend && npm run build`
   - Hasil: **Berhasil tanpa error (exit code 0)**.
3. **Backend Regression Test Suite:**
   - Perintah: `./backend/.venv/bin/pytest backend/tests/test_admin_orders_batch_performance.py backend/tests/test_corrective_p1_payment_integrity.py backend/tests/test_phase2_checkout_delivery_maps.py backend/tests/test_phase1_order_payment_core.py`
   - Hasil: **89 passed, 0 failed (exit code 0)**.

---

## 4. Integritas Kode & Batasan Sistem
- **Zero Backend Changes:** Tidak ada baris kode backend yang diubah.
- **Zero Database Operations:** Tidak ada modifikasi data atau indeks pada MongoDB production.
- **Zero Commit & Push:** Seluruh perubahan tetap berada dalam *working tree* lokal siap ditinjau.
