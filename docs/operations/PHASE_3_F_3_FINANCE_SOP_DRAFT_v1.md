# STANDAR OPERASIONAL PROSEDUR (SOP) KEUANGAN
## Pembayaran dan Pembatalan (Void) Upah Pekerja (Phase 3.F.3)

---

### METADATA DOKUMEN

| Parameter | Keterangan |
| :--- | :--- |
| **Nomor Dokumen** | `SOP-FIN-2026-003-DRAFT` |
| **Judul Dokumen** | Standar Operasional Prosedur Pembayaran dan Pembatalan (Void) Upah Pekerja |
| **Versi Dokumen** | `v1.3-FINAL-DRAFT (Minimum Safe Wage Settlement Procedures)` |
| **Tanggal Penyusunan** | 14 Oktober 2026 |
| **Pemilik Dokumen** | Tim Keuangan & Operasional Sogil Furniture |
| **Status Dokumen** | **DRAFT — MENUNGGU PENGESAHAN FINAL OWNER** |
| **Tanggal Efektif** | ____________________ *(Dikosongkan hingga disahkan)* |
| **Disahkan Oleh (Owner)**| ____________________ *(Tanda Tangan & Nama Jelas)* |

> [!WARNING]
> **PERNYATAAN RESMI DRAF:**  
> Dokumen ini merupakan usulan prosedur operasional standar minimum yang aman bagi Staf Keuangan, Pengelola Kasir, dan Manajemen Operasional Sogil Furniture. Dokumen ini dirancang sederhana dan praktis untuk bisnis mebel yang dikelola langsung oleh Owner. Dokumen ini **BUKAN** kebijakan perusahaan yang mengikat sampai disetujui dan ditandatangani secara tertulis oleh Owner Sogil Furniture.

---

## 1. TUJUAN DAN RUANG LINGKUP

### 1.1. Tujuan
1. Memastikan keselarasan mutlak antara uang fisik kas di kasir/brankas dan rekening bank dengan catatan buku besar keuangan (*finance ledger*).
2. Mencegah risiko kerugian finansial akibat pembayaran ganda (*duplicate disbursement*), transaksi menggantung, atau selisih kas fisik.
3. Memberikan batasan tegas dan terukur terhadap fitur pembatalan (*void*) di aplikasi agar tidak disalahgunakan untuk menutupi selisih fisik uang kas.
4. Menstandarkan prosedur verifikasi berjenjang dan rekonsiliasi harian multimetode secara tertib, transparan, dan akuntabel.

### 1.2. Ruang Lingkup
SOP ini berlaku untuk seluruh transaksi pembayaran upah pekerja harian, borongan per unit, maupun penugasan khusus pada workshop/operasional Sogil Furniture yang dicatat melalui menu **Upah Pekerja** (`/admin/wages/pending`) dan buku besar keuangan (`/admin/finance/transactions`).

---

## 2. STRUKTUR BISNIS, PEMBAGIAN PERAN, DAN PEMISAHAN TUGAS (SEGREGATION OF DUTIES)

### 2.1. Struktur Organisasi Bisnis Sogil Furniture
Struktur organisasi dan pembagian peran di Sogil Furniture terdiri dari:
1. **Owner (Satu Orang):** Pemilik bisnis tunggal yang memegang hak kepemilikan penuh, keputusan akhir, penetapan kebijakan bisnis, pengawasan kepatuhan keuangan, dan otorisasi pengeluaran dana besar.
2. **Manager Operational merangkap Admin (Satu Orang):** Dibayar berbasis pesanan sesuai pekerjaan/peran yang dijalankan. Bertanggung jawab membantu operasional harian, mengoordinasikan produksi, mengelola pesanan, memverifikasi penugasan kerja, serta membantu administrasi kasir sesuai batas wewenang yang diberikan.
3. **Pekerja (*Workers* — Beberapa Orang):** Bekerja berdasarkan sistem borongan (*piece-rate*) atau harian berbasis pesanan (bukan karyawan tetap). Pekerja menerima upah berdasarkan penugasan kerja nyata yang telah selesai dan diverifikasi.

### 2.2. Prinsip Pemisahan Tugas (Segregation of Duties)
Untuk mencegah penyalahgunaan wewenang dan kesalahan pencatatan, operasional keuangan upah menerapkan pemisahan tugas secara tegas:
1. **Preparer (Penyusun & Pemeriksa Rincian):** Petugas Kasir / Manager Operational yang bertugas memeriksa rincian penugasan borongan, kehadiran dan identitas pekerja, ketersediaan dana fisik/bank, serta mencocokkan nomor kewajiban/pesanan.
2. **Approver (Pemberi Persetujuan Resmi):** Owner tunggal Sogil Furniture yang berwenang memberikan persetujuan resmi untuk pembayaran yang mencapai atau melampaui ambang batas besar ($\ge 5.000\text{ LE}$), pembayaran di luar batas wewenang rutin, atau penyesuaian selisih kas.
3. **Disburser / Executor (Pelaksana Pembayaran Nyata):** Petugas kasir tunai (untuk pembayaran tunai) atau petugas yang benar-benar berwenang mengeksekusi transfer bank resmi.
4. **Reviewer (Pemeriksa Rekonsiliasi):** Owner Sogil Furniture yang melakukan pemeriksaan dan verifikasi rekonsiliasi harian serta tinjauan retrospektif atas berkas fisik dan laporan pembukuan.

> [!IMPORTANT]
> **ATURAN PEMISAHAN FUNGSI MUTLAK:**  
> Satu orang **TIDAK BOLEH** dianggap memenuhi seluruh fungsi di atas hanya karena orang tersebut memiliki akses login atau hak akses administratif ke aplikasi.

### 2.3. Ketentuan Khusus Upah Kerja Nyata Owner
1. **Tidak Ada Gaji Tetap:** Owner tidak menerima gaji bulanan tetap dari kas operasional perusahaan.
2. **Kompensasi Kerja Nyata:** Owner berhak menerima pembayaran upah hanya untuk pekerjaan fisik, produksi, atau pekerjaan desain kustom (*custom furniture design*) yang benar-benar dikerjakan sendiri oleh Owner dan memenuhi kriteria upah yang sah.
3. **Transparansi & Anti Double-Counting:** Setiap penugasan kerja nyata Owner wajib dicatat secara transparan pada sistem penugasan kerja (`wage_obligations`) dengan rincian pekerjaan yang jelas, sehingga seluruh biaya produksi terdata secara akurat dan tidak dihitung ganda sebagai biaya produksi maupun dividen pemilik.
4. **Larangan Persetujuan Sepihak oleh Manager:** Manager Operational merangkap Admin **DILARANG KERAS** menjadi pemberi persetujuan (*approver*) atau pengeksekusi tunggal atas pencairan upah atas nama Owner. Seluruh pencairan upah Owner wajib diverifikasi dan disetujui langsung oleh Owner secara tertulis.

### 2.4. Realitas Kode Aplikasi vs. Disiplin Operasional Manual
- **Implementasi Perangkat Lunak Saat Ini (`backend/server.py`):**
  - Akun sistem terbagi menjadi `owner`, `manager`, `admin`, dan `employee`. Aturan *single-owner* ditegakkan di kode (`Line 5684`).
  - Namun, rute pelunasan upah (`POST /api/admin/wages/settlements`) saat ini diproteksi oleh dependensi `require_finance_or_owner()`, yang mengizinkan eksekusi oleh akun mana pun dengan atribut `access_finance: true` (termasuk Manager secara default).
  - Backend saat ini **BELUM MENEGAKKAN** pemisahan tugas, ambang batas 5.000 LE, batas delegasi, maupun antrean persetujuan (*pending approval queue*) secara otomatis di tingkat kode.
- **Disiplin Operasional Manual:**  
  Oleh karena itu, seluruh aturan persetujuan Owner, pembatasan nominal, dan pemisahan tugas ditegakkan secara ketat melalui **disiplin operasional manual staf** sesuai SOP ini.

---

## 3. PROSEDUR PERSETUJUAN OWNER UNTUK PEMBAYARAN BESAR

### 3.1. Kebijakan Ambang Batas Pembayaran Besar (5.000 LE)
Berdasarkan keputusan resmi Owner:
1. **Ambang Batas Pembayaran Besar:** Ditetapkan nominal sebesar **5.000 LE (Lima Ribu Egyptian Pounds)** sebagai ambang kebijakan operasional awal.
2. **Kewajiban Persetujuan Owner:**  
   Setiap pembayaran upah yang nominalnya **mencapai atau melampaui 5.000 LE ($\ge 5.000\text{ LE}$)** **WAJIB** memperoleh persetujuan resmi tertulis dari Owner **SEBELUM** pelunasan (*settlement*) dicatat di aplikasi dan **SEBELUM** uang fisik diserahkan atau transfer bank dilaksanakan.
3. **Pembayaran Upah Rutin Saat Owner Hadir (< 5.000 LE):**  
   Dalam kondisi operasional normal di mana Owner hadir/tersedia, pembayaran upah rutin di bawah 5.000 LE yang telah terverifikasi penyelesaian tugas fisiknya dapat diproses dan diserahkan langsung oleh Petugas Kasir / Manager Operational yang bertugas.
4. **Peringatan Disiplin Staf:**  
   Petugas Keuangan bertanggung jawab secara disiplin untuk tidak menekan tombol konfirmasi pelunasan pada sistem apabila transaksi $\ge 5.000\text{ LE}$ belum mendapatkan persetujuan tertulis resmi dari Owner.

### 3.2. Aturan Anti-Structuring dan Agregasi Berdasarkan Kewajiban yang Sama
Keputusan resmi Owner mengenai agregasi pembayaran dan larangan pemecahan transaksi (*anti-structuring*):
1. **Larangan Pemecahan Transaksi (*Anti-Structuring*):**  
   Dilarang keras memecah satu kewajiban pekerjaan atau satu kesepakatan pembayaran upah yang sebenarnya mencapai atau melampaui 5.000 LE menjadi beberapa transaksi pelunasan bernominal kecil (misalnya: memecah kewajiban borongan 7.000 LE menjadi pembayaran 4.000 LE dan 3.000 LE) dengan tujuan menghindari kewajiban persetujuan Owner. Tindakan ini merupakan pelanggaran berat integritas keuangan.
2. **Agregasi Berdasarkan Kewajiban / Pesanan yang Sama:**  
   Pembayaran bertahap atau parsial untuk satu kewajiban penugasan atau pesanan yang sama **tetap dinilai berdasarkan total kewajiban terkait**, bukan hanya jumlah cicilan yang sedang dibayar. Jika total kewajiban penugasan tersebut berjumlah $\ge 5.000\text{ LE}$, maka seluruh pencairannya (termasuk cicilan pertamanya) wajib mendapatkan persetujuan Owner.
3. **Pekerjaan Independen yang Berbeda Tidak Otomatis Digabungkan:**  
   Kewajiban independen dari pesanan yang benar-benar berbeda tidak otomatis digabungkan hanya karena penerima upahnya adalah pekerja yang sama. Pekerja yang mengerjakan beberapa pesanan independen berhak menerima pelunasan per pesanan sesuai jadwal penyelesaian masing-masing.
4. **Kewajiban Penghentian Saat Hubungan Kewajiban Tidak Jelas:**  
   Jika hubungan antara pembayaran dan kewajiban penugasan tidak jelas, atau terdapat keraguan apakah beberapa penugasan merupakan satu kesatuan proyek, petugas kasir **WAJIB MENGHENTIKAN PEMBAYARAN** dan meminta klarifikasi serta keputusan tertulis dari Owner.
5. **Ketiadaan Kontrol Otomatis Backend Saat Ini:**  
   Sistem aplikasi saat ini belum memiliki kemampuan untuk mendeteksi hubungan kewajiban atau melakukan agregasi penugasan secara otomatis. Tidak ada aturan *rolling 24 jam* otomatis yang aktif di sistem. Penegakan aturan agregasi ini dilakukan secara manual oleh petugas kasir dengan memeriksa identitas penugasan/nomor pesanan pada lembar kerja fisik dan ringkasan kewajiban di sistem.

### 3.3. Evaluasi Berkala Kebijakan Ambang Batas
Kebijakan ambang batas 5.000 LE ini berstatus usulan kebijakan operasional awal dan akan **dievaluasi kembali setelah 30 hari penggunaan operasional nyata**, atau sewaktu-waktu apabila skala dan volume pesanan bisnis Sogil Furniture mengalami perubahan signifikan.

---

## 4. PEMERIKSAAN WAJIB SEBELUM PEMBAYARAN (PRE-PAYMENT CHECKLIST)

Sebelum membuka modal pelunasan dan memproses pembayaran, Petugas Kasir / Manager Operational (selaku *Preparer*) wajib melakukan verifikasi berurutan:

1. **Verifikasi Kehadiran & Identitas Penerima:**
   - Pekerja hadir secara fisik di depan kasir, ATAU telah memberikan instruksi tertulis yang sah mengenai nomor rekening tujuan atas nama dirinya sendiri.
   - Apabila penerima upah adalah Owner (untuk kompensasi kerja fisik nyata/desain kustom), pencairan **hanya boleh dieksekusi atas persetujuan tertulis langsung dari Owner**, bukan persetujuan sepihak Manager.
2. **Pemeriksaan Kewajiban Terutang & Hubungan Pesanan di Aplikasi:**
   - Buka menu **Upah Pekerja** (`/admin/wages/pending`).
   - Pastikan kewajiban upah pekerja bersangkutan berstatus *Terakrual* (`accrued`) atau *Sebagian Terbayar* (`partially_paid`).
   - Pastikan penugasan kerja yang mendasarinya telah diverifikasi secara fisik oleh Mandor atau Manager Operational (`completed`).
   - Identifikasi nomor pesanan/kewajiban untuk memastikan total nilai penugasan tidak melanggar aturan agregasi anti-structuring.
3. **Pengecekan Ketersediaan Dana Nyata:**
   - **Metode Tunai (*Cash*):** Hitung fisik uang kertas di laci kasir; pastikan uang fisik mencukupi untuk nominal yang akan diinput.
   - **Metode Transfer Bank:** Buka mutasi/saldo rekening bank operasional resmi; pastikan saldo mencukupi untuk pembayaran dan biaya transfer (jika ada).
4. **Verifikasi Ambang Batas & Otorisasi Transaksi:**
   - **Transaksi $\ge 5.000\text{ LE}$ (atau cicilan dari kewajiban total $\ge 5.000\text{ LE}$):** Wajib memiliki lembar persetujuan fisik/tertulis bertanda tangan Owner sebelum diproses.
   - **Transaksi Saat Owner Tidak Tersedia:** Wajib memiliki Surat Mandat Delegasi Tertulis resmi bernomor dari Owner, dan nominal transaksi **tidak melebihi 1.000 LE**. Jika tidak ada mandat aktif, pembayaran **WAJIB DITUNDA**.
   - Dilarang memecah nominal transaksi untuk menghindari ambang batas (*anti-structuring*).
5. **Pencocokan Nominal Pembayaran:**
   - Masukkan nominal pembayaran (`amount_le`). Sistem secara otomatis menolak pembayaran yang melebihi total sisa kewajiban terutang pekerja (*fail-closed*).
   - Tentukan skema alokasi: alokasi otomatis berdasarkan tanggal penugasan tertua (FIFO) atau alokasi manual ke kewajiban tertentu sesuai kesepakatan dengan pekerja.
6. **Disiplin Satu Kali Klik & Idempotensi:**
   - Sistem secara otomatis mengirimkan kunci idempotensi acak (`idempotency_key`) untuk mencegah duplikasi.
   - Jika koneksi internet sedang lambat atau peramban sedang memuat (*loading*), **DILARANG KERAS MENGKLIK TOMBOL BAYAR BERULANG KALI**. Tunggu konfirmasi selesai atau ikuti prosedur penanganan gangguan jaringan pada Pasal 8.

---

## 5. TATA CARA PENCATATAN DAN PENYERAHAN PEMBAYARAN NYATA (THE GOLDEN SEQUENCE)

Untuk menjamin alur pembayaran praktis, aman, dan meminimalkan risiko kesalahan operasional pada bisnis mebel Sogil Furniture, setiap penanganan pelunasan upah dan kas **WAJIB MENGIKUTI 6 TAHAP INTI ALUR KERJA SEDERHANA**:

1. **Tahap 1 — Verifikasi Pekerja & Pekerjaan:**  
   Periksa identitas pekerja, fisik pekerjaan yang telah selesai diverifikasi mandor/manager, nomor kewajiban upah terutang di sistem (`/admin/wages/pending`), dan jumlah nominal yang tepat harus dibayar.
2. **Tahap 2 — Konfirmasi Wewenang Sah:**  
   Pastikan pihak yang memproses transaksi memiliki wewenang yang sah:
   - Jika nominal $\ge 5.000\text{ LE}$ (atau bagian dari pesanan bernilai $\ge 5.000\text{ LE}$): Wajib persetujuan tertulis resmi dari Owner SEBELUM mencatat ke sistem.
   - Jika Owner berhalangan: Manager hanya boleh memproses transaksi rutin $\le 1.000\text{ LE}$ yang dicakup Surat Mandat sah, atau pembayaran yang memiliki persetujuan tertulis jarak jauh spesifik dari Owner. Tanpa wewenang sah, **PEMBAYARAN WAJIB DITUNDA**. Dilarang membuat pengecualian darurat sepihak.
3. **Tahap 3 — Pencatatan Settlement Sekali Saja di Aplikasi:**  
   Catat pelunasan melalui alur kerja aplikasi yang sudah ada (`POST /api/admin/wages/settlements`). Tekan tombol konfirmasi pelunasan **TEPAT SATU KALI**.
4. **Tahap 4 — Konfirmasi Hasil Sistem Sebelum Menyerahkan Uang:**  
   Pastikan hasil eksekusi aplikasi berstatus `recorded` dan nomor pelunasan resmi (`WST-YYYYMMDD-XXXX`) terbit **SEBELUM** uang kas fisik diserahkan atau transfer bank dieksekusi.
   - *Peringatan:* Jika respons aplikasi ambigu atau terjadi gangguan jaringan (*timeout*), **STOP**. Periksa riwayat transaksi dan buku besar keuangan sebelum mengambil tindakan apa pun. Jangan mencoba ulang secara membabi buta dengan kunci idempotensi baru atau menganggap galat berarti transaksi tidak tercatat.
   - *Pemisahan Data vs Kas:* Catatan transaksi berstatus `recorded` di komputer **BUKAN BUKTI** bahwa uang telah sampai ke pekerja.
5. **Tahap 5 — Pencatatan Bukti Pembayaran Nyata & Tanda Terima:**  
   Serahkan uang kas fisik dari laci kasir (atau lakukan transfer bank resmi satu kali). Wajib minta tanda tangan pekerja pada lembar tanda terima fisik asli bertanda tangan basah atau simpan slip mutasi transfer bank resmi.
6. **Tahap 6 — Masukkan ke Rekonsiliasi Kas Harian:**  
   Masukkan seluruh bukti tanda terima dan nomor settlement ke dalam Formulir Rekonsiliasi Harian Kas & Upah untuk pencocokan penutupan kas sore/malam hari.

> [!IMPORTANT]
> **ATURAN INTEGRITAS AKUNTANSI KAS & BIAYA:**  
> Metadata alokasi, saldo kewajiban upah terutang (`wage_obligations`), maupun catatan cermin `employee_wages` **TIDAK BOLEH** dihitung sebagai mutasi arus kas tambahan. Tepat satu pelunasan nyata hanya boleh mencatat satu pengeluaran kas di buku besar keuangan (`finance_transactions`) tanpa duplikasi biaya.

---

## 6. PENANGANAN PEMBAYARAN SEBAGIAN (PARTIAL PAYMENTS)

1. Apabila dana kasir tidak mencukupi untuk melunasi seluruh kewajiban pekerja, atau atas kesepakatan bersama upah dibayarkan sebagian:
   - Masukkan nominal uang yang benar-benar akan diserahkan.
   - Sistem akan mengalokasikan pembayaran ke penugasan tertua terlebih dahulu.
   - Status kewajiban yang terbayar penuh berubah menjadi `paid`, sedangkan kewajiban yang baru terbayar sebagian berubah status menjadi `partially_paid`.
   - Sisa saldo hutang upah pekerja yang belum terbayar akan tetap tercatat di sistem sebagai kewajiban terutang yang sah.
2. Dilarang mencatat pembayaran penuh di sistem jika uang fisik yang diserahkan hanya sebagian.

---

## 7. PEMBATALAN (VOID) DAN LARANGAN MUTLAK PASCA-DISBURSEMENT

### 7.1. Perbedaan Mendasar Komputer vs. Uang Fisik
> [!CAUTION]
> **TINDAKAN *VOID* PADA SISTEM HANYALAH KOREKSI DATA DI KOMPUTER.**  
> Menekan tombol *Void* di aplikasi **TIDAK PERNAH MENGEMBALIKAN UANG FISIK** yang sudah keluar dari brankas kasir atau sudah dibawa pekerja.

Saat fungsi pembatalan (*void*) dijalankan pada sistem:
1. Status pelunasan pada `wage_settlements` diubah menjadi `voided`.
2. Pengeluaran kas pada `finance_transactions` ditandai batal (`is_void: True`), sehingga saldo buku kas di sistem **bertambah kembali seolah uang tidak pernah keluar**.
3. Sisa kewajiban pekerja pada `wage_obligations` **dinaikkan kembali** (pekerja tercatat belum dibayar).
4. Catatan cermin pada `employee_wages` dihapus.

### 7.2. Penanganan Kesalahan Pembayaran Setelah Uang Fisik Keluar (Overpayment After Physical Payout)
Apabila kesalahan pembayaran upah (seperti kelebihan bayar atau salah alokasi) baru disadari setelah uang fisik diserahkan atau transfer bank berhasil:
1. **Dilarang Void Sepihak:** Manager/kasir **dilarang keras membatalkan (*void*) settlement secara sepihak** di aplikasi.
2. **Lapor ke Owner:** Manager/kasir wajib segera mendokumentasikan dan melaporkan selisih/kesalahan tersebut kepada Owner.
3. **Keputusan Tertulis di Tangan Owner:** Owner memeriksa bukti pendukung dan menentukan penyelesaian atau koreksi tertulis yang sah dan terdokumentasi.
4. **Larangan Pemotongan Otomatis / Sepihak:** Tidak diperbolehkan melakukan pemotongan otomatis atau sepihak dari upah pekerja di masa depan, dan dilarang melakukan penyesuaian saldo diam-diam (*silent write-off*).
5. **Tanpa Alur Pembayaran Rumit di Rilis Ini:** Prosedur rilis ini **tidak menetapkan alur pembayaran kembali (*repayment*) atau pemotongan upah terperinci**; seluruh penyelesaian diserahkan kepada keputusan tertulis Owner demi menjaga keselamatan pembukuan dan keharmonisan tim.

### 7.3. Realitas Aplikasi vs Pengawasan Manual Owner Terkait Koreksi Upah
- **Yang Ditegakkan Aplikasi Saat Ini:**  
  Aplikasi hanya menyediakan rute atomik pembatalan administratif (`POST /api/admin/wages/settlements/{id}/void`) yang membalikkan status settlement, menandai transaksi biaya batal (`is_void: True`), dan mengembalikan sisa kewajiban upah di database. Aplikasi **TIDAK MENEGAKKAN** pengecekan apakah uang fisik sudah sampai atau belum ke tangan pekerja, tidak memiliki fitur pemotongan upah otomatis (*wage garnishment*), dan tidak mendeteksi kelebihan bayar nyata.
- **Yang Bergantung pada Pengawasan Manual Owner:**  
  Pemeriksaan fisik bukti tanda terima, verifikasi apakah dana kasir fisik benar-benar keluar, serta penetapan keputusan penyelesaian atas kesalahan pembayaran pasca-disbursement sepenuhnya bergantung pada pengawasan dan keputusan manual Owner.

---

## 8. PENANGANAN GANGGUAN JARINGAN & TRANSAKSI MENGGANTUNG (AMBIGUOUS OUTCOMES)

Apabila terjadi gangguan jaringan (layar memuat lama, peramban terputus, batas waktu habis/*timeout*, ketiadaan notifikasi konfirmasi pada antarmuka, atau muncul pesan galat) saat menekan tombol konfirmasi pembayaran:

### 8.1. Prinsip Keselamatan Operasional & Larangan Keras
1. **Status Sistem Bukan Bukti Penyerahan Nyata:** Adanya catatan berstatus `recorded` di komputer **HANYA** mengonfirmasi keberadaan catatan di sistem; status tersebut **BUKAN BUKTI** bahwa uang fisik telah sampai ke tangan pekerja atau transfer bank telah berhasil dieksekusi oleh pihak perbankan. Petugas dilarang menyerahkan dana semata-mata karena sebuah transaksi berstatus `recorded` di layar.
2. **Kesesuaian Kanal Pembayaran (*Strict Payment Channel Discipline*):** Setiap penyerahan dana wajib mengikuti kanal metode pembayaran (`payment_method`) yang tercatat:
   - Jika tercatat `cash`, pencairan dana dilakukan dari kasir tunai fisik dengan tanda terima fisik bertanda tangan.
   - Jika tercatat `bank_transfer`, transaksi dieksekusi melalui transfer rekening bank resmi dengan nomor referensi transfer bank. Dilarang keras mengganti transfer bank dengan uang tunai (atau sebaliknya) tanpa prosedur koreksi administratif tersendiri yang disahkan secara tertulis oleh Owner.
   - Dilarang keras melakukan pembayaran yang sama melalui dua kanal berbeda (misal: mentransfer via bank sekaligus menyerahkan uang tunai kasir).
3. **Ketidakpastian Bukan Berarti Gagal (*Failures Cannot Be Inferred*):** Terjadinya batas waktu habis (*timeout*), galat koneksi, peramban macet, atau saldo tampilan UI yang tampak belum berubah **BUKAN BUKTI** bahwa transaksi gagal diproses di peladen backend atau basis data. Request mungkin masih berjalan lambat (*in-flight*) atau telah berhasil tersimpan di basis data.
4. **Larangan Retrial Buta & Idempotensi Frontend:** Antarmuka web menghasilkan kunci idempotensi baru setiap kali modal pembayaran dibuka ulang. Oleh karena itu, **DILARANG KERAS** menutup modal lalu membuka ulang untuk mencoba pembayaran kembali secara membabi buta dengan kunci idempotensi baru.
5. **Ketiadaan Jeda Otomatis:** Tidak ada durasi jeda waktu tetap (termasuk jeda 2 menit) yang dapat dijadikan jaminan bahwa transaksi *in-flight* telah selesai atau gagal.

### 8.2. Prosedur Investigasi dan Verifikasi Multi-Titik (Multi-Point Verification)
Apabila status akhir transaksi tidak dapat dipastikan, petugas **WAJIB MENGHENTIKAN SELURUH PENYERAHAN DANA DAN PERCOBAAN INPUT ULANG**. Lakukan penelusuran fakta berurutan melalui prosedur verifikasi *read-only* yang sah:
1. **Titik 1 — Cek Bukti Fisik & Perbankan Nyata:** Periksa uang di laci kasir dan mutasi rekening bank resmi. Apakah ada dana nyata yang telah keluar/berpindah?
2. **Titik 2 — Cek Integritas Data Sistem (Read-Only):** Muat ulang halaman `/admin/wages/pending`. Periksa tab riwayat pelunasan (`GET /api/admin/wages/settlements`) dan daftar ringkasan kewajiban upah (`GET /api/admin/wages/pending-summary`). Periksa apakah terbentuk nomor pelunasan baru (`WST-YYYYMMDD-XXXX`) dan apakah transaksi biaya terkait pada buku besar keuangan (`/admin/finance/transactions`) terbentuk secara konsisten.
3. **Titik 3 — Bukti Operasional Pekerja:** Mintakan konfirmasi fisik kepada pekerja apakah ada penerimaan uang tunai atau mutasi transfer bank masuk. Lembar tanda terima fisik bertanda tangan dan konfirmasi pekerja merupakan bukti operasional pendukung, dan **bukan** kontrol otomatis perangkat lunak.

### 8.3. Matriks Penanganan dan Eskalasi
- **Kasus 1 (Catatan Sistem Terkonfirmasi 'recorded', Dana Belum Disalurkan):**  
  Petugas keuangan **TIDAK BOLEH** langsung menyodorkan dana. Penyaluran baru boleh dilanjutkan HANYA SETELAH:
  - Dipastikan bahwa transaksi tersebut valid, unik, dan tidak ada rekaman pelunasan ganda di sistem; DAN
  - Penyaluran dana dilakukan secara tepat melalui metode pembayaran yang tercatat (`cash`, `bank_transfer`, atau `other`); DAN
  - Untuk metode `cash`: pekerja menandatangani tanda terima fisik penyerahan uang kasir;
  - Untuk metode `bank_transfer`: transfer bank dieksekusi satu kali via portal bank resmi dengan mencantumkan nomor referensi bank;
  - Untuk metode `other`: dokumen pertanggungjawaban fisik ditandatangani kedua belah pihak.
- **Kasus 2 (Catatan Sistem Terkonfirmasi 'recorded' dan Dana Telah Disalurkan):**  
  Transaksi telah selesai secara fisik dan sistem. Dilarang melakukan tindakan input atau pengeluaran dana apa pun lagi.
- **Kasus 3 (Status Belum Dapat Dipastikan Secara Konklusif / Hasil Ambigu):**  
  **HENTIKAN SELURUH TINDAKAN OPERASIONAL.**  
  - Dilarang menyerahkan uang tunai.
  - Dilarang mengeksekusi transfer bank.
  - Dilarang mengulang penginputan data settlement di aplikasi.
  - Lakukan eskalasi segera kepada Owner dan Administrator Teknis untuk pemeriksaan status request pada sistem dan log.
  - Penyaluran dana atau penginputan ulang hanya boleh dilanjutkan setelah status dari request sebelumnya dipastikan secara konklusif (apakah berhasil tercatat atau tuntas gagal) dan kanal pembayaran serta jumlah nominal telah direkonsiliasi penuh.

---

## 9. PROSEDUR REKONSILIASI PENUTUPAN KAS HARIAN MULTIMETODE (END-OF-DAY)

Setiap akhir jam operasional, Petugas Keuangan wajib melakukan rekonsiliasi tiga arah secara terpisah:

### 9.1. Rekonsiliasi Laci Kas Tunai Fisik (Cash Drawer)
Formula perhitungan fisik kasir:
$$\text{Fisik Kas Akhir Diharapkan} = \text{Fisik Kas Awal} + \text{Total Penerimaan Kas Tunai Nyata} - \text{Total Pengeluaran Kas Tunai Nyata}$$

- *Perhatian Anti-Double Count:* Pengeluaran kas tunai nyata di atas sudah mencakup upah tunai pekerja. Jangan mengurangkan biaya upah tunai dua kali.
- Total fisik uang tunai yang keluar untuk upah wajib sama persis dengan total pelunasan di sistem yang memenuhi kriteria:  
  **Metode Pembayaran = "cash" DAN Status = "recorded"**.
- Setiap pengeluaran tunai wajib memiliki tanda terima fisik bertanda tangan pekerja.

### 9.2. Rekonsiliasi Non-Tunai / Transfer Bank
- Total pelunasan dengan kriteria **Metode Pembayaran = "bank_transfer" DAN Status = "recorded"** wajib cocok secara nominal dengan mutasi debet pada rekening koran/aplikasi bank resmi hari tersebut.
- Setiap transfer bank wajib melampirkan nomor referensi bank dan struk transfer digital.

### 9.3. Rekonsiliasi Metode Lainnya (Other)
- Transaksi bertanda **Metode Pembayaran = "other"** (misal: barter barang, kompensasi pihak ketiga) **DILARANG** digabungkan ke laci kasir fisik atau mutasi bank biasa.
- Transaksi ini wajib diaudit terpisah dengan melampirkan Berita Acara Serah Terima Barang/Kompensasi Khusus yang ditandatangani oleh penerima dan Owner.

### 9.4. Pengecualian Mutlak Transaksi Batal (Void)
- Seluruh pelunasan upah berstatus `voided` serta transaksi keuangan dengan tanda batal (`is_void: True`) **TIDAK BOLEH** dihitung sebagai pengeluaran kas yang sah.

### 9.5. Rekonsiliasi Saldo Hutang Upah Terutang (Obligation Ledger)
- Total saldo kewajiban upah pada laporan ringkasan wajib cocok dengan akumulasi sisa nominal (`total_amount_le - paid_amount_le`) dari seluruh kewajiban berstatus `accrued` atau `partially_paid`.

### 9.6. Masa Uji Coba Operasional 1 Minggu (One-Week Trial)
- Formulir Rekonsiliasi Harian Kas & Upah diberlakukan dalam **masa uji coba operasional selama 1 (satu) minggu** sejak rilis operasional dimulai.
- Pada akhir minggu pertama uji coba, Owner akan mengevaluasi apakah pengisian formulir harian ini berjalan praktis (dapat diselesaikan dalam waktu 10–15 menit pada hari kerja normal) atau membutuhkan penyederhanaan lebih lanjut.
- Masa uji coba ini merupakan evaluasi operasional berjalan dan **bukan alasan untuk menunda rilis produksi**.
- Apabila terjadi selisih kas fisik, petugas kasir wajib mencatatnya dan segera memberitahukan Owner; dilarang keras memodifikasi catatan diam-diam hanya demi membuat angka kas terlihat seimbang (*Zero Silent Write-Off*).

---

## 10. TANDA TANGAN LAPORAN, KETENTUAN KETIDAKHADIRAN OWNER, DELEGASI SEMENTARA, & PERSETUJUAN JARAK JAUH

### 10.1. Tanggung Jawab Rekonsiliasi Harian & Penandatanganan
1. **Pencatatan & Penghitungan Fisik:** Manager Operational merangkap kasir bertugas mencatat mutasi kas harian, menghitung fisik uang tunai di kasir pada saat tutup kas, dan mendokumentasikan selisih (jika ada).
2. **Pemeriksaan Owner:** Owner meninjau dan menandatangani formulir rekonsiliasi harian saat tersedia, diutamakan maksimal pada hari kerja berikutnya.
3. **Pemisahan Batas Delegasi 1.000 LE:** Batas delegasi transaksi 1.000 LE berlaku spesifik untuk otorisasi pembayaran upah delegasi, dan **tidak otomatis membatasi wewenang Manager untuk menyusun atau menandatangani formulir rekonsiliasi kasir harian**.
4. **Tanpa Lapisan Persetujuan Tambahan:** Prosedur ini sengaja dirancang sederhana tanpa menambah lapisan persetujuan baru atau menuntut tanda tangan berlebih yang membebani operasional harian.

### 10.2. Ketentuan Mutlak Saat Owner Tidak Tersedia
1. **Ketiadaan Kewenangan Pengganti Otomatis:**  
   Manager Operational merangkap Admin **TIDAK MEMPUNYAI** kewenangan pengganti secara otomatis hanya karena Owner sedang tidak berada di tempat atau berhalangan hadir.
2. **Kewajiban Penundaan Tanpa Mandat Sah:**  
   **Tanpa adanya Surat Mandat Delegasi Tertulis yang aktif dan sah dari Owner, seluruh pembayaran upah HARUS DITUNDA, termasuk pembayaran rutin dengan nominal di bawah 5.000 LE.** Dilarang membuat pengecualian darurat sepihak.
3. **Batas Delegasi Tetap 1.000 LE per Transaksi:**  
   Berdasarkan keputusan resmi Owner, batas delegasi pembayaran yang dapat diberikan kepada Manager Operational ditetapkan **maksimal 1.000 LE (Satu Ribu Egyptian Pounds) per transaksi**, dan hanya berlaku di bawah surat mandat tertulis aktif yang sah. **Batas ini tidak diubah ke 1.500 LE atau angka lain.** Pembayaran upah nominal > 1.000 LE tetap wajib menunggu kehadiran atau persetujuan tertulis spesifik dari Owner.
4. **Persetujuan Tertulis Spesifik Per Transaksi dari Owner:**  
   Jika Owner berhalangan hadir, persetujuan tertulis spesifik dari Owner dapat mengotorisasi pembayaran di atas batas delegasi Manager (1.000 LE), asalkan persetujuan tersebut otentik, dapat diverifikasi, dan secara eksplisit menyebutkan transaksi spesifik, nama penerima, dan nominal yang disetujui.
5. **Larangan Wewenang Mutlak Manager:**  
   Manager dilarang menerbitkan surat mandat untuk dirinya sendiri (*no self-delegation*), dilarang mengubah kebijakan finansial Owner, dilarang menyetujui upahnya sendiri, dan dilarang menyetujui upah kerja nyata Owner.

### 10.3. Syarat Wajib Surat Mandat Delegasi Tertulis Resmi
Delegasi wewenang hanya sah apabila dituangkan dalam surat mandat tertulis resmi bernomor yang ditandatangani oleh Owner, dan wajib memuat 8 elemen:
1. Identitas lengkap penerima mandat (Manager Operational yang ditunjuk).
2. Jenis pembayaran yang diizinkan (khusus pembayaran upah rutin pekerja harian/borongan penugasan workshop).
3. Batas nominal per transaksi (maksimal $\le 1.000\text{ LE}$).
4. Tanggal mulai (*valid from*) dan tanggal kedaluwarsa (*valid until*) yang definitif.
5. Alasan spesifik pemberian mandat / halangan Owner.
6. Bukti pembayaran fisik yang wajib disimpan (tanda terima fisik asli bertanda tangan pekerja).
7. Nomor referensi surat mandat resmi.
8. Prosedur dan hak pencabutan sewaktu-waktu (*revocation at will*) oleh Owner.

### 10.4. Batasan Kewenangan Mutlak Manager (*Explicit Non-Powers*)
Penerima mandat delegasi DILARANG KERAS:
1. Menganggap diri memiliki wewenang otomatis tanpa mandat aktif.
2. Membuat, mengubah, atau memperpanjang surat mandat untuk dirinya sendiri (*no self-delegation*).
3. Mengubah kebijakan Owner, batas nominal, atau hak aksesnya sendiri di aplikasi (`manage_settings`, `manage_admins`).
4. Menyetujui atau mencairkan pembayaran upah untuk dirinya sendiri (upah peran Manager) atau upah Owner.
5. Melakukan pembatalan (*void*) pembayaran di aplikasi tanpa bukti fisik uang tunai utuh di kasir dan persetujuan Owner.
6. Menganggap mandat aplikasi memberikan wewenang atas rekening bank utama perusahaan, akun eksternal, atau brankas fisik di luar otorisasi nyata yang tertulis.

### 10.5. Prosedur Persetujuan Jarak Jauh Saat Owner Berhalangan
Apabila terjadi kebutuhan pembayaran mendesak saat Owner berhalangan hadir:
1. **Persetujuan Tertulis Spesifik yang Dapat Diverifikasi:**  
   Owner dapat memberikan persetujuan tertulis spesifik dari jarak jauh melalui saluran komunikasi resmi yang sah dan dapat diverifikasi (misal: pesan instruksi tertulis resmi via nomor kontak resmi Owner yang dicetak/diarsipkan).
2. **Pembedaan Tegas Persetujuan Tertentu vs. Mandat Delegasi:**
   - **Persetujuan Transaksi Tertentu:** Persetujuan Owner untuk satu pembayaran yang diidentifikasi secara spesifik, mencakup identitas penerima upah, nomor penugasan/kewajiban, nominal pasti, dan metode pembayaran yang jelas.
   - **Mandat Delegasi:** Pemberian kewenangan terbatas untuk kategori pembayaran rutin upah selama kurun waktu tertentu dengan batas $\le 1.000\text{ LE}$ per transaksi.
3. **Larangan Pesan Umum Tanpa Rincian:**  
   Pesan instruksi umum (seperti *"silakan bayar upah pekerja hari ini"*) **BUKAN PERSETUJUAN YANG SAH** dan dilarang dijadikan dasar pencairan dana untuk nominal atau kewajiban apa pun.
4. **Penundaan Jika Informasi Tidak Lengkap / Berbeda:**  
   Jika bukti persetujuan jarak jauh tidak dapat diverifikasi, informasi penugasan tidak lengkap, atau nominal/metode/penerima berbeda dari instruksi Owner, pembayaran **WAJIB DITUNDA** dan dieskalasikan seketika kepada Owner. Persetujuan jarak jauh tidak memberikan wewenang kepada Manager untuk mengubah kebijakan atau menerbitkan mandat baru.

### 10.6. Arsip & Batas Waktu Tinjauan Retrospektif Owner (SLA)
1. **Target SLA Baku:**  
   Owner wajib melakukan peninjauan ulang retrospektif (*Owner Retrospective Review*) terhadap seluruh berkas rekonsiliasi, slip kas, dan tanda terima fisik pekerja dengan **target waktu maksimal hari kerja berikutnya setelah Owner kembali bertugas atau tersedia**.
2. **Kewajiban Eskalasi Segera:**  
   Apabila ditemukan transaksi ambigu, request menggantung (*network timeout*), bukti fisik tanda terima tidak lengkap, atau selisih kas fisik, Manager **WAJIB SEGERA** menghubungi dan mengeskalasikan masalah tersebut kepada Owner tanpa menunggu batas waktu review retrospektif.

---

## 11. PELAPORAN SELISIH KAS UNIVERSAL & LARANGAN ZERO SILENT WRITE-OFF

1. **Prinsip Universal Kejujuran Kas:**  
   Setiap selisih antara fisik kas di kasir dengan catatan buku besar keuangan sistem—berapapun nominalnya (bahkan 1 LE)—**wajib dicatat, dilaporkan, dan direkonsiliasi**.
2. **Sifat Pelaporan:**  
   Melaporkan selisih adalah prosedur akuntansi objektif dan transparan untuk menjaga integritas data keuangan, dan bukan otomatis tuduhan kelalaian atau kecurangan.
3. **Larangan Mutlak Hapus Buku Diam-Diam (*Zero Silent Write-Off*):**  
   Petugas kasir, staf keuangan, maupun Manager Operational **DILARANG KERAS** menutupi selisih fisik, menyeimbangkan angka secara paksa, memasukkan uang pribadi tanpa pencatatan resmi, atau membuat transaksi pengeluaran/penerimaan fiktif untuk membuat buku kas tampak seimbang (*zero silent write-offs*).
4. **Otoritas Tunggal Penyesuaian Kas:**  
   Otoritas untuk mengizinkan penyesuaian saldo (*balance adjustment*) atau pembebanan selisih berada **eksklusif di tangan Owner Sogil Furniture**.  
   - Kasir dan Manager tidak memiliki wewenang untuk menyesuaikan saldo sistem atas selisih kas.
   - Setiap selisih wajib dilaporkan melalui **Nota Insiden Selisih Kas** kepada Owner. Penyesuaian jurnal sistem hanya boleh dieksekusi setelah ada instruksi tertulis resmi dari Owner.

---

## 12. CHECKLIST OPERASIONAL PETUGAS KEUANGAN

Gunakan lembar periksa harian berikut sebelum dan sesudah bertugas:

```text
LEMBAR PERIKSA HARIAN OPERASIONAL KASIR & UPAH
Tanggal: ____________________   Nama Petugas: ____________________

[ ] SEBELUM MEMPROSES PEMBAYARAN (PRE-PAYMENT):
    [ ] Pekerja hadir fisik / nomor rekening resmi terverifikasi
    [ ] Penugasan kerja telah disetujui mandor / Manager Operational (status completed)
    [ ] Kewajiban berstatus accrued / partially_paid pada pesanan bersangkutan
    [ ] Uang fisik kasir dihitung cukup (untuk tunai) / saldo bank cukup (untuk transfer)
    [ ] Jika nominal >= 5.000 LE (atau bagian dari kewajiban total >= 5.000 LE):
        [ ] Persetujuan resmi tertulis Owner telah diperoleh (Persetujuan Owner untuk Pembayaran Besar)
    [ ] Jika Owner tidak berada di tempat / berhalangan:
        [ ] Memiliki Surat Mandat Delegasi tertulis bernomor aktif dari Owner
        [ ] Nominal transaksi <= 1.000 LE per transaksi
        [ ] Jika tidak ada mandat aktif: pembayaran DITUNDA sampai Owner tersedia
    [ ] Jika menggunakan Persetujuan Jarak Jauh Owner:
        [ ] Instruksi tertulis spesifik memuat penerima, nomor kewajiban, nominal, dan metode yang jelas
    [ ] Jika penerima upah adalah Owner: persetujuan tertulis langsung dari Owner (bukan sepihak Manager)
    [ ] Tidak ada pemecahan transaksi pada kewajiban yang sama untuk menghindari ambang batas (Anti-Structuring)
    [ ] Tidak ada settlement menggantung atau ambigu terdahulu untuk pekerja/kewajiban ini

[ ] SAAT MEMPROSES PENCATATAN & PENYERAHAN DANA (THE GOLDEN SEQUENCE):
    [ ] Input parameter settlement di sistem (metode: cash / bank_transfer / other)
    [ ] Isi nomor referensi transfer bank (jika transfer bank)
    [ ] Klik tombol Konfirmasi Pelunasan SATU KALI SAJA
    [ ] Jika sistem memuat lama / timeout: IKUTI PROSEDUR GANGGUAN JARINGAN (PASAL 8)
    [ ] Setelah status tercatat 'recorded': hitung dan serahkan uang fisik kasir (atau transfer via bank)
    [ ] Mintakan tanda tangan pekerja pada lembar tanda terima fisik resmi ber-ID WST-XXXX

[ ] SAAT PENUTUPAN KAS HARIAN:
    [ ] Hitung fisik uang kasir (Cash Count)
    [ ] Cocokkan uang keluar upah tunai dengan tabel pelunasan (metode cash, status recorded)
    [ ] Cocokkan transfer bank dengan mutasi rekening bank resmi
    [ ] Pisahkan audit transaksi bertanda "other"
    [ ] Pastikan transaksi void TIDAK dihitung sebagai pengeluaran kas
    [ ] Rekonsiliasi saldo kewajiban upah terutang
    [ ] Catat seluruh selisih jika ada (tanpa kecuali, zero silent write-off)
    [ ] Tanda tangani formulir rekonsiliasi bersama Owner / Penerima Mandat Delegasi Resmi
    [ ] Jika ditandatangani penerima mandat: jadwalkan tinjauan retrospektif Owner (SLA: hari kerja berikutnya)
```

---

## 13. LAMPIRAN TEKNIS ADMINISTRATOR (TECHNICAL APPENDIX)

Bagian ini ditujukan bagi Administrator Sistem dan Tim Teknis:

1. **Rute Endpoint API Terverifikasi (`backend/server.py`):**
   - `GET /api/admin/wages/pending-summary`: Ringkasan agregat kewajiban upah pekerja terutang (`require_finance_or_owner`).
   - `GET /api/admin/wage-obligations`: Rincian per dokumen kewajiban upah dengan opsi filter pekerja/status (`require_finance_or_owner`).
   - `POST /api/admin/wages/settlements`: Eksekusi pencatatan pelunasan upah pekerja (`require_finance_or_owner`).
   - `GET /api/admin/wages/settlements`: Riwayat dokumen pelunasan upah (`require_finance_or_owner`).
   - `POST /api/admin/wages/settlements/{settlement_id}/void`: Eksekusi pembatalan administratif pelunasan upah (`require_finance_or_owner`).  
   *(Catatan: Rute UI `/admin/wages/pending` adalah jalur antarmuka frontend SPA, berbeda dari rute API backend di atas).*

2. **Struktur Koleksi Database & Indeks:**
   - `wage_settlements`: menyimpan nomor pelunasan (`settlement_number`), `worker_id`, `amount_le`, `payment_method` (`cash`, `bank_transfer`, `other`), `status` (`recorded`, `voided`), dan `allocations`.
     - *Indeks Baru Rilis Ini:*
       - `uniq_settlement_number`: `[("settlement_number", 1)]` (unique=True)
       - `uniq_wage_settlements_idempotency`: `[("idempotency_key", 1)]` (unique=True, partialFilterExpression={"idempotency_key": {"$type": "string"}})
       - `idx_wage_settlements_worker_date`: `[("worker_id", 1), ("settlement_date", -1)]`
       - `idx_wage_settlements_finance_txn`: `[("finance_transaction_id", 1)]`
   - `finance_transactions`: mencatat pengeluaran kas resmi dengan `type: "expense"`, `category: "Pekerja"`, `account: "EGP"`. Jika di-*void*, diperbarui menjadi `is_void: true`, `status: "void"`, `void_source: "wage_settlement_void"`.
   - `wage_obligations`: menyimpan kewajiban upah dengan `status` (`accrued`, `partially_paid`, `paid`). Kolom `paid_amount_le` bertambah saat pelunasan dan berkurang saat void. Sisa saldo dihitung runtime: `total_amount_le - paid_amount_le`. Indeks koleksi ini (`uniq_obligation_number`, `idx_wage_obligations_worker_status`, dll.) telah aktif sejak Phase 2.
   - `employee_wages`: koleksi cermin untuk riwayat pekerja; dokumen dihapus permanen (`delete_many`) saat pelunasan di-*void*. Laporan keuangan membaca `db.finance_transactions` sehingga tidak terjadi penghitungan ganda.

3. **Perlindungan Integritas Database:**
   - Guard 4 pada `finance_update` (`server.py:5885`) dan `finance_delete` (`server.py:6023`) menolak pengeditan atau penghapusan manual transaksi kas pelunasan upah dengan respon `HTTP 409`.
   - Indeks parsial unik `uniq_wage_settlements_idempotency` menolak pembuatan pelunasan ganda pada kunci idempotensi yang sama.
   - Sesi transaksi multi-dokumen MongoDB menjamin mutasi serentak (ACID) antara pelunasan, buku besar, dan kewajiban upah.

4. **Kesenjangan Teknis Saat Ini vs. Rencana Owner Control Center (OCC):**
   - **Ketiadaan Threshold Check Otomatis:** Rute `POST /api/admin/wages/settlements` saat ini tidak memeriksa ambang batas 5.000 LE maupun batas delegasi 1.000 LE di tingkat kode. Siapa pun dengan `access_finance: true` dapat memproses pelunasan berapa pun nominalnya.
   - **Ketiadaan Tabel Kebijakan Dinamis & Delegasi:** Pada commit `1d8f4e59f6637a30820e42bab1f1253b9b5fb512`, tidak ada koleksi basis data untuk menyimpan konfigurasi kebijakan dinamis atau mandat delegasi.
   - **Ketiadaan Log Audit Kebijakan:** `record_audit_log` saat ini hanya mencatat transaksi pelunasan dan void, belum mencatat perubahan konfigurasi atau pendelegasian wewenang.
   - **Spesifikasi Arsitektur Masa Depan:** Rincian rancangan sistem perangkat lunak untuk menutup kesenjangan ini didokumentasikan secara komprehensif pada [`OWNER_CONTROL_CENTER_AND_DELEGATION_SPEC_DRAFT_v1.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/operations/OWNER_CONTROL_CENTER_AND_DELEGATION_SPEC_DRAFT_v1.md).
