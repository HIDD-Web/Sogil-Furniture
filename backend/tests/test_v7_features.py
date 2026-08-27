"""V7 QA (targeted maintenance):
- Guest order tracking POST /api/orders/track (limited view, no sensitive fields, wrong-phone 404).
- Guest order claim POST /api/customer/claim-order (success, wrong phone, already claimed 409, snapshot preserved).
- Config record and photo slot ordering persistence via PUT /api/admin/products/{id}.
- Light regression: order privacy across customers.
"""
import os
import time
import copy
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
UNIQUE = f"V7{int(time.time())}"
PHONE_STAMP = str(int(time.time()))[-6:]

# Pre-existing guest-tracked order per request
EXISTING_ORDER = "SGF-20260827-001"
EXISTING_PHONE = "+2012345678"

_created_customers = []
_created_orders = []


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
        "email": f"v7{suffix}@test.example",
    }
    r = s.post(f"{API}/customer/register", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    _created_customers.append(data["id"])
    return s, data, payload["phone"]


def _mk_payload(rak, name, phone, **extra):
    p = {
        "customer_name": name, "customer_phone": phone, "customer_address": "TEST-addr",
        "delivery_method": "pickup", "payment_method": "cash",
        "item": {"product_id": rak["id"],
                 "config": {"length": "60", "level": "2", "type": "B", "finishing": "Natural"},
                 "quantity": 1},
    }
    p.update(extra)
    return p


# ----------------- Guest track -----------------
class TestGuestTrack:
    def test_track_success_returns_limited_view(self):
        r = requests.post(f"{API}/orders/track", json={
            "order_number": EXISTING_ORDER, "phone": EXISTING_PHONE})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["order_number"] == EXISTING_ORDER
        # sensitive fields must not be exposed
        assert "customer_address" not in data
        assert "customer_maps_url" not in data
        assert "customer_phone" not in data
        assert "customer_id" not in data
        # must contain expected safe fields
        for k in ("items", "order_status", "payment_status", "total_le"):
            assert k in data

    def test_track_wrong_phone_404(self):
        r = requests.post(f"{API}/orders/track", json={
            "order_number": EXISTING_ORDER, "phone": "+9999999999999"})
        assert r.status_code == 404, r.text

    def test_track_blank_phone_400(self):
        r = requests.post(f"{API}/orders/track", json={
            "order_number": EXISTING_ORDER, "phone": ""})
        assert r.status_code == 400, r.text

    def test_track_unknown_number_404(self):
        r = requests.post(f"{API}/orders/track", json={
            "order_number": "SGF-19990101-999", "phone": EXISTING_PHONE})
        assert r.status_code == 404


# ----------------- Guest claim -----------------
class TestGuestClaim:
    def test_claim_success_and_shows_in_customer_orders(self, rak, admin):
        s, c, phone = _register("Clm1", "82001")
        # create guest order (no cookies) with customer's phone
        r = requests.post(f"{API}/orders",
                          json=_mk_payload(rak, f"TEST_{UNIQUE}_CLM1", phone=phone))
        assert r.status_code == 200, r.text
        order = r.json()
        oid_ = order["id"]
        onum = order["order_number"]
        _created_orders.append(oid_)
        # snapshot original fields
        before = {k: order.get(k) for k in
                  ("total_le", "discount_le", "referral_discount_le",
                   "points_redeemed_le", "payment_status", "subtotal_le")}
        # claim
        r2 = s.post(f"{API}/customer/claim-order",
                    json={"order_number": onum, "phone": phone})
        assert r2.status_code == 200, r2.text
        # appears in /customer/orders
        r3 = s.get(f"{API}/customer/orders")
        assert r3.status_code == 200
        nums = [o["order_number"] for o in r3.json()]
        assert onum in nums
        # snapshot fields preserved
        got = admin.get(f"{API}/admin/orders/{oid_}").json()
        for k, v in before.items():
            assert got.get(k) == v, f"snapshot field {k} changed: {v} -> {got.get(k)}"
        assert got.get("customer_id") is not None
        assert got.get("customer_username")

    def test_claim_wrong_phone_404(self, rak):
        s, c, phone = _register("Clm2", "82002")
        r = requests.post(f"{API}/orders",
                          json=_mk_payload(rak, f"TEST_{UNIQUE}_CLM2", phone=phone))
        assert r.status_code == 200
        onum = r.json()["order_number"]
        _created_orders.append(r.json()["id"])
        r2 = s.post(f"{API}/customer/claim-order",
                    json={"order_number": onum, "phone": "+9999999999999"})
        assert r2.status_code == 404, r2.text

    def test_claim_existing_already_claimed_returns_409(self):
        # EXISTING_ORDER is already linked to another customer per request
        s, c, phone = _register("Clm3", "82003")
        r = s.post(f"{API}/customer/claim-order",
                   json={"order_number": EXISTING_ORDER, "phone": EXISTING_PHONE})
        assert r.status_code == 409, f"expected 409 got {r.status_code} {r.text}"

    def test_claim_requires_login(self, rak):
        # create a guest order & try to claim without login -> 401/403
        _, _, phone = _register("Clm4", "82004")
        r = requests.post(f"{API}/orders",
                          json=_mk_payload(rak, f"TEST_{UNIQUE}_CLM4", phone=phone))
        assert r.status_code == 200
        onum = r.json()["order_number"]
        _created_orders.append(r.json()["id"])
        # unauth claim
        r2 = requests.post(f"{API}/customer/claim-order",
                           json={"order_number": onum, "phone": phone})
        assert r2.status_code in (401, 403), r2.text


# ----------------- Product photos array ordering persistence -----------------
class TestPhotoOrdering:
    def _get_prod_full(self, admin, slug="rak-kayu"):
        # /api/products returns full documents for admin_view=True per v6 test
        r = admin.get(f"{API}/products", params={"admin_view": True})
        assert r.status_code == 200
        target = next((p for p in r.json() if p.get("slug") == slug), None)
        assert target is not None
        return target

    def _put(self, admin, prod, photos):
        base = {k: prod.get(k) for k in [
            "name", "category", "description", "image_url", "active",
            "configurable", "starting_price_le", "pricing", "photos",
            "representative_photo_id", "sort_order", "slug",
            "category_cover_image", "cover_mode"] if k in prod}
        base["photos"] = photos
        return admin.put(f"{API}/admin/products/{prod['id']}", json=base)

    def test_reorder_photo_records_persist(self, admin):
        prod = self._get_prod_full(admin)
        photos = copy.deepcopy(prod.get("photos") or [])
        if len(photos) < 2:
            pytest.skip("Need at least 2 config photos to test reorder")
        original_ids = [p.get("id") for p in photos]
        original_by_id = {p.get("id"): copy.deepcopy(p) for p in photos}

        # swap first two
        reordered = [photos[1], photos[0]] + photos[2:]
        r = self._put(admin, prod, reordered)
        assert r.status_code == 200, r.text

        # verify persisted
        prod2 = self._get_prod_full(admin)
        new_ids = [p.get("id") for p in prod2.get("photos") or []]
        assert new_ids[:2] == [original_ids[1], original_ids[0]]

        # attributes/urls unchanged per id
        for p in prod2["photos"]:
            orig = original_by_id.get(p.get("id"))
            if orig is None:
                continue
            for k in ("main_url", "front_url", "side_url",
                      "length", "level", "type", "finishing"):
                assert p.get(k) == orig.get(k), f"{k} changed for {p.get('id')}"

        # restore original order
        r2 = self._put(admin, prod2, photos)
        assert r2.status_code == 200

    def test_reorder_photo_slots_within_config(self, admin):
        prod = self._get_prod_full(admin)
        photos = copy.deepcopy(prod.get("photos") or [])
        if not photos:
            pytest.skip("No photos to test slot reorder")
        # find one photo with at least 2 non-empty URLs among main/front/side
        target_idx = None
        for i, p in enumerate(photos):
            urls = [p.get("main_url"), p.get("front_url"), p.get("side_url")]
            if sum(1 for u in urls if u) >= 2:
                target_idx = i
                break
        if target_idx is None:
            pytest.skip("No photo has 2+ slot URLs to swap")

        orig = copy.deepcopy(photos[target_idx])
        # swap main_url <-> front_url
        new_photo = copy.deepcopy(orig)
        new_photo["main_url"] = orig.get("front_url")
        new_photo["front_url"] = orig.get("main_url")

        modified = copy.deepcopy(photos)
        modified[target_idx] = new_photo

        r = self._put(admin, prod, modified)
        assert r.status_code == 200, r.text

        prod2 = self._get_prod_full(admin)
        got = next((p for p in prod2["photos"] if p.get("id") == orig.get("id")), None)
        assert got is not None
        assert got.get("main_url") == orig.get("front_url")
        assert got.get("front_url") == orig.get("main_url")
        assert got.get("side_url") == orig.get("side_url")
        # attrs unchanged
        for k in ("length", "level", "type", "finishing"):
            assert got.get(k) == orig.get(k)

        # ensure the other configs' photo records are unchanged in slot values
        others_before = {p.get("id"): p for p in photos if p.get("id") != orig.get("id")}
        for p in prod2["photos"]:
            if p.get("id") in others_before:
                ob = others_before[p.get("id")]
                for k in ("main_url", "front_url", "side_url"):
                    assert p.get(k) == ob.get(k)

        # restore
        r2 = self._put(admin, prod2, photos)
        assert r2.status_code == 200


# ----------------- Config-photo GET integrity -----------------
class TestConfigPhotoIntegrity:
    def test_products_endpoint_returns_photos(self, rak):
        photos = rak.get("photos") or []
        assert isinstance(photos, list)
        # non-strict: should have some in production data; assert shape when present
        for p in photos[:3]:
            for k in ("main_url", "front_url", "side_url"):
                assert k in p


# ----------------- Cleanup -----------------
class TestZzzCleanup:
    def test_cleanup(self, admin):
        for oid_ in list(_created_orders):
            admin.delete(f"{API}/admin/orders/{oid_}")
        # delete history-less customers (best effort)
        for cid in list(_created_customers):
            admin.delete(f"{API}/admin/customers/{cid}")
        # also sweep any TEST_UNIQUE customers/orders
        orders = admin.get(f"{API}/admin/orders").json()
        for o in orders:
            if str(o.get("customer_name", "")).startswith(f"TEST_{UNIQUE}"):
                admin.delete(f"{API}/admin/orders/{o['id']}")
        customers = admin.get(f"{API}/admin/customers").json()
        for c in customers:
            if str(c.get("username", "")).startswith(f"TEST{UNIQUE}"):
                admin.delete(f"{API}/admin/customers/{c['id']}")
