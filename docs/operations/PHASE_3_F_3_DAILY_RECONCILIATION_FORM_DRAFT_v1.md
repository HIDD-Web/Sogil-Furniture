# FORMULIR REKONSILIASI HARIAN FISIK KAS & PEMBAYARAN UPAH PEKERJA
## Sogil Furniture — Operasional Keuangan & Kasir

> **STATUS DOKUMEN: DRAFT — MENUNGGU PENGESAHAN FINAL OWNER**  
> **Versi:** 1.3 (Phase 3.F.3.19 — Minimum Safe Procedures & One-Week Trial)  
> **Target Rilis Terkait:** Commit `1d8f4e59f6637a30820e42bab1f1253b9b5fb512`  
> **Pedoman Acuan:** [`PHASE_3_F_3_FINANCE_SOP_DRAFT_v1.md`](file:///Users/syahidmujahid/Sogil-Project/Sogil-Furniture/docs/operations/PHASE_3_F_3_FINANCE_SOP_DRAFT_v1.md)

> [!NOTE]
> **MASA UJI COBA OPERASIONAL 1 MINGGU (ONE-WEEK TRIAL):**  
> Formulir sederhana ini digunakan dalam **masa uji coba operasional selama 1 (satu) minggu** pasca-rilis. Pengisian dirancang praktis untuk diselesaikan dalam waktu **10–15 menit** pada akhir hari kerja biasa. Setelah 1 minggu berjalan, Owner akan mengevaluasi efektivitas formulir ini dan menyederhanakannya bila diperlukan. Uji coba operasional ini bukan alasan untuk menunda rilis produksi.

---

### INFORMASI SESI REKONSILIASI
| Parameter | Rincian Operasional |
| :--- | :--- |
| **Tanggal Rekonsiliasi** | `[ TTTT-BB-HH ]` |
| **Waktu Pelaksanaan** | Buka Kas: `[ JJ:MM ]` / Tutup Kas: `[ JJ:MM ]` |
| **Petugas Preparer (Penyiap Data)** | `[ Nama Lengkap & ID Staf ]` |
| **Petugas Disburser (Penyalur Kas)** | `[ Nama Lengkap & ID Kasir ]` |
| **Lokasi Kasir / Brankas** | Workshop / Kantor Utama Sogil Furniture |
| **Mata Uang Acuan** | Egyptian Pound (EGP / LE) |

---

### BAGIAN 1: PERHITUNGAN FISIK KAS TUNAI (CASH DRAWER)

> [!IMPORTANT]
> **ATURAN ANTI DOUBLE-COUNTING:**  
> Saldo akun agregat `EGP` pada software mencatat seluruh transaksi kas dan non-kas. Penghitungan fisik kasir ini khusus mencocokkan fisik uang tunai.  
> Pengeluaran upah tunai (`payment_method == "cash"`) **hanya dihitung tepat satu kali** pada baris `(D)`. Jangan memasukkan pembayaran upah tunai ke dalam baris pengeluaran operasional umum `(C)`.

| Kode | Komponen Arus Kas Tunai Fisik | Nominal (EGP / LE) | Catatan / Rujukan Dokumen |
| :---: | :--- | :--- | :--- |
| **(A)** | **Saldo Fisik Kas Awal Hari** *(Opening Cash)* | `LE ` | Sesuai saldo akhir fisik hari kemarin |
| **(B)** | **Total Penerimaan Kas Tunai Hari Ini** *(Cash Inflow)* | `LE ` | Penjualan tunai, DP tunai, pelunasan pelanggan |
| **(C)** | **Total Pengeluaran Kas Operasional Non-Upah** | `LE ` | Pembelian material tunai, logistik, konsumsi |
| **(D)** | **Total Pembayaran Upah Tunai Hari Ini** | `LE ` | Total settlement upah tunai berstatus `recorded` |
| **(E)** | **Saldo Kas Fisik Akhir yang Diharapkan** | `LE ` | **Rumus: (A) + (B) - (C) - (D)** |

#### Rincian Fisik Aktual Uang Kertas & Koin Saat Tutup Kas
| Pecahan Uang Fisik (LE) | Jumlah Lembar / Keping | Subtotal Nominal (LE) |
| :--- | :--- | :--- |
| Pecahan LE 200 | `[     ]` lembar | `LE ` |
| Pecahan LE 100 | `[     ]` lembar | `LE ` |
| Pecahan LE 50 | `[     ]` lembar | `LE ` |
| Pecahan LE 20 | `[     ]` lembar | `LE ` |
| Pecahan LE 10 | `[     ]` lembar | `LE ` |
| Pecahan LE 5 | `[     ]` lembar | `LE ` |
| Pecahan Koin / Lainnya | `[     ]` keping/lembar | `LE ` |
| **(F)** | **TOTAL FISIK KAS AKTUAL DI KASIR** | `LE ` |

#### Selisih Kas Fisik (Variance)
| Parameter Perhitungan | Nilai (LE) | Keterangan Status |
| :--- | :--- | :--- |
| **Selisih = (F) Aktual - (E) Diharapkan** | `LE ` | `[ ] NIHIL (Cocok)  [ ] LEBIH  [ ] KURANG` |

---

### BAGIAN 2: REGISTER PEMBAYARAN UPAH TUNAI & TRANSFER BANK HARI INI

> [!NOTE]
> Seluruh pembayaran upah wajib mencantumkan nomor kewajiban/pesanan terkait, dasar otorisasi (Persetujuan Owner $\ge 5.000\text{ LE}$, Mandat Delegasi $\le 1.000\text{ LE}$, atau Persetujuan Jarak Jauh), serta bukti tanda tangan/mutasi fisik.

| ID Settlement | No. Kewajiban / Pesanan | Nama Pekerja | Nominal (LE) | Metode (Cash / Bank) | Dasar Otorisasi & Persetujuan | Bukti Pembayaran Aktual |
| :--- | :--- | :--- | :--- | :---: | :--- | :---: |
| `[ WST-... ]` | `[ OBL / ORD-... ]` | `[           ]` | `LE ` | `[ Cash / Bank ]` | `[ ] Owner (>=5k)  [ ] Mandat  [ ] Rutin` | `[ ] Tanda Terima Fisik / Slip` |
| `[ WST-... ]` | `[ OBL / ORD-... ]` | `[           ]` | `LE ` | `[ Cash / Bank ]` | `[ ] Owner (>=5k)  [ ] Mandat  [ ] Rutin` | `[ ] Tanda Terima Fisik / Slip` |
| `[ WST-... ]` | `[ OBL / ORD-... ]` | `[           ]` | `LE ` | `[ Cash / Bank ]` | `[ ] Owner (>=5k)  [ ] Mandat  [ ] Rutin` | `[ ] Tanda Terima Fisik / Slip` |
| `[ WST-... ]` | `[ OBL / ORD-... ]` | `[           ]` | `LE ` | `[ Cash / Bank ]` | `[ ] Owner (>=5k)  [ ] Mandat  [ ] Rutin` | `[ ] Tanda Terima Fisik / Slip` |
| **TOTAL** | **Pembayaran Upah Hari Ini** | — | `LE ` | — | — | — |

---

### BAGIAN 3: REKONSILIASI PEMBAYARAN UPAH METODE LAINNYA (`other`)

> [!WARNING]
> Metode `other` **TIDAK BOLEH** dicampuradukkan dengan kas fisik atau rekening bank tanpa dokumen pertanggungjawaban fisik yang sah dan ditandatangani.

| ID Settlement | No. Kewajiban / Pesanan | Nama Pekerja | Nominal (LE) | Deskripsi Metode Kompensasi | Nomor Dokumen Serah Terima |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `[ WST-... ]` | `[ OBL / ORD-... ]` | `[           ]` | `LE ` | `[                       ]` | `[ BA-... ]` |
| `[ WST-... ]` | `[ OBL / ORD-... ]` | `[           ]` | `LE ` | `[                       ]` | `[ BA-... ]` |
| **TOTAL** | **Metode Other Hari Ini** | — | `LE ` | — | — |

---

### BAGIAN 4: REGISTER PEMBATALAN SETTLEMENT (VOID REGISTER)

> [!CAUTION]
> **ATURAN MUTLAK VOID:**  
> Void pada software **HANYA** boleh dieksekusi jika uang fisik **BELUM DISERAHKAN** ke pekerja atau transfer bank **BELUM DILAKUKAN**.  
> Jika uang fisik sudah diserahkan, pembatalan sistem adalah pelanggaran berat integritas keuangan.

| ID Settlement Void | Nominal (LE) | Metode Asli | Waktu Void Sistem | Alasan Void | Konfirmasi Fisik Kasir |
| :--- | :--- | :--- | :--- | :--- | :---: |
| `[ WST-... ]` | `LE ` | `[ Cash/Bank/Other ]` | `[ JJ:MM ]` | `[                   ]` | `[ ] Fisik Utuh di Kasir` |
| `[ WST-... ]` | `LE ` | `[ Cash/Bank/Other ]` | `[ JJ:MM ]` | `[                   ]` | `[ ] Fisik Utuh di Kasir` |

---

### BAGIAN 5: RINGKASAN REKONSILIASI KEWAJIBAN UPAH (WAGE OBLIGATIONS)

| Indikator Kewajiban Upah Sistem | Nilai (LE) | Rujukan Sistem |
| :--- | :--- | :--- |
| **Total Kewajiban Upah Baru Terbit Hari Ini** | `LE ` | Pekerjaan tercatat selesai hari ini |
| **Total Pembayaran Upah Hari Ini (Cash + Bank + Other)** | `LE ` | Total settlement berstatus `recorded` hari ini |
| **Total Sisa Kewajiban Belum Lunas (Outstanding Accrual)** | `LE ` | Ringkasan `/admin/wages/pending` saat tutup kas |

---

### BAGIAN 6: PELAPORAN DAN PENANGANAN SELISIH KAS (DISCREPANCY REPORT)

Setiap selisih kas fisik (baik kekurangan maupun kelebihan) **wajib dilaporkan secara tertulis**. Tidak ada toleransi untuk penghapusan sepihak (*zero silent write-offs*).

1. **Besaran Selisih yang Terjadi:** `LE ____________________`
2. **Uraian Kronologis / Dugaan Penyebab Selisih:**
   ```text
   [Tuliskan kronologi pemeriksaan, waktu transaksi yang mencurigakan, atau nota yang belum tercatat]
   ```
3. **Tindakan Investigasi Awal:**
   - [ ] Pemeriksaan ulang hitungan fisik pecahan brankas/kasir.
   - [ ] Cek silang seluruh tanda terima fisik upah bertanda tangan pekerja asli.
   - [ ] Cek riwayat settlement `GET /api/admin/wages/settlements` hari ini.
   - [ ] Cek riwayat pengeluaran kas operasional umum `/api/finance/transactions`.
4. **Status Penyesuaian Saldo Sistem:**
   > **KEBIJAKAN OTORITAS PENYESUAIAN KAS:**  
   > Otoritas penyesuaian saldo sistem atas selisih kas berada **eksklusif di tangan Owner Sogil Furniture**. Kasir dan Manager **DILARANG KERAS** membuat transaksi fiktif atau jurnal penyeimbang sepihak untuk menyeimbangkan angka sistem dengan angka fisik (*Zero Silent Write-Off*). Selisih wajib dicatat sebagai temuan gantung hingga terbit instruksi tertulis resmi dari Owner.

---

### BAGIAN 7: PENGESAHAN PENUTUPAN KASIR & PENINJAUAN OWNER

#### 1. Pernyataan Petugas Kasir / Manager (Pencatat & Penghitung Kas):
*"Saya menyatakan dengan sesungguhnya bahwa seluruh data mutasi kas harian, pembayaran upah, bukti fisik tanda terima, dan penghitungan fisik uang tunai di kasir pada formulir ini adalah benar, tercatat lengkap, dan sesuai dengan fisik uang tunai nyata saat kasir ditutup."*

| Petugas Kasir / Manager Operational | Tanda Tangan | Tanggal & Jam Tutup Kas |
| :--- | :--- | :--- |
| `[ Nama Lengkap ]` | `________________________` | `____/____/________ __:__` |

*(Catatan: Batas delegasi transaksi 1.000 LE berlaku khusus untuk otorisasi pembayaran upah delegasi tertentu, bukan membatasi wewenang Manager/kasir untuk menyusun, menghitung kas fisik, dan menandatangani formulir rekonsiliasi harian ini).*

---

#### 2. Lembar Peninjauan Owner (Owner Review):
*(Owner meninjau formulir rekonsiliasi harian saat tersedia, diutamakan maksimal pada hari kerja berikutnya. Formulir ini dirancang sederhana tanpa memerlukan lapisan persetujuan tambahan).*

- **Tanggal Peninjauan Owner:** `[ TTTT-BB-HH ]`
- **Catatan & Evaluasi Owner (jika ada selisih atau temuan):**
  ```text
  [                                                                                  ]
  ```
- **Status Evaluasi Owner:**  
  `[ ] DISETUJUI (Sesuai / Nihil)` &nbsp;&nbsp;&nbsp;&nbsp; `[ ] MEMERLUKAN TINDAK LANJUT (Ada Selisih Kas / Nota Belum Lengkap)`

- **Tanda Tangan Peninjauan Owner:**  
  
  `___________________________________`  
  **Owner Sogil Furniture**  
  Tanggal: `[ TTTT-BB-HH ]`
