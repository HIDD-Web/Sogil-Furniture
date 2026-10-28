# SOGIL FURNITURE — LAPORAN PHASE 08.1
## Core Wage Settings & Shared Piastre Allocation

**Proyek:** Sogil Furniture
**Repository:** `/Users/syahidmujahid/Sogil-Project/Sogil-Furniture`
**Branch:** `main`
**Baseline Commit:** `9bd1adab4e7a9a7303917ee573f9053bbfce123b`
**Tanggal Verifikasi:** 28 Oktober 2026
**Status Implementasi:** **SELESAI & TERVERIFIKASI PENUH (100%)**

---

### 1. RINGKASAN EKSEKUTIF (EXECUTIVE SUMMARY)

Phase 08.1 berhasil meletakkan fondasi terpusat untuk konfigurasi kebijakan upah (*Wage Settings*) dan kalkulasi pembagian desimal eksak (*Shared Piastre Allocation*) untuk seluruh sistem Sogil Furniture:

1. **Shared Integer Piastre Allocation Utility:**
   - Dibuat fungsi terpusat `distribute_wage_piastres(total_amount_le, recipients)` di `backend/server.py`.
   - Memastikan presisi desimal hingga 1 piastre (0.01 EGP) dengan jaminan matematika mutlak: **Zero Money Lost or Created** ($\sum p_i = \text{total\_piastres}$).
   - Fungsi warisan `calculate_delivery_helper_wage_allocations` direfaktor menjadi thin wrapper delegasi tanpa memodifikasi kontrak input/output, mempertahankan kompatibilitas 100%.

2. **Core Wage Settings Data Models & API:**
   - Didefinisikan model Pydantic untuk 4 kategori kebijakan upah bertingkat:
     - `production_wage_policy` (`ProductionWagePolicyInput`)
     - `delivery_wage_policy` (`DeliveryWagePolicyInput`)
     - `material_purchase_wage_policy` (`MaterialPurchaseWagePolicyInput`)
     - `admin_wage_policy` (`AdminWagePolicyInput`)
   - Disediakan endpoint terpusat:
     - `GET /api/admin/wage-policies`: membaca 4 kebijakan sekaligus (hak akses `access_finance` / Owner).
     - `GET /api/admin/wage-policies/{category}`: membaca kebijakan spesifik.
     - `PUT /api/admin/wage-policies/{category}`: mutasi kebijakan (khusus Owner/CEO, mencatat audit log).
     - `GET /api/admin/wage-policies/{category}/history`: riwayat audit perubahan kebijakan.
   - Penanganan kebijakan belum disetel (*Unconfigured State*): kategori yang belum memiliki tarif resmi mengembalikan `is_configured: False` dan `enabled: False` tanpa menebak tarif sembarangan (*fail-closed*).
   - Seluruh endpoint warisan (`GET /api/admin/delivery-wage-policy`, `PUT /api/admin/delivery-wage-policy`, `GET /api/admin/delivery-wage-policy/history`) dipertahankan 100% retrokompatibel.

3. **Evolusi Frontend & Kompatibilitas:**
   - Dibuat halaman terpusat `frontend/src/pages/admin/AdminWageSettings.jsx` dengan 4 tab: Upah Produksi, Upah Pengiriman, Upah Belanja Bahan, Upah Admin.
   - Halaman warisan `frontend/src/pages/admin/AdminDeliveryWageSettings.jsx` diubah menjadi wrapper retrokompatibel yang langsung merender tab pengiriman.
   - Menu navigasi `frontend/src/pages/admin/AdminLayout.jsx` diperbarui dari "Upah Kirim" menjadi "Pengaturan Upah" mengarah ke `/admin/wage-settings`.
   - Routing di `frontend/src/App.js` mendaftarkan rute baru `/admin/wage-settings` dan mempertahankan rute lama `/admin/delivery-wage-settings`.

4. **Verifikasi & Status Pengujian:**
   - **Backend:** 199/199 tes lulus (164 tes baseline + 35 tes baru di `backend/tests/test_phase08_1_core_wage_settings.py`).
   - **Frontend:** 120/120 tes lulus (114 tes baseline + 6 tes baru di `frontend/src/__tests__/AdminWageSettings.test.js`).
   - **Build Produksi:** `npm run build` sukses 100% tanpa error kompilasi.

---

### 2. ARSITEKTUR UTILITY ALOKASI INTEGER PIASTRE

#### Prinsip Kerja `distribute_wage_piastres`
```python
def distribute_wage_piastres(total_amount_le: float, recipients: list) -> list:
```

1. **Konversi ke Satuan Integer Piastre:**
   - Nominal input dikonversi menggunakan desimal:
     $$\text{total\_piastres} = \operatorname{int}\left(\operatorname{round}\left(d \times 100\right)\right)$$
   - Menggunakan mode pembulatan `ROUND_HALF_UP`.
2. **Validasi Input Fail-Closed:**
   - Jika `recipients` kosong atau `None`: mengembalikan `[]`.
   - Jika `total_piastres < 0`: menolak dengan `ValueError("Nominal upah tidak boleh bernilai negatif")`.
   - Deteksi duplikasi: jika terdapat duplikasi ID penerima upah, menolak dengan `ValueError("Penerima upah duplikat terdeteksi: ...")`.
3. **Pembagian Deterministik & Resolusi Sisa:**
   $$q = \lfloor \text{total\_piastres} / n \rfloor, \quad r = \text{total\_piastres} \pmod n$$
   - Sebanyak $r$ penerima pertama menerima $q + 1$ piastre.
   - Sebanyak $n - r$ penerima berikutnya menerima $q$ piastre.
4. **Jaminan Invarian (Zero Money Drift):**
   $$\sum_{i=1}^{n} p_i \equiv \text{total\_piastres}$$
   - Dilindungi assertion runtime otomatis:
     `assert total_allocated_piastres == total_piastres`
5. **Output Terstruktur:**
   Setiap alokasi mengembalikan:
   ```json
   {
     "worker_id": "...",
     "worker_name": "...",
     "amount_piastres": 1667,
     "amount_le": 16.67
   }
   ```

---

### 3. SKEMA DAN STRUKTUR KEBIJAKAN UPAH

Semua kebijakan disimpan di koleksi MongoDB `db.settings` menggunakan pola Key-Value teruji:

| Kategori | Kunci Setting | Status Default Awal | Validasi Aturan |
| :--- | :--- | :--- | :--- |
| **Produksi** | `production_wage_policy` | `is_configured: false`<br>`enabled: false` | $0 \le \text{default} \le \text{threshold} < \text{max\_cap}$ |
| **Pengiriman** | `delivery_wage_policy` | `is_configured: false` (dengan nilai dasar 50 / 100 / 500 LE) | $0 \le \text{base} \le \text{threshold} < \text{max\_cap}$ |
| **Belanja Bahan** | `material_purchase_wage_policy` | `is_configured: false`<br>`enabled: false`<br>`max_buyers: 5` | $0 \le \text{default} \le \text{threshold} < \text{max\_cap}$<br>$1 \le \text{max\_buyers} \le 20$ |
| **Admin** | `admin_wage_policy` | `is_configured: false`<br>`enabled: false` | $0 \le \text{default} \le \text{threshold} < \text{max\_cap}$<br>`default_recipient_id` diverifikasi di `db.admins` |

#### Penanganan Kebijakan Belum Dikonfigurasi (*Unconfigured State*)
Untuk kategori Produksi, Belanja Bahan, dan Admin:
- Sebelum disimpan oleh Owner, API mengembalikan:
  ```json
  {
    "default_wage_per_unit_le": null,
    "unusual_amount_threshold_le": null,
    "max_wage_per_unit_le": null,
    "enabled": false,
    "is_configured": false,
    "currency": "EGP",
    "rounding_policy": "piastre_round_half_up"
  }
  ```
- Sistem **TIDAK MENEBAK** tarif bisnis dan tidak memperlakukan 0 LE sebagai tarif aktif. Ini menjamin sistem tidak akan mengakumulasi kewajiban upah palsu pada order atau belanja bahan sebelum disetujui Owner.

---

### 4. ENDPOINT API TERPUSAT & KONTROL OTORISASI

| Metode & Path | Akses Otorisasi | Deskripsi & Perilaku |
| :--- | :--- | :--- |
| `GET /api/admin/wage-policies` | `require_perm("access_finance")` | Mengambil status dan konfigurasi 4 kebijakan sekaligus |
| `GET /api/admin/wage-policies/{category}` | `require_perm("access_finance")` | Mengambil konfigurasi kategori tertentu (`production`, `delivery`, `material_purchase`, `admin`) |
| `PUT /api/admin/wage-policies/{category}` | `require_owner()` (Khusus Owner/CEO) | Memvalidasi dan menyimpan pembaruan kebijakan, mencatat riwayat audit log |
| `GET /api/admin/wage-policies/{category}/history` | `require_perm("access_finance")` | Mengambil riwayat audit log perubahan kebijakan kategori terkait |
| `GET /api/admin/delivery-wage-policy` | `require_perm("access_finance")` | *Wrapper kompatibilitas ke belakang* untuk kebijakan pengiriman |
| `PUT /api/admin/delivery-wage-policy` | `require_owner()` | *Wrapper kompatibilitas ke belakang* untuk pembaruan pengiriman |
| `GET /api/admin/delivery-wage-policy/history` | `require_perm("access_finance")` | *Wrapper kompatibilitas ke belakang* riwayat audit pengiriman |

---

### 5. MANIFEST PERUBAHAN FILE

| No | File Path | Tipe Perubahan | Ringkasan Modifikasi |
| :---: | :--- | :---: | :--- |
| 1 | `backend/server.py` | Dimodifikasi | Model Pydantic, fungsi `distribute_wage_piastres`, refaktor `calculate_delivery_helper_wage_allocations`, getters kebijakan, dan endpoints `/admin/wage-policies`. |
| 2 | `backend/tests/test_phase08_1_core_wage_settings.py` | **Baru** | 35 pengujian otomatis untuk utility piastre, unconfigured status, validasi batasan, lookup penerima admin, dan kontrol izin Owner. |
| 3 | `frontend/src/pages/admin/AdminWageSettings.jsx` | **Baru** | Halaman Pengaturan Upah terpadu dengan 4 tab navigasi, badge peringatan belum dikonfigurasi, form bertingkat, simulator piastre, dan riwayat audit. |
| 4 | `frontend/src/pages/admin/AdminDeliveryWageSettings.jsx` | Dimodifikasi | Refaktor menjadi wrapper retrokompatibel menuju `AdminWageSettings defaultTab="delivery"`. |
| 5 | `frontend/src/pages/admin/AdminLayout.jsx` | Dimodifikasi | Update menu sidebar menjadi "Pengaturan Upah" mengarah ke `/admin/wage-settings`. |
| 6 | `frontend/src/App.js` | Dimodifikasi | Pendaftaran rute `/admin/wage-settings` dengan preservasi rute lama `/admin/delivery-wage-settings`. |
| 7 | `frontend/src/__tests__/AdminWageSettings.test.js` | **Baru** | 6 pengujian rendering 4 tab, navigasi, validasi form, penyimpanan kebijakan oleh Owner, dan mode baca tim keuangan. |
| 8 | `frontend/src/__tests__/AdminLayout.test.js` | Dimodifikasi | Penambahan verifikasi keberadaan tautan menu "Pengaturan Upah" untuk staf keuangan dan penyembunyiannya untuk staf non-keuangan. |

---

### 6. HASIL VERIFIKASI PENGUJIAN OTOMATIS

#### A. Backend Test Suite (Pytest)
```
$ ./backend/.venv/bin/pytest backend/tests/test_material_purchase_wages.py \
    backend/tests/test_pending_payments_api.py \
    backend/tests/test_phase1_financial_currency_and_wages.py \
    backend/tests/test_phase2_work_assignments_wages.py \
    backend/tests/test_phase3_f_3_wage_settlement.py \
    backend/tests/test_phase3_f_4_2_delivery_wages.py \
    backend/tests/test_tiered_delivery_wage_policy.py \
    backend/tests/test_phase08_1_core_wage_settings.py

======================= 199 passed, 10 warnings in 2.07s =======================
```
- **Total Pengujian:** 199 Passed, 0 Failed, 0 Errored.
- **Rincian:**
  - 164 tes fungsional upah dan pembayaran tertunda eksisting.
  - 35 tes baru Phase 08.1 mencakup seluruh cabang aritmatika piastre, status unconfigured, validasi batasan, role-based security, dan retrokompatibilitas.

#### B. Frontend Test Suite (Jest)
```
$ CI=true npm test -- --watchAll=false

PASS src/__tests__/format.test.js
PASS src/__tests__/AdminWageSettings.test.js
PASS src/__tests__/AdminDeliveryWageSettings.test.js
PASS src/__tests__/AdminOrderDetail.test.js
PASS src/__tests__/AdminLayout.test.js
PASS src/__tests__/AdminWorkerPendingWages.test.js
PASS src/__tests__/AdminLogistics.test.js

Test Suites: 7 passed, 7 total
Tests:       120 passed, 120 total
Snapshots:   0 total
Time:        3.111 s
Ran all test suites.
```
- **Total Pengujian:** 120 Passed, 0 Failed across 7 test suites.
- Menjamin integrasi UI, tab switching, form validation, dan proteksi role berjalan sempurna.

#### C. Frontend Production Build
```
$ npm run build
Creating an optimized production build...
Compiled with warnings (unrelated legacy hooks).
File sizes after gzip:
  419.24 kB (+3.73 kB)  build/static/js/main.1c5451d3.js
  17.55 kB (+54 B)      build/static/css/main.b14e8ca0.css
Exit Code: 0 (SUCCESS)
```

#### D. Git State & Format Check
```
$ git diff --check
(Zero formatting / whitespace errors)
```

---

### 7. AUDIT KESELAMATAN & BLAST RADIUS

- **Database Produksi:** Tidak ada mutasi, migrasi, atau koneksi ke database produksi Railway MongoDB selama fase ini berlangsung.
- **Environment & Secrets:** Tidak ada modifikasi pada file `.env`, kredensial, atau token autentikasi.
- **Deployment Platform:** Tidak ada deployment otomatis atau manual yang dipicu ke Railway maupun Cloudflare Pages.
- **Branch & Git State:** Semua perubahan berada dalam working tree lokal. Belum ada commit atau push ke remote `origin/main`.
- **Integritas Fitur Eksisting:** Kebijakan upah pengiriman bertingkat, flow serah terima order, alokasi helper, dan Pending Payment 4 kategori tetap berjalan normal tanpa interupsi.

---

### 8. KESIAPAN & REKOMENDASI TAHAP BERIKUTNYA

Dengan selesainya Phase 08.1:
1. Fondasi kebijakan upah bertingkat (`production_wage_policy`) telah siap digunakan oleh backend penugasan produksi.
2. Utility alokasi integer piastre (`distribute_wage_piastres`) siap digunakan untuk membagi upah produksi di antara banyak pekerja (*multi-worker production assignment*).
3. Fondasi ini membuka jalan bagi eksekusi **Phase 08.2: Multi-Worker Production Assignment & Wage Splitting**.
