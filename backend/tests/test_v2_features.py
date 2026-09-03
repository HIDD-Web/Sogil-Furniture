"""V2 feature tests: multi-item cart orders, phone validation, analytics,
finance auto-revenue, multi-admin perms, photo match, security."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@sogil.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


@pytest.fixture(scope="module")
def admin():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if r.status_code != 200:
        pytest.skip(f"admin login failed: {r.status_code} {r.text}")
    return s


@pytest.fixture(scope="module")
def rak():
    r = requests.get(f"{API}/products/rak-kayu")
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="module")
def darasah():
    r = requests.get(f"{API}/delivery-zones")
    zones = r.json()
    return next(z for z in zones if z["name"] == "Darasah")


# -------- Rak Type B base prices (V2 migration) --------
class TestRakTypeBPricing:
    def test_60_2_type_b_natural_565(self, rak):
        r = requests.post(f"{API}/calculate-price", json={
            "product_id": rak["id"],
            "config": {"length": "60", "level": "2", "type": "B", "finishing": "Natural"},
            "quantity": 1,
        })
        assert r.status_code == 200
        d = r.json()
        assert d["base_price_le"] == 565
        assert d["adjustments_le"] == 0
        assert d["finishing_le"] == 0
        assert d["unit_price_le"] == 565

    def test_starting_price_is_565(self, rak):
        assert rak["starting_price_le"] == 565


# -------- Phone validation (+countrycode) --------
class TestPhoneValidation:
    def test_reject_local_format(self, rak):
        r = requests.post(f"{API}/orders", json={
            "customer_name": "TEST_A", "customer_phone": "08123456789",
            "customer_address": "x", "delivery_method": "pickup", "payment_method": "cash",
            "item": {"product_id": rak["id"], "config": {"length": "60", "level": "2", "type": "B", "finishing": "Natural"}, "quantity": 1},
        })
        assert r.status_code == 400
        assert "+" in r.json().get("detail", "")

    def test_accept_intl_format(self, rak):
        r = requests.post(f"{API}/orders", json={
            "customer_name": "TEST_Intl", "customer_phone": "+201234567890",
            "customer_address": "x", "delivery_method": "pickup", "payment_method": "cash",
            "item": {"product_id": rak["id"], "config": {"length": "60", "level": "2", "type": "B", "finishing": "Natural"}, "quantity": 1},
        })
        assert r.status_code == 200
        assert r.json()["customer_phone"] == "+201234567890"


# -------- Multi-item cart order --------
class TestMultiItemOrder:
    def test_multi_item_totals_and_delivery_fee(self, rak, darasah):
        r = requests.post(f"{API}/orders", json={
            "customer_name": "TEST_Cart", "customer_phone": "+201111111111",
            "customer_address": "cart addr", "delivery_method": "delivery",
            "delivery_zone_id": darasah["id"], "payment_method": "transfer",
            "items": [
                {"product_id": rak["id"], "config": {"length": "60", "level": "2", "type": "B", "finishing": "Natural"}, "quantity": 2},
                {"product_id": rak["id"], "config": {"length": "80", "level": "5", "type": "A", "finishing": "Pernis"}, "quantity": 1},
            ],
        })
        assert r.status_code == 200, r.text
        o = r.json()
        assert len(o["items"]) == 2
        # Post V2 Rak Type B migration: 80/5 base=1335, A@80=+80, Pernis 20*5=100 -> 1515
        expected_subtotal = 565 * 2 + 1515
        assert o["subtotal_le"] == expected_subtotal
        assert o["delivery_fee_le"] == 150
        assert o["total_le"] == expected_subtotal + 150
        assert o["exchange_rate_idr_per_le"] == 357
        pytest.multi_order_id = o["id"]
        pytest.multi_order_total = o["total_le"]

    def test_empty_cart_rejected(self):
        r = requests.post(f"{API}/orders", json={
            "customer_name": "T", "customer_phone": "+201111111111", "customer_address": "x",
            "delivery_method": "pickup", "payment_method": "cash",
        })
        assert r.status_code == 400


# -------- Photo match --------
class TestMatchPhoto:
    def test_no_photos_returns_none(self, rak):
        r = requests.post(f"{API}/match-photo", json={
            "product_id": rak["id"],
            "config": {"length": "60", "level": "2", "type": "B", "finishing": "Natural"},
        })
        assert r.status_code == 200
        d = r.json()
        # rak seeded with no photos
        assert d["photo"] is None
        assert d["exact"] is False

    def test_exact_match_with_added_photo(self, admin, rak):
        # add photos to rak
        photos = [
            {"id": "p1", "main_url": "http://x/p1.jpg",
             "attributes": {"length": "60", "level": "2", "type": "B", "finishing": "Natural"}},
            {"id": "p2", "main_url": "http://x/p2.jpg",
             "attributes": {"length": "80", "level": "5", "type": "A", "finishing": "Pernis"}},
        ]
        r = admin.put(f"{API}/admin/products/{rak['id']}", json={
            "photos": photos, "representative_photo_id": "p1",
        })
        assert r.status_code == 200
        try:
            r = requests.post(f"{API}/match-photo", json={
                "product_id": rak["id"],
                "config": {"length": "80", "level": "5", "type": "A", "finishing": "Pernis"},
            })
            d = r.json()
            assert d["exact"] is True
            assert d["photo"]["id"] == "p2"
            # closest (non-exact)
            r = requests.post(f"{API}/match-photo", json={
                "product_id": rak["id"],
                "config": {"length": "80", "level": "5", "type": "B", "finishing": "Pernis"},
            })
            d = r.json()
            assert d["photo"] is not None
        finally:
            admin.put(f"{API}/admin/products/{rak['id']}", json={"photos": [], "representative_photo_id": None})


# -------- Analytics --------
class TestAnalytics:
    def test_top_configs_default(self, admin):
        r = admin.get(f"{API}/admin/analytics/top-configs")
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)

    def test_top_configs_group_by_length(self, admin):
        r = admin.get(f"{API}/admin/analytics/top-configs?category=rak&group_by=length")
        assert r.status_code == 200
        for row in r.json():
            assert "cm" in row["key"]


# -------- Finance auto-revenue dedup --------
class TestFinanceAutoRevenue:
    def test_lunas_creates_and_dedups_revenue(self, admin, rak):
        # create fresh order
        r = requests.post(f"{API}/orders", json={
            "customer_name": "TEST_Lunas", "customer_phone": "+201555000111",
            "customer_address": "x", "delivery_method": "pickup", "payment_method": "cash",
            "item": {"product_id": rak["id"], "config": {"length": "60", "level": "2", "type": "B", "finishing": "Natural"}, "quantity": 1},
        })
        oid = r.json()["id"]
        total = r.json()["total_le"]
        # set lunas twice
        admin.patch(f"{API}/admin/orders/{oid}", json={"payment_status": "lunas"})
        admin.patch(f"{API}/admin/orders/{oid}", json={"payment_status": "lunas"})
        txns = admin.get(f"{API}/admin/finance/transactions?type=order_revenue").json()
        matches = [t for t in txns if t.get("related_order_id") == oid]
        assert len(matches) == 1, f"expected 1 auto-revenue got {len(matches)}"
        assert matches[0]["amount"] == total
        assert matches[0]["currency"] == "EGP"

    def test_manual_expense(self, admin):
        r = admin.post(f"{API}/admin/finance/transactions", json={
            "type": "expense", "category": "Operasional", "amount": 100,
            "currency": "EGP", "description": "TEST_expense",
        })
        assert r.status_code == 200
        txn_id = r.json()["id"]
        # cleanup
        admin.delete(f"{API}/admin/finance/transactions/{txn_id}")

    def test_transfer_idr_to_egp(self, admin):
        r = admin.post(f"{API}/admin/finance/transfer", json={
            "from_account": "IDR", "to_account": "EGP",
            "from_amount": 100000, "to_amount": 280, "exchange_rate": 357,
            "description": "TEST_transfer",
        })
        assert r.status_code == 200
        # verify balances shift
        b = admin.get(f"{API}/admin/finance/accounts").json()["balances"]
        assert "IDR" in b and "EGP" in b

    def test_finance_stats(self, admin):
        r = admin.get(f"{API}/admin/finance/stats?period=this_month")
        assert r.status_code == 200
        d = r.json()
        assert "current" in d and "balances" in d
        assert "EGP" in d["current"] and "IDR" in d["current"]


# -------- Multi-admin & permissions --------
class TestMultiAdmin:
    def test_owner_can_create_manager_and_perms_forced(self, admin):
        payload = {
            "name": "TEST_Manager", "email": "test_manager_v2@example.com",
            "password": "pass1234", "role": "manager",
            "permissions": {"manage_orders": True, "modify_products": True,
                            "manage_settings": True, "access_finance": False,
                            "delete_data": False, "manage_admins": True},
        }
        # cleanup pre-existing
        admins = admin.get(f"{API}/admin/admins").json()
        for a in admins:
            if a.get("email") == payload["email"]:
                admin.delete(f"{API}/admin/admins/{a['id']}")
        r = admin.post(f"{API}/admin/admins", json=payload)
        assert r.status_code == 200, r.text
        created = r.json()
        assert created["permissions"]["manage_admins"] is False  # forced
        pytest.sub_admin_id = created["id"]
        pytest.sub_admin_email = payload["email"]
        pytest.sub_admin_password = payload["password"]

    def test_sub_admin_login_and_403_on_finance_and_admins(self):
        s = requests.Session()
        r = s.post(f"{API}/auth/login", json={
            "email": pytest.sub_admin_email, "password": pytest.sub_admin_password,
        })
        assert r.status_code == 200
        # finance -> 403
        assert s.get(f"{API}/admin/finance/accounts").status_code == 403
        # admins -> 403
        assert s.get(f"{API}/admin/admins").status_code == 403
        # products -> 200 (has modify_products but list endpoint uses no perm; ensure GET products works)
        assert s.get(f"{API}/products").status_code == 200

    def test_cleanup_sub_admin(self, admin):
        if hasattr(pytest, "sub_admin_id"):
            r = admin.delete(f"{API}/admin/admins/{pytest.sub_admin_id}")
            assert r.status_code == 200


# -------- Admin email & password change --------
class TestAdminEmailPassword:
    def test_change_email_wrong_password(self, admin):
        r = admin.post(f"{API}/auth/change-email", json={
            "current_password": "wrongpass", "new_email": "new@example.com",
        })
        assert r.status_code == 400

    def test_change_password_and_restore(self, admin):
        # change
        r = admin.post(f"{API}/auth/change-password", json={
            "current_password": ADMIN_PASSWORD, "new_password": "TempPass_123",
        })
        assert r.status_code == 200
        # restore
        r = admin.post(f"{API}/auth/change-password", json={
            "current_password": "TempPass_123", "new_password": ADMIN_PASSWORD,
        })
        assert r.status_code == 200


# -------- Security / 401 / 404 --------
class TestSecurity:
    @pytest.mark.parametrize("path", [
        "/admin/orders", "/admin/overview", "/admin/finance/accounts",
        "/admin/finance/transactions", "/admin/finance/stats",
        "/admin/admins", "/admin/settings", "/admin/analytics/top-configs",
    ])
    def test_admin_routes_require_auth(self, path):
        r = requests.get(f"{API}{path}")
        assert r.status_code == 401, f"{path} returned {r.status_code}"

    def test_invalid_oid_returns_404(self, admin):
        r = admin.get(f"{API}/admin/orders/not-a-real-id")
        assert r.status_code == 404
        r = requests.get(f"{API}/orders/xxxxxx")
        assert r.status_code == 404

    def test_valid_but_nonexistent_oid_404(self, admin):
        r = admin.get(f"{API}/admin/orders/507f1f77bcf86cd799439011")
        assert r.status_code == 404


# -------- Overview filters --------
class TestOverviewFilters:
    def test_overview_has_stat_keys(self, admin):
        r = admin.get(f"{API}/admin/overview")
        d = r.json()
        for k in ["total", "pesanan_masuk", "lunas", "belum_dibayar", "dp"]:
            assert k in d

    def test_orders_filter_by_status(self, admin):
        r = admin.get(f"{API}/admin/orders?status=pesanan_masuk")
        assert r.status_code == 200
        for o in r.json():
            assert o["order_status"] == "pesanan_masuk"

    def test_orders_filter_by_payment(self, admin):
        r = admin.get(f"{API}/admin/orders?payment_status=lunas")
        assert r.status_code == 200
        for o in r.json():
            assert o["payment_status"] == "lunas"
