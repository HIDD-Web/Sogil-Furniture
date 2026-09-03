"""V4 feature tests: delete-order (permissions + finance/points reversal),
customer accounts (register/login/logout/history/isolation), referral (apply,
self-referral, mutual-exclusion w/ discount), referral points (award once,
reverse on delete, max cap), points redemption (cap%, non-negative),
finance charts (monthly endpoint), 404 handling on delete."""
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
UNIQUE = f"V4_{int(time.time())}"


# ---------------------- Fixtures ----------------------
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
    assert r.status_code == 200, r.text
    return r.json()


def _mk_order_payload(rak, name, phone="+201555111000", **extra):
    p = {
        "customer_name": name, "customer_phone": phone,
        "customer_address": "x", "delivery_method": "pickup", "payment_method": "cash",
        "item": {"product_id": rak["id"],
                 "config": {"length": "60", "level": "2", "type": "B", "finishing": "Natural"},
                 "quantity": 1},
    }
    p.update(extra)
    return p


def _register_customer(username_suffix, phone_suffix):
    s = requests.Session()
    r = s.post(f"{API}/customer/register", json={
        "username": f"TEST{UNIQUE}{username_suffix}",
        "phone": f"+2015551{phone_suffix}",
        "password": "pass1234",
        "email": f"{username_suffix}@test.example",
    })
    assert r.status_code == 200, r.text
    return s, r.json()


# ---------------------- Customer accounts ----------------------
class TestCustomerAccount:
    def test_register_login_logout(self, admin):
        # register
        s, c = _register_customer("A", "10001")
        assert c["username"].startswith("TEST")
        assert c["phone"].startswith("+")
        assert c.get("referral_code")
        assert "password_hash" not in c

        # me
        me = s.get(f"{API}/customer/me")
        assert me.status_code == 200
        assert me.json()["username"] == c["username"]

        # duplicate phone rejected
        r = requests.post(f"{API}/customer/register", json={
            "username": c["username"] + "X", "phone": c["phone"], "password": "pass1234",
        })
        assert r.status_code == 400

        # logout
        r = s.post(f"{API}/customer/logout")
        assert r.status_code == 200
        r = s.get(f"{API}/customer/me")
        assert r.status_code in (401, 403)

        # login via username
        r = s.post(f"{API}/customer/login", json={"identifier": c["username"], "password": "pass1234"})
        assert r.status_code == 200
        # login via phone
        r = s.post(f"{API}/customer/login", json={"identifier": c["phone"], "password": "pass1234"})
        assert r.status_code == 200
        # wrong password
        r = requests.post(f"{API}/customer/login", json={"identifier": c["username"], "password": "wrong"})
        assert r.status_code == 401

        # cleanup
        admin.delete(f"{API}/admin/customers/{c['id']}") if False else None  # no admin delete cust endpoint verified

    def test_guest_checkout_still_works(self, rak):
        r = requests.post(f"{API}/orders", json=_mk_order_payload(rak, "TEST_Guest"))
        assert r.status_code == 200, r.text
        o = r.json()
        assert o.get("customer_id") in (None, "")
        # cleanup via admin later in zzz cleanup

    def test_logged_in_order_attaches_customer(self, admin, rak):
        s, c = _register_customer("B", "10002")
        r = s.post(f"{API}/orders", json=_mk_order_payload(rak, "TEST_LoggedIn"))
        assert r.status_code == 200, r.text
        o = r.json()
        assert o.get("customer_id") == c["id"]
        assert o.get("customer_username") == c["username"]

        # customer sees own history
        h = s.get(f"{API}/customer/orders")
        assert h.status_code == 200
        assert any(x.get("id") == o["id"] for x in h.json())


# ---------------------- Delete order ----------------------
class TestDeleteOrder:
    def test_delete_unpaid_order_succeeds(self, admin, rak):
        r = requests.post(f"{API}/orders", json=_mk_order_payload(rak, "TEST_DelUnpaid"))
        oid_ = r.json()["id"]
        r = admin.delete(f"{API}/admin/orders/{oid_}")
        assert r.status_code == 200
        assert admin.get(f"{API}/admin/orders/{oid_}").status_code == 404

    def test_delete_paid_order_reverses_revenue(self, admin, rak):
        r = requests.post(f"{API}/orders", json=_mk_order_payload(rak, "TEST_DelPaid"))
        oid_ = r.json()["id"]
        admin.patch(f"{API}/admin/orders/{oid_}", json={"payment_status": "lunas"})
        txns = admin.get(f"{API}/admin/finance/transactions?type=order_revenue").json()
        assert any(t.get("related_order_id") == oid_ for t in txns)

        # create a manual finance transaction that must survive
        mtx = admin.post(f"{API}/admin/finance/transactions", json={
            "type": "expense", "category": "Operasional", "amount": 12.34,
            "currency": "EGP", "description": f"TEST_manual_{UNIQUE}",
        })
        assert mtx.status_code == 200

        # delete order
        assert admin.delete(f"{API}/admin/orders/{oid_}").status_code == 200
        # revenue removed
        txns2 = admin.get(f"{API}/admin/finance/transactions?type=order_revenue").json()
        assert not any(t.get("related_order_id") == oid_ for t in txns2)
        # manual survived
        all_txns = admin.get(f"{API}/admin/finance/transactions").json()
        assert any(t.get("description") == f"TEST_manual_{UNIQUE}" for t in all_txns)

    def test_delete_nonexistent_returns_404(self, admin):
        r = admin.delete(f"{API}/admin/orders/000000000000000000000000")
        assert r.status_code == 404

    def test_delete_already_deleted_returns_404(self, admin, rak):
        r = requests.post(f"{API}/orders", json=_mk_order_payload(rak, "TEST_DelTwice"))
        oid_ = r.json()["id"]
        assert admin.delete(f"{API}/admin/orders/{oid_}").status_code == 200
        assert admin.delete(f"{API}/admin/orders/{oid_}").status_code == 404

    def test_sub_admin_without_delete_data_403(self, admin, rak):
        email = f"v4_nodel_{int(time.time())}@test.example"
        pr = admin.post(f"{API}/admin/admins", json={
            "name": "TEST_NoDel", "email": email, "password": "pass1234", "role": "employee",
            "permissions": {"manage_orders": True, "modify_products": False,
                            "manage_settings": False, "access_finance": False,
                            "delete_data": False, "manage_admins": False},
        })
        assert pr.status_code == 200, pr.text
        sub_id = pr.json()["id"]
        try:
            s = requests.Session()
            assert s.post(f"{API}/auth/login", json={"email": email, "password": "pass1234"}).status_code == 200
            ro = requests.post(f"{API}/orders", json=_mk_order_payload(rak, "TEST_SubDel"))
            oid_ = ro.json()["id"]
            r = s.delete(f"{API}/admin/orders/{oid_}")
            assert r.status_code == 403
            admin.delete(f"{API}/admin/orders/{oid_}")
        finally:
            admin.delete(f"{API}/admin/admins/{sub_id}")


# ---------------------- Referral ----------------------
class TestReferral:
    def test_customer_has_auto_referral_code(self):
        s, c = _register_customer("Ref1", "10010")
        pts = s.get(f"{API}/customer/points").json()
        assert pts["referral_code"] == c["referral_code"]
        assert pts["referral"] is not None
        assert pts["referral"]["status"] == "active"

    def test_self_referral_blocked(self, rak):
        s, c = _register_customer("Ref2", "10011")
        # validate endpoint
        v = s.post(f"{API}/referral/validate", json={"code": c["referral_code"], "subtotal": 1000}).json()
        assert v["valid"] is False
        # order attempt with self referral
        r = s.post(f"{API}/orders", json=_mk_order_payload(rak, "TEST_SelfRef",
                                                          referral_code=c["referral_code"]))
        assert r.status_code == 400

    def test_referral_requires_login(self, rak):
        # create a referring customer
        s, c = _register_customer("Ref3", "10012")
        # guest tries to use referral
        r = requests.post(f"{API}/orders", json=_mk_order_payload(rak, "TEST_GuestRef",
                                                                 referral_code=c["referral_code"]))
        assert r.status_code == 401

    def test_referral_applied_and_snapshot(self, admin, rak):
        # customer owner
        s_owner, owner = _register_customer("RefOwn", "10013")
        # buyer
        s_buyer, buyer = _register_customer("RefBuy", "10014")

        r = s_buyer.post(f"{API}/orders", json=_mk_order_payload(rak, "TEST_RefApply",
                                                                referral_code=owner["referral_code"]))
        assert r.status_code == 200, r.text
        o = r.json()
        assert o.get("referral") is not None
        assert o["referral"]["code"] == owner["referral_code"]
        assert o["referral"]["owner_id"] == owner["id"]
        assert o.get("referral_discount_le") > 0
        assert o.get("discount_le", 0) == 0  # promo discount empty when referral applied
        pytest.v4_ref_order_id = o["id"]
        pytest.v4_ref_owner_id = owner["id"]
        pytest.v4_ref_owner_s = s_owner
        pytest.v4_ref_code = owner["referral_code"]

    def test_referral_and_discount_mutually_exclusive(self, admin, rak):
        # create a discount
        code = f"{UNIQUE}MX"
        admin.post(f"{API}/admin/discounts", json={
            "code": code, "name": "mx", "percentage": 10, "status": "active",
        })
        s_owner, owner = _register_customer("RefOwn2", "10015")
        s_buyer, buyer = _register_customer("RefBuy2", "10016")
        r = s_buyer.post(f"{API}/orders", json=_mk_order_payload(
            rak, "TEST_Both", referral_code=owner["referral_code"], discount_code=code))
        # backend policy: referral takes priority; discount ignored
        assert r.status_code == 200, r.text
        o = r.json()
        assert o.get("referral") is not None
        # promo discount fields should be empty/0 when referral wins
        assert o.get("discount_code") in (None, "")
        assert o.get("discount_le", 0) == 0


# ---------------------- Referral points ----------------------
class TestReferralPoints:
    def test_points_awarded_only_when_lunas_and_idempotent(self, admin):
        assert hasattr(pytest, "v4_ref_order_id"), "referral order not created"
        oid_ = pytest.v4_ref_order_id
        s_owner = pytest.v4_ref_owner_s

        # not paid yet -> no points
        pts0 = s_owner.get(f"{API}/customer/points").json()
        assert pts0["available"] == 0

        # mark lunas -> award
        assert admin.patch(f"{API}/admin/orders/{oid_}", json={"payment_status": "lunas"}).status_code == 200
        pts1 = s_owner.get(f"{API}/customer/points").json()
        assert pts1["available"] > 0, pts1
        awarded = pts1["available"]

        # idempotent: patch to lunas again
        admin.patch(f"{API}/admin/orders/{oid_}", json={"payment_status": "lunas"})
        pts2 = s_owner.get(f"{API}/customer/points").json()
        assert pts2["available"] == awarded

    def test_points_reversed_on_delete(self, admin):
        oid_ = pytest.v4_ref_order_id
        s_owner = pytest.v4_ref_owner_s
        before = s_owner.get(f"{API}/customer/points").json()["available"]
        assert before > 0
        assert admin.delete(f"{API}/admin/orders/{oid_}").status_code == 200
        after = s_owner.get(f"{API}/customer/points").json()["available"]
        assert after == 0, f"points not reversed: {after}"

    def test_disabling_referral_code_does_not_erase_earned_points(self, admin, rak):
        # setup: owner + buyer, order paid to earn points
        s_owner, owner = _register_customer("RefKeep", "10020")
        s_buyer, buyer = _register_customer("RefBuyK", "10021")
        r = s_buyer.post(f"{API}/orders", json=_mk_order_payload(
            rak, "TEST_RefKeep", referral_code=owner["referral_code"]))
        oid_ = r.json()["id"]
        admin.patch(f"{API}/admin/orders/{oid_}", json={"payment_status": "lunas"})
        earned = s_owner.get(f"{API}/customer/points").json()["available"]
        assert earned > 0
        # find referral doc for owner
        refs = admin.get(f"{API}/admin/referrals").json()
        my_ref = next(r for r in refs if r["code"] == owner["referral_code"])
        admin.put(f"{API}/admin/referrals/{my_ref['id']}", json={"status": "disabled"})
        # earned points intact
        after = s_owner.get(f"{API}/customer/points").json()["available"]
        assert after == earned
        # cleanup
        admin.delete(f"{API}/admin/orders/{oid_}")


# ---------------------- Points redemption ----------------------
class TestPointsRedemption:
    def test_redeem_cap_at_max_pct_and_no_negative(self, admin, rak):
        # create owner + buyer; buyer earns first via a referral-paid order
        s_owner, owner = _register_customer("RedOwn", "10030")
        s_buyer, buyer = _register_customer("RedBuy", "10031")
        # Buyer places referral order that pays big -> owner earns points
        # But we need buyer to have points. Simplest: manually put points via admin? no such endpoint.
        # Instead have buyer refer owner? Actually points go to referral OWNER.
        # For redemption we need buyer to have their own points. Have owner be buyer of a second referral.
        # Register another 3rd party whose referral code we use.
        s3, third = _register_customer("RedThird", "10032")
        # buyer uses `third` referral: NO. That gives points to `third`, not to buyer.
        # We need to give BUYER points. Use s_buyer as referral owner in another purchase.
        s_other, other = _register_customer("RedOther", "10033")
        r = s_other.post(f"{API}/orders", json=_mk_order_payload(
            rak, "TEST_GivePts", referral_code=buyer["referral_code"]))
        oid_ = r.json()["id"]
        admin.patch(f"{API}/admin/orders/{oid_}", json={"payment_status": "lunas"})
        pts = s_buyer.get(f"{API}/customer/points").json()["available"]
        assert pts > 0

        # Now buyer redeems points at checkout
        subtotal_expected = 565  # 60cm/2lvl/B/Natural
        max_pct = 50
        max_redeem = subtotal_expected * max_pct / 100.0

        # attempt to redeem MORE than cap
        r2 = s_buyer.post(f"{API}/orders", json=_mk_order_payload(
            rak, "TEST_RedeemCap", redeem_points=99999))
        assert r2.status_code == 200, r2.text
        o = r2.json()
        assert o.get("points_redeemed_le") <= max_redeem + 0.01, o
        assert o["total_le"] >= 0

        # verify buyer's balance decreased by exactly that amount
        pts_after = s_buyer.get(f"{API}/customer/points").json()["available"]
        assert abs((pts - o["points_redeemed_le"]) - pts_after) < 0.01, (pts, o["points_redeemed_le"], pts_after)

        # cleanup
        admin.delete(f"{API}/admin/orders/{o['id']}")
        admin.delete(f"{API}/admin/orders/{oid_}")


# ---------------------- Finance ----------------------
class TestFinanceCharts:
    def test_monthly_endpoint_returns_12_months(self, admin):
        r = admin.get(f"{API}/admin/finance/monthly?currency=EGP")
        assert r.status_code == 200
        d = r.json()
        assert d["currency"] == "EGP"
        assert isinstance(d["months"], list) and len(d["months"]) == 12
        for m in d["months"]:
            assert "revenue" in m and "cost" in m and "profit" in m
            assert m["profit"] == round(m["revenue"] - m["cost"], 6) or abs(m["profit"] - (m["revenue"] - m["cost"])) < 0.01

    def test_monthly_reflects_new_paid_order(self, admin, rak):
        # baseline
        before = admin.get(f"{API}/admin/finance/monthly?currency=EGP").json()
        # create + pay an order
        r = requests.post(f"{API}/orders", json=_mk_order_payload(rak, "TEST_MonthRev"))
        oid_ = r.json()["id"]
        admin.patch(f"{API}/admin/orders/{oid_}", json={"payment_status": "lunas"})
        after = admin.get(f"{API}/admin/finance/monthly?currency=EGP").json()
        # some month revenue should have increased
        b_sum = sum(m["revenue"] for m in before["months"])
        a_sum = sum(m["revenue"] for m in after["months"])
        assert a_sum > b_sum
        admin.delete(f"{API}/admin/orders/{oid_}")


# ---------------------- Customer isolation ----------------------
class TestCustomerIsolation:
    def test_other_customer_cannot_read_via_customer_orders(self, admin, rak):
        s1, c1 = _register_customer("IsoA", "10040")
        s2, c2 = _register_customer("IsoB", "10041")
        # c1 creates an order
        r = s1.post(f"{API}/orders", json=_mk_order_payload(rak, "TEST_IsoOrder"))
        oid_ = r.json()["id"]
        # c2 lists own orders -> should NOT include c1's order
        h2 = s2.get(f"{API}/customer/orders").json()
        assert not any(o.get("id") == oid_ for o in h2)
        # note: GET /api/orders/{id} is public by design (used for order lookup by number/link)
        admin.delete(f"{API}/admin/orders/{oid_}")


# ---------------------- Cleanup ----------------------
def test_zzz_cleanup():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if r.status_code != 200:
        return
    # delete stray TEST_ orders
    orders = s.get(f"{API}/admin/orders").json()
    for o in orders:
        if o.get("customer_name", "").startswith("TEST_"):
            s.delete(f"{API}/admin/orders/{o['id']}")
    # delete TEST_ discount codes
    discs = s.get(f"{API}/admin/discounts").json()
    for d in discs:
        if d.get("code", "").startswith("V4_") or d.get("code", "").startswith("TEST"):
            s.delete(f"{API}/admin/discounts/{d['id']}")
    # delete manual test finance txns
    all_txns = s.get(f"{API}/admin/finance/transactions").json()
    for t in all_txns:
        if "TEST_manual_" in (t.get("description") or ""):
            s.delete(f"{API}/admin/finance/transactions/{t['id']}")
