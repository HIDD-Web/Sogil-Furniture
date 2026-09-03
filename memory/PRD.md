# Sogil Furniture — PRD

## Problem statement
Cairo-based furniture business. Customer ordering + price-estimation web app (NOT generic e-commerce). Customers configure furniture (Rak/Meja/Meja Rak), see instant estimated price (LE + estimated IDR), cart, checkout, order saved, redirected to WhatsApp. Admin dashboard manages orders, products, pricing, delivery, settings, finance, and admins. UI primarily Bahasa Indonesia; also EN + AR (RTL).

## Architecture
- Frontend: React (CRA + craco), Tailwind, shadcn/ui, react-router, sonner. Warm beige/wood design.
- Backend: FastAPI + Motor (MongoDB). All routes under /api. JWT cookie auth (bcrypt).
- Object storage: Emergent object storage for image uploads (products, photos, logo).
- Currency stored in LE/EGP; estimated IDR via admin-set rate (default 357), snapshotted on order.

## Personas
- Customer (no login): students/renters/small businesses ordering configurable furniture.
- Owner/CEO: full control. Manager/Admin/Employee: permission-gated staff accounts.

## Core requirements (static)
- Configurable pricing engine (server-authoritative) with admin-editable base prices, type adjustments, finishing.
- Cart -> checkout -> order saved -> WhatsApp message. Historical order pricing immutable.
- Multilingual (ID/EN/AR + RTL). International phone (+countrycode) required.
- Admin: orders, analytics, products+photos, finance (IDR/EGP), settings, multi-admin RBAC, audit.

## Implemented
### v1 (MVP) — done
- Catalog, product configurator, real-time pricing, delivery zones/pickup, order creation (SGF-YYYYMMDD-XXX), WhatsApp message, confirmation page, admin auth + dashboard (overview, orders, products CRUD, settings), seed data.

### v2 — done (2026-08-27)
- Shopping cart (Add to Cart / Order Now), multi-item orders.
- Dynamic product photo preview via weighted similarity (length/level highest); up to 3 photos per config; admin photo manager + representative image (manual star).
- International phone validation (+countrycode), normalized for WhatsApp.
- i18n ID/EN/AR with Arabic RTL.
- Admin overview clickable stat cards -> filtered orders. Order analytics (top configs, group_by).
- Multi-admin (owner/manager/admin/employee) with independent feature permissions, server-side enforcement; audit (updated_by_name) on products/settings/finance/orders.
- Admin email + password change; logo upload; app title/branding.
- Rak Type B base prices seeded/migrated (60/80/120 × 2-7 levels).
- Finance module: auto-revenue on paid orders (dedupe + removed on un-lunas), manual income/expense, IDR+EGP accounts, internal transfers, statistics with period comparison.
- Security fixes: explicit CORS origins, idempotent admin seed w/ password+role rotation, invalid ObjectId -> 404, product-update allowlist, positive transfer validation.

## Testing
- Backend: /app/backend/tests/test_v2_features.py (32/32 pass). Frontend flows verified via Playwright.

### v3 — done (2026-08-27)
- Image system fix: category cover image (manual + auto-from-orders modes) separated from per-configuration photos; removed confusing "make category image" star; weighted config-photo matching (length & levels dominant) with graceful closest-match fallback; cover never used as per-config fallback.
- Delete order: permission-gated (delete_data), removes auto order_revenue, 404 on missing; excluded from stats/finance.
- Store contacts (WhatsApp/address/Instagram/Facebook/TikTok/Email) editable in Settings; clickable in customer footer (only shown when configured).
- Discount codes: admin CRUD + server-side validation (dates/claims/cap, % clamped 0-100) + checkout apply + immutable order snapshot (code/percentage/discount_le).
- Custom finance transaction categories (CRUD, merged into transaction dropdown).
- Manual finance balance adjustment ("Set Saldo Saat Ini") recorded as balance_adjustment (affects balance, not revenue).
- Tests: /app/backend/tests/test_v3_features.py (17/17 pass).

### v4 — done (2026-08-27)
- Fixed the missing "Hapus Pesanan" action: now visible on Order Detail and Order List (gated by delete_data/owner); server-enforced 403/404; deleting a paid order reverses its auto-revenue AND any referral points; deleted orders excluded from stats/finance/auto-cover.
- Product image upload optimization: server resizes/compresses uploads to web-friendly WebP (max ~1600px, thumbnail generated), lazy loading + browser caching. Category cover stays separate from config photos; weighted similarity unchanged.
- Finance charts (recharts): monthly Revenue & Profit bars per currency/year via /admin/finance/monthly.
- Customer accounts: register (username/phone+/password, email optional), login/logout (JWT customer cookie), profile, order history, points dashboard, referral code. Guest checkout preserved.
- Referral system: auto code per customer; admin Referrals page (discount %, max LE, points/order, limits, dates, status, global ON/OFF); apply at checkout (login required); self-referral blocked; one code per order; snapshot on order.
- Points: 1 pt = 1 LE; awarded to owner only when referred order is Paid (idempotent), reversed on delete/un-pay; redemption capped at point_redeem_max_pct (default 50%) of subtotal; never negative; discount+referral are mutually exclusive; totals clamped >= 0.
- Admin Customers page (search, detail, order/point history, owner-only manual point adjustment with audit).
- Tests: /app/backend/tests/test_v4_features.py — 21/21 pass (executed 2026-06, iteration_5.json). Frontend Playwright verified: owner sees delete-order button (list+detail), sub-admin without delete_data has it hidden AND gets 403 server-side; finance recharts render (empty-data safe); customer register/login/history; checkout referral+points. NO regressions found. QA COMPLETE — safe for final production testing.

### v5 — done (2026-06)
- Order price breakdown now consistent across ALL surfaces (Admin Order Detail, customer Saved-Order confirmation, WhatsApp message) — all read the SAME immutable order snapshot (subtotal_le, discount_le, referral_discount_le, points_redeemed_le, delivery_fee_le, total_le, rate, estimated_idr). Root cause of reported inconsistency: AdminOrderDetail never rendered referral_discount_le, so subtotal+ongkir != total on screen for referral orders.
- Admin Order Detail: added Diskon Referral + Penukaran Poin rows and a "Promo & Referral" section (code/owner/percentage/amount/points) shown only when a referral was used. Historical orders never recompute from current config.
- WhatsApp message (server-generated) now includes full "Rincian Harga:" breakdown — single authoritative source, no separate WhatsApp calc.
- Customer confirmation page: full breakdown (per-item, subtotal, discount/referral, points, ongkir, total, rate, IDR).
- Admin Order search: GET /api/admin/orders?q= matches order_number/customer_name/phone/username/product name/referral code; combines with status+payment filters.
- Customer deactivation (owner-only PATCH /api/admin/customers/{cid} {active}): deactivated customers get 403 on login and lose session access; historical orders, finance, and referral records remain fully intact (soft deactivate, no destructive delete). Admin Pelanggan shows status badge + toggle.
- Tests: /app/backend/tests/test_v5_features.py — 16/16 pass (iteration_6.json). Scenarios A–L all PASS.

### v6 — final production hardening (2026-06)
- Order privacy: GET /api/orders/{id} now blocks access to customer-linked orders unless the requester is that logged-in customer (403); guest orders (no customer_id) stay publicly retrievable for checkout confirmation. Server-side enforced. Admins use RBAC-gated /admin/orders.
- Safe permanent customer delete: owner-only DELETE /api/admin/customers/{cid}; blocked (400, recommend deactivate) when the customer has ANY business history (orders as buyer, orders they referred, point_transactions, referral claims/points_awarded/reward_orders, points balance/earned). Only history-free test/spam accounts hard-delete (also removes their unused referral code). Deactivate remains the default safe path.
- Automatic category-cover preview: GET /api/admin/products/{id}/cover-preview + AdminProductEdit panel (cover-auto-preview) showing the most-ordered config, its order count, and matched image. Does NOT alter weighted similarity matching; cover never used as per-config fallback.
- DB indexes added at startup for orders (customer_id/order_number/order_status/payment_status/referral.code/created_at), customers (phone/username), point_transactions, finance_transactions, referrals — keeps search responsive.
- Verified already-satisfying requirements (no change): finance trend charts (period filter, comparison %, balances, cash flow, monthly bar, empty-safe); WebP image optimization (1600px max, quality 82); DB-driven product/config/price/photo/discount/referral/finance/contact data.
- Decision: customer login stays username/phone/password + optional email; username serves as display name; guest checkout preserved (no breaking required-field change).
- Tests: /app/backend/tests/test_v6_features.py 13/13 + combined V5+V6 29/29 PASS (iteration_7.json). Production readiness: GREEN.

### v7 — targeted maintenance (2026-06)
- Config-photo regression investigation: NO data loss and NO display bug found — all config photo records intact in DB and rendering on the customer configure page (main + thumbnails + match label). Weighted similarity matching (length/level highest weight) left unchanged. Category cover stays separate and is never a per-config fallback.
- Config-record ordering (admin): move up/down controls per configuration set in AdminProductEdit (config-up/config-down); persists via the photos array on Save; survives refresh. Does not alter attributes or photos of any set.
- Photo ordering within a configuration (admin): move left/right controls on the 3 slots (relabeled Foto 1/2/3; Foto 1 = primary/main_url); persists on Save. Independent from config-record order.
- Guest order tracking: POST /api/orders/track + /lacak page. Requires order_number + matching phone (wrong phone -> 404). Limited view only — NO address/maps/customer_id/phone exposed. Footer 'Lacak Pesanan' link added.
- Guest order claim: POST /api/customer/claim-order (auth). Verifies phone; blocks double-claim (409 if owned by another, 400 if already own); attaches only customer_id+username, preserving all historical snapshots. Claim UI in CustomerAccount. Guest checkout unchanged.
- NO schema migration; array order is the persisted ordering. Referral/points and order-privacy rules verified intact.
- Tests: /app/backend/tests/test_v7_features.py 12/12 PASS (iteration_8.json). Scenarios A-T all PASS.

### Phase 1 — production update (2026-06): accounts, RBAC, finance, wage, XLSX export
- Canonical Owner: single owner renamed to sogil.furniture@gmail.com (ADMIN_EMAIL in backend/.env updated; old syahid.mujahid02@gmail.com rejected). Stale duplicate owner ownersogil@gmail.com demoted to manager+inactive (no deletion). Seed no longer recreates a duplicate.
- Account mgmt/RBAC: owner edits name/role/permissions/status via PUT /admin/admins/{id} (same id, no new account); non-owner cannot create/promote owner; owner-only endpoints 403 for others.
- Passwords: admin self change-password (existing) + owner reset admin password via update_admin (bcrypt, no leak); customer self POST /customer/change-password; owner reset customer password (prior round). No plaintext/hash ever exposed.
- Admin status: PUT /admin/admins/{id} {status} activate/deactivate; deactivated employees excluded from wage-recipient list; wage history preserved. UI: AdminAdmins status badge/toggle/reset + employee wage totals.
- Employee↔wage: employee account = single identity + wage recipient. Recording an expense in a wage category (Pekerja/Upah/Wage) with recipient creates ONE finance txn (source of truth) + linked employee_wages row (category/description/recorded_by). employee_wages_summary adds month/year/count. finance_update fully re-syncs wage link on edit (category/recipient/wage-ness change); delete removes linked wage. No duplicate money/identity.
- Finance categories: income=[Penjualan, Pendapatan Lain] (removed Penyesuaian); 14 new expense categories incl Pekerja. Historical txn snapshots preserved. Custom categories: create/edit/soft-delete/reactivate with classification (revenue|cost|transfer). Classification integrity in stats+balances (transfers move balance only, never revenue/cost; order_revenue always revenue).
- Finance transfer IDR↔EGP (Akun labels + auto-opposite, same-account blocked). Transaction search GET /admin/finance/transactions?q= (description/category/type/classification/created_by/recipient/amount). Statistics page /admin/finance/statistics (category rankings + count/pct + revenue/transfer/cost totals + operating profit; presets incl last_3_months). Monthly charts refetch on every mutation (no refresh).
- XLSX exports (openpyxl) at /admin/export: Keuangan, Pesanan, Analitik Konfigurasi, Pelanggan, Akun+Upah (owner-only, 2 sheets), Harga Produk (history+current). RBAC-gated, read-only, NO passwords/hashes/tokens/secrets (verified by openpyxl cell scan). Product price-history recorded forward-only on product edit; historical order prices immutable.
- Tests: /app/backend/tests/test_v9_features.py 26/26 PASS (iteration_10.json). No historical data deleted; single canonical owner.

### Phase 2A — per-product configuration engine (2026-06)
- Per-product photo-matching priority: exposed existing `product.photo_weights` (backend match_photo + client matchPhoto already honored it with category-default fallback). AdminProductEdit "Prioritas Pencocokan Foto" move up/down → weights on save; per-product & isolated (editing rak never touches meja_rak). Exact match still wins; higher-priority mismatch weighs more.
- Per-product option notes: `product.option_notes` {optionKey: text}; AdminProductEdit "Catatan Opsi" inputs (keyed by option key, survive label changes); customer ProductConfigure renders note under the group heading only when non-empty. Product A note never shows on Product B.
- JSON editor: "Konfigurasi Lanjutan (JSON)" validates syntax + must be an object before save (invalid rejected, not saved); unknown/custom pricing fields preserved. Backend now also rejects non-dict pricing (400) and strips empty option_notes (defense-in-depth for non-UI clients).
- Only change to backend model: admin_update_product allowed fields += photo_weights, option_notes (+ the two guards). No new pricing/matching engine; existing pricing untouched; historical order snapshots immutable.
- RBAC: PUT /admin/products/{id} requires modify_products (403 otherwise), server-side enforced. Owner full access.
- Tests: /app/backend/tests/test_v10_features.py 12/12 + 16/16 scenarios PASS (iteration_11.json). No data loss; no global priority; rak restored to canonical state (length>level>type>finishing, note 'Jarak per tingkat ± 28 cm').

### Phase 2B (partial) — photo gallery & admin photo mgmt (2026-06)
- Task A DONE: customer marketplace-style gallery in ProductConfigure — 3:4 large image, clickable thumbnails with active-border state, horizontal-scroll thumb strip, supports >3 photos, single-photo hides thumbs, no-photo keeps fallback. Verified: thumb click swaps main image.
- Task B DONE: admin >3 photos per configuration via additive `photos[].images` array + "Add Photo" (add-photo-{id}) + per-image delete. Persists with ZERO backend/schema change (product PUT already saves photos objects); existing 3 slots (main/front/side) untouched; matching logic unchanged.
- Task C DONE (core): admin photo-set list wrapped in a max-h scrollable panel; extra-photo previews are compact (56px). (Lightbox enlarge not added — minor.)
- Zero data touched: rak restored to canonical (pricing byte-intact, priority length>level>type>finishing, note preserved); meja_rak untouched; extra-photos round-trip verified then cleaned up.
- DEFERRED to Phase 2B-cont (budget): Tasks D–G multilingual completion (footer/checkout/order-summary/confirmation i18n audit), WhatsApp message language, admin language switcher (default id), Arabic location/store-address fields with fallback, dark-mode audit, broader mobile audit. No data model changes made for these yet; order already has a `language` field to reuse.

### Phase 2A-1 — dynamic JSON-driven product configuration (2026-06) — V1 LAUNCH FINAL
- ProductConfigure.jsx renders configuration option groups generically from `product.pricing.groups` (groups.map → Section + Chips). Legacy category branches (rak/meja/meja_rak) retained as fallback when `groups` is absent. `canAdd()` validates dynamic products via `groups.every(x => config[x.key])`. NO product/category-specific frontend branch is needed for new configurable products.
- Homepage: unused 4th hero image slot removed (Home.jsx restricted to 3 slots).
- Verified END-TO-END (PASS): temp `groups` injected on papan-tulis (category papan_tulis has NO code branch) → API returned groups → /produk/papan-tulis rendered Ukuran/Jenis Frame/Finishing with options → selecting options updated config state (active highlight) → NO new frontend code required. Temp `groups` key then unset; papan-tulis restored to canonical legacy pricing (lengths/levels/types/finishings/base_prices intact).
- Regression: rak-kayu, meja, meja-rak all load, configurable, legacy pricing keys intact. Frontend compiled successfully.
- HOW A FUTURE ADMIN ADDS A CONFIGURABLE PRODUCT WITHOUT CODING: in AdminProductEdit → "Konfigurasi Lanjutan (JSON)", add a `groups` array to pricing, e.g. `{"groups":[{"key":"size","label":"Ukuran","options":["60x90","90x120"]},{"key":"surface","label":"Surface","options":[...]}]}`, save → customer page auto-renders the groups; pricing/photo-matching receive the selected values via existing engines.

### V1 Launch — final product data + pricing fix (2026-06)
- Generic "additive" pricing engine (`pricing.price_model == "additive"`) added to BOTH compute_item_price (backend) and computeBreakdown (frontend), evaluated BEFORE category branches. Model: `groups` (renders + validates via ProductConfigure generic path), `base_keys` (joined by " | ") → `base_prices`, per-group `adjust` maps. No per-product frontend/category code. Legacy rak/meja branches untouched.
- MEJA Premium FIX: root cause was engine ignoring dict finishing for `meja` (returned 0). Data (`finishing.Premium` size-keyed dict) already existed. Fix: meja branch now reads `fin[f"{size}_{height}"]` when dict. Verified: 40x80+30=1150, 40x80+75=1350, 50x80+30=1450, 50x80+75=1650; Natural/Pernis/Cat Warna unchanged. Label "Ukuran Tabletop"→"Ukuran Meja" (i18n only, key `size` kept).
- MEJA RAK: converted to additive groups — Ukuran Meja / Jumlah Tingkat Rak / Tinggi Meja / Finishing (old "Tipe" label gone). Prices preserved (base by size|levels + height +150 Kursi + finishing 100/150). 5 photos migrated variant/type→size/levels/height keys; photo_weights set → matching preserved.
- PAPAN TULIS & BLACKBOARD: fixed-price additive products, fully orderable. Papan Tulis: Gantung + '+ Kaki 150 cm' × 6 sizes. BlackBoard: renamed from "Blockboard" (display name + CATEGORY_LABELS; slug/id 'blockboard' kept). 4 fixed options.
- PESANAN CUSTOM: 5 predefined fixed-price designs with detail specs (`design_details` rendered + carried via `config._summary` into cart/checkout/WhatsApp/confirmation). No finishing/size double-charge (verified: extra finishing key ignored). custom-size toggle hidden for additive products.
- Config summary generalized: `cfg._summary` preferred in both config_summary (server) and config_summary_client (client); OrderConfirmation now renders per-item spec summary.
- CATALOG: extra products (rak-tempel, rak-gantung, gantungan-baju) set active:false → hidden from customer catalog (kept in DB/admin). Exactly 6 V1 products active.
- OWNER PASSWORD SECURITY FIX: seed() no longer resets an existing Owner's password on env mismatch (removed verify/reset block). Seed only creates Owner when none exists; restart/deploy can never overwrite the manually-set password. Verified Owner login still works.
- Verified: 25/25 backend price cases PASS; custom order e2e (price 2750, details in WhatsApp); Rak legacy price 565 intact; option notes isolated (rak note only on rak); frontend smoke on all 6 products PASS.

### V1 Launch — admin photo-config schema fix (2026-06)
- Root cause: `AdminProductEdit.jsx` derived photo-config attribute selectors from a hardcoded `PHOTO_ATTRS[category]` map (predated the additive `groups` schema) → wrong for meja_rak (variant/type) and empty for papan_tulis/blockboard/custom.
- Fix: added `getOptionDefs(prod)` — prefers the product's CURRENT `pricing.groups` ([{key,options,label}]), falls back to legacy `PHOTO_ATTRS` for Rak/Meja. Photo attribute selectors, photo-priority list, notes editor, and priority default ordering all now derive from it. No new photo architecture; matching engine untouched.
- Verified (targeted, no testing_agent): admin save→persist→match round-trip PASS for papan-tulis (mount/size) & pesanan-custom (desain) with full data restore; meja-rak's 5 migrated photos still match on size/levels/height/finishing; admin UI screenshots confirm meja-rak shows size/levels/height/finishing (old Varian/Tingkat gone) and Pesanan Custom lists all 5 designs as mappable options. Rak/Meja legacy photo config unchanged. Owner auth untouched.

## Backlog (not built)
- P2: full i18n coverage for new V4 customer/referral/admin strings (currently Indonesian; ID/EN/AR system intact for prior text) — KNOWN LIMITATION; split server.py into routers; automatic FX; payment gateway; inventory.
