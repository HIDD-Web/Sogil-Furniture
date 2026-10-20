# SOP: Pencatatan, Verifikasi, dan Pembatalan (Void) Pelunasan Upah Pekerja (Phase 3.F.3)

> [!WARNING]
> **Status Dokumen: USULAN PROSEDUR OPERASIONAL STANDAR (DRAFT FOR OPERATOR REVIEW)**  
> Dokumen ini adalah draf usulan teknis-operasional untuk ditinjau oleh operator dan pimpinan Sogil Furniture. Dokumen ini **bukan** kebijakan perusahaan yang telah berlaku resmi hingga disetujui secara tertulis oleh pihak berwenang.

---

## 1. Tujuan dan Ruang Lingkup

Standar Operasional Prosedur (SOP) ini mengatur tata cara pencatatan pembayaran (settlement) upah pekerja harian/borongan serta tata tertib pembatalan administratif (*void*) atas transaksi pembayaran upah pada sistem Sogil Furniture.

Tujuan utama SOP ini adalah:
1. Menjamin keselarasan mutlak antara uang fisik kas di kasir/brankas dengan pembukuan buku besar keuangan (*finance ledger*).
2. Mencegah kerugian finansial akibat pembayaran ganda (*double payment*) atau selisih fisik kas.
3. Mengatur pembatasan ketat terhadap fitur pembatalan (*void*) agar tidak disalahgunakan untuk menutupi kehilangan uang fisik.

---

## 2. Otorisasi dan Hak Akses

Sesuai dengan arsitektur keamanan Phase 3.F.3:

| Peran (*Role*) | Akses Pencatatan (*Create Settlement*) | Akses Pembatalan (*Void Settlement*) | Akses Lihat Data (*Read Only*) |
| :--- | :---: | :---: | :---: |
| **Owner** | Ya | Ya | Seluruh Pekerja |
| **Finance Admin** (`access_finance: true`) | Ya | Ya | Seluruh Pekerja |
| **Order/Production Admin** | Tidak | Tidak | Berdasarkan Izin Penugasan |
| **Pekerja (*Worker*)** | Tidak | Tidak | Hanya Data Upah Sendiri |

*Pekerja dilarang keras memproses pembayaran atau pembatalan upah sendiri.*

---

## 3. Prosedur Sebelum Pencatatan Pembayaran Upah (*Pre-Settlement Checklist*)

Petugas Keuangan wajib melakukan verifikasi fisik dan administratif sebelum menekan tombol pembayaran pada sistem:

1. **Verifikasi Identitas & Kehadiran:**
   - Pastikan pekerja yang bersangkutan hadir secara fisik atau telah memberikan instruksi resmi tertulis mengenai rekening penerima.
2. **Pemeriksaan Kewajiban Terutang (*Pending Obligations*):**
   - Buka menu **Upah Pekerja** (`/admin/wages/pending`).
   - Periksa daftar kewajiban upah pekerja. Pastikan status kewajiban adalah `accrued` (terakrual) atau `partially_paid` (sebagian terbayar) yang berasal dari pekerjaan yang telah diverifikasi mandor/produksi (`completed`).
3. **Pengecekan Fisik Kas / Saldo Bank:**
   - **Metode Tunai (*Cash*):** Hitung fisik uang tunai di kasir/brankas. Pastikan fisik uang tunai tersedia cukup sebelum pembayaran dicatat di sistem.
   - **Metode Transfer Bank:** Pastikan saldo rekening bank operasional mencukupi.
4. **Konfirmasi Nominal:**
   - Masukkan nominal pembayaran (`amount_le`). Sistem secara otomatis menolak pembayaran yang melebihi total sisa kewajiban pekerja (*fail-closed*).
   - Pastikan alokasi (FIFO otomatis atau spesifik manual) telah sesuai dengan kesepakatan dengan pekerja.
5. **Kebijakan Satu Kali Klik & Idempotensi:**
   - Sistem secara otomatis menyertakan kunci idempotensi (`idempotency_key`).
   - Jika koneksi internet mengalami hambatan (*lag*), **dilarang menekan tombol berulang kali**. Tunggu notifikasi konfirmasi sistem.

---

## 4. Perbedaan Mendasar: Koreksi Sistem vs. Pengembalian Fisik Uang

> [!CAUTION]
> **TINDAKAN *VOID* PADA SISTEM HANYALAH KOREKSI PEMBUKUAN DATA.**  
> Menekan tombol *Void* pada aplikasi **TIDAK MENGEMBALIKAN UANG TUNAI FISIK** yang telah keluar dari brankas atau diterima pekerja.

Saat fungsi pembatalan (*void*) dijalankan pada sistem:
1. Status dokumen `wage_settlements` diubah menjadi `voided`.
2. Transaksi pengeluaran kas pada `finance_transactions` ditandai `is_void: True`, sehingga saldo kas pada pembukuan aplikasi **bertambah kembali**.
3. Sisa kewajiban pekerja pada `wage_obligations` **dinaikkan kembali** (status kembali menjadi `accrued` atau `partially_paid`).
4. Catatan cermin pada `employee_wages` dihapus.

---

## 5. Larangan Mutlak Pembatalan (*Strict Void Prohibition*)

1. **Dilarang Keras Melakukan *Void* Jika Uang Fisik Sudah Diserahkan:**
   Petugas Keuangan **DILARANG KERAS** membatalkan (*void*) transaksi pembayaran upah di sistem apabila uang tunai telah diserahkan secara fisik kepada pekerja atau transfer bank telah berhasil terkirim, **KECUALI**:
   - Fisik uang tunai tersebut telah ditarik kembali secara nyata dari pekerja dan telah masuk kembali ke kasir/brankas perusahaan; ATAU
   - Rekening bank telah menerima pengembalian dana (*refund/reversal*) yang terverifikasi pada mutasi rekening resmi.
2. **Konsekuensi Pelanggaran:**
   Jika pembayaran di-*void* padahal uang tunai sudah dibawa pekerja:
   - Aplikasi akan mencatat kas perusahaan masih utuh (fiktif).
   - Aplikasi akan mencatat perusahaan masih berhutang kepada pekerja (pekerja tercatat belum dibayar).
   - Saat audit fisik kas harian, akan terjadi **selisih kas fisik hilang (minus)** sebesar nominal yang di-*void*.

---

## 6. Prosedur Pengecualian dan Koreksi Kesalahan

Jika terjadi kesalahan administratif (salah input nominal, salah pilih pekerja, atau salah tanggal):

### Skenario A: Uang Fisik Belum Diserahkan (Koreksi Pra-Disbursement)
1. Batalkan transaksi segera menggunakan tombol **Batalkan Pembayaran (Void)** di aplikasi.
2. Wajib mengisi kolom `Alasan Pembatalan` secara rinci dan objektif (contoh: *"Salah input nama pekerja, uang tunai belum diserahkan"*).
3. Buat catatan pembayaran baru yang benar.

### Skenario B: Uang Fisik Sudah Diterima Pekerja dan Terjadi Kelebihan Bayar
1. **Jangan lakukan *void* pada transaksi yang sudah berjalan.**
2. Hubungi pekerja dan mandor untuk konfirmasi kelebihan bayar.
3. Jika pekerja mengembalikan kelebihan uang tunai:
   - Masukkan uang ke kasir.
   - Buat transaksi kas masuk penyesuaian (*Income / Penyesuaian Saldo*) pada menu Keuangan dengan keterangan resmi.
4. Jika kelebihan bayar disepakati dipotong dari upah pekerjaan berikutnya:
   - Biarkan pembayaran tetap tercatat sah.
   - Pada pekerjaan berikutnya, catat kewajiban dan lakukan kompensasi potongan secara transparan.
5. Setiap kasus kelebihan bayar wajib dilaporkan kepada **Owner** melalui nota insiden.

---

## 7. Penanganan Permintaan Gantung (*Timeout / Ambiguous Requests*)

Jika saat menekan tombol pembayaran terjadi gangguan jaringan, layar memuat lama (*loading*), atau muncul pesan galat (*timeout*):

1. **JANGAN LANGSUNG MEMBUAT PEMBAYARAN KEDUA.**
2. **JANGAN LANGSUNG MEMBAYAR DENGAN UANG FISIK LAIN.**
3. Langkah investigasi wajib:
   - Muat ulang (*refresh*) halaman peramban (*browser*).
   - Buka tab **Riwayat Pelunasan** pada halaman Upah Pekerja.
   - Periksa apakah dokumen pembayaran dengan nomor pelunasan baru sudah tercatat dalam beberapa menit terakhir.
   - Periksa sisa saldo upah terutang pekerja tersebut pada tabel kewajiban.
   - Jika dokumen telah tercatat (`recorded`), pembayaran telah sah di sistem; serahkan fisik uang sesuai nominal tercatat.
   - Jika pembayaran tidak muncul dan saldo kewajiban belum berkurang, barulah proses pembayaran dapat diulang.

---

## 8. Rekonsiliasi Tutup Kas Harian (*End-of-Day Reconciliation*)

Setiap hari pada akhir jam operasional, Petugas Keuangan wajib melakukan rekonsiliasi tiga titik (*three-way reconciliation*):

$$\text{Fisik Kas Akhir} = \text{Kas Awal} + \text{Penerimaan Kas Harian} - \text{Pengeluaran Kas Harian}$$

Pemeriksaan silang yang wajib dilakukan:
1. **Buku Kas Fisik vs. Finance Ledger:**
   - Total pengeluaran kas kategori `Pekerja` pada menu Keuangan wajib sama persis dengan total fisik uang tunai upah yang keluar dari brankas hari tersebut.
2. **Finance Ledger vs. Settlement Table:**
   - Jumlah nominal transaksi pengeluaran `Pekerja` pada tanggal terkait wajib cocok dengan jumlah total pembayaran berstatus `recorded` pada menu Upah Pekerja.
3. **Audit Log Review:**
   - Buka menu Audit Log. Periksa apakah terdapat aktivitas `WAGE_SETTLEMENT_VOIDED` pada hari tersebut.
   - Jika ada pembatalan (*void*), periksa alasannya dan cocokkan dengan kuitansi fisik/konfirmasi pengembalian dana.

---

## 9. Prosedur Eskalasi Selisih (*Discrepancy Escalation*)

Apabila ditemukan selisih antara uang fisik kas dengan data sistem pada saat tutup buku:
1. Petugas Keuangan wajib menghentikan sementara seluruh transaksi pengeluaran kas baru.
2. Lakukan audit mundur terhadap transaksi pembayaran upah hari tersebut satu per satu terhadap tanda terima fisik pekerja.
3. Laporkan temuan selisih secara tertulis kepada **Owner** paling lambat 1x24 jam dengan menyertakan:
   - Tanggal dan jam kejadian.
   - Nama pekerja dan nomor pesanan terkait.
   - Nomor pelunasan upah (`settlement_number`) dan ID transaksi keuangan.
   - Bukti fisik/digital penerimaan uang.
4. Segala bentuk penyesuaian saldo kas wajib melalui otorisasi tertulis Owner.
