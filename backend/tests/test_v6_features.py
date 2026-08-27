"""V6 QA: (1) Order privacy on GET /api/orders/{id} (guest accessible, owner-customer
accessible, other customer 403, anonymous 403 on customer-linked orders).
(2) Safe permanent customer delete DELETE /api/admin/customers/{cid} — empty deletable,
history blocks 400, non-owner 403, no collateral deletion.
(3) Category cover preview response shape (manual vs auto with/without orders).
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
ADMIN_EMAIL = "syahid.mujahid02@gmail.com"
ADMIN_PASSWORD = "0LFOCWU9_V3k"
UNIQUE = f"V6{int(time.time())}"
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


def _mk_payload(rak, name, phone="+201555333000", **extra):
    p = {
        "customer_name": name, "customer_phone": phone, "customer_address": "x",
        "delivery_method": "pickup", "payment_method": "cash",
        "item": {"product_id": rak["id"],
                 "config": {"length": "60", "level": "2", "type": "B", "finishing": "Natural"},
                 "quantity": 1},
    }
    p.update(extra)
    return p


# ---------------- Order privacy (A) ----------------
class TestOrderPrivacy:
    def test_guest_order_publicly_accessible_by_id(self, rak):
        r = requests.post(f"{API}/orders", json=_mk_payload(rak, f"TEST_{UNIQUE}_GUEST",
                                                            phone=f"+201{PHONE_STAMP}80001"))
        assert r.status_code == 200, r.text
        oid_ = r.json()["id"]
        # anonymous get works
        r2 = requests.get(f"{API}/orders/{oid_}")
        assert r2.status_code == 200
        data = r2.json()
        assert data["id"] == oid_
        assert data.get("customer_id") in (None, "", 0)  # no linked customer
        assert "whatsapp_message" in data

    def test_customer_can_get_own_order(self, rak):
        s, c = _register("OwnA", "80002")
        r = s.post(f"{API}/orders", json=_mk_payload(rak, f"TEST_{UNIQUE}_OWNA"))
        assert r.status_code == 200, r.text
        oid_ = r.json()["id"]
        # same session (cookie set) can fetch
        r2 = s.get(f"{API}/orders/{oid_}")
        assert r2.status_code == 200, r2.text
        assert r2.json()["id"] == oid_

    def test_other_customer_cannot_get_linked_order(self, rak):
        a, ca = _register("PrivA", "80003")
        b, cb = _register("PrivB", "80004")
        r = a.post(f"{API}/orders", json=_mk_payload(rak, f"TEST_{UNIQUE}_PRIVA"))
        assert r.status_code == 200
        oid_ = r.json()["id"]
        r2 = b.get(f"{API}/orders/{oid_}")
        assert r2.status_code == 403, f"expected 403, got {r2.status_code} {r2.text}"

    def test_anon_cannot_get_linked_order(self, rak):
        a, ca = _register("AnonA", "80005")
        r = a.post(f"{API}/orders", json=_mk_payload(rak, f"TEST_{UNIQUE}_ANONA"))
        assert r.status_code == 200
        oid_ = r.json()["id"]
        r2 = requests.get(f"{API}/orders/{oid_}")  # no cookies
        assert r2.status_code == 403


# ---------------- Safe permanent customer delete (B) ----------------
class TestSafeCustomerDelete:
    def test_empty_customer_hard_deletable(self, admin):
        s, c = _register("Del1", "81001")
        cid = c["id"]
        ref_code = c["referral_code"]
        r = admin.delete(f"{API}/admin/customers/{cid}")
        assert r.status_code == 200, r.text
        # verify gone
        r2 = admin.get(f"{API}/admin/customers/{cid}")
        assert r2.status_code == 404
        # referral code should also be gone: applying it at checkout should fail
        # (login not required to validate code invalidity path — just probe validate endpoint if any;
        # otherwise attempt applying at order creation should not find the code)
        # A quick way: query admin referrals endpoint if available; else skip.

    def test_customer_with_order_history_blocked_400(self, admin, rak):
        s, c = _register("Del2", "81002")
        cid = c["id"]
        r = s.post(f"{API}/orders", json=_mk_payload(rak, f"TEST_{UNIQUE}_DEL2"))
        assert r.status_code == 200
        oid_ = r.json()["id"]
        try:
            r2 = admin.delete(f"{API}/admin/customers/{cid}")
            assert r2.status_code == 400, r2.text
            assert "riwayat" in r2.text.lower() or "nonaktif" in r2.text.lower()
            # customer still exists
            r3 = admin.get(f"{API}/admin/customers/{cid}")
            assert r3.status_code == 200
        finally:
            admin.delete(f"{API}/admin/orders/{oid_}")

    def test_customer_with_points_history_blocked_400(self, admin, rak):
        # Create A (referral owner) and B (buyer). B uses A's code -> mark lunas => A gets points_earned.
        A_s, A_c = _register("PhA", "81003")
        B_s, B_c = _register("PhB", "81004")
        r = B_s.post(f"{API}/orders", json=_mk_payload(rak, f"TEST_{UNIQUE}_PHIST",
                                                       referral_code=A_c["referral_code"]))
        assert r.status_code == 200, r.text
        oid_ = r.json()["id"]
        admin.patch(f"{API}/admin/orders/{oid_}", json={"payment_status": "lunas"})
        try:
            # A now has points history -> blocked
            r2 = admin.delete(f"{API}/admin/customers/{A_c['id']}")
            assert r2.status_code == 400, r2.text
            # B has an order -> also blocked
            r3 = admin.delete(f"{API}/admin/customers/{B_c['id']}")
            assert r3.status_code == 400, r3.text
        finally:
            admin.delete(f"{API}/admin/orders/{oid_}")

    def test_non_owner_delete_customer_403(self, admin):
        # empty deletable customer
        s, c = _register("Del3", "81005")
        cid = c["id"]
        pw = "SubPw_123!"
        stamp = int(time.time())
        r = admin.post(f"{API}/admin/admins", json={
            "email": f"sub_v6_{stamp}@test.example", "password": pw, "name": "SubV6",
            "role": "manager", "permissions": {
                "manage_orders": True, "modify_products": False, "manage_settings": False,
                "access_finance": False, "delete_data": True}})
        assert r.status_code == 200, r.text
        sub_id = r.json()["id"]
        try:
            sub = requests.Session()
            r = sub.post(f"{API}/auth/login", json={
                "email": f"sub_v6_{stamp}@test.example", "password": pw})
            assert r.status_code == 200
            r2 = sub.delete(f"{API}/admin/customers/{cid}")
            assert r2.status_code == 403, r2.text
            # owner cleanup: customer still exists, hard-delete
            r3 = admin.delete(f"{API}/admin/customers/{cid}")
            assert r3.status_code == 200
        finally:
            admin.delete(f"{API}/admin/admins/{sub_id}")

    def test_no_collateral_deletion_of_other_customers_orders(self, admin, rak):
        # customer X (empty, will be hard-deleted); customer Y has an order — Y's order must remain.
        X_s, X_c = _register("ColX", "81006")
        Y_s, Y_c = _register("ColY", "81007")
        r = Y_s.post(f"{API}/orders", json=_mk_payload(rak, f"TEST_{UNIQUE}_COLY"))
        assert r.status_code == 200
        y_order_id = r.json()["id"]
        try:
            # hard-delete X (empty)
            r2 = admin.delete(f"{API}/admin/customers/{X_c['id']}")
            assert r2.status_code == 200, r2.text
            # Y's order still fetchable via admin
            r3 = admin.get(f"{API}/admin/orders/{y_order_id}")
            assert r3.status_code == 200
            # Y still exists
            r4 = admin.get(f"{API}/admin/customers/{Y_c['id']}")
            assert r4.status_code == 200
        finally:
            admin.delete(f"{API}/admin/orders/{y_order_id}")


# ---------------- Category cover preview (C) ----------------
class TestCoverPreview:
    def _find_product_id(self, admin):
        prods = admin.get(f"{API}/products", params={"admin_view": True}).json()
        assert prods
        # pick "rak-kayu"
        rk = next((p for p in prods if p.get("slug") == "rak-kayu"), prods[0])
        return rk["id"]

    def _set_cover_mode(self, admin, pid, mode):
        # need to send full product payload back on PUT; only whitelisted keys are picked up
        prod = admin.get(f"{API}/products").json()
        # find in list
        target = next((p for p in prod if p["id"] == pid), None)
        base = {k: target.get(k) for k in ["name", "category", "description", "image_url", "active",
                "configurable", "starting_price_le", "pricing", "photos", "representative_photo_id",
                "sort_order", "slug", "category_cover_image"] if target and k in target}
        base["cover_mode"] = mode
        return admin.put(f"{API}/admin/products/{pid}", json=base)

    def test_manual_mode_selected_is_none(self, admin):
        pid = self._find_product_id(admin)
        # set to manual
        self._set_cover_mode(admin, pid, "manual")
        r = admin.get(f"{API}/admin/products/{pid}/cover-preview")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["cover_mode"] == "manual"
        assert data["selected"] is None
        assert "category_cover_image" in data
        assert "resolved_image" in data

    def test_auto_mode_shape(self, admin, rak):
        pid = self._find_product_id(admin)
        r0 = self._set_cover_mode(admin, pid, "auto")
        assert r0.status_code == 200, r0.text
        try:
            r = admin.get(f"{API}/admin/products/{pid}/cover-preview")
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["cover_mode"] == "auto"
            assert "resolved_image" in data
            # selected may be None if there are truly no orders in that category;
            # in this env there are historical orders so likely a dict.
            if data["selected"] is not None:
                sel = data["selected"]
                for k in ("config", "count", "image"):
                    assert k in sel
                assert isinstance(sel["count"], int) and sel["count"] >= 1
                assert isinstance(sel["config"], dict)
        finally:
            self._set_cover_mode(admin, pid, "manual")

    def test_cover_preview_requires_admin(self):
        # unauthenticated must be denied
        # need a product id
        s = requests.Session()
        prods = requests.get(f"{API}/products").json()
        pid = prods[0]["id"]
        r = requests.get(f"{API}/admin/products/{pid}/cover-preview")
        assert r.status_code in (401, 403)


# ---------------- Cleanup ----------------
class TestZzzCleanup:
    def test_cleanup(self, admin):
        # remove any leftover test orders and hard-delete history-less test customers
        orders = admin.get(f"{API}/admin/orders").json()
        for o in orders:
            if str(o.get("customer_name", "")).startswith(f"TEST_{UNIQUE}"):
                admin.delete(f"{API}/admin/orders/{o['id']}")
        # try to delete any TEST customers created this run
        customers = admin.get(f"{API}/admin/customers").json()
        for c in customers:
            if str(c.get("username", "")).startswith(f"TEST{UNIQUE}"):
                admin.delete(f"{API}/admin/customers/{c['id']}")  # 400 for those with history, 200 for empty
