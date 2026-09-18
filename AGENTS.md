# Sogil Furniture --- Project Architecture & Status

> Handoff document for an AI Agent working inside the local IDE/VS Code
> environment.
>
> Last updated: 2026-09-17
>
> **Important:** Development is currently done on the local project. Do
> not use the Emergent production URL as the development environment.

------------------------------------------------------------------------

## 1. Nama & Tujuan Web App

### Nama

**Sogil Furniture**

### Tujuan

Web app pemesanan furniture untuk Sogil Furniture di Cairo, Egypt.

Target customer utama: - Mahasiswa Indonesia di Cairo/Al Azhar. - Cafe
Indonesia di Cairo. - Customer yang membutuhkan furniture custom.

Tujuan utama: 1. Menampilkan katalog furniture secara visual. 2.
Memudahkan customer memilih produk. 3. Memungkinkan konfigurasi ukuran,
tingkat, tipe, finishing, dan kebutuhan custom. 4. Menghitung estimasi
harga secara langsung dengan pricing engine yang sudah ada. 5. Menambah
produk ke cart. 6. Checkout dan menyimpan order. 7. Mengarahkan customer
ke WhatsApp untuk konfirmasi. 8. Menyediakan admin area untuk
pengelolaan data bisnis.

### Prinsip UX

-   Mobile-first.
-   Visual dan sederhana.
-   Cepat dipahami customer baru.
-   Tidak terasa seperti dashboard/admin.
-   Customer dapat melihat contoh furniture sebelum memahami
    konfigurasi.
-   **Pricing engine dan photo-matching engine lama tetap
    dipertahankan.** Perubahan utama dilakukan pada UI/UX.

------------------------------------------------------------------------

## 2. Tech Stack & Database

### Frontend

-   React 19
-   Create React App / react-scripts 5
-   CRACO
-   Tailwind CSS
-   React Router
-   Axios
-   lucide-react
-   React Context API

Source:

``` text
frontend/
```

### Backend

-   Python
-   FastAPI
-   Motor
-   MongoDB driver/ObjectId handling
-   boto3 untuk Cloudflare R2 S3-compatible API

Backend utama:

``` text
backend/server.py
```

### Database

**MongoDB Atlas**

Cluster:

``` text
sogil-furniture
```

Database:

``` text
pesan-furniture-test_database
```

### Object Storage

**Cloudflare R2**

Bucket:

``` text
sogil-furniture
```

Path mempertahankan struktur:

``` text
sogil-furniture/uploads/...
sogil-furniture/products/...
```

### Repository

GitHub:

``` text
https://github.com/HIDD-Web/Sogil-Furniture
```

Local:

``` text
C:\Sogil-Project\Sogil-Furniture
```

### Production / Legacy

Production lama:

``` text
https://pesan-furniture.emergent.host/
```

Production ini **bukan development environment** dan harus dipertahankan
sebagai reference/backup sampai deployment baru terverifikasi.

### Local development

Frontend biasanya:

``` text
http://localhost:3000
```

Backend historically:

``` text
http://127.0.0.1:8000
```

Gunakan port yang benar-benar ditampilkan oleh local terminal bila
berbeda.

------------------------------------------------------------------------

## 3. Struktur Folder / File Penting

``` text
Sogil-Furniture/
├── frontend/
│   ├── src/
│   │   ├── App.js
│   │   ├── App.css
│   │   ├── index.css
│   │   ├── index.js
│   │   ├── components/
│   │   │   ├── Header.jsx
│   │   │   ├── Footer.jsx
│   │   │   ├── Logo.jsx
│   │   │   ├── ProductImage.jsx
│   │   │   ├── ProductCard.jsx
│   │   │   ├── CategorySection.jsx
│   │   │   ├── HelpSheet.jsx
│   │   │   └── ui/
│   │   │       ├── carousel.jsx
│   │   │       ├── sheet.jsx
│   │   │       ├── drawer.jsx
│   │   │       ├── skeleton.jsx
│   │   │       └── card.jsx
│   │   ├── context/
│   │   │   ├── AuthContext.jsx
│   │   │   ├── CartContext.jsx
│   │   │   ├── CustomerContext.jsx
│   │   │   └── LanguageContext.jsx
│   │   ├── lib/
│   │   │   ├── api.js
│   │   │   ├── constants.js
│   │   │   ├── format.js
│   │   │   ├── i18n.js
│   │   │   ├── photoMatch.js
│   │   │   ├── pricing.js
│   │   │   ├── summary.js
│   │   │   └── utils.js
│   │   └── pages/
│   │       ├── Home.jsx
│   │       ├── Catalog.jsx
│   │       ├── CategoryPage.jsx
│   │       ├── ProductConfigure.jsx
│   │       ├── Cart.jsx
│   │       ├── Checkout.jsx
│   │       ├── OrderConfirmation.jsx
│   │       ├── CaraPesan.jsx
│   │       ├── Kontak.jsx
│   │       ├── CustomerAccount.jsx
│   │       ├── GuestTrackOrder.jsx
│   │       └── admin/
│   └── ...
├── backend/
│   ├── server.py
│   └── ...
└── ...
```

### Customer routes di `App.js`

``` text
/
 /produk
 /produk/kategori/:category
 /produk/:slug
 /keranjang
 /checkout
 /pesanan/:id
 /cara-pesan
 /kontak
 /akun
 /lacak
```

Admin routes juga tetap ada dan jangan dirusak saat mengubah customer
UI.

### File penting

`Home.jsx` - Homepage V2. - Splash. - Hero. - Category sections. -
Starting price. - Product previews. - Help section.

`CategorySection.jsx` - Section kategori homepage. - Saat ini
menggunakan `products.slice(0, 3)` untuk preview homepage.

`ProductCard.jsx` - Card customer. - Menampilkan foto, nama, starting
price, CTA. - Card menuju `/produk/:slug`.

`CategoryPage.jsx` - Halaman `Lihat semua`. - Current basic
implementation **belum sesuai UX final**; lihat TODO.

`ProductConfigure.jsx` - Halaman konfigurasi produk. - Harus tetap
menggunakan engine V1.

`pricing.js` - Pricing engine. - **Protected logic. Jangan rewrite untuk
pekerjaan UI.**

`photoMatch.js` - Photo matching engine. - **Protected logic.**

Current weights:

``` text
rak:
  length    0.45
  level     0.35
  type      0.10
  finishing 0.10

meja:
  size      0.50
  height    0.30
  finishing 0.20

meja_rak:
  variant   0.60
  type      0.20
  finishing 0.20
```

`summary.js` - Ringkasan konfigurasi customer. - Current function:

``` js
config_summary_client(category, cfg = {}, t)
```

`Cart.jsx` - Cart customer. - Sudah meneruskan `t` ke
`config_summary_client`.

`i18n.js` - Dictionary ID/EN/AR. - i18n sudah sebagian besar
diterapkan. - Bahasa bukan prioritas saat ini.

`ProductImage.jsx` - Reusable image component. - Mendukung lazy loading,
placeholder, responsive ratio.

`api.js` - API base dari `REACT_APP_BACKEND_URL`. - Image URL melalui
backend.

------------------------------------------------------------------------

## 4. Fitur yang Sudah Selesai & Berfungsi

### V1 Git baseline

Commit:

``` text
dbe1206672f71623549bb1ea5af4996e0d5aae29
```

Tag:

``` text
v1.0.0-baseline
```

**Jangan overwrite/delete baseline.**

### Database backup/audit

Backup:

``` text
C:\Sogil-Backup\database\dump-01
C:\Sogil-Backup\database\dump-02
```

Keduanya byte-identical.

Non-empty collections:

``` text
admins              4
customers           1
delivery_zones      7
discounts           4
files             184
finance_categories 23
price_history      21
products            9
referrals           1
settings           16
```

Total:

``` text
270 documents
```

Empty collections pernah teridentifikasi:

``` text
point_transactions
orders
finance_transactions
employee_wages
```

### Object storage migration

Backup lokal:

``` text
C:\Sogil-Backup\object-storage
```

Backup result:

``` text
184/184 success
0 failed
0 mismatch
```

R2 bulk upload:

``` text
184 total
184 success
0 skipped
0 failed
0 size mismatch
0 verify failed
```

Backend R2 upload/download tests berhasil.

### Backend R2

R2 environment variables:

``` text
R2_ENDPOINT
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_BUCKET
```

Runtime Emergent Object Storage dependency sudah dihapus dari backend.

### Mixed MongoDB `_id`

Helper yang sudah ada:

``` python
def id_query(v) -> dict:
    values = [v]
    if isinstance(v, str):
        try:
            values.append(ObjectId(v))
        except (InvalidId, TypeError):
            pass
    return {"$in": values}
```

Ini memperbaiki masalah mixed string/ObjectId `_id`.

### Admin audit

Admin yang pernah ditemukan:

``` text
azkasogil@gmail.com
sogil.furniture@gmail.com
rizkisogil@gmail.com
fabiansogil@gmail.com
admin@sogil.com
```

Current active owner:

``` text
sogil.furniture@gmail.com
```

`admin@sogil.com` adalah akun lama/anomali. Jangan hapus tanpa audit
reference/id lengkap.

### Customer V2 UI

Group 1:

``` text
v1.1.0-customer-ui
```

Sudah ada: - Homepage V2. - Splash. - Category sections. - Product
cards. - Category page basic. - Help sheet. - Responsive structure. -
Customer i18n sebagian. - Cart i18n sebagian.

### Regression test status

#### STEP 1 --- Homepage

**PASS with data limitation**

Sudah diuji di localhost: - Splash. - Header/logo. - Homepage. -
Category. - Starting price. - `Lihat semua`.

Catatan: - Maksimal 3 preview per kategori belum dapat diuji penuh
karena data saat ini belum banyak. - Logic `slice(0, 3)` sudah tersedia.

#### STEP 2 --- Category Page

**Technically working, but UX not final.**

Yang bekerja: - Halaman kategori terbuka. - Judul/deskripsi. - Product
card. - Foto. - Nama. - Starting price. - Card dapat diklik.

Masalah utamanya adalah konsep catalog final, bukan crash/error.

#### STEP 3 --- Product → Configure

Sedang dalam regression test.

Yang harus diuji: - Product card → ProductConfigure. - Panjang. -
Tingkat. - Tipe. - Harga. - Photo matching. - Add to Cart.

------------------------------------------------------------------------

## 5. Bug / Error / Pekerjaan Belum Selesai

### PRIORITAS UTAMA --- Rework Category Product Gallery

File utama:

``` text
frontend/src/pages/CategoryPage.jsx
frontend/src/components/ProductCard.jsx
frontend/src/components/CategorySection.jsx
frontend/src/pages/ProductConfigure.jsx
frontend/src/lib/photoMatch.js
frontend/src/lib/pricing.js
```

**Jangan rewrite pricing/photo engine.**

### UX final yang diinginkan

Untuk kategori **Rak**, halaman `Lihat semua` tidak boleh hanya
menampilkan satu product generic `Rak Buku`.

Customer ingin melihat kumpulan contoh konfigurasi yang memiliki foto.

Identitas preview Rak:

``` text
Panjang + Tingkat + Tipe
```

Contoh:

``` text
Rak Buku
60 cm · 2 Tingkat · Tipe B
565 LE
```

``` text
Rak Buku
80 cm · 4 Tingkat · Tipe B
1125 LE
```

``` text
Rak Buku
120 cm · 5 Tingkat · Tipe A
...
```

Setiap preview mengambil foto konfigurasi yang memang tersedia.

### Homepage

Tetap ringkas:

``` text
Rak
Mulai dari 565 LE

[Preview 1] [Preview 2] [Preview 3]

Lihat semua →
```

Homepage maksimal 3 preview.

### Category Page

Tidak dibatasi 3:

``` text
Rak
----------------
[Foto] [Foto]
[Foto] [Foto]
[Foto] [Foto]
...
```

Tampilkan seluruh preview konfigurasi yang relevan/tersedia.

### Product Detail / Configure

Jika customer klik preview:

``` text
80 cm · 4 Tingkat · Tipe B
```

maka konfigurasi tersebut menjadi starting state.

Customer melihat: - Foto konfigurasi. - Panjang. - Tingkat. - Tipe. -
Harga. - Finishing.

Jika konfigurasi diubah, photo matching engine tetap mencari foto yang
sesuai.

### Finishing Rak

Default:

``` text
Natural
```

Optional:

``` text
Pernis +60 LE
Cat Warna +80 LE
```

Finishing bukan identitas preview utama.

### Pricing

Jangan membuat pricing system baru.

Tetap:

``` text
Panjang + Tingkat + Tipe
        ↓
existing pricing engine
        ↓
harga
```

### Photo

Tetap:

``` text
Konfigurasi
    ↓
existing photo matching
    ↓
foto terdekat
```

------------------------------------------------------------------------

### i18n belum 100% selesai

File:

``` text
frontend/src/lib/i18n.js
frontend/src/components/ProductImage.jsx
frontend/src/components/ProductCard.jsx
```

Status: **Non-blocking / polish later.**

Known items: 1. `ProductImage.jsx` masih punya placeholder hardcoded:
`text    Foto produk segera tersedia` 2. `ProductCard.jsx` masih memakai
`CATEGORY_LABELS` untuk category label, sehingga belum sepenuhnya
dynamic terhadap bahasa.

Customer utama masih Indonesia, jadi jangan jadikan i18n sebagai blocker
fitur utama.

------------------------------------------------------------------------

### Unused `description` prop

`Home.jsx` masih dapat mengirim description ke `CategorySection`, tetapi
`CategorySection.jsx` saat ini tidak menggunakannya.

Non-blocking.

------------------------------------------------------------------------

### Unused import

`ProductConfigure.jsx` pernah teridentifikasi memiliki kemungkinan
unused `ImageOff` import dari `lucide-react`.

Non-blocking.

------------------------------------------------------------------------

### Legacy/anomalous object

Object:

``` text
sogil-furniture/products/81429520-9261-4034-a7ad-0f1de527fd53.jpeg
```

Tidak direferensikan oleh product aktif dan pernah berisi image yang
bukan produk Sogil.

Jangan hapus sebelum final migration/backup aman.

------------------------------------------------------------------------

### Unreferenced file metadata

Dari 184 `files` records: - 89 unique active product photo references. -
Semua 89 mempunyai satu active `files` record. - 95 file records tidak
direferensikan oleh current product fields.

Jangan bulk-delete sebelum audit final.

------------------------------------------------------------------------

### R2 test object

Object test:

``` text
sogil-furniture/test/backend-upload-d4aeec27-c5e0-4fc3-9cd3-161d5a61a88e.txt
```

Boleh dibersihkan setelah migration test selesai.

------------------------------------------------------------------------

### Backups

Jangan hapus:

``` text
C:\Sogil-Backup\databaseC:\Sogil-Backup\object-storageC:\Sogil-Backup\storage```

sampai deployment baru benar-benar terverifikasi.

---

### MongoDB credential rotation
MongoDB credential pernah terekspos dalam proses development.

Setelah final migration/backup aman:
- rotate credential,
- update environment variables,
- jangan paste credential ke chat.

---

## 6. Aturan / Konvensi Coding

### Workflow
Gunakan:
```text
Plan
→ Inspect
→ Implement
→ Test
→ Fix
→ Commit
→ Next group
```

Gunakan grouped feature commits, bukan commit untuk setiap perubahan
kecil.

### Roadmap commits

``` text
v1.0.0-baseline
v1.1.0-customer-ui
v1.2.0-product-catalog
v1.3.0-dynamic-categories
v1.4.0-custom-order
v1.5.0-custom-production
v1.6.0-admin-roles
v1.7.0-finance-payee
v1.8.0-pwa
```

### Satu feature group sekaligus

Roadmap: 1. Customer UI + Homepage 2. Product Catalog + Product Detail
3. Dynamic Categories + Custom Collection 4. Custom Order 5. Custom →
Order → Production → Custom Collection 6. Admin Roles 7. Finance Payee
8. PWA

Selesaikan test group sebelum commit.

### Minimal change

-   Inspect current implementation terlebih dahulu.
-   Jika task hanya membutuhkan satu file, jangan refactor file lain
    tanpa alasan.
-   Jangan mengubah logic yang tidak terkait.
-   Jangan melakukan cleanup kecil yang tidak diperlukan ketika sedang
    mengerjakan feature besar.

### Protected V1 logic

Jangan rewrite:

``` text
pricing.js
photoMatch.js
CartContext
existing order logic
existing checkout logic
```

kecuali requirement memang mengharuskan.

Prinsip: \> UI baru harus memanfaatkan engine V1, bukan menggantikan
engine V1.

### Local vs production

Development:

``` text
C:\Sogil-Project\Sogil-Furniture
```

Production:

``` text
https://pesan-furniture.emergent.host/
```

**Jangan melakukan perubahan production ketika mengembangkan V2.**

### Git

`v1.0.0-baseline` adalah checkpoint penting.

Jangan: - force reset baseline, - delete baseline, - overwrite baseline.

### Environment variables

Gunakan environment variables untuk secrets:

``` text
REACT_APP_BACKEND_URL
R2_ENDPOINT
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_BUCKET
```

Jangan hardcode credential. Jangan commit `.env` yang berisi credential.
Jangan meminta user paste secret ke chat.

### i18n

React component:

``` js
const { t } = useLang();
```

Translation:

``` js
t("namespace.key")
```

Utility non-React seperti `summary.js` menerima translator sebagai
argument:

``` js
config_summary_client(category, cfg, t)
```

### Data vs UI text

Data produk tidak diterjemahkan: - nama produk, - ukuran, - harga, -
konfigurasi, - data finishing.

UI labels dapat diterjemahkan: - Tingkat, - Tipe, - Tinggi, - Lihat
Produk, - Mulai dari.

### Mobile-first

Prioritaskan: - touch target, - spacing, - readable typography, -
2-column product grid, - swipeable images, - bottom sheet untuk help, -
responsive tablet/desktop.

### Product preview architecture

Jangan menganggap satu database product record = satu customer-facing
preview.

Satu product dapat memiliki banyak configuration previews.

Contoh:

``` text
Rak Buku
├── 60 × 2 × B
├── 60 × 3 × B
├── 80 × 4 × B
├── 80 × 5 × A
└── ...
```

Preview hanya ditampilkan jika konfigurasi/foto relevan tersedia.

------------------------------------------------------------------------

## Current Roadmap

### v1.1.0 --- Customer UI + Homepage

Status: **🟡 Hampir selesai / regression test**

Sudah: - Homepage V2. - Splash. - Category sections. - Product card. -
Category page basic. - Help sheet. - Responsive structure. - i18n
sebagian. - Cart i18n sebagian.

Belum final: - Category gallery UX sesuai configuration-preview
requirement. - Full regression sampai WhatsApp. - i18n polish.

### v1.2.0 --- Product Catalog & Product Detail

Status: **⏭️ NEXT MAJOR FEATURE**

Target: - Configuration-based product gallery. - Category page dengan
banyak contoh foto. - Preview berdasarkan konfigurasi. - Product detail
yang membuka konfigurasi sesuai preview. - Foto sesuai konfigurasi. -
Pricing tetap menggunakan engine lama. - Finishing ditampilkan
user-friendly. - Tidak membuat pricing engine baru.

### v1.3.0 --- Dynamic Categories + Koleksi Custom

Belum dikerjakan.

### v1.4.0 --- Custom Order / Request Custom

Belum dikerjakan.

### v1.5.0 --- Custom → Order → Produksi → Koleksi Custom

Belum dikerjakan.

### v1.6.0 --- Admin Roles & Permissions

Belum dikerjakan.

### v1.7.0 --- Finance --- Penerima Upah

Belum dikerjakan.

### v1.8.0 --- PWA Customer + Admin

Belum dikerjakan.

------------------------------------------------------------------------

## Critical Handoff Rules for AI Agent

1.  Work on **localhost**, not production Emergent.
2.  Do not change production.
3.  Do not delete the V1 baseline.
4.  Never ask the user to paste secrets.
5.  Do not rewrite pricing engine unless explicitly required.
6.  Do not rewrite photo matching unless explicitly required.
7.  Preserve existing cart/order/checkout logic during UI work.
8.  Work one feature group at a time.
9.  Inspect current code before modifying it.
10. Test/build after each grouped feature before committing.
11. Treat current i18n imperfections as non-blocking.
12. The main architectural task is to redesign product/category
    presentation around **configuration previews**, while keeping
    existing pricing and photo-matching engines.
13. Do not confuse a database product record with a customer-facing
    configuration preview.
14. Keep local database/object-storage backups until migration is fully
    verified.
15. Never invent product configuration data or photos not present in the
    database/storage.
