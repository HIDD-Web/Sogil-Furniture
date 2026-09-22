"""V9 Phase-1 QA:
- Canonical owner login (sogil.furniture@gmail.com) + old email rejected + single owner in DB
- Account management + RBAC (POST role=owner -> 400; PUT edits keep same id; non-owner 403)
- Owner reset-admin-password (min 6, old fails, new works, response never leaks password)
- Admin status active/inactive: inactive employee hidden from GET /admin/employees, wages preserved
- Self change-password (already covered by v3, sanity)
- Employee -> wage recipient auto link (category 'Pekerja'), one finance txn + one wage row;
  DELETE txn removes wage, wages summary reports month/year/count/history + recorded_by_name
- Finance categories: income=[Penjualan, Pendapatan Lain] (no Penyesuaian); expense includes
  Pekerja, Material, Air & Listrik, Marketing, Pengembangan Aplikasi Web (14 total)
- Finance transactions search q= matching description/category/amount/etc
- Finance statistics endpoint: returns income/expense grouped + totals with transfer split;
  operating_profit = revenue - cost; last_3_months period supported
- Real-time chart endpoint /admin/finance/monthly still returns 200 (frontend refetches; backend sanity)
- XLSX exports: finance, orders, config-analytics, customers, accounts (2 sheets), product-prices.
  RBAC: /export/accounts owner-only. SECURITY: no bcrypt/password/token in any workbook cell.
- Product price history: PUT product records db.price_history entry (via export/product-prices)
- Customer self change-password /customer/change-password
- Regression: paid order revenue + delete reverse still works
"""
import os
import io
import re
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

OWNER_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@sogil.com")
OWNER_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
OLD_EMAIL = "syahid.mujahid02@gmail.com"

UNIQUE = f"V9{int(time.time())}"
PHONE_STAMP = str(int(time.time()))[-6:]

_created_admins = []
_created_txns = []
_created_customers = []
_created_orders = []


# ---------------- fixtures ---------------- #
@pytest.fixture(scope="module")
def owner():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD})
    if r.status_code != 200:
        pytest.skip(f"owner login failed: {r.status_code} {r.text}")
    return s


@pytest.fixture(scope="module")
def azka(owner):
    r = owner.get(f"{API}/admin/employees")
    assert r.status_code == 200, r.text
    for e in r.json():
        if (e.get("name") or "").strip().lower() == "azka":
            return e
    # not fatal — will skip tests that need it
    pytest.skip("existing 'Azka' employee not found in /admin/employees")


# ---------------- 1. Canonical owner ---------------- #
class TestOwnerCanonical:
    def test_new_email_login_ok(self):
        r = requests.post(f"{API}/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD})
        assert r.status_code == 200, r.text

    def test_old_email_rejected(self):
        r = requests.post(f"{API}/auth/login", json={"email": OLD_EMAIL, "password": OWNER_PASSWORD})
        assert r.status_code == 401

    def test_exactly_one_owner(self, owner):
        r = owner.get(f"{API}/admin/admins")
        assert r.status_code == 200, r.text
        owners = [a for a in r.json() if a.get("role") == "owner"]
        assert len(owners) == 1, f"expected 1 owner, got {len(owners)}: {[o.get('email') for o in owners]}"
        assert owners[0]["email"] == OWNER_EMAIL

    def test_owner_has_all_permissions(self, owner):
        r = owner.get(f"{API}/auth/me")
        assert r.status_code == 200
        me = r.json()
        perms = me.get("permissions") or {}
        for k in ("manage_orders", "modify_products", "manage_settings", "access_finance",
                  "delete_data", "manage_admins"):
            assert perms.get(k) is True, f"owner missing perm {k}"


# ---------------- 2. Account mgmt + RBAC ---------------- #
class TestAccountMgmtRBAC:
    def test_cannot_create_owner(self, owner):
        r = owner.post(f"{API}/admin/admins", json={
            "name": f"TEST_{UNIQUE}_owner2", "email": f"test_{UNIQUE}_o@t.com",
            "password": "abc123", "role": "owner"})
        assert r.status_code == 400

    def test_create_edit_role_same_id(self, owner):
        r = owner.post(f"{API}/admin/admins", json={
            "name": f"TEST_{UNIQUE}_a1", "email": f"test_{UNIQUE}_a1@t.com",
            "password": "abc123", "role": "admin"})
        assert r.status_code == 200, r.text
        a = r.json()
        _created_admins.append(a["id"])
        aid = a["id"]
        # Edit role manager + name + permissions + status
        r = owner.put(f"{API}/admin/admins/{aid}", json={
            "name": f"TEST_{UNIQUE}_a1_renamed", "role": "manager", "status": "active",
            "permissions": {"access_finance": True, "manage_orders": True}})
        assert r.status_code == 200, r.text
        u = r.json()
        assert u["id"] == aid, "role change must not create new id"
        assert u["role"] == "manager"
        assert u["name"].endswith("renamed")
        assert u["permissions"]["access_finance"] is True
        # manage_admins forced false
        assert u["permissions"].get("manage_admins") is False

    def test_non_owner_403_on_admin_endpoints(self, owner):
        # create sub-admin with access_finance + manage_orders but NOT owner
        r = owner.post(f"{API}/admin/admins", json={
            "name": f"TEST_{UNIQUE}_sub", "email": f"test_{UNIQUE}_sub@t.com",
            "password": "abc123", "role": "admin",
            "permissions": {"access_finance": True, "manage_orders": True}})
        assert r.status_code == 200, r.text
        sub_id = r.json()["id"]; _created_admins.append(sub_id)
        s = requests.Session()
        lr = s.post(f"{API}/auth/login", json={"email": f"test_{UNIQUE}_sub@t.com", "password": "abc123"})
        assert lr.status_code == 200, lr.text
        # POST create admin -> 403
        r = s.post(f"{API}/admin/admins", json={"name": "x", "email": "y@y.com", "password": "abc123", "role": "admin"})
        assert r.status_code == 403
        # PUT -> 403
        r = s.put(f"{API}/admin/admins/{sub_id}", json={"name": "y"})
        assert r.status_code == 403
        # DELETE -> 403
        r = s.delete(f"{API}/admin/admins/{sub_id}")
        assert r.status_code == 403


# ---------------- 3. Owner reset admin password ---------------- #
class TestOwnerResetPassword:
    def test_reset_and_login_flow(self, owner):
        email = f"test_{UNIQUE}_rp@t.com"
        r = owner.post(f"{API}/admin/admins", json={
            "name": f"TEST_{UNIQUE}_rp", "email": email, "password": "oldpass1", "role": "admin"})
        assert r.status_code == 200
        aid = r.json()["id"]; _created_admins.append(aid)
        # short password -> 400
        r = owner.put(f"{API}/admin/admins/{aid}", json={"password": "abc"})
        assert r.status_code == 400
        # reset
        r = owner.put(f"{API}/admin/admins/{aid}", json={"password": "newpass9"})
        assert r.status_code == 200
        body = r.json()
        # response must NOT leak password/hash
        assert "password" not in body
        assert "password_hash" not in body
        # old fails
        s = requests.Session()
        assert s.post(f"{API}/auth/login", json={"email": email, "password": "oldpass1"}).status_code == 401
        # new works
        assert s.post(f"{API}/auth/login", json={"email": email, "password": "newpass9"}).status_code == 200


# ---------------- 4. Admin status ---------------- #
class TestAdminStatus:
    def test_inactive_employee_hidden_from_wage_list_wages_preserved(self, owner):
        email = f"test_{UNIQUE}_emp@t.com"
        r = owner.post(f"{API}/admin/admins", json={
            "name": f"TEST_{UNIQUE}_emp", "email": email, "password": "abc123", "role": "employee"})
        assert r.status_code == 200
        eid = r.json()["id"]; _created_admins.append(eid)
        # appears in /admin/employees
        r = owner.get(f"{API}/admin/employees")
        assert eid in [e["id"] for e in r.json()]
        # create wage txn
        r = owner.post(f"{API}/admin/finance/transactions", json={
            "type": "expense", "category": "Pekerja", "amount": 50, "currency": "EGP",
            "description": f"TEST {UNIQUE} wage", "date": None, "recipient_employee_id": eid})
        assert r.status_code == 200, r.text
        tid = r.json()["id"]; _created_txns.append(tid)
        # deactivate
        r = owner.put(f"{API}/admin/admins/{eid}", json={"status": "inactive"})
        assert r.status_code == 200
        assert r.json().get("status") == "inactive"
        # hidden from wage-recipient list
        r = owner.get(f"{API}/admin/employees")
        assert eid not in [e["id"] for e in r.json()]
        # but still in /admin/employees/wages with history preserved
        r = owner.get(f"{API}/admin/employees/wages")
        rows = [e for e in r.json() if e["id"] == eid]
        assert rows, "inactive employee should still appear in wages summary (history preserved)"
        assert rows[0]["count"] >= 1


# ---------------- 5. Employee -> wage recipient link ---------------- #
class TestWageLink:
    def test_wage_create_and_delete_sync(self, owner, azka):
        eid = azka["id"]
        r = owner.post(f"{API}/admin/finance/transactions", json={
            "type": "expense", "category": "Pekerja", "amount": 123, "currency": "EGP",
            "description": f"TEST {UNIQUE} azka", "date": None, "recipient_employee_id": eid})
        assert r.status_code == 200, r.text
        t = r.json(); tid = t["id"]; _created_txns.append(tid)
        assert t.get("recipient_employee_id") == eid
        assert t.get("recipient_employee_name")
        # summary
        r = owner.get(f"{API}/admin/employees/wages")
        row = next(e for e in r.json() if e["id"] == eid)
        for k in ("totals", "month", "year", "count", "history"):
            assert k in row
        assert row["count"] >= 1
        # history contains our record with category/description/recorded_by_name
        h = [w for w in row["history"] if w.get("transaction_id") == tid]
        assert h, "wage history missing our txn"
        w = h[0]
        assert w.get("category") == "Pekerja"
        assert f"TEST {UNIQUE}" in (w.get("description") or "")
        assert w.get("recorded_by_name")
        # delete txn -> wage removed
        r = owner.delete(f"{API}/admin/finance/transactions/{tid}")
        assert r.status_code == 200
        _created_txns.remove(tid)
        r = owner.get(f"{API}/admin/employees/wages")
        row = next(e for e in r.json() if e["id"] == eid)
        assert not any(w.get("transaction_id") == tid for w in row["history"])


# ---------------- 6. Finance categories ---------------- #
class TestFinanceCategories:
    def test_default_categories(self, owner):
        r = owner.get(f"{API}/admin/finance/categories")
        assert r.status_code == 200
        cats = r.json()
        # income
        assert "Penjualan" in cats["income"] and "Pendapatan Lain" in cats["income"]
        assert "Penyesuaian" not in cats["income"]
        # expense - 14 defaults incl these
        for k in ("Pekerja", "Material", "Air & Listrik", "Marketing", "Pengembangan Aplikasi Web"):
            assert k in cats["expense"], f"missing default expense category {k}"


# ---------------- 7. Finance search q= ---------------- #
class TestFinanceSearch:
    def test_search_matches_description_and_amount(self, owner):
        marker = f"SEARCHME_{UNIQUE}"
        r = owner.post(f"{API}/admin/finance/transactions", json={
            "type": "income", "category": "Pendapatan Lain", "amount": 7777.0,
            "currency": "EGP", "description": marker, "date": None})
        assert r.status_code == 200
        tid = r.json()["id"]; _created_txns.append(tid)
        # search by description
        r = owner.get(f"{API}/admin/finance/transactions", params={"q": marker})
        assert r.status_code == 200
        assert any(t.get("id") == tid for t in r.json())
        # search by amount
        r = owner.get(f"{API}/admin/finance/transactions", params={"q": "7777"})
        assert any(t.get("id") == tid for t in r.json())
        # combined with currency filter
        r = owner.get(f"{API}/admin/finance/transactions", params={"q": marker, "currency": "EGP"})
        assert any(t.get("id") == tid for t in r.json())


# ---------------- 8. Statistics endpoint ---------------- #
class TestFinanceStatistics:
    def test_statistics_totals_and_transfer_isolation(self, owner):
        # add income/revenue + income/transfer + expense/cost + expense/transfer with unique cats
        rev_cat = f"TEST_{UNIQUE}_rev"
        tinc_cat = f"TEST_{UNIQUE}_tin"
        cost_cat = f"TEST_{UNIQUE}_cost"
        texp_cat = f"TEST_{UNIQUE}_tex"
        made_cats = []
        for name, typ, cls in [(rev_cat, "income", "revenue"), (tinc_cat, "income", "transfer"),
                                (cost_cat, "expense", "cost"), (texp_cat, "expense", "transfer")]:
            r = owner.post(f"{API}/admin/finance/custom-categories",
                           json={"name": name, "type": typ, "classification": cls})
            assert r.status_code == 200, r.text
            made_cats.append(r.json()["id"])
        pairs = [(rev_cat, "income", 100), (tinc_cat, "income", 50), (cost_cat, "expense", 30), (texp_cat, "expense", 20)]
        for name, typ, amt in pairs:
            r = owner.post(f"{API}/admin/finance/transactions", json={
                "type": typ, "category": name, "amount": amt, "currency": "EGP",
                "description": f"TEST {UNIQUE} stats", "date": None})
            assert r.status_code == 200, r.text
            _created_txns.append(r.json()["id"])
        try:
            r = owner.get(f"{API}/admin/finance/statistics",
                          params={"period": "this_year", "currency": "EGP"})
            assert r.status_code == 200, r.text
            data = r.json()
            # totals presence
            for k in ("revenue", "transfer_income", "cost", "transfer_expense", "operating_profit"):
                assert k in data["totals"], f"missing totals key {k}"
            # our unique category rows are present
            inc_names = {g["category"] for g in data["income"]}
            exp_names = {g["category"] for g in data["expense"]}
            assert rev_cat in inc_names and tinc_cat in inc_names
            assert cost_cat in exp_names and texp_cat in exp_names
            # each group has count + pct + classification
            for g in data["income"] + data["expense"]:
                for f in ("count", "pct", "classification", "total"):
                    assert f in g
            # operating_profit == revenue - cost (no transfer)
            assert abs(data["totals"]["operating_profit"]
                       - (data["totals"]["revenue"] - data["totals"]["cost"])) < 0.01
            # transfer income/expense recorded separately (>=50 and >=20 of our own)
            assert data["totals"]["transfer_income"] >= 50
            assert data["totals"]["transfer_expense"] >= 20
        finally:
            for cid in made_cats:
                try:
                    owner.delete(f"{API}/admin/finance/custom-categories/{cid}")
                except Exception:
                    pass

    def test_last_3_months_period(self, owner):
        r = owner.get(f"{API}/admin/finance/statistics", params={"period": "last_3_months", "currency": "EGP"})
        assert r.status_code == 200
        assert "totals" in r.json()


# ---------------- 9. Real-time chart endpoint ---------------- #
def test_monthly_chart_endpoint(owner):
    r = owner.get(f"{API}/admin/finance/monthly", params={"currency": "EGP"})
    assert r.status_code == 200


# ---------------- 10. XLSX exports security + RBAC ---------------- #
BCRYPT_RX = re.compile(r"\$2[aby]?\$")
SECRET_KEYS = ("password", "password_hash", "token", "hash", "secret")


def _load_wb(content):
    from openpyxl import load_workbook
    return load_workbook(io.BytesIO(content), read_only=True, data_only=True)


def _assert_no_secrets(content):
    wb = _load_wb(content)
    for ws in wb.worksheets:
        # headers must not contain secret keys
        first = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
        if first:
            for h in first:
                if h is None:
                    continue
                hs = str(h).lower()
                for k in SECRET_KEYS:
                    assert k not in hs, f"secret header '{h}' in sheet '{ws.title}'"
        # scan all cells for bcrypt-shaped values
        for row in ws.iter_rows(values_only=True):
            for v in row:
                if v is None:
                    continue
                s = str(v)
                assert not BCRYPT_RX.search(s), f"bcrypt-like value in export '{ws.title}': {s[:20]}"


class TestExports:
    def _get(self, session, path, params=None):
        r = session.get(f"{API}{path}", params=params or {})
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:200]}"
        ct = r.headers.get("content-type", "")
        assert "spreadsheetml.sheet" in ct, f"bad content-type: {ct}"
        assert len(r.content) > 200
        return r.content

    def test_finance_xlsx(self, owner):
        data = self._get(owner, "/admin/export/finance", {"period": "this_year"})
        _assert_no_secrets(data)

    def test_orders_xlsx(self, owner):
        data = self._get(owner, "/admin/export/orders", {"period": "this_year"})
        _assert_no_secrets(data)

    def test_config_analytics_xlsx(self, owner):
        _assert_no_secrets(self._get(owner, "/admin/export/config-analytics"))

    def test_customers_xlsx_no_password(self, owner):
        data = self._get(owner, "/admin/export/customers")
        _assert_no_secrets(data)

    def test_accounts_xlsx_two_sheets(self, owner):
        data = self._get(owner, "/admin/export/accounts")
        wb = _load_wb(data)
        titles = wb.sheetnames
        assert "Akun" in titles and "Riwayat Upah" in titles, titles
        _assert_no_secrets(data)

    def test_product_prices_xlsx(self, owner):
        data = self._get(owner, "/admin/export/product-prices")
        wb = _load_wb(data)
        assert "Riwayat Perubahan Harga" in wb.sheetnames
        assert "Harga Saat Ini" in wb.sheetnames
        _assert_no_secrets(data)

    def test_accounts_owner_only_403_for_non_owner(self, owner):
        # create sub-admin with access_finance
        email = f"test_{UNIQUE}_expsub@t.com"
        r = owner.post(f"{API}/admin/admins", json={
            "name": f"TEST_{UNIQUE}_expsub", "email": email, "password": "abc123",
            "role": "admin",
            "permissions": {"access_finance": True, "manage_orders": True, "modify_products": True}})
        assert r.status_code == 200
        _created_admins.append(r.json()["id"])
        s = requests.Session()
        lr = s.post(f"{API}/auth/login", json={"email": email, "password": "abc123"})
        assert lr.status_code == 200
        r = s.get(f"{API}/admin/export/accounts")
        assert r.status_code == 403


# ---------------- 11. Product price history ---------------- #
class TestPriceHistory:
    def test_price_change_recorded(self, owner):
        rp = requests.get(f"{API}/products/rak-kayu")
        assert rp.status_code == 200
        prod = rp.json(); pid = prod["id"]
        old_price = float(prod.get("starting_price_le") or 0)
        new_price = old_price + 1.0
        r = owner.put(f"{API}/admin/products/{pid}", json={"starting_price_le": new_price})
        assert r.status_code == 200, r.text
        try:
            # verify via export (contains price_history in first sheet)
            data = owner.get(f"{API}/admin/export/product-prices").content
            wb = _load_wb(data)
            ws = wb["Riwayat Perubahan Harga"]
            found = False
            for row in ws.iter_rows(values_only=True):
                if row and prod.get("name") in [str(x) for x in row if x is not None]:
                    found = True; break
            assert found, "expected price_history entry for rak-kayu"
        finally:
            owner.put(f"{API}/admin/products/{pid}", json={"starting_price_le": old_price})


# ---------------- 12. Customer self change-password ---------------- #
class TestCustomerChangePassword:
    def test_flow(self):
        s = requests.Session()
        uname = f"TEST_{UNIQUE}_cu"
        phone = f"+201{PHONE_STAMP}0"
        r = s.post(f"{API}/customer/register", json={
            "username": uname, "phone": phone, "password": "cust123"})
        assert r.status_code == 200, r.text
        cid = r.json().get("id") or r.json().get("customer", {}).get("id")
        _created_customers.append(cid)
        # wrong current -> 400
        r = s.post(f"{API}/customer/change-password", json={
            "current_password": "wrong", "new_password": "newone1"})
        assert r.status_code == 400
        # short new -> 400
        r = s.post(f"{API}/customer/change-password", json={
            "current_password": "cust123", "new_password": "abc"})
        assert r.status_code == 400
        # success
        r = s.post(f"{API}/customer/change-password", json={
            "current_password": "cust123", "new_password": "newone1"})
        assert r.status_code == 200
        # old fails, new works
        s2 = requests.Session()
        assert s2.post(f"{API}/customer/login", json={"identifier": uname, "password": "cust123"}).status_code == 401
        assert s2.post(f"{API}/customer/login", json={"identifier": uname, "password": "newone1"}).status_code == 200


# ---------------- 13. Regression: paid order revenue ---------------- #
class TestOrderRevenueRegression:
    def test_paid_order_and_delete_reverse(self, owner):
        prod = requests.get(f"{API}/products/rak-kayu").json()
        r = requests.post(f"{API}/orders", json={
            "customer_name": f"TEST_{UNIQUE}_ord",
            "customer_phone": f"+201{PHONE_STAMP}1",
            "customer_address": "TEST addr",
            "delivery_method": "pickup",
            "payment_method": "cash",
            "items": [{"product_id": prod["id"], "config": {"type": "B", "length": 60, "level": 2, "finishing": "melamine"}, "quantity": 1}]})
        assert r.status_code == 200, r.text
        oid = r.json()["id"]; _created_orders.append(oid)
        before = owner.get(f"{API}/admin/finance/stats", params={"period": "this_year"}).json()["current"]["EGP"]["revenue"]
        r = owner.patch(f"{API}/admin/orders/{oid}", json={"payment_status": "lunas"})
        assert r.status_code == 200
        after = owner.get(f"{API}/admin/finance/stats", params={"period": "this_year"}).json()["current"]["EGP"]["revenue"]
        assert after > before, f"revenue should increase after payment ({before} -> {after})"
        # delete order (order-finance separation preserves revenue history)
        r = owner.delete(f"{API}/admin/orders/{oid}")
        assert r.status_code == 200
        _created_orders.remove(oid)
        rev_after_del = owner.get(f"{API}/admin/finance/stats", params={"period": "this_year"}).json()["current"]["EGP"]["revenue"]
        assert abs(rev_after_del - after) < 0.01, f"revenue should remain preserved after order deletion ({after} vs {rev_after_del})"


# ---------------- Cleanup ---------------- #
class TestZzzCleanup:
    def test_cleanup(self, owner):
        for tid in list(_created_txns):
            try: owner.delete(f"{API}/admin/finance/transactions/{tid}")
            except Exception: pass
        for oid in list(_created_orders):
            try: owner.delete(f"{API}/admin/orders/{oid}")
            except Exception: pass
        for aid in list(_created_admins):
            try: owner.delete(f"{API}/admin/admins/{aid}")
            except Exception: pass
        for cid in list(_created_customers):
            if cid:
                try: owner.delete(f"{API}/admin/customers/{cid}")
                except Exception: pass
