"""Unit and integration tests for scripts/migrate_legacy_inventory_units.py.

Validates all 14 test scenarios:
  1. Dry-run execution (passes, 0 writes)
  2. Successful local migration (4 updates in transaction)
  3. Quantity invariance (24.0, 18.0 preserved)
  4. Referential integrity (stock_form_id and material_id preserved)
  5. Unique index collision preflight (aborts on existing 'lembar' cut)
  6. Wrong parent unit (aborts if BlockBoard unit != 'lembar')
  7. Wrong quantity (aborts if quantity changed)
  8. Wrong stock form unit (aborts if unexpected unit)
  9. Missing target document (aborts fail-closed)
  10. Transaction failure / rollback (zero documents mutated)
  11. Idempotent complete state (NO-OP, 0 writes)
  12. Inconsistent/partial state (fails closed, human review required)
  13. Unrelated documents (remain completely untouched)
  14. Global consistency check (zero mismatches after migration)
"""
import copy
from unittest.mock import MagicMock
from bson import ObjectId
import pytest

from scripts.migrate_legacy_inventory_units import (
    execute_migration,
    MigrationError,
    PARENT_MATERIAL_ID,
    TARGET_SF1_ID,
    TARGET_SF2_ID,
    TARGET_MS1_ID,
    TARGET_MS2_ID,
)


class MockCollection:
    def __init__(self, name: str, docs: list = None, indexes: dict = None):
        self.name = name
        self.docs = {str(d["_id"]): copy.deepcopy(d) for d in (docs or [])}
        self._indexes = indexes or {}

    def count_documents(self, filter_q=None, **kwargs):
        if not filter_q:
            return len(self.docs)
        matches = [d for d in self.docs.values() if self._matches(d, filter_q)]
        return len(matches)

    def find_one(self, filter_q, **kwargs):
        for d in self.docs.values():
            if self._matches(d, filter_q):
                return copy.deepcopy(d)
        return None

    def find(self, filter_q=None, **kwargs):
        res = []
        for d in self.docs.values():
            if not filter_q or self._matches(d, filter_q):
                res.append(copy.deepcopy(d))
        return res

    def index_information(self):
        return copy.deepcopy(self._indexes)

    def update_one(self, filter_q, update_q, session=None):
        target_id = None
        for doc_id, d in self.docs.items():
            if self._matches(d, filter_q):
                target_id = doc_id
                break

        res = MagicMock()
        if not target_id:
            res.matched_count = 0
            res.modified_count = 0
            return res

        res.matched_count = 1
        res.modified_count = 1
        if session and getattr(session, "in_transaction", False):
            if session.fail_on_update:
                raise Exception("Simulated transaction update failure")

        if "$set" in update_q:
            for k, v in update_q["$set"].items():
                self.docs[target_id][k] = v

        return res

    def _matches(self, doc: dict, filter_q: dict) -> bool:
        for k, v in filter_q.items():
            if k == "_id":
                if isinstance(v, dict) and "$ne" in v:
                    if str(doc.get("_id")) == str(v["$ne"]):
                        return False
                else:
                    if str(doc.get("_id")) != str(v):
                        return False
            else:
                if doc.get(k) != v:
                    return False
        return True


class MockSession:
    def __init__(self, client):
        self.client = client
        self.in_transaction = False
        self.fail_on_update = False
        self.aborted = False
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.abort_transaction()

    def start_transaction(self):
        self.in_transaction = True
        return self

    def commit_transaction(self):
        self.committed = True
        self.in_transaction = False

    def abort_transaction(self):
        self.aborted = True
        self.in_transaction = False
        # Rollback mock state
        self.client.restore_backup()


class MockClient:
    def __init__(self, db):
        self.db = db
        self._backup = None
        self.fail_session = False

    def start_session(self):
        if self.fail_session:
            raise Exception("Cannot start session")
        # Save snapshot for transaction rollback
        self._backup = {
            cname: copy.deepcopy(col.docs) for cname, col in self.db._collections.items()
        }
        return MockSession(self)

    def restore_backup(self):
        if self._backup:
            for cname, docs in self._backup.items():
                self.db._collections[cname].docs = copy.deepcopy(docs)

    def close(self):
        pass


class MockDatabase:
    def __init__(self, initial_data: dict, indexes: dict = None):
        self._collections = {
            "materials": MockCollection("materials", initial_data.get("materials", [])),
            "stock_forms": MockCollection("stock_forms", initial_data.get("stock_forms", []), indexes=indexes.get("stock_forms") if indexes else None),
            "material_stocks": MockCollection("material_stocks", initial_data.get("material_stocks", [])),
            "stock_transformations": MockCollection("stock_transformations", initial_data.get("stock_transformations", [])),
            "material_purchases": MockCollection("material_purchases", initial_data.get("material_purchases", [])),
        }

    def __getattr__(self, name: str):
        if name in self._collections:
            return self._collections[name]
        raise AttributeError(f"No collection {name}")


def create_fixture_data():
    """Builds standard mock fixture representing live production before migration."""
    materials = [
        {
            "_id": ObjectId(PARENT_MATERIAL_ID),
            "name": "BlockBoard",
            "category": "Material",
            "specs": "244x122 cm",
            "unit": "lembar",
            "status": "active",
            "current_stock": 0.0,
        },
        {
            "_id": ObjectId("6ac144ac8d54d51a83fdf240"),
            "name": "MDF Lapis HPL",
            "category": "Material",
            "specs": "244x122 cm",
            "unit": "lembar",
            "status": "active",
            "current_stock": 0.0,
        }
    ]

    stock_forms = [
        {
            "_id": ObjectId(TARGET_SF1_ID),
            "material_id": PARENT_MATERIAL_ID,
            "form_type": "standard",
            "width": 20.0,
            "length": 60.0,
            "thickness": 1.6,
            "dimension_unit": "cm",
            "stock_unit": "pcs",
            "label": "Rak 60x20",
            "current_quantity": 24.0,
            "is_active": True,
        },
        {
            "_id": ObjectId(TARGET_SF2_ID),
            "material_id": PARENT_MATERIAL_ID,
            "form_type": "standard",
            "width": 20.0,
            "length": 80.0,
            "thickness": 1.6,
            "dimension_unit": "cm",
            "stock_unit": "pcs",
            "label": "Rak 80x20",
            "current_quantity": 18.0,
            "is_active": True,
        },
        {
            "_id": ObjectId("6ac35a8231665b7e4febc00e"),
            "material_id": PARENT_MATERIAL_ID,
            "form_type": "standard",
            "width": 20.0,
            "length": 120.0,
            "thickness": 1.6,
            "dimension_unit": "cm",
            "stock_unit": "lembar",
            "label": "Rak 120x20",
            "current_quantity": 26.0,
            "is_active": True,
        }
    ]

    material_stocks = [
        {
            "_id": ObjectId(TARGET_MS1_ID),
            "material_id": PARENT_MATERIAL_ID,
            "stock_form_id": TARGET_SF1_ID,
            "movement_type": "transformation_in",
            "movement_number": "ST-20261005-0003",
            "quantity_delta": 24.0,
            "unit": "pcs",
        },
        {
            "_id": ObjectId(TARGET_MS2_ID),
            "material_id": PARENT_MATERIAL_ID,
            "stock_form_id": TARGET_SF2_ID,
            "movement_type": "adjustment_in",
            "movement_number": "ST-20261005-0024",
            "quantity_delta": 18.0,
            "unit": "pcs",
        },
        {
            "_id": ObjectId("6ac3f877d059c322df25dc57"),
            "material_id": PARENT_MATERIAL_ID,
            "stock_form_id": "6ac35a8231665b7e4febc00e",
            "movement_type": "adjustment_in",
            "movement_number": "ST-20261005-0025",
            "quantity_delta": 26.0,
            "unit": "lembar",
        }
    ]

    indexes = {
        "stock_forms": {
            "uniq_stock_form_spec": {"unique": True}
        }
    }

    return {"materials": materials, "stock_forms": stock_forms, "material_stocks": material_stocks}, indexes


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

def test_01_dry_run():
    """1. Dry-run passes preflight, plans 4 mutations, executes 0 writes."""
    data, indexes = create_fixture_data()
    db = MockDatabase(data, indexes)
    client = MockClient(db)

    res = execute_migration(client, db, dry_run=True)
    assert res["ok"] is True
    assert res["action"] == "dry_run_passed"
    assert res["writes_executed"] == 0

    # Ensure no docs were changed
    sf1 = db.stock_forms.find_one({"_id": ObjectId(TARGET_SF1_ID)})
    assert sf1["stock_unit"] == "pcs"


def test_02_successful_local_migration():
    """2. Live local execution updates exactly the 4 target documents."""
    data, indexes = create_fixture_data()
    db = MockDatabase(data, indexes)
    client = MockClient(db)

    res = execute_migration(client, db, dry_run=False)
    assert res["ok"] is True
    assert res["writes_executed"] == 4

    sf1 = db.stock_forms.find_one({"_id": ObjectId(TARGET_SF1_ID)})
    sf2 = db.stock_forms.find_one({"_id": ObjectId(TARGET_SF2_ID)})
    ms1 = db.material_stocks.find_one({"_id": ObjectId(TARGET_MS1_ID)})
    ms2 = db.material_stocks.find_one({"_id": ObjectId(TARGET_MS2_ID)})

    assert sf1["stock_unit"] == "lembar"
    assert sf2["stock_unit"] == "lembar"
    assert ms1["unit"] == "lembar"
    assert ms2["unit"] == "lembar"


def test_03_quantity_invariance():
    """3. Physical quantities and deltas are strictly invariant."""
    data, indexes = create_fixture_data()
    db = MockDatabase(data, indexes)
    client = MockClient(db)

    execute_migration(client, db, dry_run=False)

    sf1 = db.stock_forms.find_one({"_id": ObjectId(TARGET_SF1_ID)})
    sf2 = db.stock_forms.find_one({"_id": ObjectId(TARGET_SF2_ID)})
    ms1 = db.material_stocks.find_one({"_id": ObjectId(TARGET_MS1_ID)})
    ms2 = db.material_stocks.find_one({"_id": ObjectId(TARGET_MS2_ID)})

    assert sf1["current_quantity"] == 24.0
    assert sf2["current_quantity"] == 18.0
    assert ms1["quantity_delta"] == 24.0
    assert ms2["quantity_delta"] == 18.0


def test_04_referential_integrity():
    """4. Foreign key references remain strictly unchanged."""
    data, indexes = create_fixture_data()
    db = MockDatabase(data, indexes)
    client = MockClient(db)

    execute_migration(client, db, dry_run=False)

    ms1 = db.material_stocks.find_one({"_id": ObjectId(TARGET_MS1_ID)})
    ms2 = db.material_stocks.find_one({"_id": ObjectId(TARGET_MS2_ID)})

    assert ms1["stock_form_id"] == TARGET_SF1_ID
    assert ms1["material_id"] == PARENT_MATERIAL_ID
    assert ms2["stock_form_id"] == TARGET_SF2_ID
    assert ms2["material_id"] == PARENT_MATERIAL_ID


def test_05_collision_preflight_aborts():
    """5. Preflight detects existing 'lembar' cut and aborts without mutation."""
    data, indexes = create_fixture_data()
    # Add colliding form
    data["stock_forms"].append({
        "_id": ObjectId(),
        "material_id": PARENT_MATERIAL_ID,
        "form_type": "standard",
        "width": 20.0,
        "length": 60.0,
        "thickness": 1.6,
        "dimension_unit": "cm",
        "stock_unit": "lembar",
        "label": "Rak 60x20",
        "current_quantity": 0.0,
        "is_active": True,
    })
    db = MockDatabase(data, indexes)
    client = MockClient(db)

    with pytest.raises(MigrationError, match="Collision detected"):
        execute_migration(client, db, dry_run=False)

    # Verify no mutations
    sf1 = db.stock_forms.find_one({"_id": ObjectId(TARGET_SF1_ID)})
    assert sf1["stock_unit"] == "pcs"


def test_06_wrong_parent_unit_aborts():
    """6. Aborts if parent material unit != 'lembar'."""
    data, indexes = create_fixture_data()
    data["materials"][0]["unit"] = "batang"
    db = MockDatabase(data, indexes)
    client = MockClient(db)

    with pytest.raises(MigrationError, match="Parent material unit is 'batang', expected 'lembar'"):
        execute_migration(client, db, dry_run=False)


def test_07_wrong_quantity_aborts():
    """7. Aborts if target quantity changed from 24.0 or 18.0."""
    data, indexes = create_fixture_data()
    data["stock_forms"][0]["current_quantity"] = 23.0
    db = MockDatabase(data, indexes)
    client = MockClient(db)

    with pytest.raises(MigrationError, match="sf1 current_quantity 23.0 != 24.0"):
        execute_migration(client, db, dry_run=False)


def test_08_wrong_stock_form_unit_aborts():
    """8. Aborts if target unit is an unexpected value (e.g. 'meter')."""
    data, indexes = create_fixture_data()
    data["stock_forms"][0]["stock_unit"] = "meter"
    db = MockDatabase(data, indexes)
    client = MockClient(db)

    with pytest.raises(MigrationError, match="Inconsistent/partial unit state"):
        execute_migration(client, db, dry_run=False)


def test_09_missing_target_aborts():
    """9. Aborts fail-closed if any target document is missing."""
    data, indexes = create_fixture_data()
    data["material_stocks"].pop(0)  # remove ms1
    db = MockDatabase(data, indexes)
    client = MockClient(db)

    with pytest.raises(MigrationError, match="Target Material Stock 1.*not found"):
        execute_migration(client, db, dry_run=False)


def test_10_transaction_failure_rolls_back():
    """10. Transaction failure aborts and rolls back completely."""
    data, indexes = create_fixture_data()
    db = MockDatabase(data, indexes)
    client = MockClient(db)

    # Force failure during transaction execution
    original_start_session = client.start_session
    def failing_session():
        sess = original_start_session()
        sess.fail_on_update = True
        return sess
    client.start_session = failing_session

    with pytest.raises(Exception):
        execute_migration(client, db, dry_run=False)

    # Verify that rollback restored original states
    sf1 = db.stock_forms.find_one({"_id": ObjectId(TARGET_SF1_ID)})
    sf2 = db.stock_forms.find_one({"_id": ObjectId(TARGET_SF2_ID)})
    assert sf1["stock_unit"] == "pcs"
    assert sf2["stock_unit"] == "pcs"


def test_11_idempotent_complete_state():
    """11. Rerunning against fully normalized state is a clean NO-OP."""
    data, indexes = create_fixture_data()
    # Normalize all 4
    data["stock_forms"][0]["stock_unit"] = "lembar"
    data["stock_forms"][1]["stock_unit"] = "lembar"
    data["material_stocks"][0]["unit"] = "lembar"
    data["material_stocks"][1]["unit"] = "lembar"

    db = MockDatabase(data, indexes)
    client = MockClient(db)

    res = execute_migration(client, db, dry_run=False)
    assert res["ok"] is True
    assert res["action"] == "already_completed"
    assert res["writes_executed"] == 0


def test_12_partial_state_fails_closed():
    """12. Partially migrated state (e.g. 1 lembar, 3 pcs) fails closed."""
    data, indexes = create_fixture_data()
    data["stock_forms"][0]["stock_unit"] = "lembar"  # only 1 changed

    db = MockDatabase(data, indexes)
    client = MockClient(db)

    with pytest.raises(MigrationError, match="Inconsistent/partial unit state"):
        execute_migration(client, db, dry_run=False)


def test_13_unrelated_documents_untouched():
    """13. Unrelated stock forms and movements remain completely untouched."""
    data, indexes = create_fixture_data()
    db = MockDatabase(data, indexes)
    client = MockClient(db)

    execute_migration(client, db, dry_run=False)

    unrelated_sf = db.stock_forms.find_one({"_id": ObjectId("6ac35a8231665b7e4febc00e")})
    unrelated_ms = db.material_stocks.find_one({"_id": ObjectId("6ac3f877d059c322df25dc57")})

    assert unrelated_sf["label"] == "Rak 120x20"
    assert unrelated_sf["stock_unit"] == "lembar"
    assert unrelated_sf["current_quantity"] == 26.0

    assert unrelated_ms["movement_number"] == "ST-20261005-0025"
    assert unrelated_ms["unit"] == "lembar"
    assert unrelated_ms["quantity_delta"] == 26.0


def test_14_global_consistency_verification():
    """14. Global consistency check verifies 0 unit mismatches across database."""
    data, indexes = create_fixture_data()
    db = MockDatabase(data, indexes)
    client = MockClient(db)

    execute_migration(client, db, dry_run=False)

    # Scan all forms
    mismatches = 0
    for sf in db.stock_forms.find():
        mat = db.materials.find_one({"_id": ObjectId(sf["material_id"])})
        if sf.get("stock_unit") != mat.get("unit"):
            mismatches += 1

    assert mismatches == 0
