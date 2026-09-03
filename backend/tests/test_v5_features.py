"""V5 QA: order-breakdown consistency (admin/confirmation/whatsapp share the same
authoritative snapshot), admin order search across 6 fields, owner-only customer
deactivation blocking login, and data integrity after deactivation.
"""
import os
import time
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
UNIQUE = f"V5{int(time.time())}"
# short numeric suffix for phone uniqueness (last 6 digits of epoch)
PHONE_STAMP = str(int(time.time()))[-6:]


# ---------------- Fixtures ----------------
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


def _register(suffix, phone_suffix):
    s = requests.Session()
    payload = {
        "username": f"TEST{UNIQUE}{suffix}",
        "phone": f"+201{PHONE_STAMP}{phone_suffix}",
        "password": "pass1234",
        "email": f"{suffix}@test.example",
    }
    r = s.post(f"{API}/customer/register", json=payload)
    assert r.status_code == 200, r.text
    return s, r.json()


def _mk_payload(rak, name, phone="+201555222000", **extra):
    p = {
        "customer_name": name, "customer_phone": phone, "customer_address": "x",
        "delivery_method": "pickup", "payment_method": "cash",
        "item": {"product_id": rak["id"],
                 "config": {"length": "60", "level": "2", "type": "B", "finishing": "Natural"},
                 "quantity": 1},
    }
    p.update(extra)
    return p


def _mk_delivery(rak, name, zone_id, phone="+201555222000", **extra):
    p = _mk_payload(rak, name, phone)
    p["delivery_method"] = "delivery"
    p["delivery_zone_id"] = zone_id
    p.update(extra)
    return p


@pytest.fixture(scope="module")
def zone(admin):
    zs = admin.get(f"{API}/delivery-zones").json()
    active = [z for z in zs if z.get("active")]
    if not active:
        pytest.skip("No active delivery zones")
    return active[0]


# ---------------- Order total math (scenarios A-D) ----------------
class TestOrderTotalMath:
    def test_A_no_discount(self, rak):
        r = requests.post(f"{API}/orders", json=_mk_payload(rak, f"TEST_{UNIQUE}_A"))
        assert r.status_code == 200, r.text
        o = r.json()
        assert o["subtotal_le"] > 0
        assert o["discount_le"] == 0
        assert o["referral_discount_le"] == 0
        assert o["points_redeemed_le"] == 0
        expected = o["subtotal_le"] - 0 - 0 - 0 + o["delivery_fee_le"]
        assert abs(o["total_le"] - expected) < 0.01

    def test_B_promo_discount(self, admin, rak):
        code = f"V5PROMO{int(time.time())}"[:14]
        # create a promo discount
        r = admin.post(f"{API}/admin/discounts", json={
            "code": code, "percentage": 10, "max_discount_le": 1000,
            "start_date": None, "end_date": None, "status": "active", "max_claims": 0,
        })
        assert r.status_code == 200, r.text
        did = r.json()["id"]
        try:
            r = requests.post(f"{API}/orders", json=_mk_payload(rak, f"TEST_{UNIQUE}_B", discount_code=code))
            assert r.status_code == 200, r.text
            o = r.json()
            assert o["discount_le"] > 0
            assert o["referral_discount_le"] == 0
            expected = o["subtotal_le"] - o["discount_le"] - 0 - 0 + o["delivery_fee_le"]
            assert abs(o["total_le"] - expected) < 0.01
            # whatsapp message must show Diskon line
            assert "Diskon" in o["whatsapp_message"]
            assert "Rincian Harga:" in o["whatsapp_message"]
        finally:
            admin.delete(f"{API}/admin/discounts/{did}")

    def test_C_referral(self, rak):
        owner_s, owner_c = _register("Cown", "30001")
        buyer_s, buyer_c = _register("Cbuy", "30002")
        code = owner_c["referral_code"]
        r = buyer_s.post(f"{API}/orders", json=_mk_payload(rak, f"TEST_{UNIQUE}_C", referral_code=code))
        assert r.status_code == 200, r.text
        o = r.json()
        assert o["referral_discount_le"] > 0
        assert o["discount_le"] == 0
        assert o["referral"]["code"] == code
        expected = o["subtotal_le"] - 0 - o["referral_discount_le"] - 0 + o["delivery_fee_le"]
        assert abs(o["total_le"] - expected) < 0.01
        assert "Diskon Referral" in o["whatsapp_message"]

    def test_D_referral_plus_points(self, admin, rak):
        # A (owner of referral), B (buyer with points), C (uses B's code to give B points)
        A_s, A_c = _register("Down", "40001")
        B_s, B_c = _register("Dbuy", "40002")
        C_s, C_c = _register("Dpts", "40003")

        # C uses B's code -> place & mark lunas -> B earns points
        r = C_s.post(f"{API}/orders", json=_mk_payload(rak, f"TEST_{UNIQUE}_Dseed", referral_code=B_c["referral_code"]))
        assert r.status_code == 200
        oid_seed = r.json()["id"]
        admin.patch(f"{API}/admin/orders/{oid_seed}", json={"payment_status": "lunas"})

        me = B_s.get(f"{API}/customer/points").json()
        pts = me["available"]
        assert pts > 0, f"B should have earned points: {me}"

        # Now B places order using A's code + redeems some points
        redeem = min(pts, 5)
        r = B_s.post(f"{API}/orders", json=_mk_payload(
            rak, f"TEST_{UNIQUE}_D", referral_code=A_c["referral_code"], redeem_points=redeem))
        assert r.status_code == 200, r.text
        o = r.json()
        assert o["referral_discount_le"] > 0
        assert o["points_redeemed_le"] > 0
        expected = o["subtotal_le"] - 0 - o["referral_discount_le"] - o["points_redeemed_le"] + o["delivery_fee_le"]
        assert abs(o["total_le"] - expected) < 0.01
        assert "Diskon Referral" in o["whatsapp_message"]
        assert "Penukaran Poin" in o["whatsapp_message"]


# ---------------- WhatsApp / confirmation / admin detail consistency ----------------
class TestBreakdownConsistency:
    def test_whatsapp_contains_rincian_and_matches_admin_and_confirmation(self, admin, rak):
        owner_s, owner_c = _register("Wown", "50001")
        buyer_s, buyer_c = _register("Wbuy", "50002")
        r = buyer_s.post(f"{API}/orders", json=_mk_payload(
            rak, f"TEST_{UNIQUE}_W", referral_code=owner_c["referral_code"]))
        assert r.status_code == 200
        created = r.json()
        oid_ = created["id"]

        # public GET (used by /order/{id} confirmation) — buyer is logged in so use their session
        conf = buyer_s.get(f"{API}/orders/{oid_}").json()
        assert conf["total_le"] == created["total_le"]
        assert conf["referral_discount_le"] == created["referral_discount_le"]
        assert conf["subtotal_le"] == created["subtotal_le"]

        # admin detail
        adm = admin.get(f"{API}/admin/orders/{oid_}").json()
        assert adm["total_le"] == created["total_le"]
        assert adm["referral_discount_le"] == created["referral_discount_le"]

        # whatsapp message content
        wa = conf["whatsapp_message"]
        for tok in ["Rincian Harga:", "Subtotal:", "Diskon Referral", "Ongkir:", "Total:", "Rate:"]:
            assert tok in wa, f"missing '{tok}' in whatsapp:\n{wa}"


# ---------------- Admin order search ----------------
class TestAdminOrderSearch:
    @pytest.fixture(scope="class")
    def seed(self, admin, rak):
        owner_s, owner_c = _register("Sown", "60001")
        buyer_s, buyer_c = _register("Sbuy", "60002")
        # order with referral (so referral.code is searchable)
        r = buyer_s.post(f"{API}/orders", json=_mk_payload(
            rak, f"TEST_{UNIQUE}_SNAME", phone=f"+201{PHONE_STAMP}60099", referral_code=owner_c["referral_code"]))
        assert r.status_code == 200
        return {"order": r.json(), "owner": owner_c, "buyer": buyer_c}

    def test_search_by_order_number(self, admin, seed):
        on = seed["order"]["order_number"]
        r = admin.get(f"{API}/admin/orders", params={"q": on})
        assert r.status_code == 200
        assert any(o["order_number"] == on for o in r.json())

    def test_search_by_customer_name(self, admin, seed):
        r = admin.get(f"{API}/admin/orders", params={"q": f"TEST_{UNIQUE}_SNAME"})
        assert any(o["id"] == seed["order"]["id"] for o in r.json())

    def test_search_by_phone(self, admin, seed):
        r = admin.get(f"{API}/admin/orders", params={"q": f"{PHONE_STAMP}60099"})
        assert any(o["id"] == seed["order"]["id"] for o in r.json())

    def test_search_by_product_name(self, admin, seed):
        # product name snapshot ("Rak Kayu") should be searchable
        r = admin.get(f"{API}/admin/orders", params={"q": "Rak"})
        assert any(o["id"] == seed["order"]["id"] for o in r.json())

    def test_search_by_customer_username(self, admin, seed):
        r = admin.get(f"{API}/admin/orders", params={"q": seed["buyer"]["username"]})
        assert any(o["id"] == seed["order"]["id"] for o in r.json())

    def test_search_by_referral_code(self, admin, seed):
        r = admin.get(f"{API}/admin/orders", params={"q": seed["owner"]["referral_code"]})
        assert any(o["id"] == seed["order"]["id"] for o in r.json())

    def test_search_combined_with_status_filter(self, admin, seed):
        # order defaults to pesanan_masuk + belum_dibayar
        r = admin.get(f"{API}/admin/orders", params={
            "q": seed["order"]["order_number"], "status": "pesanan_masuk"})
        assert r.status_code == 200
        assert any(o["id"] == seed["order"]["id"] for o in r.json())
        # negative: wrong status filter should not match
        r2 = admin.get(f"{API}/admin/orders", params={
            "q": seed["order"]["order_number"], "status": "selesai"})
        assert not any(o["id"] == seed["order"]["id"] for o in r2.json())

    def test_search_combined_with_payment_filter(self, admin, seed):
        r = admin.get(f"{API}/admin/orders", params={
            "q": seed["order"]["order_number"], "payment_status": "belum_dibayar"})
        assert any(o["id"] == seed["order"]["id"] for o in r.json())


# ---------------- Customer deactivation + integrity ----------------
class TestCustomerDeactivation:
    def test_deactivate_blocks_login_and_reactivate_restores(self, admin, rak):
        s, c = _register("Dact", "70001")
        cid = c["id"]
        # customer places an order (so we can check integrity later)
        r = s.post(f"{API}/orders", json=_mk_payload(rak, f"TEST_{UNIQUE}_DACT"))
        assert r.status_code == 200
        order_id = r.json()["id"]
        # mark lunas so revenue is recorded
        admin.patch(f"{API}/admin/orders/{order_id}", json={"payment_status": "lunas"})

        # admin customer detail contains active=True by default
        det = admin.get(f"{API}/admin/customers/{cid}").json()
        assert det["customer"].get("active") is True

        # deactivate
        r = admin.patch(f"{API}/admin/customers/{cid}", json={"active": False})
        assert r.status_code == 200
        assert r.json()["active"] is False

        # login blocked
        r = requests.post(f"{API}/customer/login", json={
            "identifier": c["username"], "password": "pass1234"})
        assert r.status_code == 403
        assert "dinonaktifkan" in r.text.lower() or "nonaktif" in r.text.lower()

        # data intact: order still returns via admin list and detail
        found = [o for o in admin.get(f"{API}/admin/orders").json() if o["id"] == order_id]
        assert found, "order missing after deactivation"
        det2 = admin.get(f"{API}/admin/customers/{cid}").json()
        assert any(o["id"] == order_id for o in det2["orders"]), "order missing in customer detail"

        # finance/order_revenue survives (only if access_finance) — check via finance monthly count doesn't drop
        # (best-effort: ensure endpoint responds)
        fin = admin.get(f"{API}/admin/finance/monthly")
        assert fin.status_code == 200

        # reactivate restores login
        r = admin.patch(f"{API}/admin/customers/{cid}", json={"active": True})
        assert r.status_code == 200
        assert r.json()["active"] is True
        r = requests.post(f"{API}/customer/login", json={
            "identifier": c["username"], "password": "pass1234"})
        assert r.status_code == 200

    def test_non_owner_cannot_patch_customer(self, admin, rak):
        # register a customer to poke at
        s, c = _register("Nown", "70002")
        cid = c["id"]

        # create a manager sub-admin (no access to owner-only endpoints)
        pw = "SubPass_123!"
        stamp = int(time.time())
        r = admin.post(f"{API}/admin/admins", json={
            "email": f"sub_{stamp}@test.example", "password": pw, "name": "SubTest",
            "role": "manager", "permissions": {
                "manage_orders": True, "modify_products": False, "manage_settings": False,
                "access_finance": False, "delete_data": False}})
        assert r.status_code == 200, r.text
        sub_id = r.json()["id"]
        try:
            sub = requests.Session()
            r = sub.post(f"{API}/auth/login", json={
                "email": f"sub_{stamp}@test.example", "password": pw})
            assert r.status_code == 200

            r = sub.patch(f"{API}/admin/customers/{cid}", json={"active": False})
            assert r.status_code == 403
        finally:
            admin.delete(f"{API}/admin/admins/{sub_id}")


# ---------------- Cleanup ----------------
class TestZzzCleanup:
    def test_cleanup(self, admin):
        # remove test orders
        orders = admin.get(f"{API}/admin/orders").json()
        for o in orders:
            if str(o.get("customer_name", "")).startswith(f"TEST_{UNIQUE}"):
                admin.delete(f"{API}/admin/orders/{o['id']}")
        # remove test customers isn't a route; leaving them (deactivation/toggle tested).
