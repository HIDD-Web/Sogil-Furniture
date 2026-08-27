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

## Backlog (not built)
- P1: Customer accounts + login (guest checkout preserved), referral codes + points (award on paid, dedupe, reverse on delete), customer order-history area — DEFERRED to next phase (large subsystem).
- P2: split server.py into routers; automatic FX; payment gateway; inventory.
