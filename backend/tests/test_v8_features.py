"""V8 QA (targeted maintenance):
- Finance category classification: income/revenue, income/transfer, expense/cost, expense/transfer.
  * revenue counts to Revenue, cost counts to Cost, transfer only moves balance.
  * All txns still affect balances.
- Transfer endpoint /admin/finance/transfer: same-account rejected 400; not counted as revenue/cost.
- Custom category soft-delete: DELETE marks status=inactive; hidden from GET categories; historical
  txns keep their category name + classification.
- Wage tracking: expense txn with 'Upah'/'Wage' category + recipient_employee_id -> stores recipient
  and creates a linked employee_wages record. DELETE finance txn removes linked wage.
- Customer password recovery: /customer/find-username (found/404/invalid, no password leak).
- Owner reset-password: works, <6 rejected, non-owner 403, old pw stops working, new pw works,
  response never contains the password.
- Regression: paid order -> order_revenue counted in Revenue; deleting that order reverses.
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

UNIQUE = f"V8{int(time.time())}"
PHONE_STAMP = str(int(time.time()))[-6:]

_created_customers = []
_created_txns = []
_created_categories = []
_created_admins = []
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
    assert r.status_code == 200, r.text
    return r.json()


def _get_stats(admin, period="this_year"):
    r = admin.get(f"{API}/admin/finance/stats", params={"period": period})
    assert r.status_code == 200, r.text
    return r.json()


def _balances(admin):
    r = admin.get(f"{API}/admin/finance/accounts")
    assert r.status_code == 200
    return r.json()["balances"]


def _create_cat(admin, name, typ, classification):
    r = admin.post(f"{API}/admin/finance/custom-categories",
                   json={"name": name, "type": typ, "classification": classification})
    assert r.status_code == 200, r.text
    doc = r.json()
    _created_categories.append(doc["id"])
    return doc


def _create_txn(admin, typ, category, amount, currency="EGP", **extra):
    payload = {"type": typ, "category": category, "amount": amount, "currency": currency,
               "date": None, "description": f"TEST {UNIQUE}"}
    payload.update(extra)
    r = admin.post(f"{API}/admin/finance/transactions", json=payload)
    assert r.status_code == 200, r.text
    doc = r.json()
    _created_txns.append(doc["id"])
    return doc


# ---------- Classification effect on stats + balance ----------
class TestClassificationEffects:
    def test_income_revenue_increases_revenue_and_balance(self, admin):
        cat = _create_cat(admin, f"TEST_{UNIQUE}_IncRev", "income", "revenue")
        stats_before = _get_stats(admin)
        bal_before = _balances(admin)
        _create_txn(admin, "income", cat["name"], 123.45, "EGP")
        stats_after = _get_stats(admin)
        bal_after = _balances(admin)
        rev_delta = stats_after["current"]["EGP"]["revenue"] - stats_before["current"]["EGP"]["revenue"]
        cost_delta = stats_after["current"]["EGP"]["cost"] - stats_before["current"]["EGP"]["cost"]
        bal_delta = bal_after["EGP"] - bal_before["EGP"]
        assert round(rev_delta, 2) == 123.45
        assert round(cost_delta, 2) == 0.0
        assert round(bal_delta, 2) == 123.45

    def test_income_transfer_only_moves_balance_no_revenue(self, admin):
        cat = _create_cat(admin, f"TEST_{UNIQUE}_IncXfer", "income", "transfer")
        assert cat["classification"] == "transfer"
        stats_before = _get_stats(admin)
        bal_before = _balances(admin)
        txn = _create_txn(admin, "income", cat["name"], 77.0, "EGP")
        assert txn["classification"] == "transfer"
        stats_after = _get_stats(admin)
        bal_after = _balances(admin)
        rev_delta = stats_after["current"]["EGP"]["revenue"] - stats_before["current"]["EGP"]["revenue"]
        cost_delta = stats_after["current"]["EGP"]["cost"] - stats_before["current"]["EGP"]["cost"]
        bal_delta = bal_after["EGP"] - bal_before["EGP"]
        assert round(rev_delta, 2) == 0.0, f"transfer income leaked into revenue: {rev_delta}"
        assert round(cost_delta, 2) == 0.0
        assert round(bal_delta, 2) == 77.0

    def test_expense_cost_increases_cost_and_decreases_balance(self, admin):
        cat = _create_cat(admin, f"TEST_{UNIQUE}_ExpCost", "expense", "cost")
        stats_before = _get_stats(admin)
        bal_before = _balances(admin)
        _create_txn(admin, "expense", cat["name"], 40.0, "EGP")
        stats_after = _get_stats(admin)
        bal_after = _balances(admin)
        cost_delta = stats_after["current"]["EGP"]["cost"] - stats_before["current"]["EGP"]["cost"]
        rev_delta = stats_after["current"]["EGP"]["revenue"] - stats_before["current"]["EGP"]["revenue"]
        bal_delta = bal_after["EGP"] - bal_before["EGP"]
        assert round(cost_delta, 2) == 40.0
        assert round(rev_delta, 2) == 0.0
        assert round(bal_delta, 2) == -40.0

    def test_expense_transfer_no_cost_only_balance(self, admin):
        # e.g. owner withdrawal / prive
        cat = _create_cat(admin, f"TEST_{UNIQUE}_ExpXfer", "expense", "transfer")
        assert cat["classification"] == "transfer"
        stats_before = _get_stats(admin)
        bal_before = _balances(admin)
        txn = _create_txn(admin, "expense", cat["name"], 30.0, "EGP")
        assert txn["classification"] == "transfer"
        stats_after = _get_stats(admin)
        bal_after = _balances(admin)
        cost_delta = stats_after["current"]["EGP"]["cost"] - stats_before["current"]["EGP"]["cost"]
        rev_delta = stats_after["current"]["EGP"]["revenue"] - stats_before["current"]["EGP"]["revenue"]
        bal_delta = bal_after["EGP"] - bal_before["EGP"]
        assert round(cost_delta, 2) == 0.0, f"transfer expense leaked into cost: {cost_delta}"
        assert round(rev_delta, 2) == 0.0
        assert round(bal_delta, 2) == -30.0


# ---------- Transfer endpoint ----------
class TestTransfer:
    def test_transfer_same_account_400(self, admin):
        r = admin.post(f"{API}/admin/finance/transfer", json={
            "from_account": "IDR", "to_account": "IDR",
            "from_amount": 100, "to_amount": 100})
        assert r.status_code == 400

    def test_transfer_moves_balance_not_revenue(self, admin):
        stats_before = _get_stats(admin)
        bal_before = _balances(admin)
        r = admin.post(f"{API}/admin/finance/transfer", json={
            "from_account": "IDR", "to_account": "EGP",
            "from_amount": 3570, "to_amount": 10, "exchange_rate": 357})
        assert r.status_code == 200, r.text
        _created_txns.append(r.json()["id"])
        stats_after = _get_stats(admin)
        bal_after = _balances(admin)
        for cur in ("IDR", "EGP"):
            assert round(stats_after["current"][cur]["revenue"] - stats_before["current"][cur]["revenue"], 2) == 0.0
            assert round(stats_after["current"][cur]["cost"] - stats_before["current"][cur]["cost"], 2) == 0.0
        assert round(bal_after["IDR"] - bal_before["IDR"], 2) == -3570.0
        assert round(bal_after["EGP"] - bal_before["EGP"], 2) == 10.0


# ---------- Soft-delete custom category ----------
class TestCategorySoftDelete:
    def test_soft_delete_hides_from_selectable_but_keeps_txn_history(self, admin):
        cat = _create_cat(admin, f"TEST_{UNIQUE}_SoftDel", "income", "revenue")
        # create a txn using it
        txn = _create_txn(admin, "income", cat["name"], 5.0, "EGP")
        assert txn["classification"] == "revenue"
        # soft delete
        r = admin.delete(f"{API}/admin/finance/custom-categories/{cat['id']}")
        assert r.status_code == 200
        # not in selectable list
        r = admin.get(f"{API}/admin/finance/categories")
        assert r.status_code == 200
        cats = r.json()
        assert cat["name"] not in cats["income"], f"inactive cat still selectable: {cats['income']}"
        # historical txn still has category name + classification
        r = admin.get(f"{API}/admin/finance/transactions", params={"type": "income"})
        assert r.status_code == 200
        found = [t for t in r.json() if t.get("id") == txn["id"]]
        assert found and found[0]["category"] == cat["name"]
        assert found[0]["classification"] == "revenue"

    def test_put_can_reactivate_and_change_classification(self, admin):
        cat = _create_cat(admin, f"TEST_{UNIQUE}_Toggle", "expense", "cost")
        r = admin.put(f"{API}/admin/finance/custom-categories/{cat['id']}",
                      json={"classification": "transfer", "status": "active"})
        assert r.status_code == 200
        assert r.json()["classification"] == "transfer"
        # verify appears in selectable list
        r = admin.get(f"{API}/admin/finance/categories")
        assert cat["name"] in r.json()["expense"]


# ---------- Wage tracking ----------
class TestWageTracking:
    @pytest.fixture(scope="class")
    def employee(self, admin):
        r = admin.get(f"{API}/admin/employees")
        assert r.status_code == 200, r.text
        emps = r.json()
        if not emps:
            pytest.skip("no employee account seeded")
        # prefer 'Azka'
        azka = next((e for e in emps if (e.get("name") or "").lower() == "azka"), emps[0])
        return azka

    def test_wage_expense_creates_linked_wage(self, admin, employee):
        wage_cat = f"TEST_{UNIQUE}_Upah"
        _create_cat(admin, wage_cat, "expense", "cost")
        stats_before = _get_stats(admin)
        wr = admin.get(f"{API}/admin/employees/wages")
        assert wr.status_code == 200
        totals_before = next((e for e in wr.json() if e["id"] == employee["id"]), {"totals": {}})["totals"]
        egp_before = totals_before.get("EGP", 0)
        txn = _create_txn(admin, "expense", wage_cat, 55.0, "EGP",
                          recipient_employee_id=employee["id"])
        assert txn.get("recipient_employee_id") == employee["id"]
        assert txn.get("recipient_employee_name") == employee.get("name")
        # wage summary should reflect
        wr = admin.get(f"{API}/admin/employees/wages")
        emp_row = next(e for e in wr.json() if e["id"] == employee["id"])
        assert round(emp_row["totals"].get("EGP", 0) - egp_before, 2) == 55.0
        history = [h for h in emp_row["history"] if h.get("transaction_id") == txn["id"]]
        assert len(history) == 1
        assert history[0].get("recorded_by_name")  # admin name recorded
        # cost also increased by 55 (classification=cost by default for wage)
        stats_after = _get_stats(admin)
        cost_delta = stats_after["current"]["EGP"]["cost"] - stats_before["current"]["EGP"]["cost"]
        assert round(cost_delta, 2) == 55.0

    def test_delete_wage_txn_removes_linked_wage_no_orphan(self, admin, employee):
        wage_cat = f"TEST_{UNIQUE}_Upah2"
        _create_cat(admin, wage_cat, "expense", "cost")
        txn = _create_txn(admin, "expense", wage_cat, 22.0, "EGP",
                          recipient_employee_id=employee["id"])
        wr = admin.get(f"{API}/admin/employees/wages")
        emp_row = next(e for e in wr.json() if e["id"] == employee["id"])
        assert any(h.get("transaction_id") == txn["id"] for h in emp_row["history"])
        # delete
        r = admin.delete(f"{API}/admin/finance/transactions/{txn['id']}")
        assert r.status_code == 200
        _created_txns.remove(txn["id"])
        wr = admin.get(f"{API}/admin/employees/wages")
        emp_row = next(e for e in wr.json() if e["id"] == employee["id"])
        assert not any(h.get("transaction_id") == txn["id"] for h in emp_row["history"]), \
            "orphan wage record after txn delete"


# ---------- Find username ----------
class TestFindUsername:
    @pytest.fixture(scope="class")
    def new_customer(self):
        phone = f"+201{PHONE_STAMP}09"
        username = f"TEST{UNIQUE}FU"
        payload = {"username": username, "phone": phone, "password": "pass1234",
                   "email": f"{UNIQUE}fu@test.example"}
        r = requests.post(f"{API}/customer/register", json=payload)
        assert r.status_code == 200, r.text
        _created_customers.append(r.json()["id"])
        # ensure no password leak in register response either
        assert "password" not in r.json() and "password_hash" not in r.json()
        return {"id": r.json()["id"], "phone": phone, "username": username, "password": "pass1234"}

    def test_find_success_returns_only_username(self, new_customer):
        r = requests.post(f"{API}/customer/find-username", json={"phone": new_customer["phone"]})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["username"] == new_customer["username"]
        assert "password" not in data and "password_hash" not in data
        assert set(data.keys()) == {"username"}, f"extra fields leaked: {data.keys()}"

    def test_find_404_for_unknown_phone(self):
        r = requests.post(f"{API}/customer/find-username", json={"phone": "+2019999999999"})
        assert r.status_code == 404

    def test_find_400_for_invalid_phone(self):
        r = requests.post(f"{API}/customer/find-username", json={"phone": "abc123"})
        assert r.status_code == 400


# ---------- Owner reset customer password ----------
class TestResetPassword:
    @pytest.fixture(scope="class")
    def cust(self):
        phone = f"+201{PHONE_STAMP}08"
        username = f"TEST{UNIQUE}RP"
        old_pw = "oldpass1"
        r = requests.post(f"{API}/customer/register",
                         json={"username": username, "phone": phone, "password": old_pw,
                               "email": f"{UNIQUE}rp@test.example"})
        assert r.status_code == 200, r.text
        _created_customers.append(r.json()["id"])
        return {"id": r.json()["id"], "phone": phone, "username": username, "old_pw": old_pw}

    def test_reset_short_400(self, admin, cust):
        r = admin.post(f"{API}/admin/customers/{cust['id']}/reset-password",
                       json={"new_password": "abc"})
        assert r.status_code == 400

    def test_reset_ok_and_login_switch(self, admin, cust):
        new_pw = "newpass9X"
        r = admin.post(f"{API}/admin/customers/{cust['id']}/reset-password",
                       json={"new_password": new_pw})
        assert r.status_code == 200, r.text
        # response never contains password
        body = r.json()
        assert "password" not in body and "password_hash" not in body and new_pw not in str(body)
        # old password fails
        r = requests.post(f"{API}/customer/login",
                          json={"identifier": cust["phone"], "password": cust["old_pw"]})
        assert r.status_code == 401
        # new password works
        r = requests.post(f"{API}/customer/login",
                          json={"identifier": cust["phone"], "password": new_pw})
        assert r.status_code == 200, r.text
        assert "password_hash" not in r.json()

    def test_non_owner_gets_403(self, admin, cust):
        # create an employee/admin (non-owner) account
        emp_email = f"test_{UNIQUE}_nonowner@test.example"
        emp_pw = "nopw1234"
        r = admin.post(f"{API}/admin/admins", json={
            "name": f"TEST {UNIQUE} NonOwner", "email": emp_email, "password": emp_pw,
            "role": "admin", "permissions": {"manage_orders": True, "access_finance": True}})
        assert r.status_code == 200, r.text
        _created_admins.append(r.json()["id"])
        # login as non-owner
        s = requests.Session()
        lr = s.post(f"{API}/auth/login", json={"email": emp_email, "password": emp_pw})
        assert lr.status_code == 200, lr.text
        r = s.post(f"{API}/admin/customers/{cust['id']}/reset-password",
                   json={"new_password": "anothernew1"})
        assert r.status_code == 403, f"non-owner should be forbidden, got {r.status_code}"
        # non-owner also cannot DELETE customers
        r = s.delete(f"{API}/admin/customers/{cust['id']}")
        assert r.status_code == 403


# ---------- Regression: paid order revenue + reversal ----------
class TestOrderRevenueRegression:
    @pytest.fixture(scope="class")
    def order(self, admin, rak):
        # build minimal order using first available product/zone
        zones = admin.get(f"{API}/admin/settings/delivery-zones")
        if zones.status_code != 200:
            zones = requests.get(f"{API}/delivery-zones")
        active_zone = None
        for z in zones.json():
            if z.get("active"):
                active_zone = z; break
        if not active_zone:
            pytest.skip("no active delivery zone")
        # simplest: pickup order to avoid zone complexity
        pid = rak["id"]
        # build a valid rak-kayu config quickly using first available option set
        cfg = {"type": "B", "length": 60, "level": 2, "finishing": "melamine"}
        payload = {
            "customer_name": f"TEST {UNIQUE} Buyer", "customer_phone": f"+201{PHONE_STAMP}07",
            "customer_address": "TEST addr", "customer_maps_url": "",
            "delivery_method": "pickup", "payment_method": "cash",
            "items": [{"product_id": pid, "config": cfg, "quantity": 1}]
        }
        r = requests.post(f"{API}/orders", json=payload)
        if r.status_code != 200:
            pytest.skip(f"could not build order: {r.status_code} {r.text}")
        o = r.json()
        _created_orders.append(o["id"])
        return o

    def test_paid_order_creates_order_revenue(self, admin, order):
        stats_before = _get_stats(admin)
        r = admin.patch(f"{API}/admin/orders/{order['id']}", json={"payment_status": "lunas"})
        assert r.status_code == 200, r.text
        stats_after = _get_stats(admin)
        delta = stats_after["current"]["EGP"]["revenue"] - stats_before["current"]["EGP"]["revenue"]
        assert round(delta, 2) == round(order["total_le"], 2), \
            f"revenue delta {delta} != order total_le {order['total_le']}"

    def test_delete_paid_order_preserves_revenue(self, admin, order):
        stats_before = _get_stats(admin)
        r = admin.delete(f"{API}/admin/orders/{order['id']}")
        assert r.status_code == 200
        _created_orders.remove(order["id"])
        stats_after = _get_stats(admin)
        delta = stats_after["current"]["EGP"]["revenue"] - stats_before["current"]["EGP"]["revenue"]
        # Revenue remains preserved because deleting an order no longer deletes finance records
        assert round(delta, 2) == 0, \
            f"revenue changed unexpectedly upon order deletion: delta={delta}"


# ---------- Cleanup ----------
class TestZzzCleanup:
    def test_cleanup(self, admin):
        for tid in list(_created_txns):
            admin.delete(f"{API}/admin/finance/transactions/{tid}")
        for cid in list(_created_categories):
            admin.delete(f"{API}/admin/finance/custom-categories/{cid}")
        for oid_ in list(_created_orders):
            admin.delete(f"{API}/admin/orders/{oid_}")
        for aid in list(_created_admins):
            admin.delete(f"{API}/admin/admins/{aid}")
        for cust_id in list(_created_customers):
            admin.delete(f"{API}/admin/customers/{cust_id}")
