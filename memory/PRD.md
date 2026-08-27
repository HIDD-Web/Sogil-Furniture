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

## Backlog (not built)
- P2: full i18n coverage for new V4 customer/referral/admin strings (currently Indonesian; ID/EN/AR system intact for prior text) — KNOWN LIMITATION; split server.py into routers; automatic FX; payment gateway; inventory.
