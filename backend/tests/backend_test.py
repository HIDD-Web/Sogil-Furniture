"""Sogil Furniture backend tests - covers pricing, orders, admin auth & CRUD."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback: read from frontend/.env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

API = f"{BASE_URL}/api"
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@sogil.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


# ---- Session fixtures ----
@pytest.fixture(scope="session")
def public_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def admin_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if r.status_code != 200:
        pytest.skip(f"Admin login failed: {r.status_code} {r.text}")
    return s


@pytest.fixture(scope="session")
def products(public_client):
    r = public_client.get(f"{API}/products")
    assert r.status_code == 200
    return r.json()


@pytest.fixture(scope="session")
def zones(public_client):
    r = public_client.get(f"{API}/delivery-zones")
    assert r.status_code == 200
    return r.json()


# ---- Public: store info, products, zones ----
class TestPublic:
    def test_store_info(self, public_client):
        r = public_client.get(f"{API}/store-info")
        assert r.status_code == 200
        d = r.json()
        assert d["store_name"]
        assert float(d["exchange_rate_idr_per_le"]) > 0

    def test_products_list(self, products):
        assert len(products) >= 9
        slugs = [p["slug"] for p in products]
        for s in ["rak-kayu", "meja", "meja-rak", "papan-tulis"]:
            assert s in slugs

    def test_product_by_slug(self, public_client):
        r = public_client.get(f"{API}/products/rak-kayu")
        assert r.status_code == 200
        assert r.json()["slug"] == "rak-kayu"

    def test_product_not_found(self, public_client):
        r = public_client.get(f"{API}/products/nonexistent-xyz")
        assert r.status_code == 404

    def test_delivery_zones(self, zones):
        assert len(zones) >= 1
        darasah = [z for z in zones if z["name"] == "Darasah"]
        assert darasah and float(darasah[0]["fee_le"]) == 150.0


# ---- Pricing engine ----
class TestPricing:
    def test_rak_80_5_A_pernis(self, public_client, products):
        rak = next(p for p in products if p["slug"] == "rak-kayu")
        r = public_client.post(f"{API}/calculate-price", json={
            "product_id": rak["id"],
            "config": {"length": "80", "level": "5", "type": "A", "finishing": "Pernis"},
            "quantity": 1,
        })
        assert r.status_code == 200
        bd = r.json()
        # base(80,5) = 1500 + (5-2)*200 = 2100; type A@80 = 80; pernis 20*5 = 100
        assert bd["base_price_le"] == 2100
        assert bd["adjustments_le"] == 80
        assert bd["finishing_le"] == 100
        assert bd["unit_price_le"] == 2280
        assert bd["subtotal_le"] == 2280

    def test_rak_quantity_multiplier(self, public_client, products):
        rak = next(p for p in products if p["slug"] == "rak-kayu")
        r = public_client.post(f"{API}/calculate-price", json={
            "product_id": rak["id"],
            "config": {"length": "80", "level": "5", "type": "A", "finishing": "Pernis"},
            "quantity": 3,
        })
        assert r.json()["subtotal_le"] == 2280 * 3

    def test_custom_size_flag(self, public_client, products):
        rak = next(p for p in products if p["slug"] == "rak-kayu")
        r = public_client.post(f"{API}/calculate-price", json={
            "product_id": rak["id"],
            "config": {"custom_size": True, "note": "special size"},
            "quantity": 1,
        })
        bd = r.json()
        assert bd["requires_admin_confirmation"] is True
        assert bd["subtotal_le"] == 0

    def test_meja_pricing(self, public_client, products):
        meja = next(p for p in products if p["slug"] == "meja")
        r = public_client.post(f"{API}/calculate-price", json={
            "product_id": meja["id"],
            "config": {"size": "40x80", "height": "75", "finishing": "Pernis"},
            "quantity": 1,
        })
        bd = r.json()
        assert bd["base_price_le"] == 800
        assert bd["finishing_le"] == 40
        assert bd["subtotal_le"] == 840


# ---- Orders ----
class TestOrders:
    def test_create_delivery_order(self, public_client, products, zones):
        rak = next(p for p in products if p["slug"] == "rak-kayu")
        darasah = next(z for z in zones if z["name"] == "Darasah")
        payload = {
            "customer_name": "TEST_Ahmad",
            "customer_phone": "628123456789",
            "customer_address": "Test Street 1",
            "delivery_method": "delivery",
            "delivery_zone_id": darasah["id"],
            "payment_method": "transfer",
            "notes": "",
            "item": {
                "product_id": rak["id"],
                "config": {"length": "80", "level": "5", "type": "A", "finishing": "Pernis"},
                "quantity": 1,
            },
        }
        r = public_client.post(f"{API}/orders", json=payload)
        assert r.status_code == 200, r.text
        o = r.json()
        assert o["order_number"].startswith("SGF-")
        assert o["subtotal_le"] == 2280
        assert o["total_le"] == 2280 + 150
        assert o["delivery_fee_le"] == 150
        assert o["exchange_rate_idr_per_le"] == 357
        assert o["estimated_total_idr"] == round((2280 + 150) * 357)
        assert o["whatsapp_message"]
        assert "SGF-" in o["whatsapp_message"]
        assert o["order_status"] == "pesanan_masuk"
        assert o["payment_status"] == "belum_dibayar"
        # persist
        r2 = public_client.get(f"{API}/orders/{o['id']}")
        assert r2.status_code == 200
        assert r2.json()["order_number"] == o["order_number"]
        pytest.created_order_id = o["id"]
        pytest.created_order_total = o["total_le"]

    def test_create_pickup_order(self, public_client, products):
        rak = next(p for p in products if p["slug"] == "rak-kayu")
        payload = {
            "customer_name": "TEST_Pickup",
            "customer_phone": "628999888777",
            "customer_address": "Pickup addr",
            "delivery_method": "pickup",
            "delivery_zone_id": None,
            "payment_method": "cash",
            "item": {
                "product_id": rak["id"],
                "config": {"length": "60", "level": "2", "type": "B", "finishing": "Natural"},
                "quantity": 1,
            },
        }
        r = public_client.post(f"{API}/orders", json=payload)
        assert r.status_code == 200
        o = r.json()
        assert o["delivery_fee_le"] == 0
        assert o["total_le"] == o["subtotal_le"]

    def test_create_custom_order(self, public_client, products):
        rak = next(p for p in products if p["slug"] == "rak-kayu")
        payload = {
            "customer_name": "TEST_Custom",
            "customer_phone": "628111",
            "customer_address": "Addr",
            "delivery_method": "pickup",
            "payment_method": "cash",
            "notes": "custom special dimensions",
            "item": {"product_id": rak["id"], "config": {"custom_size": True}, "quantity": 1},
        }
        r = public_client.post(f"{API}/orders", json=payload)
        assert r.status_code == 200
        o = r.json()
        assert o["requires_admin_confirmation"] is True

    def test_missing_name_rejected(self, public_client, products):
        rak = next(p for p in products if p["slug"] == "rak-kayu")
        r = public_client.post(f"{API}/orders", json={
            "customer_name": "  ", "customer_phone": "1", "customer_address": "1",
            "delivery_method": "pickup", "payment_method": "cash",
            "item": {"product_id": rak["id"], "config": {"length": "60", "level": "2", "type": "B", "finishing": "Natural"}, "quantity": 1},
        })
        assert r.status_code == 400

    def test_delivery_without_zone_rejected(self, public_client, products):
        rak = next(p for p in products if p["slug"] == "rak-kayu")
        r = public_client.post(f"{API}/orders", json={
            "customer_name": "TEST_X", "customer_phone": "1", "customer_address": "1",
            "delivery_method": "delivery", "payment_method": "cash",
            "item": {"product_id": rak["id"], "config": {"length": "60", "level": "2", "type": "B", "finishing": "Natural"}, "quantity": 1},
        })
        assert r.status_code == 400


# ---- Auth ----
class TestAuth:
    def test_login_success(self, admin_client):
        r = admin_client.get(f"{API}/auth/me")
        assert r.status_code == 200
        assert r.json()["email"] == ADMIN_EMAIL

    def test_login_invalid(self, public_client):
        s = requests.Session()
        r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong"})
        assert r.status_code == 401

    def test_protected_requires_auth(self, public_client):
        s = requests.Session()
        r = s.get(f"{API}/admin/orders")
        assert r.status_code == 401


# ---- Admin ----
class TestAdmin:
    def test_admin_orders_list(self, admin_client):
        r = admin_client.get(f"{API}/admin/orders")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_admin_overview(self, admin_client):
        r = admin_client.get(f"{API}/admin/overview")
        assert r.status_code == 200
        d = r.json()
        assert "total" in d and "pesanan_masuk" in d

    def test_admin_update_order_status(self, admin_client):
        # get an order
        orders = admin_client.get(f"{API}/admin/orders").json()
        assert orders
        oid = orders[0]["id"]
        r = admin_client.patch(f"{API}/admin/orders/{oid}", json={
            "order_status": "dikonfirmasi", "payment_status": "dp", "admin_note": "TEST note"
        })
        assert r.status_code == 200
        d = r.json()
        assert d["order_status"] == "dikonfirmasi"
        assert d["payment_status"] == "dp"
        assert d["admin_note"] == "TEST note"
        # verify persistence
        r2 = admin_client.get(f"{API}/admin/orders/{oid}").json()
        assert r2["order_status"] == "dikonfirmasi"

    def test_historical_price_immutable(self, admin_client, public_client, products):
        """Change product price and confirm existing order total unchanged."""
        # Use last created order via public list? Use admin list.
        orders = admin_client.get(f"{API}/admin/orders").json()
        order = orders[0]
        original_total = order["total_le"]
        # bump product's starting_price_le (harmless), get id
        rak = next(p for p in products if p["slug"] == "rak-kayu")
        # temporarily modify pricing base
        new_pricing = dict(rak["pricing"])
        new_pricing["base_prices"] = dict(new_pricing["base_prices"])
        original_base = new_pricing["base_prices"]["80_5"]
        new_pricing["base_prices"]["80_5"] = original_base + 1000
        r = admin_client.put(f"{API}/admin/products/{rak['id']}", json={"pricing": new_pricing})
        assert r.status_code == 200
        # verify order total unchanged
        fetched = admin_client.get(f"{API}/admin/orders/{order['id']}").json()
        assert fetched["total_le"] == original_total
        # restore
        new_pricing["base_prices"]["80_5"] = original_base
        admin_client.put(f"{API}/admin/products/{rak['id']}", json={"pricing": new_pricing})

    def test_delivery_zone_crud(self, admin_client):
        r = admin_client.post(f"{API}/admin/delivery-zones", json={
            "name": "TEST_Zone", "fee_le": 999, "active": True
        })
        assert r.status_code == 200
        zid = r.json()["id"]
        r2 = admin_client.put(f"{API}/admin/delivery-zones/{zid}", json={
            "name": "TEST_Zone2", "fee_le": 888, "active": False
        })
        assert r2.status_code == 200
        assert r2.json()["fee_le"] == 888
        r3 = admin_client.delete(f"{API}/admin/delivery-zones/{zid}")
        assert r3.status_code == 200

    def test_settings_update(self, admin_client):
        # get current
        r = admin_client.get(f"{API}/admin/settings")
        assert r.status_code == 200
        original_rate = r.json()["exchange_rate_idr_per_le"]
        # update
        r2 = admin_client.put(f"{API}/admin/settings", json={"exchange_rate_idr_per_le": 360})
        assert r2.status_code == 200
        assert r2.json()["exchange_rate_idr_per_le"] == 360
        # restore
        admin_client.put(f"{API}/admin/settings", json={"exchange_rate_idr_per_le": original_rate})
