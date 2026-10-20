"""Index Provisioning & Verification Engine for Sogil Furniture.

Separates index mutation from application startup, guarantees fail-closed
financial integrity verification, preflight duplicate detection, and actionable
diagnostics.
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any, Optional, Union
import logging
import inspect
import pymongo
from pymongo.errors import OperationFailure

logger = logging.getLogger(__name__)

try:
    from backend.tests.isolation_guard import validate_test_database_isolation
except ImportError:
    try:
        from tests.isolation_guard import validate_test_database_isolation
    except ImportError:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from backend.tests.isolation_guard import validate_test_database_isolation


class CriticalFinanceIndexError(RuntimeError):
    """Raised when a critical unique financial integrity index fails to be created/verified."""
    def __init__(self, collection_name: str, index_name: str, reason: str):
        self.collection_name = collection_name
        self.index_name = index_name
        self.reason = reason
        super().__init__(
            f"Failed to create critical financial integrity index '{index_name}' "
            f"on collection '{collection_name}': {reason}"
        )


class DuplicateRecordError(CriticalFinanceIndexError):
    """Raised when duplicate records are detected during preflight check before index creation."""
    def __init__(self, collection_name: str, index_name: str, duplicates: List[Dict[str, Any]]):
        self.duplicates = duplicates
        report = format_duplicate_report(collection_name, index_name, duplicates)
        super().__init__(collection_name, index_name, f"Duplicate records detected in preflight:\n{report}")


def format_duplicate_report(collection: str, index_name: str, duplicates: List[Dict[str, Any]]) -> str:
    lines = [
        f"DUPLICATE KEY CONFLICT IN [{collection}] FOR INDEX '{index_name}':",
        f"Found {len(duplicates)} distinct conflict group(s):"
    ]
    for i, dup in enumerate(duplicates[:20], 1):
        key_str = ", ".join(f"{k}={v!r}" for k, v in dup.get("key", {}).items())
        ids = dup.get("sample_ids", [])
        lines.append(f"  {i}. Key: ({key_str}) | Count: {dup.get('count')} | Sample IDs: {ids}")
    if len(duplicates) > 20:
        lines.append(f"  ... and {len(duplicates) - 20} more conflict group(s).")
    return "\n".join(lines)


@dataclass(frozen=True)
class IndexSpec:
    collection: str
    keys: List[Tuple[str, int]]
    name: str
    unique: bool = False
    partial_filter_expression: Optional[Dict[str, Any]] = None
    sparse: bool = False
    expire_after_seconds: Optional[int] = None
    category: str = "critical_unique"  # "critical_unique", "required_unique", "performance"
    description: str = ""


# Master list of all required indexes across Phase 1, Phase 2, Phase 3
REQUIRED_INDEX_SPECS: List[IndexSpec] = [
    # --- Critical Unique Financial & Operational Constraints ---
    IndexSpec(
        collection="payments",
        keys=[("payment_number", 1)],
        name="uniq_payment_number",
        unique=True,
        category="critical_unique",
        description="Strict uniqueness on human-readable payment numbers",
    ),
    IndexSpec(
        collection="payments",
        keys=[("idempotency_key", 1)],
        name="uniq_payments_idempotency",
        unique=True,
        partial_filter_expression={"idempotency_key": {"$type": "string"}},
        category="critical_unique",
        description="Guarantees idempotent payment ingestion and rejects duplicates",
    ),
    IndexSpec(
        collection="wage_obligations",
        keys=[("accrual_event_key", 1)],
        name="uniq_wage_obligation_accrual_event",
        unique=True,
        category="critical_unique",
        description="Prevents duplicate wage accruals for the same task/completion event",
    ),
    IndexSpec(
        collection="wage_obligations",
        keys=[("obligation_number", 1)],
        name="uniq_obligation_number",
        unique=True,
        category="critical_unique",
        description="Unique sequential identifier for wage obligations",
    ),
    IndexSpec(
        collection="wage_obligations",
        keys=[("order_id", 1), ("worker_id", 1), ("task_category", 1)],
        name="uniq_delivery_wage_order_worker",
        unique=True,
        partial_filter_expression={"task_category": "delivery"},
        category="critical_unique",
        description="Enforces unique delivery wage entitlement per order and worker",
    ),
    IndexSpec(
        collection="wage_settlements",
        keys=[("settlement_number", 1)],
        name="uniq_settlement_number",
        unique=True,
        category="critical_unique",
        description="Unique sequential identifier for wage settlements",
    ),
    IndexSpec(
        collection="wage_settlements",
        keys=[("idempotency_key", 1)],
        name="uniq_wage_settlements_idempotency",
        unique=True,
        partial_filter_expression={"idempotency_key": {"$type": "string"}},
        category="critical_unique",
        description="Prevents double settlement execution on retried requests",
    ),
    IndexSpec(
        collection="customer_credit_events",
        keys=[("event_number", 1)],
        name="uniq_credit_event_number",
        unique=True,
        category="critical_unique",
        description="Unique sequential ledger identifier for customer credit movements",
    ),
    IndexSpec(
        collection="customer_credit_events",
        keys=[("source_payment_id", 1), ("event_type", 1)],
        name="uniq_credit_event_source_payment",
        unique=True,
        partial_filter_expression={"source_payment_id": {"$type": "string"}},
        category="critical_unique",
        description="Prevents multiple overpayment credit issuances from a single payment",
    ),
    IndexSpec(
        collection="customer_credit_events",
        keys=[("idempotency_key", 1)],
        name="uniq_credit_events_idempotency",
        unique=True,
        partial_filter_expression={"idempotency_key": {"$type": "string"}},
        category="critical_unique",
        description="Guarantees idempotency for credit adjustments and grants",
    ),
    IndexSpec(
        collection="finance_adjustments",
        keys=[("adjustment_id", 1)],
        name="uniq_adjustment_id",
        unique=True,
        category="critical_unique",
        description="Unique identifier for financial manual and systematic adjustments",
    ),
    IndexSpec(
        collection="finance_adjustments",
        keys=[("idempotency_key", 1)],
        name="uniq_adjustments_idempotency",
        unique=True,
        partial_filter_expression={"idempotency_key": {"$type": "string"}},
        category="critical_unique",
        description="Prevents duplicate financial ledger adjustment mutations",
    ),
    IndexSpec(
        collection="work_assignments",
        keys=[("order_item_id", 1), ("worker_id", 1), ("task_category", 1)],
        name="uniq_active_worker_task_per_item",
        unique=True,
        partial_filter_expression={"status": {"$in": ["assigned", "in_progress", "ready_for_review", "accruing"]}},
        category="critical_unique",
        description="Enforces at most one active assignment per worker per item task",
    ),
    IndexSpec(
        collection="outbox_events",
        keys=[("event_id", 1)],
        name="uniq_outbox_event_id",
        unique=True,
        category="critical_unique",
        description="Enforces strict uniqueness on transactional outbox event identity",
    ),
    IndexSpec(
        collection="assignment_groups",
        keys=[("group_number", 1)],
        name="uniq_assignment_group_number",
        unique=True,
        partial_filter_expression={"group_number": {"$type": "string"}},
        category="critical_unique",
        description="Enforces uniqueness on batch assignment group numbers",
    ),
    IndexSpec(
        collection="material_purchases",
        keys=[("purchase_number", 1)],
        name="uniq_purchase_number",
        unique=True,
        category="critical_unique",
        description="Unique identifier for raw material purchase batches",
    ),
    IndexSpec(
        collection="material_stocks",
        keys=[("movement_number", 1)],
        name="uniq_movement_number",
        unique=True,
        category="critical_unique",
        description="Unique sequential identifier for inventory stock movements",
    ),
    IndexSpec(
        collection="material_stocks",
        keys=[("related_purchase_id", 1), ("movement_type", 1)],
        name="uniq_purchase_stock_movement",
        unique=True,
        partial_filter_expression={"related_purchase_id": {"$type": "string"}},
        category="critical_unique",
        description="Prevents duplicate inventory movements linked to the same purchase",
    ),
    IndexSpec(
        collection="finance_transactions",
        keys=[("reference_id", 1), ("reference_type", 1), ("type", 1)],
        name="uniq_purchase_finance_expense",
        unique=True,
        partial_filter_expression={"reference_type": "material_purchase", "type": "expense"},
        category="critical_unique",
        description="Prevents double ledger debit entries for material purchases",
    ),
    IndexSpec(
        collection="finance_transactions",
        keys=[("reference_id", 1), ("is_reversal", 1)],
        name="uniq_purchase_finance_reversal",
        unique=True,
        partial_filter_expression={"reference_type": "material_purchase", "is_reversal": True},
        category="critical_unique",
        description="Prevents double reversal ledger entries for canceled purchases",
    ),
    IndexSpec(
        collection="stock_transformations",
        keys=[("transformation_number", 1)],
        name="uniq_transformation_number",
        unique=True,
        category="critical_unique",
        description="Unique identifier for timber cutting/transformation operations",
    ),
    IndexSpec(
        collection="delivery_trips",
        keys=[("trip_number", 1)],
        name="uniq_delivery_trip_number",
        unique=True,
        category="critical_unique",
        description="Unique identifier for multi-stop delivery trips",
    ),

    # --- Required Unique Constraints ---
    IndexSpec(
        collection="admins",
        keys=[("email", 1)],
        name="uniq_admin_email",
        unique=True,
        category="required_unique",
        description="Ensures unique email address across system administrators",
    ),
    IndexSpec(
        collection="products",
        keys=[("slug", 1)],
        name="uniq_product_slug",
        unique=True,
        category="required_unique",
        description="Ensures unique slug for product catalog routing",
    ),
    IndexSpec(
        collection="invoices",
        keys=[("invoice_number", 1)],
        name="uniq_invoice_number",
        unique=True,
        category="required_unique",
        description="Ensures unique invoice numbering",
    ),
    IndexSpec(
        collection="materials",
        keys=[("name_normalized", 1), ("specs_normalized", 1)],
        name="uniq_material_name_specs",
        unique=True,
        category="required_unique",
        description="Prevents duplicate material definitions by normalized name and specs",
    ),
    IndexSpec(
        collection="stock_forms",
        keys=[
            ("material_id", 1),
            ("form_type", 1),
            ("width", 1),
            ("length", 1),
            ("thickness", 1),
            ("dimension_unit", 1),
            ("stock_unit", 1),
            ("label", 1),
        ],
        name="uniq_stock_form_spec",
        unique=True,
        category="required_unique",
        description="Enforces uniqueness on specific raw/cut material dimension specs",
    ),

    # --- Performance & Lookup Indexes ---
    IndexSpec(
        collection="orders",
        keys=[("customer_id", 1)],
        name="idx_orders_customer_id",
        category="performance",
    ),
    IndexSpec(
        collection="orders",
        keys=[("order_number", 1)],
        name="idx_orders_order_number",
        category="performance",
    ),
    IndexSpec(
        collection="orders",
        keys=[("order_status", 1)],
        name="idx_orders_order_status",
        category="performance",
    ),
    IndexSpec(
        collection="orders",
        keys=[("payment_status", 1)],
        name="idx_orders_payment_status",
        category="performance",
    ),
    IndexSpec(
        collection="orders",
        keys=[("created_at", -1)],
        name="idx_orders_created_at_desc",
        category="performance",
    ),
    IndexSpec(
        collection="orders",
        keys=[("active_delivery_trip_id", 1)],
        name="idx_orders_active_delivery_trip",
        category="performance",
    ),
    IndexSpec(
        collection="customers",
        keys=[("phone", 1)],
        name="idx_customers_phone",
        category="performance",
    ),
    IndexSpec(
        collection="point_transactions",
        keys=[("customer_id", 1)],
        name="idx_point_transactions_customer",
        category="performance",
    ),
    IndexSpec(
        collection="invoices",
        keys=[("order_id", 1)],
        name="idx_invoices_order_id",
        category="performance",
    ),
    IndexSpec(
        collection="audit_logs",
        keys=[("entity_type", 1), ("entity_id", 1)],
        name="idx_audit_logs_entity",
        category="performance",
    ),
    IndexSpec(
        collection="audit_logs",
        keys=[("timestamp", -1)],
        name="idx_audit_logs_timestamp",
        category="performance",
    ),
    IndexSpec(
        collection="payments",
        keys=[("order_id", 1), ("status", 1)],
        name="idx_payments_order_status",
        category="performance",
    ),
    IndexSpec(
        collection="payments",
        keys=[("finance_transaction_id", 1)],
        name="idx_payments_finance_txn",
        category="performance",
    ),
    IndexSpec(
        collection="work_assignments",
        keys=[("order_id", 1), ("order_item_id", 1)],
        name="idx_work_assignments_order_item",
        category="performance",
    ),
    IndexSpec(
        collection="work_assignments",
        keys=[("worker_id", 1), ("status", 1)],
        name="idx_work_assignments_worker_status",
        category="performance",
    ),
    IndexSpec(
        collection="wage_obligations",
        keys=[("work_assignment_id", 1)],
        name="idx_wage_obligations_assignment",
        category="performance",
    ),
    IndexSpec(
        collection="wage_obligations",
        keys=[("worker_id", 1), ("status", 1)],
        name="idx_wage_obligations_worker_status",
        category="performance",
    ),
    IndexSpec(
        collection="wage_settlements",
        keys=[("worker_id", 1), ("settlement_date", -1)],
        name="idx_wage_settlements_worker_date",
        category="performance",
    ),
    IndexSpec(
        collection="outbox_events",
        keys=[("status", 1), ("created_at", 1)],
        name="idx_outbox_status_created",
        category="performance",
    ),
    IndexSpec(
        collection="outbox_events",
        keys=[("aggregate_type", 1), ("aggregate_id", 1)],
        name="idx_outbox_aggregate",
        category="performance",
    ),
    IndexSpec(
        collection="outbox_events",
        keys=[("status", 1), ("next_retry_at", 1), ("lease_expires_at", 1)],
        name="idx_outbox_claim",
        category="performance",
    ),
    IndexSpec(
        collection="outbox_events",
        keys=[("claim_token", 1)],
        name="idx_outbox_claim_token",
        sparse=True,
        category="performance",
    ),
    IndexSpec(
        collection="customer_credit_events",
        keys=[("customer_id", 1), ("currency", 1)],
        name="idx_credit_events_customer_currency",
        category="performance",
    ),
    IndexSpec(
        collection="finance_adjustments",
        keys=[("order_id", 1), ("is_void", 1), ("created_at", -1)],
        name="idx_adjustments_order_lookup",
        category="performance",
    ),
    IndexSpec(
        collection="delivery_trips",
        keys=[("scheduled_date", 1), ("status", 1)],
        name="idx_delivery_trips_date_status",
        category="performance",
    ),
]


def normalize_key_tuples(keys: Any) -> List[Tuple[str, Union[int, str]]]:
    """Normalizes index key representations into List[Tuple[str, Union[int, str]]].
    Preserves exact field names, compound key order, and direction/type.
    """
    if isinstance(keys, str):
        return [(keys, 1)]
    if isinstance(keys, dict):
        keys = list(keys.items())
    res = []
    for item in keys:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            field = str(item[0])
            val = item[1]
            try:
                if isinstance(val, (int, float)) and int(val) == val:
                    res.append((field, int(val)))
                else:
                    res.append((field, val))
            except Exception:
                res.append((field, val))
        elif isinstance(item, str):
            res.append((item, 1))
    return res


async def check_duplicate_records(db_inst, spec: IndexSpec) -> List[Dict[str, Any]]:
    """Runs an aggregation pipeline to detect any documents that violate spec uniqueness.
    Respects partialFilterExpression.
    """
    if not spec.unique:
        return []

    pipeline: List[Dict[str, Any]] = []
    if spec.partial_filter_expression:
        pipeline.append({"$match": spec.partial_filter_expression})
    elif spec.sparse:
        pipeline.append({"$match": {"$or": [{k: {"$exists": True, "$ne": None}} for k, _ in spec.keys]}})

    group_id = {k.replace(".", "_"): f"${k}" for k, _ in spec.keys}
    pipeline.extend([
        {
            "$group": {
                "_id": group_id,
                "count": {"$sum": 1},
                "sample_ids": {"$push": {"$toString": "$_id"}},
            }
        },
        {"$match": {"count": {"$gt": 1}}},
        {"$limit": 100}
    ])

    coll = getattr(db_inst, spec.collection, None)
    if coll is None:
        try:
            coll = db_inst[spec.collection]
        except Exception:
            return []

    if not hasattr(coll, "aggregate"):
        return []

    cursor = coll.aggregate(pipeline)
    to_list_fn = getattr(cursor, "to_list", None)
    if callable(to_list_fn):
        res_coro = to_list_fn(100)
        docs = await res_coro if inspect.isawaitable(res_coro) else []
    else:
        docs = []
        if hasattr(cursor, "__aiter__"):
            async for d in cursor:
                docs.append(d)
        elif hasattr(cursor, "__iter__"):
            for d in cursor:
                docs.append(d)

    duplicates = []
    for d in docs:
        duplicates.append({
            "key": d.get("_id", {}),
            "count": d.get("count", 0),
            "sample_ids": (d.get("sample_ids") or [])[:10],
        })
    return duplicates


async def verify_required_indexes(
    db_inst,
    specs: Optional[List[IndexSpec]] = None,
    fail_closed: bool = True
) -> Dict[str, Any]:
    """Inspects existing indexes on all target collections and verifies they match specs.
    Returns:
        {
            "valid": bool,
            "verified": List[IndexSpec],
            "missing": List[Dict[str, Any]],
            "incompatible": List[Dict[str, Any]],
            "errors": List[str]
        }
    """
    if specs is None:
        specs = REQUIRED_INDEX_SPECS

    verified: List[IndexSpec] = []
    missing: List[Dict[str, Any]] = []
    incompatible: List[Dict[str, Any]] = []
    errors: List[str] = []

    # Cache index_information per collection
    collection_indexes: Dict[str, Dict[str, Any]] = {}

    for spec in specs:
        coll_name = spec.collection
        if coll_name not in collection_indexes:
            coll = getattr(db_inst, coll_name, None)
            if coll is None:
                try:
                    coll = db_inst[coll_name]
                except Exception:
                    collection_indexes[coll_name] = {}
                    continue
            try:
                info_fn = getattr(coll, "index_information", None)
                if callable(info_fn):
                    info_coro = info_fn()
                    info = await info_coro if inspect.isawaitable(info_coro) else info_coro
                    collection_indexes[coll_name] = info or {}
                else:
                    collection_indexes[coll_name] = {}
            except Exception as e:
                collection_indexes[coll_name] = {}
                logger.debug(f"Could not read index_information for {coll_name}: {e}")

        coll_info = collection_indexes.get(coll_name, {})

        matched_index = None
        # 1. Match by exact name
        if spec.name in coll_info:
            matched_index = coll_info[spec.name]
        else:
            # 2. Match by key structure
            spec_keys_norm = normalize_key_tuples(spec.keys)
            for existing_name, existing_def in coll_info.items():
                if normalize_key_tuples(existing_def.get("key", [])) == spec_keys_norm:
                    matched_index = existing_def
                    break

        if matched_index is None:
            item = {"collection": spec.collection, "spec": spec, "reason": "Index does not exist"}
            missing.append(item)
            msg = f"Missing {spec.category} index '{spec.name}' on '{spec.collection}'"
            errors.append(msg)
            if fail_closed:
                raise CriticalFinanceIndexError(spec.collection, spec.name, f"Index does not exist: {msg}")
            continue

        reasons = []
        # Check key specification, exact field names, compound key order, and direction
        existing_keys = normalize_key_tuples(matched_index.get("key", []))
        expected_keys = normalize_key_tuples(spec.keys)
        if existing_keys != expected_keys:
            reasons.append(
                f"key structure mismatch: expected {expected_keys}, got {existing_keys}"
            )

        # Check uniqueness
        existing_unique = bool(matched_index.get("unique", False))
        if spec.unique != existing_unique:
            reasons.append(f"unique mismatch: expected {spec.unique}, got {existing_unique}")

        # Check partialFilterExpression
        existing_partial = matched_index.get("partialFilterExpression")
        if spec.partial_filter_expression != existing_partial:
            reasons.append(
                f"partialFilterExpression mismatch: expected {spec.partial_filter_expression}, got {existing_partial}"
            )

        # Check sparse
        existing_sparse = bool(matched_index.get("sparse", False))
        if spec.sparse != existing_sparse:
            reasons.append(f"sparse mismatch: expected {spec.sparse}, got {existing_sparse}")

        # Check expireAfterSeconds
        existing_ttl = matched_index.get("expireAfterSeconds")
        if spec.expire_after_seconds is not None:
            if existing_ttl != spec.expire_after_seconds:
                reasons.append(
                    f"expireAfterSeconds mismatch: expected {spec.expire_after_seconds}, got {existing_ttl}"
                )
        elif existing_ttl is not None:
            reasons.append(
                f"expireAfterSeconds mismatch: expected None, got {existing_ttl}"
            )

        if reasons:
            reason_str = "; ".join(reasons)
            item = {"collection": spec.collection, "spec": spec, "reason": reason_str}
            incompatible.append(item)
            msg = f"Incompatible {spec.category} index '{spec.name}' on '{spec.collection}': {reason_str}"
            errors.append(msg)
            if fail_closed:
                raise CriticalFinanceIndexError(spec.collection, spec.name, msg)
        else:
            verified.append(spec)

    is_valid = len(missing) == 0 and len(incompatible) == 0
    return {
        "valid": is_valid,
        "verified": verified,
        "missing": missing,
        "incompatible": incompatible,
        "errors": errors,
    }


async def provision_indexes(
    db_inst,
    specs: Optional[List[IndexSpec]] = None,
    dry_run: bool = False,
    target_uri: Optional[str] = None,
    db_name: Optional[str] = None,
    fail_closed: bool = True,
) -> Dict[str, Any]:
    """Provisions indexes according to specifications.
    
    In dry_run mode: Inspects and plans index creation without database writes.
    In apply mode: Validates database isolation, executes preflight duplicate detection,
    and creates missing indexes sequentially. Reports completed, failed, and pending items.
    """
    if specs is None:
        specs = REQUIRED_INDEX_SPECS

    # Security check: if not dry_run, validate database isolation
    if not dry_run and (target_uri or db_name):
        validate_test_database_isolation(target_uri, db_name)

    # First verify existing state
    verification = await verify_required_indexes(db_inst, specs=specs, fail_closed=False)
    verified_names = {s.name for s in verification["verified"]}
    incompatible_map = {item["spec"].name: item for item in verification["incompatible"]}

    specs_to_create = [s for s in specs if s.name not in verified_names]

    if dry_run:
        duplicates_found: Dict[str, List[Dict[str, Any]]] = {}
        for s in specs_to_create:
            if s.unique:
                dups = await check_duplicate_records(db_inst, s)
                if dups:
                    duplicates_found[s.name] = dups

        return {
            "dry_run": True,
            "verified_count": len(verification["verified"]),
            "missing_count": len(verification["missing"]),
            "incompatible_count": len(verification["incompatible"]),
            "planned_creations": [s.name for s in specs_to_create],
            "duplicates_detected": duplicates_found,
            "status": "PLAN_GENERATED",
        }

    completed: List[str] = []
    failed: List[Dict[str, Any]] = []
    pending: List[IndexSpec] = list(specs_to_create)

    for spec in list(specs_to_create):
        # 0. Incompatible index pre-check: fail closed or mark failed instead of blind create_index
        if spec.name in incompatible_map:
            inc_reason = incompatible_map[spec.name]["reason"]
            failed.append({"spec": spec, "error": f"Incompatible index exists: {inc_reason}"})
            pending.remove(spec)
            if fail_closed:
                raise CriticalFinanceIndexError(
                    spec.collection, spec.name, f"Cannot provision over incompatible index: {inc_reason}"
                )
            continue
        # 1. Duplicate preflight check for unique indexes
        if spec.unique:
            dups = await check_duplicate_records(db_inst, spec)
            if dups:
                report = format_duplicate_report(spec.collection, spec.name, dups)
                logger.error(f"PREFLIGHT DUPLICATE ERROR: {report}")
                failed.append({"spec": spec, "error": f"Duplicate records detected in preflight: {len(dups)} conflict(s)"})
                pending.remove(spec)
                if fail_closed:
                    raise DuplicateRecordError(spec.collection, spec.name, dups)
                continue

        # 2. Build index options
        kwargs: Dict[str, Any] = {"name": spec.name}
        if spec.unique:
            kwargs["unique"] = True
        if spec.partial_filter_expression is not None:
            kwargs["partialFilterExpression"] = spec.partial_filter_expression
        if spec.sparse:
            kwargs["sparse"] = True
        if spec.expire_after_seconds is not None:
            kwargs["expireAfterSeconds"] = spec.expire_after_seconds

        coll = getattr(db_inst, spec.collection, None)
        if coll is None:
            coll = db_inst[spec.collection]

        try:
            res_coro = coll.create_index(spec.keys, **kwargs)
            if inspect.isawaitable(res_coro):
                await res_coro
            completed.append(spec.name)
            pending.remove(spec)
        except Exception as e:
            failed.append({"spec": spec, "error": str(e)})
            pending.remove(spec)
            logger.error(f"INDEX CREATION FAILED for '{spec.name}' on '{spec.collection}': {e}")
            if fail_closed:
                summary = (
                    f"Index creation failed on '{spec.name}'. "
                    f"Completed: {completed}, "
                    f"Failed: {[f['spec'].name for f in failed]}, "
                    f"Pending: {[p.name for p in pending]}"
                )
                raise CriticalFinanceIndexError(spec.collection, spec.name, f"{e}. Progress: {summary}")

    return {
        "dry_run": False,
        "completed": completed,
        "failed": failed,
        "pending": [p.name for p in pending],
        "status": "COMPLETED" if not failed else "PARTIAL_FAILURE",
    }
