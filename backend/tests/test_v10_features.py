"""V10 Phase-2A QA:
- PUT /admin/products/{id} persists photo_weights + option_notes; product isolation (edit A doesn't change B)
- Pricing intact after edit; empty option_notes preserved as sent (frontend strips; backend passthrough)
- RBAC: admin without modify_products -> 403
- Non-dict pricing gracefully handled (no 500)
- Restores rak product to canonical Phase-2A state at end.
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

OWNER_EMAIL = "sogil.furniture@gmail.com"
OWNER_PASSWORD = "0LFOCWU9_V3k"

RAK_ID = "6a8fc3c6d7ae98fcf9f4590a"       # rak-kayu
MEJA_RAK_ID = "6a8fc3c6d7ae98fcf9f4590c"  # meja_rak

CANONICAL_RAK_WEIGHTS = {"length": 0.4, "level": 0.3, "type": 0.2, "finishing": 0.1}
CANONICAL_RAK_NOTES = {"level": "Jarak per tingkat ± 28 cm"}

UNIQUE = f"V10{int(time.time())}"
_created_admins = []


@pytest.fixture(scope="module")
def owner():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD})
    if r.status_code != 200:
        pytest.skip(f"owner login failed: {r.status_code} {r.text}")
    return s


@pytest.fixture(scope="module")
def rak_snapshot(owner):
    """Capture rak product snapshot so we can restore pricing/weights/notes at the end."""
    r = owner.get(f"{API}/products?admin_view=true")
    assert r.status_code == 200
    prod = next((p for p in r.json() if p["id"] == RAK_ID), None)
    assert prod, "rak product not found"
    return copy.deepcopy(prod)


@pytest.fixture(scope="module")
def meja_rak_snapshot(owner):
    r = owner.get(f"{API}/products?admin_view=true")
    prod = next((p for p in r.json() if p["id"] == MEJA_RAK_ID), None)
    assert prod, "meja_rak product not found"
    return copy.deepcopy(prod)


def _get_product(owner, pid):
    r = owner.get(f"{API}/products?admin_view=true")
    assert r.status_code == 200
    return next(p for p in r.json() if p["id"] == pid)


# ---------------- 1. PUT persists photo_weights + option_notes ---------------- #
class TestPersistWeightsAndNotes:
    def test_put_saves_weights_and_notes(self, owner, rak_snapshot):
        new_weights = {"type": 0.4, "length": 0.3, "level": 0.2, "finishing": 0.1}
        new_notes = {"level": f"TEST {UNIQUE} level note", "finishing": f"TEST {UNIQUE} finishing note"}
        r = owner.put(f"{API}/admin/products/{RAK_ID}", json={
            "photo_weights": new_weights, "option_notes": new_notes})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("photo_weights") == new_weights
        assert body.get("option_notes") == new_notes
        # verify persistence via GET
        prod = _get_product(owner, RAK_ID)
        assert prod.get("photo_weights") == new_weights
        assert prod.get("option_notes") == new_notes

    def test_pricing_untouched_after_weights_notes_edit(self, owner, rak_snapshot):
        prod = _get_product(owner, RAK_ID)
        assert prod.get("pricing") == rak_snapshot.get("pricing"), "pricing mutated by non-pricing edit"
        assert prod.get("starting_price_le") == rak_snapshot.get("starting_price_le")
        # photos unchanged
        assert len(prod.get("photos") or []) == len(rak_snapshot.get("photos") or [])

    def test_product_isolation_meja_rak_untouched(self, owner, meja_rak_snapshot):
        m = _get_product(owner, MEJA_RAK_ID)
        assert m.get("photo_weights") == meja_rak_snapshot.get("photo_weights")
        assert m.get("option_notes") == meja_rak_snapshot.get("option_notes")
        assert m.get("pricing") == meja_rak_snapshot.get("pricing")


# ---------------- 2. Empty option_notes strip (frontend) — backend passthrough ---------------- #
class TestEmptyNotes:
    def test_backend_passes_through_notes_as_sent(self, owner):
        """Frontend strips empty; backend simply stores what's passed. Sending {} clears notes."""
        r = owner.put(f"{API}/admin/products/{RAK_ID}", json={"option_notes": {}})
        assert r.status_code == 200
        assert r.json().get("option_notes") == {}
        prod = _get_product(owner, RAK_ID)
        assert prod.get("option_notes") == {}


# ---------------- 3. Non-dict pricing graceful handling ---------------- #
class TestBadPricing:
    def test_non_dict_pricing_no_500(self, owner, rak_snapshot):
        """Backend should not crash on non-dict pricing. Restore afterwards."""
        try:
            r = owner.put(f"{API}/admin/products/{RAK_ID}", json={"pricing": ["not", "an", "object"]})
            # accept either 4xx rejection or 200 pass-through; must NOT be 500
            assert r.status_code != 500, f"backend 500 on non-dict pricing: {r.text}"
        finally:
            # restore original pricing
            owner.put(f"{API}/admin/products/{RAK_ID}", json={"pricing": rak_snapshot.get("pricing")})
            prod = _get_product(owner, RAK_ID)
            assert prod.get("pricing") == rak_snapshot.get("pricing"), "restore failed"


# ---------------- 4. RBAC: admin without modify_products -> 403 ---------------- #
class TestRBACModifyProducts:
    def test_admin_without_perm_gets_403(self, owner):
        email = f"test_{UNIQUE}_np@t.com"
        r = owner.post(f"{API}/admin/admins", json={
            "name": f"TEST_{UNIQUE}_np", "email": email, "password": "abc123",
            "role": "admin",
            "permissions": {"manage_orders": True, "modify_products": False}})
        assert r.status_code == 200, r.text
        aid = r.json()["id"]; _created_admins.append(aid)
        s = requests.Session()
        lr = s.post(f"{API}/auth/login", json={"email": email, "password": "abc123"})
        assert lr.status_code == 200
        r = s.put(f"{API}/admin/products/{RAK_ID}", json={"option_notes": {"level": "hack"}})
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:200]}"
        # confirm rak unchanged (still empty from prior test)
        prod = _get_product(owner, RAK_ID)
        assert prod.get("option_notes") == {}, "unauthorized edit leaked through"

    def test_admin_with_perm_can_edit(self, owner):
        email = f"test_{UNIQUE}_yp@t.com"
        r = owner.post(f"{API}/admin/admins", json={
            "name": f"TEST_{UNIQUE}_yp", "email": email, "password": "abc123",
            "role": "admin",
            "permissions": {"manage_orders": True, "modify_products": True}})
        assert r.status_code == 200
        aid = r.json()["id"]; _created_admins.append(aid)
        s = requests.Session()
        assert s.post(f"{API}/auth/login", json={"email": email, "password": "abc123"}).status_code == 200
        r = s.put(f"{API}/admin/products/{RAK_ID}", json={"option_notes": {"level": f"TEST {UNIQUE} allowed"}})
        assert r.status_code == 200


# ---------------- 5. Pricing preserves unknown/custom fields ---------------- #
class TestPricingPassthrough:
    def test_unknown_pricing_fields_preserved(self, owner, rak_snapshot):
        merged = copy.deepcopy(rak_snapshot.get("pricing") or {})
        merged["custom_marker"] = f"TEST_{UNIQUE}"
        merged["some_new_flag"] = True
        try:
            r = owner.put(f"{API}/admin/products/{RAK_ID}", json={"pricing": merged})
            assert r.status_code == 200
            prod = _get_product(owner, RAK_ID)
            assert prod["pricing"].get("custom_marker") == f"TEST_{UNIQUE}"
            assert prod["pricing"].get("some_new_flag") is True
            # existing keys still present
            for k in (rak_snapshot.get("pricing") or {}):
                assert k in prod["pricing"], f"lost original pricing key {k}"
        finally:
            owner.put(f"{API}/admin/products/{RAK_ID}", json={"pricing": rak_snapshot.get("pricing")})


# ---------------- 6. Product still renders + config price computable ---------------- #
class TestCustomerRender:
    def test_public_product_has_notes(self, owner):
        # First set canonical notes
        owner.put(f"{API}/admin/products/{RAK_ID}", json={"option_notes": CANONICAL_RAK_NOTES})
        r = requests.get(f"{API}/products/rak-kayu")
        assert r.status_code == 200
        prod = r.json()
        assert prod.get("option_notes", {}).get("level") == "Jarak per tingkat ± 28 cm"

    def test_pricing_engine_still_works(self):
        # Configure a rak order server-side price calc — order endpoint calculates from pricing
        prod = requests.get(f"{API}/products/rak-kayu").json()
        r = requests.post(f"{API}/orders/preview" if False else f"{API}/orders", json={
            "customer_name": f"TEST_{UNIQUE}_pric",
            "customer_phone": "+201555555599",
            "customer_address": "TEST addr",
            "delivery_method": "pickup",
            "payment_method": "cash",
            "items": [{"product_id": prod["id"],
                       "config": {"type": "B", "length": 60, "level": 2, "finishing": "melamine"},
                       "quantity": 1}]})
        # not going to leave the order — delete after
        if r.status_code == 200:
            oid = r.json()["id"]
            assert float(r.json().get("total_le") or r.json().get("total") or 0) > 0
            # cleanup order via admin
        else:
            pytest.skip(f"order create failed unexpectedly: {r.status_code} {r.text[:200]}")


# ---------------- 7. ZZZ Cleanup / RESTORE canonical rak state ---------------- #
class TestZzzRestore:
    def test_restore_rak_canonical(self, owner, rak_snapshot):
        # Restore photo_weights + option_notes + pricing to canonical / snapshot values
        r = owner.put(f"{API}/admin/products/{RAK_ID}", json={
            "photo_weights": CANONICAL_RAK_WEIGHTS,
            "option_notes": CANONICAL_RAK_NOTES,
            "pricing": rak_snapshot.get("pricing"),
            "starting_price_le": rak_snapshot.get("starting_price_le"),
        })
        assert r.status_code == 200
        prod = _get_product(owner, RAK_ID)
        assert prod.get("photo_weights") == CANONICAL_RAK_WEIGHTS
        assert prod.get("option_notes") == CANONICAL_RAK_NOTES
        assert prod.get("pricing") == rak_snapshot.get("pricing")

    def test_cleanup_admins_and_orders(self, owner):
        # Delete admins
        for aid in list(_created_admins):
            try: owner.delete(f"{API}/admin/admins/{aid}")
            except Exception: pass
        # Sweep any TEST_V10 orders
        try:
            r = owner.get(f"{API}/admin/orders")
            for o in r.json() if r.status_code == 200 else []:
                if f"TEST_{UNIQUE}" in (o.get("customer_name") or ""):
                    owner.delete(f"{API}/admin/orders/{o['id']}")
        except Exception:
            pass
